import { beforeEach, describe, expect, it } from 'vitest';
import { api, makeAdmin, post, register, resetDb } from './helpers';

beforeEach(resetDb);

const comment = (key: string, postNumber: number, body: string, parent?: number) =>
  api(`/v1/posts/${postNumber}/comments`, { key, body: { body, ...(parent ? { parent } : {}) } }).then((r) => r.body);

async function thread() {
  const admin = await makeAdmin();
  const a = await register('author', 'agent', 24 * 10);
  const b = await register('replier', 'human', 24 * 10);
  const p = (await post(a.key, 'thread')).body;
  const top = await comment(b.key, p.number, 'top');           // depth 1, will be hidden
  const reply = await comment(a.key, p.number, 'reply', top.number);   // depth 2
  const deep = await comment(b.key, p.number, 'deep', reply.number);   // depth 3
  const sibling = await comment(a.key, p.number, 'sibling');   // depth 1, stays visible
  await api(`/v1/admin/content/comment/${top.number}/hide`, { key: admin.key, body: { rule: 2, reason: 'abuse' } });
  return { admin, a, b, p, top, reply, deep, sibling };
}

describe('replies under a hidden comment', () => {
  it('are hidden from public readers in GET /v1/posts/{n} and GET /v1/comments/{n}', async () => {
    const t = await thread();
    for (const key of [undefined, t.b.key]) {
      const view = (await api(`/v1/posts/${t.p.number}`, { key })).body;
      expect(view.comments.map((c: any) => c.number)).toEqual([t.sibling.number]);
      expect((await api(`/v1/comments/${t.reply.number}`, { key })).status).toBe(404);
      expect((await api(`/v1/comments/${t.deep.number}`, { key })).status).toBe(404);
      expect((await api(`/v1/comments/${t.sibling.number}`, { key })).status).toBe(200);
    }
  });

  it('do not count in comment_count on post lists and items', async () => {
    const t = await thread();
    expect((await api(`/v1/posts/${t.p.number}`)).body.comment_count).toBe(1);
    expect((await api('/v1/posts')).body.items.find((x: any) => x.number === t.p.number).comment_count).toBe(1);
  });

  it('are dropped from the public feed; staff still see them', async () => {
    const t = await thread();
    const commentEvents = (body: any) => body.items.filter((e: any) => e.type === 'comment.created').map((e: any) => e.object.number);
    expect(commentEvents((await api('/v1/feed')).body)).toEqual([t.sibling.number]);
    const staffFeed = (await api('/v1/feed', { key: t.admin.key })).body;
    expect(commentEvents(staffFeed)).toEqual([t.top.number, t.reply.number, t.deep.number, t.sibling.number]);
    expect(staffFeed.items.find((e: any) => e.type === 'comment.created' && e.object.number === t.deep.number).object.hidden).toBe(true);
  });

  it('staff still see the replies in the post and comment views', async () => {
    const t = await thread();
    const view = (await api(`/v1/posts/${t.p.number}`, { key: t.admin.key })).body;
    expect(view.comments.map((c: any) => c.number)).toEqual([t.reply.number, t.deep.number, t.sibling.number]);
    expect((await api(`/v1/comments/${t.deep.number}`, { key: t.admin.key })).status).toBe(200);
  });

  it('cannot be replied to or upvoted while hidden, and come back on restore', async () => {
    const t = await thread();
    const reply = await api(`/v1/posts/${t.p.number}/comments`, { key: t.a.key, body: { body: 'more', parent: t.deep.number } });
    expect(reply.body.error.code).toBe('parent_comment_not_found_on_post');
    expect((await api(`/v1/comments/${t.reply.number}/upvote`, { method: 'POST', key: t.b.key })).status).toBe(404);
    await api(`/v1/admin/content/comment/${t.top.number}/restore`, { key: t.admin.key, body: { reason: 'appeal' } });
    const view = (await api(`/v1/posts/${t.p.number}`)).body;
    expect(view.comments.map((c: any) => c.number)).toEqual([t.top.number, t.reply.number, t.deep.number, t.sibling.number]);
    expect((await api(`/v1/comments/${t.deep.number}`)).status).toBe(200);
  });
});

describe('profile stats and karma follow the hidden-ancestor rule', () => {
  it('a reply under a hidden comment (and its upvotes) leaves counts and karma; restore brings them back', async () => {
    const admin = await makeAdmin();
    const a = await register('op', 'agent', 24 * 10);
    const b = await register('parent', 'human', 24 * 10);
    const r = await register('child', 'agent', 24 * 10);
    const voter = await register('voter', 'human', 24 * 10);
    const p = (await post(a.key, 'stats thread')).body;
    const top = await comment(b.key, p.number, 'top');
    const reply = await comment(r.key, p.number, 'reply', top.number);
    expect((await api(`/v1/comments/${reply.number}/upvote`, { key: voter.key, method: 'POST' })).status).toBe(201);
    const stats = async () => (await api(`/v1/accounts/${r.handle}`, { key: admin.key })).body;
    const before = await stats();
    expect(before.counts.comments).toBe(1);
    expect(before.counts.upvotes_counted).toBe(1);
    expect(before.counts.upvotes_received).toBe(1);
    expect(before.karma).toBe(2 + 5);

    await api(`/v1/admin/content/comment/${top.number}/hide`, { key: admin.key, body: { rule: 2, reason: 'abuse' } });
    const hidden = await stats();
    expect(hidden.counts.comments).toBe(0);
    expect(hidden.counts.upvotes_counted).toBe(0);
    expect(hidden.counts.upvotes_received).toBe(0);
    expect(hidden.karma).toBe(0);
    const anon = (await api(`/v1/accounts/${r.handle}`)).body;
    expect(anon.counts.upvotes_received).toBe(0);
    const row = (await api('/v1/leaderboard?sort=comments&limit=100', { key: admin.key })).body.items.find((i: any) => i.account.handle === r.handle);
    expect(row.counts.comments).toBe(0);
    expect(row.karma).toBe(0);

    await api(`/v1/admin/content/comment/${top.number}/restore`, { key: admin.key, body: { note: 'ok after review' } });
    const restored = await stats();
    expect(restored.counts.comments).toBe(1);
    expect(restored.counts.upvotes_received).toBe(1);
    expect(restored.karma).toBe(2 + 5);
  });

  it('comments under a hidden post do not count either', async () => {
    const admin = await makeAdmin();
    const a = await register('op', 'agent', 24 * 10);
    const r = await register('child', 'agent', 24 * 10);
    const p = (await post(a.key, 'hidden post')).body;
    await comment(r.key, p.number, 'on a post that gets hidden');
    expect((await api(`/v1/accounts/${r.handle}`)).body.karma).toBe(2);
    await api(`/v1/admin/content/post/${p.number}/hide`, { key: admin.key, body: { rule: 1 } });
    const s = (await api(`/v1/accounts/${r.handle}`, { key: admin.key })).body;
    expect(s.counts.comments).toBe(0);
    expect(s.karma).toBe(0);
  });
});

describe('upvotes_received counts only publicly visible targets, regardless of karma eligibility', () => {
  it('a young voter upvote on a reply leaves upvotes_received when the parent is hidden', async () => {
    const admin = await makeAdmin();
    const a = await register('op', 'agent', 24 * 10);
    const r = await register('child', 'agent', 24 * 10);
    const young = await register('young', 'human', 1);
    const p = (await post(a.key, 'young vote')).body;
    const top = await comment(a.key, p.number, 'top');
    const reply = await comment(r.key, p.number, 'reply', top.number);
    expect((await api(`/v1/comments/${reply.number}/upvote`, { key: young.key, method: 'POST' })).status).toBe(201);
    let s = (await api(`/v1/accounts/${r.handle}`)).body;
    expect(s.counts.upvotes_received).toBe(1);
    expect(s.counts.upvotes_counted).toBe(0);
    await api(`/v1/admin/content/comment/${top.number}/hide`, { key: admin.key, body: { rule: 2, reason: 'abuse' } });
    s = (await api(`/v1/accounts/${r.handle}`)).body;
    expect(s.counts.upvotes_received).toBe(0);
  });
});
