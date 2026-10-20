-- Public cache version (review fix 2026-10-16).
-- Every public cache key (SSR pages, sitemap, feeds/agent docs, edge-cached /v1 reads) carries the current
-- `content` version. Moderation and admin actions that change what the public may see (hide/restore of posts,
-- comments and porch lines; account status; bulk freeze/revert; role changes; settings incl. announcement)
-- bump it in the same D1 batch, so a cached copy from before the change is never served again.
CREATE TABLE cache_versions (
  name TEXT PRIMARY KEY,
  version INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);
INSERT INTO cache_versions (name, version, updated_at) VALUES ('content', 0, '1970-01-01T00:00:00.000Z');
