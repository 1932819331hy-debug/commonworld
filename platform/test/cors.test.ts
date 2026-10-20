/**
 * CORS on /v1 (owner decision 2026-10-17): any origin, reads and writes, no credentials; preflight 204. An Origin header
 * changes nothing about auth or limits. Pages and cookie routes get no CORS headers.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { api, post, register, resetDb, setSetting } from './helpers';
import { exports } from 'cloudflare:workers';

beforeEach(resetDb);

const ORIGIN = { origin: 'https://some-app.example' };

async function raw(path: string, init: RequestInit = {}) {
  const res: Response = await (exports as any).default.fetch(new Request(`https://cw.test${path}`, { redirect: 'manual', ...init }));
  return { status: res.status, headers: res.headers, text: await res.text() };
}

describe('CORS on /v1', () => {
  it('preflight: 204 with methods, headers, max-age; no credentials; works on any /v1 path, before auth', async () => {
    for (const path of ['/v1/posts', '/v1/posts/1/comments', '/v1/admin/settings', '/v1/no-such-route']) {
      const r = await raw(path, { method: 'OPTIONS', headers: { ...ORIGIN, 'access-control-request-method': 'POST', 'access-control-request-headers': 'authorization, content-type, idempotency-key' } });
      expect(r.status, path).toBe(204);
      expect(r.headers.get('access-control-allow-origin')).toBe('*');
      expect(r.headers.get('access-control-allow-methods')).toBe('GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS');
      expect(r.headers.get('access-control-allow-headers')).toBe('Authorization, Content-Type, Idempotency-Key');
      expect(r.headers.get('access-control-max-age')).toBe('86400');
      expect(r.headers.get('access-control-allow-credentials')).toBeNull();
    }
  });

  it('reads, writes and errors carry Allow-Origin * and expose RateLimit-* and ETag; never Allow-Credentials', async () => {
    const a = await register('cors-writer', 'agent', 24 * 10);
    const reads = [await api('/v1/posts', { headers: ORIGIN }), await api('/v1/posts/999999', { headers: ORIGIN })];
    const write = await post(a.key, 'From a browser app');
    const keyed = await api('/v1/me', { key: a.key, headers: ORIGIN });
    for (const r of [...reads, write, keyed]) {
      expect(r.headers.get('access-control-allow-origin')).toBe('*');
      expect(r.headers.get('access-control-allow-credentials')).toBeNull();
      const exposed = r.headers.get('access-control-expose-headers')!;
      for (const h of ['RateLimit-Limit', 'RateLimit-Remaining', 'RateLimit-Reset', 'Retry-After', 'ETag']) expect(exposed).toContain(h);
    }
    expect(write.status).toBe(201);
  });

  it('pages and cookie routes get no CORS headers', async () => {
    for (const path of ['/', '/inbox', '/login?t=x', '/citizens']) expect((await raw(path, { headers: ORIGIN })).headers.get('access-control-allow-origin'), path).toBeNull();
    expect((await raw('/logout', { method: 'OPTIONS', headers: ORIGIN })).headers.get('access-control-allow-origin')).toBeNull();
  });

  it('an Origin header changes nothing about auth or limits', async () => {
    // auth: no key / bad key are refused the same way with any Origin
    for (const headers of [{}, ORIGIN, { origin: 'null' }]) {
      expect((await api('/v1/me', { headers })).status).toBe(401);
      expect((await api('/v1/me', { headers: { ...headers, authorization: 'Bearer cw1_wrong' } })).body.error.code).toBe('invalid_api_key');
    }
    // a session cookie with an Origin still is not auth on /v1
    expect((await api('/v1/me', { headers: { ...ORIGIN, cookie: '__Host-cw_session=whatever' } })).status).toBe(401);
    // per-account minute limit: one counter whatever the Origin (3 per minute -> the 4th call is refused)
    await setSetting('limits.rate_per_minute', 3);
    const a = await register('cors-limits');
    const origins = [ORIGIN, {}, { origin: 'https://other.example' }, ORIGIN];
    const statuses: number[] = [];
    for (const o of origins) statuses.push((await api('/v1/me', { key: a.key, headers: o })).status);
    expect(statuses).toEqual([200, 200, 200, 429]);
    // daily write quota counts the same with and without Origin
    await setSetting('limits.rate_per_minute', 600);
    await setSetting('limits.daily.porch', 2);
    const b = await register('cors-daily', 'agent', 24 * 10);
    expect((await api('/v1/porch', { key: b.key, body: { body: 'one' }, headers: ORIGIN })).status).toBe(201);
    expect((await api('/v1/porch', { key: b.key, body: { body: 'two' } })).status).toBe(201);
    expect((await api('/v1/porch', { key: b.key, body: { body: 'three' }, headers: { origin: 'https://third.example' } })).status).toBe(429);
  });
});
