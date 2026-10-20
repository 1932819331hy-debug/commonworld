import { beforeEach, describe, expect, it } from 'vitest';
import { env } from 'cloudflare:workers';
import { api, post, recount, register, resetDb, setSetting } from './helpers';

beforeEach(resetDb);

async function scene() {
  await setSetting('limits.daily.post', 10);
  const h1 = await register('human-a', 'human', 24 * 10);
  const g1 = await register('agent-b', 'agent', 24 * 10);
  const g2 = await register('agent-c', 'agent', 24 * 10);
  // h1: 2 posts; g1: 1 post + upvote from h1 and g2; g2: 3 comments
  const p1 = (await post(h1.key, 'h1 a')).body;
  await post(h1.key, 'h1 b');
  const gp = (await post(g1.key, 'g1 a')).body;
  await api(`/v1/posts/${gp.number}/upvote`, { method: 'POST', key: h1.key });
  await api(`/v1/posts/${gp.number}/upvote`, { method: 'POST', key: g2.key });
  for (let i = 0; i < 3; i++) await api(`/v1/posts/${p1.number}/comments`, { key: g2.key, body: { body: `c${i}` } });
  return { h1, g1, g2 };
}

const handles = (res: any) => res.body.items.map((i: any) => i.account.handle);

describe('leaderboard', () => {
  it('sorts by karma all-time: g1 13, h1 6, g2 6 (ties by registration order)', async () => {
    const { h1, g1, g2 } = await scene();
    const res = await api('/v1/leaderboard');
    expect(res.status).toBe(200);
    expect(handles(res)).toEqual([g1.handle, h1.handle, g2.handle]);
    expect(res.body.items[0]).toMatchObject({ rank: 1, karma: 13 });
    expect(res.body.karma_formula).toEqual({ upvote: 5, post: 3, comment: 2, porch: 1 });
  });

  it('sorts by posts, comments and newest', async () => {
    const { h1, g1, g2 } = await scene();
    expect(handles(await api('/v1/leaderboard?sort=posts'))[0]).toBe(h1.handle);
    expect(handles(await api('/v1/leaderboard?sort=comments'))[0]).toBe(g2.handle);
    expect(handles(await api('/v1/leaderboard?sort=newest'))).toEqual([g2.handle, g1.handle, h1.handle]);
  });

  it('karma_7d only counts the last 7 days', async () => {
    const { h1, g1 } = await scene();
    const old = new Date(Date.now() - 8 * 24 * 3_600_000).toISOString();
    await env.DB.prepare('UPDATE votes SET created_at = ?').bind(old).run();
    await env.DB.prepare('UPDATE posts SET created_at = ? WHERE author_id = ?').bind(old, g1.id).run();
    await recount(); // raw-SQL time travel bypasses the write paths (the nightly reconcile repairs that)
    const res = await api('/v1/leaderboard?sort=karma_7d');
    expect(handles(res)[0]).not.toBe(g1.handle);
    const g1Row = res.body.items.find((i: any) => i.account.handle === g1.handle);
    expect(g1Row).toMatchObject({ karma: 13, karma_7d: 0 });
    expect(res.body.items.find((i: any) => i.account.handle === h1.handle).karma_7d).toBe(6);
  });

  it('filters by kind and validates parameters', async () => {
    const { h1 } = await scene();
    expect(handles(await api('/v1/leaderboard?kind=human'))).toEqual([h1.handle]);
    expect(handles(await api('/v1/leaderboard?kind=agent'))).toHaveLength(2);
    expect((await api('/v1/leaderboard?sort=money')).body.error.code).toBe('invalid_sort');
    expect((await api('/v1/leaderboard?kind=robot')).status).toBe(400);
    expect((await api('/v1/leaderboard?limit=1000')).status).toBe(400);
  });

  it('profile shows counts and karma', async () => {
    const { g1 } = await scene();
    const prof = (await api(`/v1/accounts/${g1.handle}`)).body;
    expect(prof).toMatchObject({ karma: 13, counts: { posts: 1, upvotes_received: 2, upvotes_counted: 2 } });
    expect((await api('/v1/accounts/nobody-here')).status).toBe(404);
  });
});
