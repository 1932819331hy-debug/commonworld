import { expect, type APIRequestContext } from '@playwright/test';
import { sitemapText } from './env';

export interface ApiResult { status: number; json: any; text: string; headers: Record<string, string> }

export async function api(request: APIRequestContext, method: string, path: string, opts: { key?: string; body?: unknown; headers?: Record<string, string>; raw?: string } = {}): Promise<ApiResult> {
  const headers: Record<string, string> = { ...(opts.headers ?? {}) };
  if (opts.key) headers.authorization = `Bearer ${opts.key}`;
  if (opts.body !== undefined || opts.raw !== undefined) headers['content-type'] ??= 'application/json';
  const res = await request.fetch(path, { method, headers, data: opts.raw ?? (opts.body === undefined ? undefined : JSON.stringify(opts.body)), maxRedirects: 0, failOnStatusCode: false });
  const text = await res.text();
  let json: any = null;
  try { json = JSON.parse(text); } catch { /* not JSON */ }
  return { status: res.status(), json, text, headers: res.headers() };
}

export async function sitemap(request: APIRequestContext): Promise<string> {
  return sitemapText(async (p) => {
    const r = await request.get(p, { failOnStatusCode: false });
    expect(r.status(), `${p} status`).toBe(200);
    return r.text();
  });
}

/** The page's <meta name="robots"> value plus the X-Robots-Tag header, lower-cased. */
export async function robotsOf(request: APIRequestContext, path: string) {
  const r = await request.get(path, { failOnStatusCode: false, maxRedirects: 0 });
  const html = await r.text();
  const meta = html.match(/<meta name="robots" content="([^"]*)"/)?.[1] ?? '';
  return { status: r.status(), meta: meta.toLowerCase(), header: (r.headers()['x-robots-tag'] ?? '').toLowerCase(), html, headers: r.headers() };
}

/** Matches a <loc> for exactly this path (not a longer one, e.g. /posts/1 vs /posts/12). */
export const locFor = (path: string) => new RegExp(`<loc>[^<]*${path.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}</loc>`);
