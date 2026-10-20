/**
 * Public cache versioning. The Workers Cache API (caches.default) cannot be purged by URL prefix from inside the
 * Worker, so instead every public cache key carries the current content version (migrations/0006_cache_version.sql).
 * Any action that changes what the public may see bumps the version in the same D1 batch as the change; the next
 * anonymous request then misses the cache and renders fresh. Old entries simply expire (s-maxage <= 300).
 *
 * Read on every edge-cacheable request (one primary-key lookup, never cached in the isolate) so a hide is visible
 * everywhere at once, not after an isolate-local TTL.
 *
 * The lookup is best effort: if D1 throws (a transient `D1_ERROR: internal error` turned / and /llms.txt into HTTP 500
 * on production on 2026-10-20), it is retried once and then the request goes on without the edge cache (no read, no
 * write: a copy stored under an unknown version could outlive a hide). A cache-version failure never becomes a 500.
 */
import type { Env } from './env';
import { nowIso } from './http';

export const CACHE_VERSION_PARAM = '__cv';

export async function contentCacheVersion(env: Env): Promise<number> {
  const row = await env.DB.prepare("SELECT version FROM cache_versions WHERE name = 'content'").first<{ version: number }>();
  return row?.version ?? 0;
}

/** contentCacheVersion with one retry; null (and a warning) when D1 failed both times. Never throws. */
export async function contentCacheVersionOrNull(env: Env): Promise<number | null> {
  for (let attempt = 1; ; attempt++) {
    try {
      return await contentCacheVersion(env);
    } catch (error) {
      if (attempt >= 2) {
        console.warn('cache version lookup failed; serving without the edge cache', String((error as Error)?.message ?? error));
        return null;
      }
    }
  }
}

/** Statement to put in the same batch as a visibility-changing write. */
export function bumpContentCacheVersion(db: D1Database): D1PreparedStatement {
  return db.prepare(`INSERT INTO cache_versions (name, version, updated_at) VALUES ('content', 1, ?)
    ON CONFLICT(name) DO UPDATE SET version = version + 1, updated_at = excluded.updated_at`).bind(nowIso());
}

/**
 * Cache key for a public GET: the given URL plus the current content version. null when the version could not be read
 * (D1 error after one retry): the caller then skips the edge cache for this request and renders fresh.
 */
export async function versionedCacheKey(env: Env, url: URL): Promise<Request | null> {
  const version = await contentCacheVersionOrNull(env);
  if (version === null) return null;
  const keyUrl = new URL(url.toString());
  keyUrl.searchParams.set(CACHE_VERSION_PARAM, String(version));
  return new Request(keyUrl.toString(), { method: 'GET' });
}
