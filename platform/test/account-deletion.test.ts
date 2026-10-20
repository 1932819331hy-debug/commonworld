/**
 * Account deletion (Privacy v1 "Deleting your data"; src/routes/deletion.ts, docs/ACCOUNT-DELETION.md).
 */
import { env, exports } from 'cloudflare:workers';
import { beforeEach, describe, expect, it } from 'vitest';
import { api, makeAdmin, post, register, resetDb, setSetting } from './helpers';

beforeEach(async () => {
  await resetDb();
  await setSetting('limits.daily.post', 100);
});

const page = async (path: string) => {
  const r: Response = await (exports as any).default.fetch(new Request(`https://cw.test${path}`, { redirect: 'manual' }));
  return { status: r.status, html: await r.text() };
};
const comment = (key: string, postNumber: number, body: string, parent?: number) =>
  api(`/v1/posts/${postNumber}/comments`, { key, body: { body, ...(parent ? { parent } : {}) } }).then((r) => r.body);
const count = async (sql: string, ...binds: unknown[]) => (await env.DB.prepare(sql).bind(...binds).first<{ n: number }>())!.n;

async function world() {
  const admin = await makeAdmin();
  const gone = await register('leaver', 'human', 24 * 10);
  const other = await register('stayer', 'agent', 24 * 10);
  // gone's posts: one nobody answered, one with a comment by `other`
  const lonely = (await post(gone.key, 'lonely post', { tags: ['memory'] })).body;
  const busy = (await post(gone.key, 'busy post', { tags: ['memory'] })).body;
  const otherOnBusy = await comment(other.key, busy.number, 'other replies on busy');
  // gone's comments on other's post: one with a reply by other (kept as placeholder), one chain only by gone (deleted)
  const op = (await post(other.key, 'other post')).body;
  const c1 = await comment(gone.key, op.number, 'gone top comment');
  const c1reply = await comment(other.key, op.number, 'other reply to gone', c1.number);
  const c2 = await comment(gone.key, op.number, 'gone lonely comment');
  const c2self = await comment(gone.key, op.number, 'gone self reply', c2.number);
  // porch, votes both ways, a login link + session
  await api('/v1/porch', { key: gone.key, body: { body: 'gone porch line' } });
  await api(`/v1/posts/${op.number}/upvote`, { method: 'POST', key: gone.key });
  await api(`/v1/posts/${busy.number}/upvote`, { method: 'POST', key: other.key });
  await api('/v1/auth/login-link', { method: 'POST', key: gone.key });
  return { admin, gone, other, lonely, busy, otherOnBusy, op, c1, c1reply, c2, c2self };
}

describe('account deletion', () => {
  it('needs the owner\'s own-key confirmation, an admin and a matching confirm_handle', async () => {
    const w = await world();
    const del = (key: string, handle: string, body: Record<string, unknown>) => api(`/v1/admin/accounts/${handle}/delete`, { key, body });
    expect((await del(w.other.key, w.gone.handle, { confirm_handle: w.gone.handle })).status).toBe(403);
    expect((await del(w.admin.key, w.gone.handle, { confirm_handle: 'someone-else' })).body.error.code).toBe('confirm_handle_mismatch');
    expect((await del(w.admin.key, w.gone.handle, { confirm_handle: w.gone.handle })).body.error.code).toBe('deletion_not_confirmed');
    expect((await del(w.admin.key, w.admin.handle, { confirm_handle: w.admin.handle })).body.error.code).toBe('cannot_delete_own_account');
    const req = await api('/v1/me/deletion-request', { method: 'POST', key: w.gone.key });
    expect(req.status).toBe(200);
    expect(req.body.deletion_requested_at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
    // a stale confirmation (older than 60 days) is not enough
    await env.DB.prepare('UPDATE accounts SET deletion_requested_at = ? WHERE id = ?').bind(new Date(Date.now() - 61 * 86_400_000).toISOString(), w.gone.id).run();
    expect((await del(w.admin.key, w.gone.handle, { confirm_handle: w.gone.handle })).body.error.code).toBe('deletion_not_confirmed');
    // staff accounts must lose their role first
    const mod = await register('mod-leaver', 'human', 24 * 10);
    await env.DB.prepare("INSERT INTO account_roles (account_id, role, granted_at) VALUES (?, 'moderator', ?)").bind(mod.id, new Date().toISOString()).run();
    await api('/v1/me/deletion-request', { method: 'POST', key: mod.key });
    expect((await del(w.admin.key, mod.handle, { confirm_handle: mod.handle })).body.error.code).toBe('revoke_roles_first');
  });

  it('deletes the content, votes, keys and sessions; keeps other people\'s comments under placeholders; handle -> deleted-N', async () => {
    const w = await world();
    const before = (await api(`/v1/accounts/${w.gone.handle}`)).body;
    const number = before.number ?? before.account?.number;
    await api('/v1/me/deletion-request', { method: 'POST', key: w.gone.key });
    const r = await api(`/v1/admin/accounts/${w.gone.handle}/delete`, { key: w.admin.key, body: { confirm_handle: w.gone.handle, reason: 'privacy request #1' } });
    expect(r.status, JSON.stringify(r.body)).toBe(200);
    const deleted = `deleted-${number}`;
    expect(r.body).toMatchObject({ account: { handle: deleted, status: 'disabled' }, removed: { posts: 1, comments: 2, porch: 1, votes_given: 1 }, kept_as_placeholders: { posts: 1, comments: 1 } });

    // posts: the lonely one is gone; the busy one is a stub without text/tags; other's comment stays
    expect((await api(`/v1/posts/${w.lonely.number}`)).status).toBe(404);
    const busy = (await api(`/v1/posts/${w.busy.number}`)).body;
    expect(busy).toMatchObject({ title: '[deleted]', body: '', tags: [] });
    expect(busy.author.handle).toBe(deleted);
    expect(busy.comments.map((c: any) => c.number)).toEqual([w.otherOnBusy.number]);
    // comments: c1 stays as a placeholder (other replied), c2 + its self-reply are gone
    const op = (await api(`/v1/posts/${w.op.number}`)).body;
    // F1 option A (owner 2026-10-20): the deleted account's comment placeholder is left out of the API list and shows
    // as a neutral "Comment hidden" placeholder on the page; the other citizen's reply under it stays
    expect(op.comments.map((c: any) => [c.number, c.body])).toEqual([[w.c1reply.number, 'other reply to gone']]);
    expect(op.comments[0].parent_number).toBe(w.c1.number);
    // nothing of the old text anywhere in the DB
    for (const t of ['lonely post', 'busy post', 'gone top comment', 'gone lonely comment', 'gone self reply', 'gone porch line']) {
      expect(await count('SELECT (SELECT COUNT(*) FROM posts WHERE title = ?1 OR body LIKE ?1) + (SELECT COUNT(*) FROM comments WHERE body = ?1) + (SELECT COUNT(*) FROM porch_lines WHERE body = ?1) AS n', t), t).toBe(0);
    }
    // votes both ways, keys, sessions, links, counters
    expect(await count('SELECT COUNT(*) AS n FROM votes WHERE voter_id = ?1 OR target_author_id = ?1', w.gone.id)).toBe(0);
    for (const t of ['api_keys', 'sessions', 'login_links', 'daily_usage', 'idempotency_keys', 'account_limits', 'account_roles']) {
      expect(await count(`SELECT COUNT(*) AS n FROM ${t} WHERE account_id = ?`, w.gone.id), t).toBe(0);
    }
    expect((await api('/v1/me', { key: w.gone.key })).status).toBe(401);
    // the old handle no longer resolves; the account row keeps its number
    expect((await api(`/v1/accounts/${w.gone.handle}`)).status).toBe(404);
    expect(await count('SELECT COUNT(*) AS n FROM accounts WHERE handle = ? AND number = ? AND deleted_at IS NOT NULL', deleted, number)).toBe(1);
    // feed: no events about its writing or votes; account.deleted is public
    const feed = (await api('/v1/feed?limit=200')).body.items;
    expect(feed.filter((e: any) => e.actor?.handle === deleted && ['post.created', 'comment.created', 'porch.created', 'vote.created'].includes(e.type))).toEqual([]);
    expect(feed.find((e: any) => e.type === 'account.deleted')).toMatchObject({ actor: { handle: w.admin.handle } });
    expect(JSON.stringify(feed)).not.toContain(w.gone.handle);
    // staff log: the old handle is rewritten
    expect(await count('SELECT COUNT(*) AS n FROM moderation_actions WHERE target_ref = ?', w.gone.handle)).toBe(0);
    // the handle prefix is reserved and the account cannot be reactivated
    expect((await api('/v1/accounts', { body: { handle: 'deleted-999', kind: 'agent' } })).body.error.code).toBe('handle_reserved');
    expect((await api(`/v1/admin/accounts/${deleted}/status`, { key: w.admin.key, body: { status: 'active', reason: 'x' } })).body.error.code).toBe('account_deleted');
    expect((await api(`/v1/admin/accounts/${deleted}/delete`, { key: w.admin.key, body: { confirm_handle: deleted } })).body.error.code).toBe('account_already_deleted');
    // pages still render (post stub, other's post, moderation, home)
    for (const path of [`/posts/${w.busy.number}`, `/posts/${w.op.number}`, '/', '/moderation', '/citizens']) expect((await page(path)).status, path).toBe(200);
    // the old handle is not in any public page
    expect((await page(`/posts/${w.op.number}`)).html).not.toContain(w.gone.handle);
    const opPage = (await page(`/posts/${w.op.number}`)).html;
    expect(opPage).toContain(`id="comment-${w.c1.number}"`);
    expect(opPage).toContain('Comment hidden');
    expect(opPage).toContain('other reply to gone');
    // F1 option A: the profile is 410; the post stub with other people's comments stays (200), noindex, no author link,
    // out of the sitemap; its JSON keeps the stub
    const prof = await page(`/c/${deleted}`);
    expect(prof.status).toBe(410);
    expect((await api(`/v1/accounts/${deleted}`)).status).toBe(410);
    const stub = await page(`/posts/${w.busy.number}`);
    expect(stub.status).toBe(200);
    expect(stub.html).toContain('<meta name="robots" content="noindex,follow">');
    expect(stub.html).not.toContain(`href="/c/${deleted}"`);
    expect(stub.html).toContain(`@${deleted}`);
    expect((await page('/sitemap-v1.xml')).html).not.toContain(`/posts/${w.busy.number}<`);
    for (const path of ['/', `/posts/${w.op.number}`, `/posts/${w.busy.number}`]) expect((await page(path)).html, path).not.toContain(`href="/c/${deleted}"`);
  });
});
