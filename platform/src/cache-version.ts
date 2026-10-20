/**
 * Public cache versioning. The Workers Cache API (caches.default) cannot be purged by URL prefix from inside the
 * Worker, so instead every public cache key carries the current content version (migrations/0006_cache_version.sql).
 * Any action that changes what the public may see bumps the version in the same D1 batch as the change; the next
 * anonymous request then misses the cache and renders fresh. Old entries simply expire (s-maxage <= 300).
 *
 * Read on every edge-cacheable request (one primary-key lookup, never cached in the isolate) so a hide is visible
 * everywhere at once, not after an isolate-local TTL.
 */
import type { Env } from './env';
import { nowIso } from './http';

export const CACHE_VERSION_PARAM = '__cv';

export async function contentCacheVersion(env: Env): Promise<number> {
  const row = await env.DB.prepare("SELECT version FROM cache_versions WHERE name = 'content'").first<{ version: number }>();
  return row?.version ?? 0;
}

/** Statement to put in the same batch as a visibility-changing write. */
export function bumpContentCacheVersion(db: D1Database): D1PreparedStatement {
  return db.prepare(`INSERT INTO cache_versions (name, version, updated_at) VALUES ('content', 1, ?)
    ON CONFLICT(name) DO UPDATE SET version = version + 1, updated_at = excluded.updated_at`).bind(nowIso());
}

/** Cache key for a public GET: the given URL plus the current content version. */
export async function versionedCacheKey(env: Env, url: URL): Promise<Request> {
  const keyUrl = new URL(url.toString());
  keyUrl.searchParams.set(CACHE_VERSION_PARAM, String(await contentCacheVersion(env)));
  return new Request(keyUrl.toString(), { method: 'GET' });
}
