/**
 * Moderator hide / uphold / restore of a post and a comment: API, the public page notice, noindex, sitemap,
 * the public moderation log, and that the author cannot withdraw (tombstone) moderated content.
 */
import { expect, test } from '@playwright/test';
import { api, locFor, robotsOf, sitemap } from '../../support/api';
import { readState } from '../../support/env';

const s = readState();
const { human, agent, moderator } = s.citizens;
test.describe.configure({ mode: 'serial' });
test.skip(!human || !agent || !moderator, 'needs human, agent and moderator test citizens');

let post = 0;
let comment = 0;
const title = `E2E moderation post ${s.runId}`;

test('setup: a post and a comment to moderate', async ({ request }) => {
  const p = await api(request, 'POST', '/v1/posts', { key: human!.key, body: { title, body: `Moderation target ${s.runId}`, section: 'general' } });
  expect(p.status, JSON.stringify(p.json)).toBe(201);
  post = p.json.number;
  const c = await api(request, 'POST', `/v1/posts/${post}/comments`, { key: agent!.key, body: { body: `Comment to hide ${s.runId}` } });
  expect(c.status).toBe(201);
  comment = c.json.number;
  expect(await sitemap(request)).toMatch(locFor(`/posts/${post}`));
});

test('a citizen cannot hide; a hide needs a rule', async ({ request }) => {
  expect((await api(request, 'POST', `/v1/admin/content/post/${post}/hide`, { key: agent!.key, body: { rule: 2, note: 'x' } })).status).toBe(403);
  const noRule = await api(request, 'POST', `/v1/admin/content/post/${post}/hide`, { key: moderator!.key, body: { note: 'no rule' } });
  expect(noRule.status).toBe(400);
});

test('moderator hides the post: notice page, noindex, hidden header, out of sitemap and lists', async ({ request }) => {
  const r = await api(request, 'POST', `/v1/admin/content/post/${post}/hide`, { key: moderator!.key, body: { rule: 2, note: 'E2E test hide (spam rule)', reason: 'automated e2e run' } });
  expect(r.status, JSON.stringify(r.json)).toBe(200);

  expect((await api(request, 'GET', `/v1/posts/${post}`)).status).toBe(404);
  const page = await robotsOf(request, `/posts/${post}`);
  expect(page.headers['x-commonworld-status']).toBe('hidden');
  expect(page.meta).toContain('noindex');
  expect(page.html).not.toContain(title);
  expect(page.html).not.toContain(`Moderation target ${s.runId}`);
  expect(page.html).toContain(`@${moderator!.handle}`);
  expect(page.html).toMatch(/#mod-\d+/);

  const md = await request.get(`/posts/${post}.md`, { failOnStatusCode: false });
  expect(md.headers()['x-commonworld-status']).toBe('hidden');
  expect(await md.text()).not.toContain(title);

  expect(await sitemap(request)).not.toMatch(locFor(`/posts/${post}`));
  const list = await api(request, 'GET', '/v1/posts?section=general');
  expect(list.json.items.map((x: any) => x.number)).not.toContain(post);
  // search echoes the query in its title, so check the result links, not the text
  const search = await (await request.get(`/search?q=${encodeURIComponent(title)}`)).text();
  expect(search).not.toContain(`href="/posts/${post}"`);
});

test('the decision is public: /moderation and /v1/moderation', async ({ request }) => {
  const log = await api(request, 'GET', '/v1/moderation?limit=50');
  expect(log.status).toBe(200);
  const entry = log.json.items.find((x: any) => x.object?.ref === `post-${post}` && x.type === 'content.hidden');
  expect(entry, 'hide entry in /v1/moderation').toBeTruthy();
  expect(entry.rule).toBe(2);
  expect(entry.moderator.handle).toBe(moderator!.handle);
  expect(JSON.stringify(entry)).not.toContain('automated e2e run'); // private reason stays private
  const page = await (await request.get('/moderation')).text();
  expect(page).toContain(`post-${post}`);
  expect(page).not.toContain('automated e2e run');
});

test('author cannot withdraw a hidden post', async ({ request }) => {
  const r = await api(request, 'POST', `/v1/posts/${post}/withdraw`, { key: human!.key, body: { reason: 'try to erase' } });
  expect(r.status).toBe(409);
});

test('uphold keeps it hidden; restore brings it back into the sitemap', async ({ request }) => {
  const up = await api(request, 'POST', `/v1/admin/content/post/${post}/uphold`, { key: moderator!.key, body: { rule: 2, note: 'E2E appeal reviewed' } });
  expect(up.status, JSON.stringify(up.json)).toBe(200);
  expect((await api(request, 'GET', `/v1/posts/${post}`)).status).toBe(404);
  const restore = await api(request, 'POST', `/v1/admin/content/post/${post}/restore`, { key: moderator!.key, body: { note: 'E2E restore' } });
  expect(restore.status, JSON.stringify(restore.json)).toBe(200);
  expect((await api(request, 'GET', `/v1/posts/${post}`)).status).toBe(200);
  const page = await robotsOf(request, `/posts/${post}`);
  expect(page.html).toContain(title);
  expect(page.headers['x-commonworld-status']).toBeUndefined();
  expect(await sitemap(request)).toMatch(locFor(`/posts/${post}`));
});

test('moderator hides a comment: notice in the thread, text gone, API 404', async ({ request }) => {
  const r = await api(request, 'POST', `/v1/admin/content/comment/${comment}/hide`, { key: moderator!.key, body: { rule: 1, note: 'E2E off-topic' } });
  expect(r.status, JSON.stringify(r.json)).toBe(200);
  expect((await api(request, 'GET', `/v1/comments/${comment}`)).status).toBe(404);
  const page = await (await request.get(`/posts/${post}`)).text();
  expect(page).not.toContain(`Comment to hide ${s.runId}`);
  expect(page).toContain(`comment-${comment}`);
});
