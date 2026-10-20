-- Per-account cap on brand-new tags per UTC day (src/routes/content.ts createPost, setting limits.new_tags_per_day).
-- Trusted accounts and staff are exempt; using an existing tag is never limited. null = no cap.
INSERT OR IGNORE INTO settings (key, value_json, updated_at, updated_by) VALUES
  ('limits.new_tags_per_day', '10', '1970-01-01T00:00:00.000Z', 'migration');
