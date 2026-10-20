/** Auth model and role boundaries: anyone / citizen (human, agent) / moderator / admin. */
import { expect, test } from '@playwright/test';
import { api } from '../../support/api';
import { readState } from '../../support/env';

const s = readState();
const { human, agent, moderator, admin } = s.citizens;

test('health answers', async ({ request }) => {
  const r = await api(request, 'GET', '/health');
  expect(r.status).toBe(200);
  expect(r.json.ok).toBe(true);
});

test('no key and a bad key are refused on /v1/me', async ({ request }) => {
  expect((await api(request, 'GET', '/v1/me')).status).toBe(401);
  expect((await api(request, 'GET', '/v1/me', { key: 'cw1_definitely-not-a-real-key-000000000000000' })).status).toBe(401);
});

test('test citizens: kind and roles are what the plan expects', async ({ request }) => {
  test.skip(!human || !agent, 'no human/agent test citizen');
  const h = await api(request, 'GET', '/v1/me', { key: human!.key });
  expect(h.status).toBe(200);
  expect(h.json.account.kind).toBe('human');
  expect(h.json.account.roles).toEqual([]);
  // every keyed /v1 response carries the per-account minute window headers
  expect(h.headers['ratelimit-limit']).toBeTruthy();
  expect(h.headers['ratelimit-policy']).toBeTruthy();
  const a = await api(request, 'GET', '/v1/me', { key: agent!.key });
  expect(a.json.account.kind).toBe('agent');
});

test('citizen cannot reach staff routes', async ({ request }) => {
  test.skip(!human, 'no human test citizen');
  expect((await api(request, 'GET', '/v1/admin/citizens', { key: human!.key })).status).toBe(403);
  expect((await api(request, 'GET', '/v1/admin/actions', { key: human!.key })).status).toBe(403);
  expect((await api(request, 'POST', '/v1/admin/content/post/1/hide', { key: human!.key, body: { rule: 2, note: 'e2e' } })).status).toBe(403);
  expect((await api(request, 'GET', '/v1/admin/citizens')).status).toBe(401);
});

test('moderator: staff reads yes, admin-only routes no', async ({ request }) => {
  test.skip(!moderator, 'no moderator test citizen');
  expect((await api(request, 'GET', '/v1/admin/citizens', { key: moderator!.key })).status).toBe(200);
  expect((await api(request, 'GET', '/v1/admin/modes', { key: moderator!.key })).status).toBe(200);
  expect((await api(request, 'PATCH', '/v1/admin/settings', { key: moderator!.key, body: { values: { announcement: null } } })).status).toBe(403);
  expect((await api(request, 'GET', '/v1/admin/recovery', { key: moderator!.key })).status).toBe(403);
  expect((await api(request, 'POST', `/v1/admin/accounts/${human?.handle ?? 'nobody'}/status`, { key: moderator!.key, body: { status: 'frozen', reason: 'e2e' } })).status).toBe(403);
});

test('admin: settings, recovery queue and citizens readable', async ({ request }) => {
  test.skip(!admin, 'no admin test citizen');
  expect((await api(request, 'GET', '/v1/admin/settings', { key: admin!.key })).status).toBe(200);
  expect((await api(request, 'GET', '/v1/admin/recovery', { key: admin!.key })).status).toBe(200);
  const c = await api(request, 'GET', '/v1/admin/citizens', { key: admin!.key });
  expect(c.status).toBe(200);
});

test('admin cannot change own status', async ({ request }) => {
  test.skip(!admin, 'no admin test citizen');
  const r = await api(request, 'POST', `/v1/admin/accounts/${admin!.handle}/status`, { key: admin!.key, body: { status: 'frozen', reason: 'e2e self-check' } });
  expect(r.status).toBe(409);
  expect(r.json.error.code).toBe('cannot_change_own_status');
});

test('the /admin page is staff-only', async ({ request }) => {
  const r = await request.get('/admin', { failOnStatusCode: false, maxRedirects: 0 });
  expect(r.status()).toBe(401);
  expect(r.headers()['cache-control']).toContain('no-store');
});
