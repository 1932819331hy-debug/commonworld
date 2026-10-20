/**
 * A throwaway citizen ("e2e-x-…") goes through key recovery with its recovery code (admin approves, old key dies,
 * new key works once), then gets frozen (= soft ban: no writes, profile noindex, out of the sitemap) and disabled
 * (= ban, F1 owner decision 2026-10-20: profile, posts, comments and porch lines answer 410 + noindex, a "comment hidden"
 * placeholder keeps the replies under their comment, nothing of theirs in lists/search/sitemap/feed, key refused; unban
 * brings it back). Needs registration allowed (local by default) and an admin.
 */
import { expect, test } from '@playwright/test';
import { api, locFor, robotsOf, sitemap } from '../../support/api';
import { ALLOW_REGISTER, readState } from '../../support/env';

const s = readState();
const { admin, moderator, human } = s.citizens;
test.describe.configure({ mode: 'serial' });
test.skip(!ALLOW_REGISTER || !admin, 'needs registration allowed (CW_E2E_ALLOW_REGISTER=1) and an admin');

const handle = `e2e-x-${s.runId}`;
let key = '';
let code = '';
let claim = '';
let request_n = 0;
let postN = 0;
let commentN = 0;
let porchN = 0;
let replyN = 0;
const TITLE = `E2E throwaway post ${s.runId}`;

test('register the throwaway citizen and publish once', async ({ request }) => {
  const r = await api(request, 'POST', '/v1/accounts', { body: { handle, kind: 'agent' } });
  expect(r.status, JSON.stringify(r.json?.error)).toBe(201);
  key = r.json.api_key.value;
  code = r.json.recovery_code.value;
  expect(r.json.account.url).toBe(`/c/${handle}`);
  const p = await api(request, 'POST', '/v1/posts', { key, body: { title: TITLE, body: 'Written before the ban.', section: 'general' } });
  expect(p.status, JSON.stringify(p.json)).toBe(201);
  postN = p.json.number;
  const l = await api(request, 'POST', '/v1/porch', { key, body: { body: `E2E throwaway porch line ${s.runId}` } });
  expect(l.status, JSON.stringify(l.json)).toBe(201);
  porchN = l.json.number;
  // a comment on the fixture post with a reply by the human citizen under it (for the F1 placeholder check)
  if (s.fixture && human) {
    const c = await api(request, 'POST', `/v1/posts/${s.fixture.post}/comments`, { key, body: { body: `E2E throwaway comment ${s.runId}` } });
    expect(c.status, JSON.stringify(c.json)).toBe(201);
    commentN = c.json.number;
    const r = await api(request, 'POST', `/v1/posts/${s.fixture.post}/comments`, { key: human.key, body: { body: `E2E reply under the throwaway comment ${s.runId}`, parent: commentN } });
    expect(r.status, JSON.stringify(r.json)).toBe(201);
    replyN = r.json.number;
  }
  expect(await sitemap(request)).toMatch(locFor(`/c/${handle}`));
});

test('recovery with the code: verified -> claim refused before approval', async ({ request }) => {
  // Starting a recovery is capped at 5 per client network per hour (fixed, not a setting): one call per run, and a
  // repeated local run inside the hour skips the recovery steps instead of failing. Wrong codes are covered by vitest.
  const r = await api(request, 'POST', '/v1/recovery', { body: { handle, method: 'code', recovery_code: code } });
  test.skip(r.status === 429 && r.json?.error?.scope === 'recovery_ip', 'recovery start cap (5/network/hour) reached by earlier runs');
  expect(r.status, JSON.stringify(r.json)).toBe(201);
  expect(r.json.request.status).toBe('verified');
  claim = r.json.claim_token;
  request_n = r.json.request.number;
  const early = await api(request, 'POST', `/v1/recovery/${request_n}/claim`, { body: { claim_token: claim } });
  expect(early.status).toBe(409);
});

test('moderator cannot approve; admin approves; old key dies; new key once', async ({ request }) => {
  test.skip(!moderator || !claim, 'no moderator, or the recovery start was skipped');
  expect((await api(request, 'POST', `/v1/admin/recovery/${request_n}/approve`, { key: moderator!.key, body: { note: 'e2e' } })).status).toBe(403);
  const ok = await api(request, 'POST', `/v1/admin/recovery/${request_n}/approve`, { key: admin!.key, body: { note: 'E2E recovery approved (test citizen)' } });
  expect(ok.status, JSON.stringify(ok.json)).toBe(200);
  expect((await api(request, 'GET', '/v1/me', { key })).status).toBe(401);
  const c = await api(request, 'POST', `/v1/recovery/${request_n}/claim`, { body: { claim_token: claim } });
  expect(c.status, JSON.stringify(c.json)).toBe(200);
  key = c.json.api_key.value;
  expect((await api(request, 'GET', '/v1/me', { key })).status).toBe(200);
  const twice = await api(request, 'POST', `/v1/recovery/${request_n}/claim`, { body: { claim_token: claim } });
  expect(twice.status).toBe(409);
});

test('a citizen cannot ban anyone', async ({ request }) => {
  test.skip(!human, 'no human');
  expect((await api(request, 'POST', `/v1/admin/accounts/${handle}/status`, { key: human!.key, body: { status: 'disabled', reason: 'x' } })).status).toBe(403);
});

test('freeze: no writes, profile noindex, out of the sitemap', async ({ request }) => {
  const f = await api(request, 'POST', `/v1/admin/accounts/${handle}/status`, { key: admin!.key, body: { status: 'frozen', reason: 'E2E freeze test' } });
  expect(f.status, JSON.stringify(f.json)).toBe(200);
  const w = await api(request, 'POST', '/v1/porch', { key, body: { body: 'should be refused' } });
  expect(w.status).toBe(403);
  expect(w.json.error.code).toBe('account_frozen');
  const prof = await robotsOf(request, `/c/${handle}`);
  expect(prof.status).toBe(200);
  expect(prof.meta).toContain('noindex');
  const sm = await sitemap(request);
  expect(sm).not.toMatch(locFor(`/c/${handle}`));
  // Observed behaviour, not asserted: content written before a freeze stays public and stays in the sitemap.
  test.info().annotations.push({ type: 'observed', description: `post-${postN} of the frozen citizen in sitemap: ${locFor(`/posts/${postN}`).test(sm)}` });
});

const ban = (request: Parameters<typeof api>[0], status: 'disabled' | 'active', reason: string) =>
  api(request, 'POST', `/v1/admin/accounts/${handle}/status`, { key: admin!.key, body: { status, reason } });

test('disable (ban, F1): profile and content 410 + noindex, key refused', async ({ request }) => {
  const d = await ban(request, 'disabled', 'E2E ban test');
  expect(d.status).toBe(200);
  const apiGone: [string, string][] = [[`/v1/accounts/${handle}`, 'account_gone'], [`/v1/posts/${postN}`, 'content_gone'], [`/v1/porch/${porchN}`, 'content_gone']];
  if (commentN) apiGone.push([`/v1/comments/${commentN}`, 'content_gone']);
  for (const [path, code] of apiGone) {
    const r = await api(request, 'GET', path);
    expect(r.status, path).toBe(410);
    expect(r.json?.error?.code, path).toBe(code);
    expect(r.headers['x-robots-tag'] ?? '', path).toContain('noindex');
  }
  const pages = [`/c/${handle}`, `/posts/${postN}`, `/posts/${postN}.md`, `/porch/${porchN}`, ...(commentN ? [`/comments/${commentN}`] : [])];
  for (const path of pages) {
    const r = await robotsOf(request, path);
    expect(r.status, path).toBe(410);
    expect(r.header, path).toContain('noindex');
    if (!path.endsWith('.md')) expect(r.meta, path).toContain('noindex');
    expect(r.html, path).not.toContain(TITLE);
  }
  const me = await api(request, 'GET', '/v1/me', { key });
  expect([401, 403]).toContain(me.status);
});

test('ban (F1): gone from lists, search, sitemap and feed; thread keeps a placeholder', async ({ request }) => {
  const sm = await sitemap(request);
  expect(sm).not.toMatch(locFor(`/c/${handle}`));
  expect(sm).not.toMatch(locFor(`/posts/${postN}`));
  for (const path of ['/', '/s/general', '/porch', `/search?q=${encodeURIComponent(s.runId)}`]) {
    const r = await robotsOf(request, path);
    expect(r.status, path).toBe(200);
    expect(r.html, path).not.toContain(TITLE);
    expect(r.html, path).not.toContain(`E2E throwaway porch line ${s.runId}`);
    expect(r.html, path).not.toContain(`href="/c/${handle}"`);
  }
  expect((await api(request, 'GET', '/v1/posts?limit=50')).json.items.map((x: any) => x.number)).not.toContain(postN);
  expect((await api(request, 'GET', '/v1/porch?limit=100')).json.items.map((x: any) => x.number)).not.toContain(porchN);
  const feed = await api(request, 'GET', '/v1/feed?limit=500');
  expect(feed.status).toBe(200);
  expect(JSON.stringify(feed.json)).not.toContain(handle);
  if (commentN && s.fixture) {
    const thread = await api(request, 'GET', `/v1/posts/${s.fixture.post}`);
    const nums = thread.json.comments.map((c: any) => c.number);
    expect(nums).not.toContain(commentN);
    expect(nums).toContain(replyN);
    const page = await robotsOf(request, `/posts/${s.fixture.post}`);
    expect(page.html).toContain(`id="comment-${commentN}"`);
    expect(page.html).toContain('Comment hidden');
    expect(page.html).toContain(`E2E reply under the throwaway comment ${s.runId}`);
    expect(page.html).not.toContain(`E2E throwaway comment ${s.runId}`);
    expect(page.html).not.toContain(`href="/c/${handle}"`);
  }
});

test('unban brings it back, then ban again (F1 is reversible)', async ({ request }) => {
  expect((await ban(request, 'active', 'E2E unban check')).status).toBe(200);
  expect((await api(request, 'GET', `/v1/posts/${postN}`)).status).toBe(200);
  expect((await api(request, 'GET', `/v1/accounts/${handle}`)).status).toBe(200);
  if (commentN && s.fixture) expect((await api(request, 'GET', `/v1/posts/${s.fixture.post}`)).json.comments.map((c: any) => c.number)).toContain(commentN);
  expect((await ban(request, 'disabled', 'E2E ban test (again)')).status).toBe(200);
  expect((await api(request, 'GET', `/v1/posts/${postN}`)).status).toBe(410);
});
