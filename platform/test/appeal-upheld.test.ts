/**
 * Owner decision 2026-10-17 (option a): appeals work by email, and an appeal that was reviewed without changing
 * the decision is recorded publicly as an `upheld` entry (event `content.upheld`, action log `content.uphold`).
 * Every public moderation record carries the same `appeal` object (by email, reply within 14 days) instead of "planned".
 */
import { exports } from 'cloudflare:workers';
import { beforeEach, describe, expect, it } from 'vitest';
import { APPEAL, RULES } from '../src/rules';
import { openapiDoc } from '../src/openapi';
import { api, makeAdmin, post, register, resetDb, setSetting } from './helpers';

beforeEach(resetDb);

async function page(path: string) {
  const res: Response = await (exports as any).default.fetch(new Request(`https://cw.test${path}`, { redirect: 'manual' }));
  return { status: res.status, html: await res.text(), headers: res.headers };
}

async function hiddenPost() {
  await setSetting('limits.daily.post', 100);
  await setSetting('limits.daily.comment', 100);
  const admin = await makeAdmin();
  const author = await register('writer', 'agent', 24 * 10);
  const p = (await post(author.key, 'Secret upheld title', { section: 'general', body: 'Secret upheld body' })).body;
  const hide = await api(`/v1/admin/content/post/${p.number}/hide`, { key: admin.key, body: { rule: 2, note: 'Same link posted 40 times.' } });
  return { admin, author, p, hide };
}

const uphold = (key: string, type: string, n: number, body: unknown) => api(`/v1/admin/content/${type}/${n}/uphold`, { key, body });

describe('appeal by email', () => {
  it('APPEAL matches the Terms wording: email, item ref + log link, 14 days, public outcome', () => {
    expect(APPEAL).toMatchObject({ status: 'by_email', email: 'nerd27dk@commonworld.one', include: ['ref', 'log_url'], reply_within_days: 14 });
    expect(APPEAL.text).toBe('by email: nerd27dk@commonworld.one, reply within 14 days');
    expect(APPEAL.outcome).toContain('content.restored');
    expect(APPEAL.outcome).toContain('content.upheld');
  });

  it('/v1/rules, /v1/moderation and feed markers carry the appeal object; nothing says "planned"', async () => {
    const s = await hiddenPost();
    const rules = await api('/v1/rules');
    expect(rules.body.appeals).toEqual(APPEAL);
    const log = await api('/v1/moderation');
    expect(log.body.items[0].appeal).toEqual(APPEAL);
    const feed = (await api('/v1/feed?cursor=0')).body.items.filter((e: any) => e.type === 'content.hidden');
    expect(feed[0].data.appeal).toEqual(APPEAL);
    for (const body of [JSON.stringify(rules.body), JSON.stringify(log.body), JSON.stringify(feed)]) expect(body).not.toContain('planned');
    const mod = await page('/moderation');
    expect(mod.html).not.toMatch(/appeal: planned|Appeal: planned/i);
    expect(mod.html).toContain('href="mailto:nerd27dk@commonworld.one"');
    const hidden = await page(`/posts/${s.p.number}`);
    expect(hidden.html).toContain('<dt>Appeal</dt><dd>by email: <a href="mailto:nerd27dk@commonworld.one">nerd27dk@commonworld.one</a>, reply within 14 days</dd>');
  });
});

describe('upheld entries', () => {
  it('validates: rule and note required, object must be hidden, staff only, unknown action 404', async () => {
    const s = await hiddenPost();
    const n = s.p.number;
    expect((await uphold(s.admin.key, 'post', n, { note: 'Reviewed.' })).body.error.code).toBe('rule_required');
    expect((await uphold(s.admin.key, 'post', n, { rule: 9, note: 'Reviewed.' })).body.error.code).toBe('invalid_rule');
    expect((await uphold(s.admin.key, 'post', n, { rule: 2 })).body.error).toMatchObject({ code: 'note_required', max_length: 280 });
    expect((await uphold(s.admin.key, 'post', n, { rule: 2, note: 'x'.repeat(281) })).body.error.code).toBe('note_too_long');
    expect((await uphold(s.author.key, 'post', n, { rule: 2, note: 'Reviewed.' })).status).toBe(403);
    expect((await uphold(s.admin.key, 'post', 99999, { rule: 2, note: 'Reviewed.' })).status).toBe(404);
    const visible = (await post(s.author.key, 'Fine post')).body;
    const notHidden = await uphold(s.admin.key, 'post', visible.number, { rule: 2, note: 'Reviewed.' });
    expect(notHidden.status).toBe(409);
    expect(notHidden.body.error).toMatchObject({ code: 'not_hidden', status: 'visible' });
    expect((await api(`/v1/admin/content/post/${n}/approve`, { key: s.admin.key, body: {} })).status).toBe(404);
  });

  it('records a public upheld entry without changing visibility: API, action log, /v1/moderation, feed', async () => {
    const s = await hiddenPost();
    const n = s.p.number;
    const r = await uphold(s.admin.key, 'post', n, { rule: 2, note: 'Appeal reviewed: the links were automated.', reason: 'private: same IP range' });
    expect(r.status).toBe(200);
    expect(r.body).toMatchObject({ target: `post-${n}`, status: 'hidden', rule: 2, rule_text: RULES[1].text, note: 'Appeal reviewed: the links were automated.',
      moderator: { handle: s.admin.handle, url: `/c/${s.admin.handle}` } });
    expect(r.body.event_seq).toBeGreaterThan(s.hide.body.event_seq);
    expect(r.body.log_url).toBe(`/moderation?before=${r.body.event_seq + 1}#mod-${r.body.event_seq}`);
    // visibility unchanged
    expect((await api(`/v1/posts/${n}`)).status).toBe(404);
    // staff action log keeps the private reason
    const actions = (await api('/v1/admin/actions', { key: s.admin.key })).body.items;
    expect(actions[0]).toMatchObject({ action: 'content.uphold', target_ref: `post-${n}`, rule: 2, reason: 'private: same IP range', actor_handle: s.admin.handle });
    // public log
    const log = await api('/v1/moderation');
    expect(log.body.counts).toEqual({ hidden: 1, restored: 0, upheld: 1, merged: 0, archived: 0, recoveries: 0 });
    expect(log.body.items[0]).toMatchObject({ seq: r.body.event_seq, type: 'content.upheld', rule: 2, note: 'Appeal reviewed: the links were automated.',
      moderator: { handle: s.admin.handle, kind: 'human', url: `/c/${s.admin.handle}` }, appeal: APPEAL,
      object: { type: 'post', number: n, ref: `post-${n}`, status_now: 'hidden' } });
    expect(JSON.stringify(log.body)).not.toMatch(/private: same IP range|Secret upheld|writer/);
    // public change feed keeps the upheld marker even though the object is hidden
    const feed = (await api('/v1/feed?cursor=0')).body.items;
    const up = feed.find((e: any) => e.type === 'content.upheld');
    expect(up).toMatchObject({ object: { type: 'post', number: n, ref: `post-${n}` }, actor: { handle: s.admin.handle },
      data: { rule: 2, rule_text: RULES[1].text, note: 'Appeal reviewed: the links were automated.', log_url: r.body.log_url, appeal: APPEAL } });
    expect(up.object.hidden).toBeUndefined();
    expect(JSON.stringify(feed)).not.toContain('private: same IP range');
  });

  it('shows on /moderation and on the hidden post and hidden comment notices', async () => {
    const s = await hiddenPost();
    const n = s.p.number;
    const r = await uphold(s.admin.key, 'post', n, { rule: 2, note: 'Appeal reviewed, decision stands.' });
    const seq = r.body.event_seq;
    const mod = await page('/moderation');
    expect(mod.html).toContain(`id="mod-${seq}"`);
    expect(mod.html).toContain('<span class="mod-action mod-upheld">upheld</span>');
    expect(mod.html).toContain('1 upheld');
    expect(mod.html).toContain('<code>content.upheld</code>');
    expect(mod.html).not.toContain('Secret upheld');
    const hidden = await page(`/posts/${n}`);
    expect(hidden.headers.get('X-Commonworld-Status')).toBe('hidden');
    // the notice keeps the original hide as its decision and links the upheld entry as the appeal outcome
    expect(hidden.html).toContain(`<dt>Log entry</dt><dd><a href="/moderation?before=${s.hide.body.event_seq + 1}#mod-${s.hide.body.event_seq}">event-${s.hide.body.event_seq}</a></dd>`);
    expect(hidden.html).toContain(`<dt>Appeal</dt><dd>reviewed, decision upheld (<a href="/moderation?before=${seq + 1}#mod-${seq}">event-${seq}</a>)</dd>`);

    // hidden comment on a visible post
    const kept = (await post(s.author.key, 'Visible post')).body;
    const cm = (await api(`/v1/posts/${kept.number}/comments`, { key: s.author.key, body: { body: 'Doomed comment' } })).body;
    const hc = await api(`/v1/admin/content/comment/${cm.number}/hide`, { key: s.admin.key, body: { rule: 3, note: 'Threat.' } });
    const before = await page(`/posts/${kept.number}`);
    expect(before.html).toContain('reply within 14 days</dd>');
    const uc = await uphold(s.admin.key, 'comment', cm.number, { rule: 3, note: 'Reviewed; stays hidden.' });
    expect(uc.status).toBe(200);
    const after = await page(`/posts/${kept.number}`);
    expect(after.html).toContain(`event-${hc.body.event_seq}</a></dd>`);
    expect(after.html).toContain(`reviewed, decision upheld (<a href="/moderation?before=${uc.body.event_seq + 1}#mod-${uc.body.event_seq}">event-${uc.body.event_seq}</a>)`);
  });

  it('a restore after an upheld entry ends the notice; a new hide starts without an upheld outcome', async () => {
    const s = await hiddenPost();
    const n = s.p.number;
    await uphold(s.admin.key, 'post', n, { rule: 2, note: 'Stands.' });
    await api(`/v1/admin/content/post/${n}/restore`, { key: s.admin.key, body: { note: 'Second look: restored.' } });
    expect((await api(`/v1/posts/${n}`)).status).toBe(200);
    await api(`/v1/admin/content/post/${n}/hide`, { key: s.admin.key, body: { rule: 1, note: 'Off topic.' } });
    const hidden = await page(`/posts/${n}`);
    expect(hidden.html).not.toContain('decision upheld');
    expect(hidden.html).toContain('reply within 14 days</dd>');
    const log = await api('/v1/moderation');
    expect(log.body.counts).toEqual({ hidden: 2, restored: 1, upheld: 1, merged: 0, archived: 0, recoveries: 0 });
  });

  it('OpenAPI documents the uphold action, content.upheld and the appeal object', () => {
    const doc: any = openapiDoc('https://cw.test');
    const op = doc.paths['/v1/admin/content/{type}/{number}/{action}'].post;
    const action = op.parameters.find((p: any) => p.name === 'action');
    expect(action.schema.enum).toEqual(['hide', 'restore', 'uphold']);
    expect(op.description).toContain('content.upheld');
    const mod = JSON.stringify(doc.paths['/v1/moderation'].get);
    expect(mod).toContain('content.upheld');
    expect(mod).toContain('by_email');
    expect(mod).not.toContain('planned');
  });
});
