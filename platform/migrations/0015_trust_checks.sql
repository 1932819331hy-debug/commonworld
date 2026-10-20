-- Hourly trust check of our own domains (src/trust.ts, standard: TRUST.md in commonworld-one/commonworld).
-- One row per run x configured domain: the combined status and every source's answer (JSON array of
-- {name, verdict, checked_at, evidence_url, detail?, error?}). Public read: GET /v1/trust/status. Kept 90 days (nightly cron).
CREATE TABLE IF NOT EXISTS trust_checks (
  run_at TEXT NOT NULL,       -- ISO 8601 UTC, same for every domain of one run
  domain TEXT NOT NULL,       -- configured name, e.g. www.commonworld.one
  checked_as TEXT NOT NULL,   -- name the engine checked (www. is folded: commonworld.one)
  status TEXT NOT NULL CHECK (status IN ('clean', 'flagged', 'no_data')),
  sources TEXT NOT NULL,      -- JSON array of per-source answers
  PRIMARY KEY (run_at, domain)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS trust_checks_run_at ON trust_checks (run_at);
