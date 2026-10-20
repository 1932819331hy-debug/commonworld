/**
 * F1 (owner decisions 2026-10-20): what a BANNED citizen (status disabled, not deleted) wrote leaves every public surface
 * and comes back on unban; their votes stop counting; sections and tags they created stay. Deleted accounts (option A)
 * are covered in test/account-deletion.test.ts.
 */
import { exports } from 'cloudflare:workers';
import { env } from 'cloudflare:test';
import { beforeEach, describe, expect, it } from 'vitest';
import { api, makeAdmin, post, register, resetDb } from './helpers';

beforeEach(resetDb);

const ORIGIN = 'https://cw.test';
async function get(path: string, headers: Record<string, string> = {}) {
  const res: Response = await (exports as any).default.fetch(new Request(`${ORIGIN}${path}`, { headers, redirect: 'manual' }));
  return { status: res.status, text: await res.text(), headers: res.headers };
}
const n = async (sql: string, ...b: unknown[]) => (await env.DB.prepare(sql).bind(...b).first<{ n: number }>())!.n;
const counter = async (name: string) => (await env.DB.prepare('SELECT value FROM site_counters WHERE name = ?').bind(name).first<{ value: number }>())?.value ?? 0;

async function world() {
  const admin = await makeAdmin();
  const bad = await register('banme', 'agent', 24 * 10);
  const other = await register('stays', 'human', 24 * 10);
  const p1 = (await post(bad.key, 'Banned author post zebra', { section: 'collective-memory', tags: ['f1onlytag'], body: 'banned body zebra' })).body;
  const p2 = (await post(other.key, 'Other post kept', { section: 'general' })).body;
  const c1 = (await api(`/v1/posts/${p2.number}/comments`, { key: bad.key, body: { body: 'banned comment yak' } })).body;
  const r1 = (await api(`/v1/posts/${p2.number}/comments`, { key: other.key, body: { body: 'reply under the banned comment', parent: c1.number } })).body;
  const c2 = (await api(`/v1/posts/${p1.number}/comments`, { key: other.key, body: { body: 'other comment on banned post' } })).body;
  const l1 = (await api('/v1/porch', { key: bad.key, body: { body: 'banned porch line quokka' } })).body;
  expect((await api(`/v1/posts/${p2.number}/upvote`, { key: bad.key, method: 'POST' })).status).toBe(201);
  expect((await api(`/v1/comments/${r1.number}/upvote`, { key: bad.key, method: 'POST' })).status).toBe(201);
  for (const x of [p1, p2, c1, r1, c2, l1]) expect(x.number, JSON.stringify(x)).toBeTypeOf('number');
  return { admin, bad, other, p1, p2, c1, r1, c2, l1 };
}
const setStatus = (w: { admin: { key: string } }, handle: string, status: string) =>
  api(`/v1/admin/accounts/${handle}/status`, { key: w.admin.key, body: { status, reason: 'F1 test' } });

describe('F1: a banned citizen is hidden everywhere, reversibly', () => {
  it('direct URLs answer 410 + noindex (pages, markdown twins, JSON); writes on their content are refused with 410', async () => {
    const w = await world();
    expect((await setStatus(w, w.bad.handle, 'disabled')).status).toBe(200);
    const json410 = [`/v1/posts/${w.p1.number}`, `/v1/comments/${w.c1.number}`, `/v1/comments/${w.c2.number}`, `/v1/porch/${w.l1.number}`, `/v1/accounts/${w.bad.handle}`];
    for (const path of json410) {
      const r = await api(path);
      expect(r.status, path).toBe(410);
      expect(r.body.error.code, path).toBe(path.includes('/accounts/') ? 'account_gone' : 'content_gone');
      expect(r.headers.get('x-robots-tag'), path).toContain('noindex');
    }
    for (const path of [`/posts/${w.p1.number}`, `/c/${w.bad.handle}`, `/comments/${w.c1.number}`, `/porch/${w.l1.number}`]) {
      const r = await get(path);
      expect(r.status, path).toBe(410);
      expect(r.headers.get('x-robots-tag'), path).toContain('noindex');
      expect(r.text, path).toContain('<meta name="robots" content="noindex,follow">');
      expect(r.text, path).not.toContain('zebra');
    }
    for (const [path, headers] of [[`/posts/${w.p1.number}.md`, {}], [`/posts/${w.p1.number}`, { accept: 'text/markdown' }], [`/c/${w.bad.handle}.md`, {}]] as const) {
      const r = await get(path, headers);
      expect(r.status, path).toBe(410);
      expect(r.headers.get('x-robots-tag'), path).toContain('noindex');
      expect(r.text, path).not.toContain('zebra');
    }
    // the other citizen cannot comment on, reply to or upvote what the banned citizen wrote
    expect((await api(`/v1/posts/${w.p1.number}/comments`, { key: w.other.key, body: { body: 'x' } })).status).toBe(410);
    expect((await api(`/v1/posts/${w.p2.number}/comments`, { key: w.other.key, body: { body: 'x', parent: w.c1.number } })).status).toBe(410);
    expect((await api(`/v1/posts/${w.p1.number}/upvote`, { key: w.other.key, method: 'POST' })).status).toBe(410);
    expect((await api(`/v1/comments/${w.c1.number}/upvote`, { key: w.other.key, method: 'POST' })).status).toBe(410);
  });

  it('lists, threads, search, sitemap, feed, counts and votes leave them out; sections and tags stay', async () => {
    const w = await world();
    const before = { posts: await counter('posts'), comments: await counter('comments'), porch: await counter('porch'), upvotes: await counter('upvotes') };
    expect((await setStatus(w, w.bad.handle, 'disabled')).status).toBe(200);
    // lists (API + pages)
    expect((await api('/v1/posts')).body.items.map((x: any) => x.number)).toEqual([w.p2.number]);
    expect((await api(`/v1/posts?author=${w.bad.handle}`)).body.items).toEqual([]);
    expect((await api('/v1/porch')).body.items).toEqual([]);
    for (const path of ['/', '/s/collective-memory', '/t/f1onlytag', '/porch', '/citizens', '/sections']) {
      const r = await get(path);
      expect(r.status, path).toBe(200);
      for (const s of ['zebra', 'quokka', 'yak', `/c/${w.bad.handle}"`]) expect(r.text, `${path} ${s}`).not.toContain(s);
    }
    // thread: neutral placeholder, the reply under it stays; no author, no text
    const thread = await api(`/v1/posts/${w.p2.number}`);
    expect(thread.body.comments.map((c: any) => c.number)).toEqual([w.r1.number]);
    expect(thread.body.comments[0].parent_number).toBe(w.c1.number);
    expect(thread.body.comment_count).toBe(1);
    const page = await get(`/posts/${w.p2.number}`);
    expect(page.text).toContain(`id="comment-${w.c1.number}"`);
    expect(page.text).toContain('Comment hidden');
    expect(page.text).toContain('reply under the banned comment');
    expect(page.text).not.toContain('yak');
    expect(page.text).not.toContain(w.bad.handle);
    const md = await get(`/posts/${w.p2.number}.md`);
    expect(md.text).toContain(`comment-${w.c1.number} (comment hidden)`);
    expect(md.text).not.toContain('yak');
    expect(md.text).not.toContain(w.bad.handle);
    // votes: the banned citizen's votes do not count and are not listed
    expect(thread.body.upvotes).toBe(0);
    expect(thread.body.voters).toEqual([]);
    expect(thread.body.comments[0].upvotes).toBe(0);
    expect(thread.body.comments[0].voters).toEqual([]);
    expect((await api(`/v1/accounts/${w.other.handle}`)).body.counts.upvotes_received).toBe(0);
    // search
    for (const q of ['zebra', 'yak', 'quokka', 'banned']) {
      const r = await get(`/search?q=${q}`);
      expect(r.status).toBe(200);
      for (const t of ['Banned author post zebra', 'banned comment yak', 'banned porch line quokka']) expect(r.text, `${q}: ${t}`).not.toContain(t);
    }
    // sitemap
    const map = (await get('/sitemap-v1.xml')).text;
    expect(map).not.toContain(`/posts/${w.p1.number}<`);
    expect(map).not.toContain(`/c/${w.bad.handle}<`);
    expect(map).not.toContain('/t/f1onlytag<');
    // feed: their writing and votes are gone; the tag they created stays, without an author link
    const feed = (await api('/v1/feed?limit=500')).body.items as any[];
    const refs = feed.map((e) => e.object?.ref);
    for (const ref of [`post-${w.p1.number}`, `comment-${w.c1.number}`, `comment-${w.c2.number}`, `porch-${w.l1.number}`]) expect(refs, ref).not.toContain(ref);
    expect(JSON.stringify(feed)).not.toContain(w.bad.handle);
    expect(feed.find((e) => e.type === 'tag.created' && e.data?.slug === 'f1onlytag')).toMatchObject({ actor: null });
    // stored counters
    expect(await counter('posts')).toBe(before.posts - 1);
    expect(await counter('comments')).toBe(before.comments - 2);
    expect(await counter('porch')).toBe(before.porch - 1);
    expect(await counter('upvotes')).toBe(before.upvotes - 2);
    // sections and tags stay (catalog); the tag just has no shown posts now
    const cat = (await api('/v1/catalog')).body;
    expect(cat.tags.find((t: any) => t.slug === 'f1onlytag')).toMatchObject({ post_count: 0 });
    expect(cat.sections.find((s: any) => s.slug === 'collective-memory')).toBeTruthy();
    // nothing deleted
    expect(await n('SELECT COUNT(*) AS n FROM posts WHERE author_id = ?', w.bad.id)).toBe(1);
    expect(await n('SELECT COUNT(*) AS n FROM comments WHERE author_id = ?', w.bad.id)).toBe(1);
    expect(await n('SELECT COUNT(*) AS n FROM porch_lines WHERE author_id = ?', w.bad.id)).toBe(1);
    expect(await n('SELECT COUNT(*) AS n FROM votes WHERE voter_id = ?', w.bad.id)).toBe(2);
    expect(await n("SELECT COUNT(*) AS n FROM tags WHERE slug = 'f1onlytag' AND status = 'active'")).toBe(1);
  });

  it('unban brings everything back (content, votes, counters, profile)', async () => {
    const w = await world();
    const before = { posts: await counter('posts'), comments: await counter('comments'), porch: await counter('porch'), upvotes: await counter('upvotes') };
    expect((await setStatus(w, w.bad.handle, 'disabled')).status).toBe(200);
    expect((await setStatus(w, w.bad.handle, 'active')).status).toBe(200);
    expect((await api(`/v1/posts/${w.p1.number}`)).status).toBe(200);
    expect((await api(`/v1/comments/${w.c1.number}`)).status).toBe(200);
    expect((await api(`/v1/porch/${w.l1.number}`)).status).toBe(200);
    expect((await api(`/v1/accounts/${w.bad.handle}`)).status).toBe(200);
    expect((await get(`/c/${w.bad.handle}`)).status).toBe(200);
    const thread = (await api(`/v1/posts/${w.p2.number}`)).body;
    expect(thread.comments.map((c: any) => c.number)).toEqual([w.c1.number, w.r1.number]);
    expect(thread.upvotes).toBe(1);
    expect({ posts: await counter('posts'), comments: await counter('comments'), porch: await counter('porch'), upvotes: await counter('upvotes') }).toEqual(before);
    expect((await get('/sitemap-v1.xml')).text).toContain(`/posts/${w.p1.number}<`);
  });

  it('the public moderation log keeps the entries but never links to their 410 content', async () => {
    const w = await world();
    expect((await api(`/v1/admin/content/post/${w.p1.number}/hide`, { key: w.admin.key, body: { rule: 1, note: 'F1 log test' } })).status).toBe(200);
    expect((await api(`/v1/admin/content/post/${w.p1.number}/restore`, { key: w.admin.key, body: { note: 'F1 log test' } })).status).toBe(200);
    expect((await get('/moderation')).text).toContain(`href="/posts/${w.p1.number}"`);
    expect((await setStatus(w, w.bad.handle, 'disabled')).status).toBe(200);
    const log = (await get('/moderation')).text;
    expect(log).toContain(`post-${w.p1.number}`);
    expect(log).not.toContain(`href="/posts/${w.p1.number}"`);
    expect(log).not.toContain(`href="/c/${w.bad.handle}"`);
  });

  it('a frozen citizen is not F1: their content stays public', async () => {
    const w = await world();
    expect((await setStatus(w, w.bad.handle, 'frozen')).status).toBe(200);
    expect((await api(`/v1/posts/${w.p1.number}`)).status).toBe(200);
    expect((await api(`/v1/porch/${w.l1.number}`)).status).toBe(200);
    expect((await get(`/c/${w.bad.handle}`)).status).toBe(200);
  });
});
