-- Stored counters (src/counters.ts): pages and /v1 reads stop counting whole tables per request.
-- Filled by the Worker on first read after this migration (ensureCounters), kept on every write, fully recounted
-- on staff actions and by the nightly cron.
CREATE TABLE site_counters (
  name TEXT PRIMARY KEY,
  value INTEGER NOT NULL DEFAULT 0
);

ALTER TABLE sections ADD COLUMN post_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE sections ADD COLUMN comment_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tags ADD COLUMN post_count INTEGER NOT NULL DEFAULT 0;

-- Per-account stats (same definitions as stats.ts statsSelect). karma, counts: exact (kept on every write, recounted
-- on staff actions). karma_7d: added on every write, items leaving the 7-day window subtracted by the hourly cron.
-- rank_all / rank_kind: leaderboard position (karma DESC, number ASC) among active accounts, refreshed by the hourly
-- cron and every full recount; NULL for accounts that are not active.
CREATE TABLE account_stats (
  account_id TEXT PRIMARY KEY REFERENCES accounts(id),
  account_number INTEGER NOT NULL,
  posts INTEGER NOT NULL DEFAULT 0,
  comments INTEGER NOT NULL DEFAULT 0,
  porch INTEGER NOT NULL DEFAULT 0,
  upvotes_received INTEGER NOT NULL DEFAULT 0,
  upvotes_counted INTEGER NOT NULL DEFAULT 0,
  karma INTEGER NOT NULL DEFAULT 0,
  karma_7d INTEGER NOT NULL DEFAULT 0,
  rank_all INTEGER,
  rank_kind INTEGER,
  updated_at TEXT NOT NULL
);
CREATE INDEX account_stats_karma ON account_stats(karma DESC, account_number);
CREATE INDEX account_stats_karma7 ON account_stats(karma_7d DESC, account_number);
CREATE INDEX account_stats_posts ON account_stats(posts DESC, account_number);
CREATE INDEX account_stats_comments ON account_stats(comments DESC, account_number);
CREATE UNIQUE INDEX account_stats_number ON account_stats(account_number);

-- Time indexes for the windowed counts (hourly karma_7d expiry, new7, porch24).
CREATE INDEX votes_created ON votes(created_at);
CREATE INDEX comments_created ON comments(created_at);
CREATE INDEX porch_created ON porch_lines(created_at);
