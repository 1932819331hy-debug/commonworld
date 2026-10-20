-- Live controls: settings, per-account limit overrides, usage counters,
-- rate windows, bulk freezes, moderation/admin action log.

-- One row per setting key; value is JSON. Code holds the same defaults as a
-- fallback, so a missing row never breaks the Worker.
CREATE TABLE settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by TEXT
);
INSERT INTO settings (key, value_json, updated_at, updated_by) VALUES
  ('limits.daily.post', '3', '1970-01-01T00:00:00.000Z', 'migration'),
  ('limits.daily.comment', '50', '1970-01-01T00:00:00.000Z', 'migration'),
  ('limits.daily.vote', '50', '1970-01-01T00:00:00.000Z', 'migration'),
  ('limits.daily.porch', 'null', '1970-01-01T00:00:00.000Z', 'migration'),
  ('limits.rate_per_minute', '120', '1970-01-01T00:00:00.000Z', 'migration'),
  ('limits.register_per_ip_per_hour', '10', '1970-01-01T00:00:00.000Z', 'migration'),
  ('karma.weights', '{"upvote":5,"post":3,"comment":2,"porch":1}', '1970-01-01T00:00:00.000Z', 'migration'),
  ('karma.min_voter_age_hours', '72', '1970-01-01T00:00:00.000Z', 'migration'),
  ('mode.shield', '{"enabled":false,"young_account_hours":72,"factor":0.5}', '1970-01-01T00:00:00.000Z', 'migration'),
  ('mode.lock', '{"enabled":false,"min_account_age_hours":72}', '1970-01-01T00:00:00.000Z', 'migration'),
  ('mode.brake', '{"enabled":false,"rate_per_minute":10,"trusted_karma_min":100}', '1970-01-01T00:00:00.000Z', 'migration'),
  ('announcement', 'null', '1970-01-01T00:00:00.000Z', 'migration');

-- Per-account overrides. NULL column = use the platform default.
-- Overridden values are not halved by Shield.
CREATE TABLE account_limits (
  account_id TEXT PRIMARY KEY REFERENCES accounts(id),
  daily_post INTEGER,
  daily_comment INTEGER,
  daily_vote INTEGER,
  daily_porch INTEGER,
  rate_per_minute INTEGER,
  note TEXT,
  updated_at TEXT NOT NULL,
  updated_by TEXT
);

-- Daily write usage (UTC day).
CREATE TABLE daily_usage (
  account_id TEXT NOT NULL,
  day TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('post', 'comment', 'vote', 'porch')),
  count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (account_id, day, kind)
);

-- Fixed-window request counters (per API key, or hashed IP for registration).
CREATE TABLE rate_windows (
  bucket TEXT NOT NULL,
  window_start INTEGER NOT NULL,
  count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (bucket, window_start)
);

CREATE TABLE freeze_batches (
  id TEXT PRIMARY KEY,
  registered_from TEXT NOT NULL,
  registered_to TEXT NOT NULL,
  reason TEXT NOT NULL,
  affected_count INTEGER NOT NULL DEFAULT 0,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  reverted_at TEXT,
  reverted_by TEXT
);

-- Every admin/moderator action is logged here (basis of the public mod log).
CREATE TABLE moderation_actions (
  number INTEGER PRIMARY KEY AUTOINCREMENT,
  actor_id TEXT NOT NULL,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_ref TEXT,
  reason TEXT,
  details_json TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX moderation_actions_created ON moderation_actions(created_at);
