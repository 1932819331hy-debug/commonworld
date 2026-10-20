/**
 * Routing option A (src/atlas-proxy.ts): with ATLAS_ORIGIN set the Worker forwards the Atlas paths to the Pages
 * project and keeps everything else. B2: no path ever redirects to itself (prod-like SITE_ORIGIN, with and without
 * the Atlas proxy).
 */
import { createExecutionContext, waitOnExecutionContext } from 'cloudflare:test';
import { env } from 'cloudflare:workers';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import worker from '../src/index';
import { ATLAS_PATHS, atlasOrigin, isAtlasPath } from '../src/atlas-proxy';
import { resetDb } from './helpers';

beforeEach(resetDb);
afterEach(() => vi.restoreAllMocks());

const ATLAS = 'https://atlas-pages.test';
const PROD = 'https://commonworld.one';

async function call(path: string, vars: Record<string, string>, init: RequestInit = {}, origin = PROD) {
  const ctx = createExecutionContext();
  const res = await worker.fetch(new Request(`${origin}${path}`, { redirect: 'manual', ...init }), { ...env, PUBLIC_EDGE_CACHE: '0', ...vars } as any, ctx);
  await waitOnExecutionContext(ctx);
  return { status: res.status, headers: res.headers, text: await res.text() };
}

/** Fake Pages origin: records requested URLs, answers like Pages would. */
function fakePages() {
  const seen: string[] = [];
  const real = globalThis.fetch;
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const u = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
    if (u.origin !== ATLAS) return real(input as any, init);
    seen.push(u.pathname + u.search);
    if (u.pathname === '/llms.txt') return new Response('# Atlas llms\n- [Atlas home](https://commonworld.one/atlas/)\n', { headers: { 'content-type': 'text/plain' } });
    if (u.pathname === '/llms-full.txt') return new Response('# Atlas full\nentry-one\n', { headers: { 'content-type': 'text/plain' } });
    if (u.pathname === '/atlas/moved') return new Response(null, { status: 308, headers: { location: `${ATLAS}/atlas/moved/` } });
    if (u.pathname === '/atlas/missing/') return new Response('<h1>404</h1>', { status: 404, headers: { 'content-type': 'text/html' } });
    return new Response(`atlas:${u.pathname}`, { status: 200, headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'public, max-age=0, must-revalidate', etag: '"abc"', 'content-security-policy': "default-src 'self'", 'set-cookie': 'x=1' } });
  });
  return seen;
}

describe('Atlas routing table', () => {
  it('sends Atlas paths to Pages and keeps v1 paths', () => {
    for (const p of ['/atlas/', '/atlas/platforms/1f916/', '/atlas/platforms.json', '/atlas/assets/atlas.css', '/atlas/og/atlas.png', '/atlas/sitemap.xml', '/atlas/badge/x.svg',
      '/privacy/', '/terms/', '/about/', '/api/v1/index.json', '/api/v1/openapi.json', '/api/v1/schemas/platform.schema.json', '/.well-known/security.txt',
      '/0123456789abcdef0123456789abcdef.txt', '/404.html']) expect(isAtlasPath(p), p).toBe(true);
    for (const p of ['/', '/porch', '/sections', '/s/general', '/t/memory', '/posts/1', '/citizens', '/c/someone', '/search', '/moderation', '/inbox', '/login', '/logout',
      '/v1/catalog', '/v1/openapi.json', '/health', '/assets/ssr.css', '/favicon.ico', '/robots.txt', '/sitemap.xml', '/sitemap-v1.xml', '/llms.txt', '/llms-full.txt', '/openapi.json',
      '/atlas', '/privacy', '/terms', '/about', '/apiv1', '/api/v2/x']) expect(isAtlasPath(p), p).toBe(false);
    expect(ATLAS_PATHS.length).toBeGreaterThan(0);
  });

  it('accepts only an https origin without path as ATLAS_ORIGIN', () => {
    expect(atlasOrigin({ ATLAS_ORIGIN: 'https://commonworld.pages.dev/' } as any)).toBe('https://commonworld.pages.dev');
    for (const bad of ['', 'http://commonworld.pages.dev', 'https://x.test/sub', 'not a url', 'https://x.test/?a=1']) expect(atlasOrigin({ ATLAS_ORIGIN: bad } as any), bad).toBeNull();
  });
});

describe('Atlas proxy (ATLAS_ORIGIN set)', () => {
  const vars = { ATLAS_ORIGIN: ATLAS, SITE_ORIGIN: PROD };

  it('passes status, headers and body through; strips set-cookie; never touches D1 pages', async () => {
    const seen = fakePages();
    const r = await call('/atlas/platforms/1f916/?ref=x', vars);
    expect(r.status).toBe(200);
    expect(r.text).toBe('atlas:/atlas/platforms/1f916/');
    expect(r.headers.get('etag')).toBe('"abc"');
    expect(r.headers.get('content-security-policy')).toBe("default-src 'self'");
    expect(r.headers.get('cache-control')).toBe('public, max-age=0, must-revalidate');
    expect(r.headers.get('set-cookie')).toBeNull();
    expect(r.headers.get('x-cw-upstream')).toBe('atlas');
    expect(seen).toEqual(['/atlas/platforms/1f916/?ref=x']);
    expect((await call('/atlas/missing/', vars)).status).toBe(404);
    for (const p of ['/privacy/', '/terms/', '/about/', '/api/v1/index.json', '/.well-known/security.txt']) {
      const x = await call(p, vars);
      expect(x.status, p).toBe(200);
      expect(x.text, p).toBe(`atlas:${p}`);
    }
    expect((await call('/atlas/x', vars, { method: 'POST', body: 'a' })).status).toBe(405);
  });

  it('rewrites a Location on the Pages origin to the same host; bare /atlas, /privacy, /terms, /about get a same-host 301', async () => {
    fakePages();
    const moved = await call('/atlas/moved', vars);
    expect(moved.status).toBe(308);
    expect(moved.headers.get('location')).toBe('/atlas/moved/');
    for (const p of ['/atlas', '/privacy', '/terms', '/about']) {
      const r = await call(p + '?a=1', vars);
      expect(r.status, p).toBe(301);
      expect(r.headers.get('location'), p).toBe(`${p}/?a=1`);
    }
  });

  it('marks proxied pages noindex on closed staging', async () => {
    fakePages();
    const r = await call('/atlas/', { ...vars, PAGES_NOINDEX: '1' });
    expect(r.headers.get('x-robots-tag')).toBe('noindex, nofollow');
  });

  it('keeps / and v1 pages on the Worker; sitemap index + merged llms files', async () => {
    const seen = fakePages();
    const home = await call('/', vars);
    expect(home.status).toBe(200);
    expect(home.text).toContain('A shared world');
    const idx = await call('/sitemap.xml', vars);
    expect(idx.text).toContain('<sitemapindex');
    expect(idx.text).toContain(`<loc>${PROD}/sitemap-v1.xml</loc>`);
    expect(idx.text).toContain(`<loc>${PROD}/atlas/sitemap.xml</loc>`);
    const v1map = await call('/sitemap-v1.xml', vars);
    expect(v1map.text).toContain('<urlset');
    expect(v1map.text).toContain(`<loc>${PROD}/privacy/</loc>`);
    const robots = await call('/robots.txt', vars);
    expect(robots.text).toContain(`Sitemap: ${PROD}/sitemap.xml`);
    const llms = await call('/llms.txt', vars);
    expect(llms.text.indexOf('# Commonworld')).toBe(0);
    expect(llms.text).toContain('# Atlas llms');
    const full = await call('/llms-full.txt', vars);
    expect(full.text).toContain('# Commonworld: full reference for agents');
    expect(full.text).toContain('# Atlas full');
    expect(seen).toEqual(['/llms.txt', '/llms-full.txt']);
  });
});

describe('B2: no redirect to itself', () => {
  it('without ATLAS_ORIGIN on the prod host, /privacy/ etc. do not 301 to the same URL', async () => {
    for (const p of ['/privacy/', '/terms/', '/about/']) {
      const r = await call(p, { SITE_ORIGIN: PROD });
      if (r.status === 301) expect(new URL(r.headers.get('location')!, PROD).href, p).not.toBe(`${PROD}${p}`);
      else expect(r.status, p).toBe(404);
    }
    // bare paths go to the slash form once, which then stops
    const bare = await call('/privacy', { SITE_ORIGIN: PROD });
    expect(bare.status).toBe(301);
    expect(bare.headers.get('location')).toBe(`${PROD}/privacy/`);
  });

  it('on another host (staging without proxy) the legal pages still 301 to the Atlas on commonworld.one', async () => {
    const r = await call('/privacy/', { SITE_ORIGIN: 'https://staging.commonworld.one' }, {}, 'https://staging.commonworld.one');
    expect(r.status).toBe(301);
    expect(r.headers.get('location')).toBe(`${PROD}/privacy/`);
  });

  it('no Atlas path or legal path redirects to itself with the proxy on', async () => {
    fakePages();
    for (const p of ['/privacy', '/privacy/', '/terms', '/terms/', '/about', '/about/', '/atlas', '/atlas/']) {
      const r = await call(p, { ATLAS_ORIGIN: ATLAS, SITE_ORIGIN: PROD });
      const loc = r.headers.get('location');
      if (loc) expect(new URL(loc, PROD + p).href, p).not.toBe(PROD + p);
    }
  });
});
