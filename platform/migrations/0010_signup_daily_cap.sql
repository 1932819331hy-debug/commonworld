-- Platform-wide cap on new accounts per UTC day (src/routes/accounts.ts register, setting limits.register_per_day).
-- Same default as DEFAULTS in src/settings.ts; staff change it with PATCH /v1/admin/settings (null = no cap).
INSERT OR IGNORE INTO settings (key, value_json, updated_at, updated_by) VALUES
  ('limits.register_per_day', '500', '1970-01-01T00:00:00.000Z', 'migration');
