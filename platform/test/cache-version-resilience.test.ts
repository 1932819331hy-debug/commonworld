/**
 * The content cache version (src/cache-version.ts) is read from D1 on every edge-cacheable request. On production a
 * transient `D1_ERROR: internal error` from that one lookup turned / and /llms.txt into HTTP 500 (2026-10-20). The
 * lookup is now best effort: one retry, then the request renders without the edge cache and still answers 200.
 */
import { createExecutionContext, waitOnExecutionContext } from 'cloudflare:test';
import { env } from 'cloudflare:workers';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import worker from '../src/index';
import { contentCacheVersionOrNull, versionedCacheKey } from '../src/cache-version';
import { resetDb } from './helpers';

beforeEach(resetDb);
afterEach(() => vi.restoreAllMocks());

/** env.DB whose cache_versions SELECT throws like D1 does (`failures` times, Infinity = always); every other query is real. */
function flakyDb(failures: number) {
  const state = { calls: 0 };
  const db = new Proxy(env.DB, {
    get(target, prop) {
      if (prop === 'prepare') {
        return (sql: string) => {
          const stmt = target.prepare(sql);
          if (!/^\s*SELECT version FROM cache_versions/i.test(sql)) return stmt;
          const fail = async () => {
            state.calls++;
            if (state.calls <= failures) throw new Error('D1_ERROR: internal error; reference = test');
            return stmt.first();
          };
          return new Proxy(stmt, { get: (s, p) => (p === 'first' ? fail : (s as any)[p]?.bind?.(s) ?? (s as any)[p]) });
        };
      }
      const value = (target as any)[prop];
      return typeof value === 'function' ? value.bind(target) : value;
    },
  });
  return { db: db as D1Database, state };
}

async function call(path: string, db: D1Database) {
  const ctx = createExecutionContext();
  const res = await worker.fetch(new Request(`https://cw.test${path}`, { redirect: 'manual' }), { ...env, PUBLIC_EDGE_CACHE: '1', DB: db } as any, ctx);
  await waitOnExecutionContext(ctx);
  return { status: res.status, headers: res.headers, text: await res.text() };
}

describe('content cache version: a D1 error never becomes a 500', () => {
  it('D1 failing on every try: /, /llms.txt, a Markdown twin and an edge-cached /v1 read answer 200 without the cache', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const match = vi.spyOn(caches.default, 'match');
    const put = vi.spyOn(caches.default, 'put');
    for (const path of ['/', '/llms.txt', '/porch.md', '/v1/catalog']) {
      const { db, state } = flakyDb(Infinity);
      const res = await call(path, db);
      expect(res.status, path).toBe(200);
      expect(res.headers.get('x-cw-cache'), path).toBeNull();
      expect(state.calls, path).toBe(2); // one retry, then give up
    }
    // no key: the edge cache is neither read nor written (a copy under an unknown version could outlive a hide)
    expect(match).not.toHaveBeenCalled();
    expect(put).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('cache version lookup failed'), expect.stringContaining('D1_ERROR'));
  });

  // Without a known version the response must not be kept by any HTTP cache downstream either (a CDN or proxy copy of
  // a public s-maxage response could be served after a hide). D1 healthy: the usual public headers, unchanged.
  const PATHS: Array<[string, string]> = [
    ['/', 'public, max-age=0, s-maxage=30'],
    ['/porch', 'public, max-age=0, s-maxage=30'],
    ['/llms.txt', 'public, max-age=300, s-maxage=300'],
    ['/porch.md', 'public, max-age=0, s-maxage=30'],
    ['/v1/catalog', 'public, max-age=0, s-maxage=300'],
  ];

  it('D1 failing on every try: HTML pages, /llms.txt, a Markdown twin and /v1/catalog go out Cache-Control: no-store', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    for (const [path] of PATHS) {
      const res = await call(path, flakyDb(Infinity).db);
      expect(res.status, path).toBe(200);
      expect(res.headers.get('cache-control'), path).toBe('no-store');
    }
  });

  it('D1 healthy: the same routes keep their public Cache-Control', async () => {
    for (const [path, cacheControl] of PATHS) {
      const res = await call(path, flakyDb(0).db);
      expect(res.status, path).toBe(200);
      expect(res.headers.get('cache-control'), path).toBe(cacheControl);
    }
  });

  it('one transient failure: the retry succeeds and the edge cache is used as normal', async () => {
    const match = vi.spyOn(caches.default, 'match');
    const { db, state } = flakyDb(1);
    const res = await call('/llms.txt', db);
    expect(res.status).toBe(200);
    expect(state.calls).toBe(2);
    expect(match).toHaveBeenCalledTimes(1);
    expect(String((match.mock.calls[0][0] as Request).url)).toMatch(/[?&]__cv=\d+/);
  });

  it('helpers: null key on failure, versioned key when D1 answers', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const url = new URL('https://cw.test/porch');
    expect(await contentCacheVersionOrNull({ ...env, DB: flakyDb(Infinity).db } as any)).toBeNull();
    expect(await versionedCacheKey({ ...env, DB: flakyDb(Infinity).db } as any, url)).toBeNull();
    const key = await versionedCacheKey({ ...env, DB: flakyDb(0).db } as any, url);
    expect(key?.url).toMatch(/^https:\/\/cw\.test\/porch\?__cv=\d+$/);
  });
});
