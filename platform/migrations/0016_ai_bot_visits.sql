-- AI crawler / agent visit log (src/ai-bots.ts). Aggregated counts only: no IP, no full User-Agent, no query string,
-- no cookies, no account. One row per UTC day x bot name (from policy/ai-bots.json) x path x HTTP status.
-- Kept AI_BOT_RETENTION_DAYS (400) days, pruned by the nightly cron. Read: GET /v1/admin/ai-bots (admin).
CREATE TABLE IF NOT EXISTS ai_bot_visits (
  day TEXT NOT NULL,          -- YYYY-MM-DD (UTC)
  bot TEXT NOT NULL,          -- name from policy/ai-bots.json, never the raw User-Agent
  path TEXT NOT NULL,         -- URL path only (no query), at most 200 chars
  status INTEGER NOT NULL,    -- HTTP status the Worker answered
  count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, bot, path, status)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ai_bot_visits_bot_day ON ai_bot_visits (bot, day);
