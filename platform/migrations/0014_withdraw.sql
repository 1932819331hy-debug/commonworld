-- Withdraw your own content (POST /v1/{posts|comments|porch}/{n}/withdraw, src/routes/withdraw.ts).
-- The author redacts their own post, comment or porch line with a short public reason. The row, its number, its
-- author, its replies and its votes stay; title/body are emptied (post tags removed) and the pages and API show
-- "Withdrawn by author: <reason>". Not an edit: there is no edit. Refused once moderation has acted on the object.
ALTER TABLE posts ADD COLUMN withdrawn_at TEXT;
ALTER TABLE posts ADD COLUMN withdraw_reason TEXT;
ALTER TABLE comments ADD COLUMN withdrawn_at TEXT;
ALTER TABLE comments ADD COLUMN withdraw_reason TEXT;
ALTER TABLE porch_lines ADD COLUMN withdrawn_at TEXT;
ALTER TABLE porch_lines ADD COLUMN withdraw_reason TEXT;

-- Per-account cap on withdrawals per UTC day (null = no cap). Same value as DEFAULTS in src/settings.ts.
INSERT OR IGNORE INTO settings (key, value_json, updated_at, updated_by) VALUES ('limits.daily.withdraw', '5', '1970-01-01T00:00:00.000Z', 'migration');
