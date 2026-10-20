-- AI bot visit log gets Cloudflare's own verdict (src/ai-bots.ts verifiedStatus): was this request from a bot that
-- Cloudflare verified (request.cf.verifiedBotCategory, available on every plan)? Still aggregated counts only: no IP,
-- no full User-Agent, no query string. verified = 'verified' | 'not_verified' | 'unknown'; category = Cloudflare's
-- verified-bot category string (e.g. 'AI Crawler'), '' unless verified. Rows written before this migration become
-- 'unknown' (no signal was stored then). Kept 400 days like before. The primary key changes, so the table is rebuilt.
CREATE TABLE ai_bot_visits_v2 (
  day TEXT NOT NULL,          -- YYYY-MM-DD (UTC)
  bot TEXT NOT NULL,          -- name from policy/ai-bots.json, never the raw User-Agent
  verified TEXT NOT NULL DEFAULT 'unknown' CHECK (verified IN ('verified', 'not_verified', 'unknown')),
  category TEXT NOT NULL DEFAULT '',  -- Cloudflare verified-bot category, at most 64 chars, '' when not verified
  path TEXT NOT NULL,         -- URL path only (no query), at most 200 chars
  status INTEGER NOT NULL,    -- HTTP status the Worker answered
  count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, bot, verified, category, path, status)
) WITHOUT ROWID;
INSERT INTO ai_bot_visits_v2 (day, bot, verified, category, path, status, count)
  SELECT day, bot, 'unknown', '', path, status, count FROM ai_bot_visits;
DROP TABLE ai_bot_visits;
ALTER TABLE ai_bot_visits_v2 RENAME TO ai_bot_visits;
CREATE INDEX IF NOT EXISTS ai_bot_visits_bot_day ON ai_bot_visits (bot, day);
