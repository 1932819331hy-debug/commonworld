/**
 * Per-response CSP nonce (router.ts withFreshNonce): header and inline script share one fresh nonce per response,
 * also on Workers-cache hits; Cloudflare's injected scripts are allowed by that nonce, 'self' (/cdn-cgi/...) and the
 * Web Analytics hosts; never 'unsafe-inline'.
 */
import { createExecutionContext, waitOnExecutionContext } from 'cloudflare:test';
import { env } from 'cloudflare:workers';
import { beforeEach, describe, expect, it } from 'vitest';
import worker from '../src/index';
import { resetDb } from './helpers';

beforeEach(resetDb);

async function get(path: string, vars: Record<string, string> = {}) {
  const ctx = createExecutionContext();
  const res = await worker.fetch(new Request(`https://cw.test${path}`, { redirect: 'manual' }), { ...env, PUBLIC_EDGE_CACHE: '0', ...vars } as any, ctx);
  await waitOnExecutionContext(ctx);
  return { status: res.status, headers: res.headers, text: await res.text() };
}
const headerNonce = (csp: string) => /script-src [^;]*'nonce-([A-Za-z0-9+/=]+)'/.exec(csp)?.[1];
const bodyNonces = (html: string) => [...html.matchAll(/<script\b[^>]*\snonce="([^"]*)"/g)].map((m) => m[1]);

describe('CSP nonce', () => {
  it('header nonce = inline script nonce, 128-bit, new on every response; no unsafe-inline; CF hosts allowed', async () => {
    const a = await get('/');
    const b = await get('/');
    const csp = a.headers.get('content-security-policy')!;
    const n1 = headerNonce(csp)!;
    expect(n1).toMatch(/^[A-Za-z0-9+/]{22}==$/);
    expect(bodyNonces(a.text)).toEqual([n1]);
    expect(a.text).not.toContain('cw-nonce');
    expect(headerNonce(b.headers.get('content-security-policy')!)).not.toBe(n1);
    expect(csp).not.toContain('unsafe-inline');
    expect(csp).toMatch(/script-src 'self' 'sha256-[^']+' 'nonce-[^']+' https:\/\/static\.cloudflareinsights\.com;/);
    expect(csp).toMatch(/connect-src 'self' https:\/\/cloudflareinsights\.com;/);
  });

  it('a Workers-cache hit never repeats the nonce of the copy it was stored from', async () => {
    const vars = { PUBLIC_EDGE_CACHE: '1' };
    const { bumpContentCacheVersion } = await import('../src/cache-version');
    await bumpContentCacheVersion(env.DB).run();
    const first = await get('/citizens', vars);
    const hit = await get('/citizens', vars);
    const hit2 = await get('/citizens', vars);
    expect(hit.headers.get('x-cw-cache')).toBe('HIT');
    const nonces = [first, hit, hit2].map((r) => headerNonce(r.headers.get('content-security-policy')!));
    expect(new Set(nonces).size).toBe(3);
    for (const r of [first, hit, hit2]) expect(bodyNonces(r.text)).toEqual([headerNonce(r.headers.get('content-security-policy')!)]);
  });

  it('error pages get a nonce too; markdown, JSON and assets do not carry a script nonce', async () => {
    const e = await get('/no-such-page');
    expect(e.status).toBe(404);
    expect(bodyNonces(e.text)).toEqual([headerNonce(e.headers.get('content-security-policy')!)]);
    for (const path of ['/index.md', '/v1/catalog', '/assets/site.js']) {
      expect((await get(path)).headers.get('content-security-policy') ?? '', path).not.toContain('nonce-');
    }
  });

  it('llms-full.txt documents the CSP with a nonce placeholder, not a real nonce', async () => {
    const r = await get('/llms-full.txt');
    expect(r.text).toContain("'nonce-<random, new on every response>'");
  });
});
