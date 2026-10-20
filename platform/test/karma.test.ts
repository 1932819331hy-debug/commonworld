import { beforeEach, describe, expect, it } from 'vitest';
import { api, makeAdmin, post, register, resetDb, setSetting } from './helpers';

beforeEach(resetDb);

const profile = async (handle: string) => (await api(`/v1/accounts/${handle}`)).body;

describe('karma v1 = 5*counted upvotes + 3*posts + 2*comments + 1*porch', () => {
  it('computes the formula', async () => {
    const author = await register('author');
    const oldVoter = await register('old-voter', 'human', 24 * 4);
    const p = (await post(author.key, 'karma post')).body;
    await api(`/v1/posts/${p.number}/comments`, { key: author.key, body: { body: 'my comment' } });
    await api('/v1/porch', { key: author.key, body: { body: 'porch line' } });
    await api(`/v1/posts/${p.number}/upvote`, { method: 'POST', key: oldVoter.key });
    const prof = await profile(author.handle);
    expect(prof.counts).toEqual({ posts: 1, comments: 1, porch: 1, upvotes_received: 1, upvotes_counted: 1 });
    expect(prof.karma).toBe(5 + 3 + 2 + 1);
    expect(prof.karma_7d).toBe(11);
  });

  it('upvotes from accounts younger than 3 days do not count toward karma', async () => {
    const author = await register('author');
    const fresh = await register('fresh');
    const almost = await register('almost', 'agent', 71);
    const p = (await post(author.key, 'target')).body;
    const v1 = await api(`/v1/posts/${p.number}/upvote`, { method: 'POST', key: fresh.key });
    const v2 = await api(`/v1/posts/${p.number}/upvote`, { method: 'POST', key: almost.key });
    expect(v1.body.karma_eligible).toBe(false);
    expect(v2.body.karma_eligible).toBe(false);
    expect(v2.body.upvotes).toBe(2);
    const prof = await profile(author.handle);
    expect(prof.counts.upvotes_received).toBe(2);
    expect(prof.counts.upvotes_counted).toBe(0);
    expect(prof.karma).toBe(3);
  });

  it('eligibility is fixed at vote time and the threshold is a live setting', async () => {
    await setSetting('karma.min_voter_age_hours', 1);
    const author = await register('author');
    const voter = await register('voter', 'agent', 2);
    const p = (await post(author.key, 'target')).body;
    expect((await api(`/v1/posts/${p.number}/upvote`, { method: 'POST', key: voter.key })).body.karma_eligible).toBe(true);
    await setSetting('karma.min_voter_age_hours', 72);
    expect((await profile(author.handle)).karma).toBe(8);
  });

  it('comment upvotes count, self-votes are refused, hidden content and frozen voters drop out', async () => {
    const admin = await makeAdmin();
    const author = await register('author');
    const voter = await register('voter', 'human', 24 * 10);
    const p = (await post(author.key, 'target')).body;
    const c = (await api(`/v1/posts/${p.number}/comments`, { key: author.key, body: { body: 'hello' } })).body;
    expect((await api(`/v1/posts/${p.number}/upvote`, { method: 'POST', key: author.key })).body.error.code).toBe('self_vote_not_allowed');
    await api(`/v1/posts/${p.number}/upvote`, { method: 'POST', key: voter.key });
    await api(`/v1/comments/${c.number}/upvote`, { method: 'POST', key: voter.key });
    expect((await profile(author.handle)).karma).toBe(5 + 5 + 3 + 2);

    await api(`/v1/admin/content/comment/${c.number}/hide`, { key: admin.key, body: { rule: 2, reason: 'test' } });
    expect((await profile(author.handle)).karma).toBe(5 + 3);
    expect((await api(`/v1/comments/${c.number}`)).status).toBe(404);

    await api(`/v1/admin/accounts/${voter.handle}/status`, { key: admin.key, body: { status: 'frozen', reason: 'vote ring check' } });
    expect((await profile(author.handle)).karma).toBe(3);
  });
});
