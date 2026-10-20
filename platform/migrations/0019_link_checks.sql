-- Link check at publish (src/link-check.ts, TRUST.md "Links in posts and comments"): one row per create of a post,
-- comment or porch line whose text links at least one outside domain. Never the text itself.
--   outcome     allowed | rejected (a source flagged a domain: nothing was published)
--   decided_by  'hark' = the automatic decision, as the trust standard records it
--   domains_json  [{domain, status, sources: [{name, verdict, checked_at, evidence_url, detail?, error?}]}]
--   flagged_json  ["domain", ...] (empty for allowed)
-- Allowed rows are pruned after 90 days (nightly); rejected rows stay as the record.
CREATE TABLE link_checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  checked_at TEXT NOT NULL,
  account_id TEXT NOT NULL,
  object_type TEXT NOT NULL CHECK (object_type IN ('post', 'comment', 'porch')),
  outcome TEXT NOT NULL CHECK (outcome IN ('allowed', 'rejected')),
  decided_by TEXT NOT NULL,
  domains_json TEXT NOT NULL,
  flagged_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX link_checks_time ON link_checks (outcome, checked_at);
CREATE INDEX link_checks_account ON link_checks (account_id, checked_at);
