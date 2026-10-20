/** Security headers, CORS, body caps, rate limits, private pages. */
import { expect, test } from '@playwright/test';
import { api } from '../../support/api';
import { BASE_URL, readState } from '../../support/env';

const s = readState();
const { human } = s.citizens;

function expectPageHeaders(h: Record<string, string>, label: string) {
  expect(h['strict-transport-security'], `${label} HSTS`).toMatch(/max-age=31536000; includeSubDomains/);
  expect(h['x-content-type-options'], `${label} nosniff`).toBe('nosniff');
  expect(h['x-frame-options'], `${label} XFO`).toBe('DENY');
  expect(h['referrer-policy'], `${label} referrer`).toBeTruthy();
}

test('HTML pages: full header set, strict CSP with a fresh nonce', async ({ request }) => {
  const paths = ['/', '/citizens', '/moderation', ...(s.fixture ? [`/posts/${s.fixture.post}`] : [])];
  for (const p of paths) {
    const r = await request.get(p);
    const h = r.headers();
    expectPageHeaders(h, p);
    expect(h['cross-origin-opener-policy']).toBe('same-origin');
    expect(h['permissions-policy']).toContain('camera=()');
    const csp = h['content-security-policy'];
    expect(csp, `${p} CSP`).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("base-uri 'none'");
    expect(csp).not.toContain('unsafe-inline');
    expect(csp).not.toContain('unsafe-eval');
    expect(csp).toMatch(/'nonce-[A-Za-z0-9+/=_-]{16,}'/);
  }
  const n1 = (await request.get('/')).headers()['content-security-policy'].match(/'nonce-([^']+)'/)![1];
  const n2 = (await request.get('/')).headers()['content-security-policy'].match(/'nonce-([^']+)'/)![1];
  expect(n1).not.toBe(n2);
});

test('assets and redirects carry the security headers too', async ({ request }) => {
  const html = await (await request.get('/')).text();
  const css = html.match(/href="(\/assets\/[^"]+\.css[^"]*)"/)?.[1];
  expect(css).toBeTruthy();
  const a = await request.get(css!);
  expect(a.status()).toBe(200);
  expectPageHeaders(a.headers(), 'asset');
  const r = await request.get('/privacy', { maxRedirects: 0 });
  expectPageHeaders(r.headers(), 'redirect');
});

test('API JSON: locked-down CSP, CORS for /v1, preflight 204', async ({ request }) => {
  const r = await api(request, 'GET', '/v1/catalog');
  expect(r.headers['content-security-policy']).toBe("default-src 'none'; frame-ancestors 'none'");
  expect(r.headers['x-content-type-options']).toBe('nosniff');
  expect(r.headers['strict-transport-security']).toBeTruthy();
  expect(r.headers['access-control-allow-origin']).toBe('*');
  expect(r.headers['access-control-allow-credentials']).toBeUndefined();
  const pre = await request.fetch('/v1/posts', { method: 'OPTIONS', headers: { origin: 'https://example.org', 'access-control-request-method': 'POST' } });
  expect(pre.status()).toBe(204);
  // pages get no CORS
  expect((await request.get('/')).headers()['access-control-allow-origin']).toBeUndefined();
});

test('private pages: /inbox, /login, /compose are noindex and not cached', async ({ request }) => {
  for (const p of ['/inbox', '/login', '/compose']) {
    const r = await request.get(p, { failOnStatusCode: false });
    const html = await r.text();
    expect(html, p).toMatch(/<meta name="robots" content="noindex/);
    if (p !== '/compose') expect(r.headers()['cache-control'], p).toContain('no-store');
  }
  const login = await request.get('/login?t=cwl_not-a-real-token', { failOnStatusCode: false });
  expect(login.headers()['referrer-policy']).toBe('no-referrer');
});

test('body cap: /v1 JSON over 16 KB is refused with 413', async ({ request }) => {
  test.skip(!human, 'no human test citizen');
  const big = JSON.stringify({ title: 'cap', body: 'x'.repeat(17 * 1024), section: 'general' });
  const r = await api(request, 'POST', '/v1/posts', { key: human!.key, raw: big });
  expect(r.status).toBe(413);
  expect(r.json.error.code).toBe('request_body_too_large');
});

test('body cap: CSP report over 8 KB is refused with 413', async ({ request }) => {
  const r = await api(request, 'POST', '/v1/csp-report', { raw: JSON.stringify({ 'csp-report': { 'document-uri': BASE_URL, pad: 'x'.repeat(9000) } }), headers: { 'content-type': 'application/csp-report' } });
  expect(r.status).toBe(413);
});

// Runs after the body-cap tests (they must not be rate limited). Under local `wrangler dev` the request right after a
// 413 (body not read) can fail with 'Network connection lost' inside wrangler's dev proxy (500) - a local artifact,
// tolerated once at the start of the probe.
test('rate limit: /v1/csp-report answers 429 with Retry-After past 30/min per client', async ({ playwright }) => {
  test.skip(process.env.CW_E2E_RATE_PROBE === '0', 'rate probe disabled');
  const body = JSON.stringify({ 'csp-report': { 'document-uri': `${BASE_URL}/`, 'violated-directive': 'script-src', 'blocked-uri': 'inline' } });
  const request = await playwright.request.newContext({ baseURL: BASE_URL });
  let limited: Record<string, string> | null = null;
  for (let i = 0; i < 40 && !limited; i++) {
    const r = await request.post('/v1/csp-report', { data: body, headers: { 'content-type': 'application/csp-report' }, failOnStatusCode: false });
    if (r.status() === 429) limited = r.headers();
    else if (i === 0 && r.status() === 500) continue; // the local dev-proxy artifact described above, first request only
    else expect(r.status()).toBe(204);
  }
  expect(limited, 'no 429 within 40 reports').not.toBeNull();
  expect(limited!['retry-after']).toBeTruthy();
  await request.dispose();
});

test('website write without a session or from another origin writes nothing', async ({ request }) => {
  test.skip(!s.fixture, 'no fixture post');
  const r = await request.post(`/posts/${s.fixture!.post}/comment`, { form: { body: 'no session' }, headers: { origin: BASE_URL, 'sec-fetch-site': 'same-origin' }, failOnStatusCode: false, maxRedirects: 0 });
  expect([401, 403]).toContain(r.status());
  const x = await request.post(`/posts/${s.fixture!.post}/comment`, { form: { body: 'cross site' }, headers: { origin: 'https://evil.example', 'sec-fetch-site': 'cross-site' }, failOnStatusCode: false, maxRedirects: 0 });
  expect(x.status()).toBe(403);
});
