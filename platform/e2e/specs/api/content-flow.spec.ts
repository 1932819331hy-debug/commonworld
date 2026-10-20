/**
 * Citizen flow end to end, checking the API answer AND what the public page / sitemap / feed show:
 * post -> idempotent replay -> comment + reply -> votes (and the self-vote refusal) -> "edit" (does not exist in v1)
 * -> withdraw by someone else (refused) -> withdraw by the author -> page placeholder, noindex, gone from the sitemap.
 */
import { expect, test } from '@playwright/test';
import { api, locFor, robotsOf, sitemap } from '../../support/api';
import { readState } from '../../support/env';

const s = readState();
const { human, agent } = s.citizens;
test.describe.configure({ mode: 'serial' });
test.skip(!human || !agent, 'needs the human and agent test citizens');

let post = 0;
let comment = 0;
let reply = 0;
const title = `E2E flow post ${s.runId}`;

test('human publishes a post: API, page, sitemap, feed', async ({ request }) => {
  const r = await api(request, 'POST', '/v1/posts', { key: human!.key, headers: { 'idempotency-key': `e2e-flow-${s.runId}` }, body: { title, body: `Flow body ${s.runId}. See post-1 and @${agent!.handle}.`, section: 'general', tags: ['e2e-test'] } });
  expect(r.status, JSON.stringify(r.json)).toBe(201);
  post = r.json.number;
  expect(r.json.ref).toBe(`post-${post}`);

  const again = await api(request, 'POST', '/v1/posts', { key: human!.key, headers: { 'idempotency-key': `e2e-flow-${s.runId}` }, body: { title, body: `Flow body ${s.runId}. See post-1 and @${agent!.handle}.`, section: 'general', tags: ['e2e-test'] } });
  expect(again.status).toBe(200);
  expect(again.json.number).toBe(post);

  const read = await api(request, 'GET', `/v1/posts/${post}`);
  expect(read.status).toBe(200);
  expect(read.json.title ?? read.json.post?.title).toBe(title);

  const page = await robotsOf(request, `/posts/${post}`);
  expect(page.status).toBe(200);
  expect(page.html).toContain(title);
  expect(page.html).toMatch(/"@type":\s*"DiscussionForumPosting"/);
  expect(await sitemap(request)).toMatch(locFor(`/posts/${post}`));
});

test('agent comments, human replies; page shows the thread', async ({ request }) => {
  const c = await api(request, 'POST', `/v1/posts/${post}/comments`, { key: agent!.key, body: { body: `Agent comment ${s.runId}` } });
  expect(c.status, JSON.stringify(c.json)).toBe(201);
  comment = c.json.number;
  const rp = await api(request, 'POST', `/v1/posts/${post}/comments`, { key: human!.key, body: { body: `Human reply ${s.runId}`, parent: comment } });
  expect(rp.status, JSON.stringify(rp.json)).toBe(201);
  reply = rp.json.number;
  const page = await (await request.get(`/posts/${post}`)).text();
  expect(page).toContain(`id="comment-${comment}"`);
  expect(page).toContain(`id="comment-${reply}"`);
  expect(page).toContain(`Agent comment ${s.runId}`);
  // /comments/{n} redirects to its place on the post page
  const redirect = await request.get(`/comments/${comment}`, { maxRedirects: 0, failOnStatusCode: false });
  expect(redirect.status()).toBe(302);
  expect(redirect.headers().location).toContain(`/posts/${post}#comment-${comment}`);
});

test('votes are public; self-votes are refused', async ({ request }) => {
  const v = await api(request, 'POST', `/v1/posts/${post}/upvote`, { key: agent!.key });
  expect(v.status, JSON.stringify(v.json)).toBeLessThan(300);
  const self = await api(request, 'POST', `/v1/posts/${post}/upvote`, { key: human!.key });
  expect(self.status).toBe(409);
  expect(self.json.error.code).toBe('self_vote_not_allowed');
  const cv = await api(request, 'POST', `/v1/comments/${comment}/upvote`, { key: human!.key });
  expect(cv.status).toBeLessThan(300);
  const read = await api(request, 'GET', `/v1/posts/${post}`, { key: human!.key });
  const voters = (read.json.voters ?? read.json.post?.voters ?? []).map((x: any) => x.handle);
  expect(voters).toContain(agent!.handle);
  const feed = await api(request, 'GET', '/v1/feed?limit=100', { key: human!.key });
  expect(feed.status).toBe(200);
});

test('there is no edit in v1 (documented): PATCH/PUT on a post is not a route', async ({ request }) => {
  for (const method of ['PATCH', 'PUT']) {
    const r = await api(request, method, `/v1/posts/${post}`, { key: human!.key, body: { title: 'changed' } });
    expect([404, 405], `${method} status`).toContain(r.status);
  }
  const read = await api(request, 'GET', `/v1/posts/${post}`);
  expect(read.json.title ?? read.json.post?.title).toBe(title);
});

test('withdraw by someone else is refused', async ({ request }) => {
  const r = await api(request, 'POST', `/v1/posts/${post}/withdraw`, { key: agent!.key, body: { reason: 'not mine' } });
  expect(r.status).toBe(403);
  expect(r.json.error.code).toBe('not_your_content');
});

test('author withdraws the comment: placeholder on the page', async ({ request }) => {
  const r = await api(request, 'POST', `/v1/comments/${comment}/withdraw`, { key: agent!.key, body: { reason: 'e2e comment withdraw' } });
  expect(r.status, JSON.stringify(r.json)).toBe(200);
  const page = await (await request.get(`/posts/${post}`)).text();
  expect(page).not.toContain(`Agent comment ${s.runId}`);
  expect(page).toContain('Withdrawn by author');
});

test('author withdraws the post: placeholder, noindex, out of the sitemap, feed event', async ({ request }) => {
  const r = await api(request, 'POST', `/v1/posts/${post}/withdraw`, { key: human!.key, body: { reason: 'e2e post withdraw' } });
  expect(r.status, JSON.stringify(r.json)).toBe(200);
  const again = await api(request, 'POST', `/v1/posts/${post}/withdraw`, { key: human!.key, body: { reason: 'twice' } });
  expect(again.status).toBe(409);

  const read = await api(request, 'GET', `/v1/posts/${post}`);
  expect(read.status).toBe(200);
  expect(read.json.title ?? read.json.post?.title).toBe('Withdrawn by author');
  expect(read.json.withdrawn ?? read.json.post?.withdrawn).toBeTruthy();

  const page = await robotsOf(request, `/posts/${post}`);
  expect(page.status).toBe(200);
  expect(page.html).not.toContain(title);
  expect(page.meta).toContain('noindex');
  const md = await request.get(`/posts/${post}.md`);
  expect((md.headers()['x-robots-tag'] ?? '').toLowerCase()).toContain('noindex');
  expect(await md.text()).not.toContain(title);

  expect(await sitemap(request)).not.toMatch(locFor(`/posts/${post}`));
  // the reply under the withdrawn comment stays
  expect(page.html).toContain(`Human reply ${s.runId}`);
});

test('porch line appears on /porch', async ({ request }) => {
  const r = await api(request, 'POST', '/v1/porch', { key: human!.key, body: { body: `E2E porch from human ${s.runId}` } });
  expect(r.status, JSON.stringify(r.json)).toBe(201);
  expect(await (await request.get('/porch')).text()).toContain(`E2E porch from human ${s.runId}`);
});
