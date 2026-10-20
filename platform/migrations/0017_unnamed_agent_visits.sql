-- Second AI-visit counter, HEURISTIC and NOT VERIFIED (src/ai-bots.ts classifyUnnamedAgent): requests that look like a
-- non-browser program (no Sec-Fetch-* headers, no Cookie, ...) but do not name a known AI bot. Aggregated counts only:
-- no IP, no User-Agent, no query string, no cookies, no account. Kept 400 days (nightly cron). Read: GET /v1/admin/ai-bots.
CREATE TABLE IF NOT EXISTS unnamed_agent_visits (
  day TEXT NOT NULL,          -- YYYY-MM-DD (UTC)
  class TEXT NOT NULL,        -- 'unnamed-agent' | 'generic-http-client'
  family TEXT NOT NULL,       -- HTTP-client family from policy/ai-bots.json heuristic.http_clients (e.g. 'curl'), '' if none
  path TEXT NOT NULL,         -- URL path only (no query), at most 200 chars
  status INTEGER NOT NULL,    -- HTTP status the Worker answered
  count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, class, family, path, status)
) WITHOUT ROWID;
