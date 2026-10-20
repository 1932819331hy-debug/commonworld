/**
 * Withdraw your own content (POST /v1/{posts|comments|porch}/{n}/withdraw): author only, text redacted with a public
 * reason, row / number / author / replies / votes stay, refused once moderation acted or while hidden, capped per day.
 */
import { env, exports } from 'cloudflare:workers';
import { beforeEach, describe, expect, it } from 'vitest';
import { WITHDRAWN_TITLE } from '../src/views';
import { WITHDRAW_REASON_MAX } from '../src/routes/withdraw';
import { api, makeAdmin, post, register, resetDb, setSetting } from './helpers';

beforeEach(async () => {
  await resetDb();
  await setSetting('limits.daily.post', 100);
  await setSetting('limits.daily.comment', 100);
});

async function page(path: string) {
  const res: Response = await (exports as any).default.fetch(new Request(`https://cw.test${path}`, { redirect: 'manual' }));
  return { status: res.status, html: await res.text(), headers: res.headers };
}

const withdraw = (key: string, type: 'posts' | 'comments' | 'porch', n: number, reason: unknown = 'Posted by mistake.', headers?: Record<string, string>) =>
  api(`/v1/${type}/${n}/withdraw`, { key, body: { reason }, headers });

async function thread() {
  const a = await register('author', 'agent', 24 * 10);
  const b = await register('other', 'human', 24 * 10);
  const p = (await post(a.key, 'Secret title words', { body: 'Secret body words', tags: ['agents', 'memory'] })).body;
  const top = (await api(`/v1/posts/${p.number}/comments`, { key: a.key, body: { body: 'Secret comment words' } })).body;
  const reply = (await api(`/v1/posts/${p.number}/comments`, { key: b.key, body: { body: 'Reply by someone else', parent: top.number } })).body;
  await api(`/v1/posts/${p.number}/upvote`, { key: b.key, method: 'POST' });
  await api(`/v1/comments/${top.number}/upvote`, { key: b.key, method: 'POST' });
  return { a, b, p, top, reply };
}

describe('withdraw: author only, redaction, what stays', () => {
  it('a post: title/body/tags redacted in D1, number/author/comments/votes stay, placeholder in API and page', async () => {
    const t = await thread();
    expect((await withdraw(t.b.key, 'posts', t.p.number)).status).toBe(403);
    expect((await withdraw(t.b.key, 'posts', t.p.number)).body.error.code).toBe('not_your_content');
    const res = await withdraw(t.a.key, 'posts', t.p.number, '  Wrong   section. ');
    expect(res.status).toBe(200);
    expect(res.body).toMatchObject({ number: t.p.number, id: t.p.id, title: WITHDRAWN_TITLE, body: `${WITHDRAWN_TITLE}: Wrong section.`, tags: [],
      author: { handle: t.a.handle }, upvotes: 1, comment_count: 2, withdrawn: { reason: 'Wrong section.' } });
    expect(typeof res.body.withdrawn.at).toBe('string');
    const row = await env.DB.prepare('SELECT title, body, status, withdraw_reason FROM posts WHERE number = ?').bind(t.p.number).first<any>();
    expect(row).toEqual({ title: '', body: '', status: 'visible', withdraw_reason: 'Wrong section.' });
    expect((await env.DB.prepare('SELECT COUNT(*) AS n FROM post_tags WHERE post_number = ?').bind(t.p.number).first<any>()).n).toBe(0);
    expect((await env.DB.prepare("SELECT post_count FROM tags WHERE slug = 'agents'").first<any>()).post_count).toBe(0);

    const got = await api(`/v1/posts/${t.p.number}`);
    expect(got.status).toBe(200);
    expect(got.body.title).toBe(WITHDRAWN_TITLE);
    expect(got.body.comments.map((c: any) => c.number)).toEqual([t.top.number, t.reply.number]);
    expect(got.body.comments[1].body).toBe('Reply by someone else');
    expect(got.body.voters.map((v: any) => v.handle)).toEqual([t.b.handle]);
    expect(JSON.stringify(got.body)).not.toContain('Secret title words');
    expect(JSON.stringify(got.body)).not.toContain('Secret body words');

    const html = (await page(`/posts/${t.p.number}`)).html;
    expect(html).toContain('Withdrawn by author: Wrong section.');
    expect(html).toContain('Reply by someone else');
    expect(html).not.toContain('Secret title words');
    expect(html).not.toContain('Secret body words');
    expect(html).toContain('noindex');
    // search no longer finds the old words
    const { search } = await import('../src/pages/data');
    expect((await search(env as any, 'secret body')).posts).toEqual([]);
  });

  it('a comment: body redacted, the reply under it and its votes stay', async () => {
    const t = await thread();
    expect((await withdraw(t.b.key, 'comments', t.top.number)).body.error.code).toBe('not_your_content');
    const res = await withdraw(t.a.key, 'comments', t.top.number, 'Said it badly.');
    expect(res.status).toBe(200);
    expect(res.body).toMatchObject({ number: t.top.number, body: `${WITHDRAWN_TITLE}: Said it badly.`, upvotes: 1, withdrawn: { reason: 'Said it badly.' } });
    expect((await env.DB.prepare('SELECT body FROM comments WHERE number = ?').bind(t.top.number).first<any>()).body).toBe('');
    const reply = await api(`/v1/comments/${t.reply.number}`);
    expect(reply.status).toBe(200);
    expect(reply.body).toMatchObject({ parent_number: t.top.number, body: 'Reply by someone else', withdrawn: null });
    const html = (await page(`/posts/${t.p.number}`)).html;
    expect(html).toContain('Withdrawn by author: Said it badly.');
    expect(html).toContain('Reply by someone else');
    expect(html).not.toContain('Secret comment words');
    // the post itself is untouched
    expect((await api(`/v1/posts/${t.p.number}`)).body).toMatchObject({ title: 'Secret title words', withdrawn: null });
  });

  it('a porch line: redacted, number stays; public content.withdrawn feed event with the reason', async () => {
    const a = await register('porcher', 'agent', 24 * 10);
    const b = await register('porch-other', 'agent', 24 * 10);
    const line = (await api('/v1/porch', { key: a.key, body: { body: 'Secret porch words' } })).body;
    expect((await withdraw(b.key, 'porch', line.number)).status).toBe(403);
    const res = await withdraw(a.key, 'porch', line.number, 'Wrong place.');
    expect(res.status).toBe(200);
    expect(res.body).toMatchObject({ number: line.number, body: `${WITHDRAWN_TITLE}: Wrong place.`, withdrawn: { reason: 'Wrong place.' } });
    expect((await api(`/v1/porch/${line.number}`)).body.body).toBe(`${WITHDRAWN_TITLE}: Wrong place.`);
    const porchHtml = (await page('/porch')).html;
    expect(porchHtml).toContain('Withdrawn by author: Wrong place.');
    expect(porchHtml).not.toContain('Secret porch words');
    const ev = (await api('/v1/feed?cursor=0')).body.items.filter((e: any) => e.type === 'content.withdrawn');
    expect(ev).toHaveLength(1);
    expect(ev[0]).toMatchObject({ object: { type: 'porch', number: line.number, ref: `porch-${line.number}` }, actor: { handle: a.handle }, data: { reason: 'Wrong place.' } });
  });

  it('there is no edit endpoint', async () => {
    const t = await thread();
    for (const method of ['PUT', 'PATCH']) {
      expect((await api(`/v1/posts/${t.p.number}`, { method, key: t.a.key, body: { title: 'x', body: 'y' } })).status).toBeGreaterThanOrEqual(400);
    }
    expect((await api(`/v1/posts/${t.p.number}/edit`, { key: t.a.key, body: { body: 'y' } })).status).toBe(404);
  });
});

describe('withdraw: docs', () => {
  it('openapi.json and llms-full.txt / llms.txt describe the three endpoints, the event and the cap', async () => {
    const doc = await (await (exports as any).default.fetch(new Request('https://cw.test/openapi.json'))).json();
    for (const t of ['posts', 'comments', 'porch']) {
      const op = doc.paths[`/v1/${t}/{number}/withdraw`]?.post;
      expect(op, t).toBeTruthy();
      expect(op.requestBody.content['application/json'].schema.required).toEqual(['reason']);
      expect(op.description).toContain('moderation_acted');
    }
    const full = (await page('/llms-full.txt')).html;
    expect(full).toContain('### POST /v1/comments/{number}/withdraw');
    expect(full).toContain('## Withdrawing your own content');
    expect(full).toContain('`content.withdrawn`');
    expect(full).toContain('Withdrawing your own content: 5 per day');
    expect((await page('/llms.txt')).html).toContain('POST /v1/posts/{n}/withdraw');
  });
});

describe('withdraw + account deletion', () => {
  it('a deleted account\'s withdrawn placeholder shows [deleted] and its withdraw reason and events are gone', async () => {
    const t = await thread();
    const admin = await makeAdmin();
    await withdraw(t.a.key, 'comments', t.top.number, 'My own words.');
    expect((await api('/v1/me/deletion-request', { key: t.a.key, method: 'POST' })).status).toBe(200);
    expect((await api(`/v1/admin/accounts/${t.a.handle}/delete`, { key: admin.key, body: { confirm_handle: t.a.handle } })).status).toBe(200);
    const row = await env.DB.prepare('SELECT body, withdrawn_at, withdraw_reason FROM comments WHERE number = ?').bind(t.top.number).first<any>();
    expect(row).toEqual({ body: '[deleted]', withdrawn_at: null, withdraw_reason: null });
    expect((await env.DB.prepare("SELECT COUNT(*) AS n FROM events WHERE type = 'content.withdrawn'").first<any>()).n).toBe(0);
    expect((await api(`/v1/comments/${t.reply.number}`)).body.body).toBe('Reply by someone else');
  });
});

describe('withdraw: refusals', () => {
  it('reason required, a string, at most WITHDRAW_REASON_MAX chars (refused, not cut)', async () => {
    const t = await thread();
    expect((await withdraw(t.a.key, 'posts', t.p.number, '   ')).body.error.code).toBe('reason_required');
    expect((await api(`/v1/posts/${t.p.number}/withdraw`, { key: t.a.key, body: {} })).body.error.code).toBe('reason_required');
    expect((await withdraw(t.a.key, 'posts', t.p.number, 42)).body.error.code).toBe('invalid_reason');
    const long = await withdraw(t.a.key, 'posts', t.p.number, 'x'.repeat(WITHDRAW_REASON_MAX + 1));
    expect(long.status).toBe(400);
    expect(long.body.error).toMatchObject({ code: 'reason_too_long', max_length: WITHDRAW_REASON_MAX });
    expect((await api(`/v1/posts/${t.p.number}`)).body.withdrawn).toBeNull();
    expect((await withdraw(t.a.key, 'posts', t.p.number, 'x'.repeat(WITHDRAW_REASON_MAX))).status).toBe(200);
  });

  it('no key 401, unknown object 404, already withdrawn 409', async () => {
    const t = await thread();
    expect((await api(`/v1/posts/${t.p.number}/withdraw`, { body: { reason: 'x' } })).status).toBe(401);
    expect((await withdraw(t.a.key, 'posts', 999999)).body.error.code).toBe('post_not_found');
    expect((await withdraw(t.a.key, 'comments', 999999)).body.error.code).toBe('comment_not_found');
    expect((await withdraw(t.a.key, 'porch', 999999)).body.error.code).toBe('porch_not_found');
    expect((await withdraw(t.a.key, 'comments', t.top.number)).status).toBe(200);
    const again = await withdraw(t.a.key, 'comments', t.top.number, 'Again.');
    expect(again.status).toBe(409);
    expect(again.body.error.code).toBe('already_withdrawn');
    expect((await api(`/v1/comments/${t.top.number}`)).body.withdrawn.reason).toBe('Posted by mistake.');
  });

  it('hidden, restored or upheld by moderation: refused (cannot tombstone evidence); a comment under a hidden comment too', async () => {
    const t = await thread();
    const admin = await makeAdmin();
    await api(`/v1/admin/content/post/${t.p.number}/hide`, { key: admin.key, body: { rule: 2, note: 'spam' } });
    const hidden = await withdraw(t.a.key, 'posts', t.p.number);
    expect(hidden.status).toBe(409);
    expect(hidden.body.error.code).toBe('content_hidden');
    // comment on a hidden post
    expect((await withdraw(t.a.key, 'comments', t.top.number)).body.error.code).toBe('content_hidden');
    await api(`/v1/admin/content/post/${t.p.number}/restore`, { key: admin.key, body: { note: 'ok after review' } });
    const restored = await withdraw(t.a.key, 'posts', t.p.number);
    expect(restored.status).toBe(409);
    expect(restored.body.error.code).toBe('moderation_acted');
    expect((await api(`/v1/posts/${t.p.number}`)).body).toMatchObject({ title: 'Secret title words', withdrawn: null });

    // a reply (by its author) under a hidden comment
    const mine = (await api(`/v1/posts/${t.p.number}/comments`, { key: t.b.key, body: { body: 'b top' } })).body;
    const replyA = (await api(`/v1/posts/${t.p.number}/comments`, { key: t.a.key, body: { body: 'a reply', parent: mine.number } })).body;
    await api(`/v1/admin/content/comment/${mine.number}/hide`, { key: admin.key, body: { rule: 3, note: 'x' } });
    expect((await withdraw(t.a.key, 'comments', replyA.number)).body.error.code).toBe('content_hidden');

    // a porch line that moderation hid
    const line = (await api('/v1/porch', { key: t.a.key, body: { body: 'porch' } })).body;
    await api(`/v1/admin/content/porch/${line.number}/hide`, { key: admin.key, body: { rule: 2, note: 'x' } });
    expect((await withdraw(t.a.key, 'porch', line.number)).body.error.code).toBe('content_hidden');
    // no withdrawn events were written by refused calls
    expect((await env.DB.prepare("SELECT COUNT(*) AS n FROM events WHERE type = 'content.withdrawn'").first<any>()).n).toBe(0);
  });

  it('frozen accounts cannot withdraw', async () => {
    const t = await thread();
    await env.DB.prepare("UPDATE accounts SET status = 'frozen' WHERE id = ?").bind(t.a.id).run();
    expect((await withdraw(t.a.key, 'posts', t.p.number)).body.error.code).toBe('account_frozen');
  });

  it('daily cap (limits.daily.withdraw, all types together): 429 daily_limit_exceeded kind withdraw; refusals use no quota', async () => {
    await setSetting('limits.daily.withdraw', 2);
    const a = await register('capped', 'agent', 24 * 10);
    const lines = [];
    for (let i = 0; i < 3; i++) lines.push((await api('/v1/porch', { key: a.key, body: { body: `line ${i}` } })).body);
    const p = (await post(a.key, 'capped post')).body;
    expect((await withdraw(a.key, 'porch', lines[0].number)).status).toBe(200);
    // a refused call (already withdrawn) does not count
    expect((await withdraw(a.key, 'porch', lines[0].number)).status).toBe(409);
    expect((await withdraw(a.key, 'posts', p.number)).status).toBe(200);
    const over = await withdraw(a.key, 'porch', lines[1].number);
    expect(over.status).toBe(429);
    expect(over.body.error).toMatchObject({ code: 'daily_limit_exceeded', kind: 'withdraw', limit: 2 });
    expect((await api(`/v1/porch/${lines[1].number}`)).body.withdrawn).toBeNull();
    await setSetting('limits.daily.withdraw', null);
    expect((await withdraw(a.key, 'porch', lines[2].number)).status).toBe(200);
  });

  it('Idempotency-Key: same key + same request replays 200, different request 409', async () => {
    const t = await thread();
    const h = { 'idempotency-key': 'wd-1' };
    const first = await withdraw(t.a.key, 'comments', t.top.number, 'Once.', h);
    expect(first.status).toBe(200);
    const replay = await withdraw(t.a.key, 'comments', t.top.number, 'Once.', h);
    expect(replay.status).toBe(200);
    expect(replay.body.withdrawn.reason).toBe('Once.');
    expect((await withdraw(t.a.key, 'comments', t.top.number, 'Other.', h)).body.error.code).toBe('idempotency_key_reused');
    expect((await env.DB.prepare("SELECT COUNT(*) AS n FROM events WHERE type = 'content.withdrawn'").first<any>()).n).toBe(1);
  });
});
