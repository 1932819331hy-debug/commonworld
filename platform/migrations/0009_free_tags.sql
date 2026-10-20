-- Free tags (owner decision 2026-10-17): a post may carry up to 5 tags; an unknown tag slug is created on first use.
-- Staff can merge a tag into another (POST /v1/admin/tags/{slug}/merge): the source keeps its row and number with
-- status 'merged' and merged_into = target slug, so old /t/{source} links and ?tag={source} filters resolve to the target.
-- SQLite cannot change a CHECK constraint in place, so the tags table is rebuilt (same columns, numbers and rows).
PRAGMA defer_foreign_keys = true;
CREATE TABLE tags_new (
  number INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived', 'merged')),
  merged_into TEXT,
  created_at TEXT,
  CHECK ((status = 'merged') = (merged_into IS NOT NULL))
);
INSERT INTO tags_new (number, slug, name, status) SELECT number, slug, name, status FROM tags;
DROP TABLE tags;
ALTER TABLE tags_new RENAME TO tags;
CREATE INDEX tags_merged_into ON tags(merged_into) WHERE merged_into IS NOT NULL;
PRAGMA defer_foreign_keys = false;
