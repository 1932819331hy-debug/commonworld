-- Browser sign-in by one-time link (POST /v1/auth/login-link -> GET/POST /login) and cookie sessions (cw_session).
-- Neither the link token nor the session value is stored: only HMAC-SHA256(KEY_PEPPER, value), like API keys.
-- Expired rows are deleted by the nightly retention clean-up (src/retention.ts).

-- A link is valid for 10 minutes and can be used once (used_at set atomically on POST /login).
CREATE TABLE login_links (
  token_hash TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT
);
CREATE INDEX login_links_account ON login_links(account_id, created_at);
CREATE INDEX login_links_expires ON login_links(expires_at);

-- Sliding session: ends after 30 days without a visit; each visit (at most once per day) moves expires_at
-- to now + 30 days. Deleted on sign-out, key rotation, and when the account is frozen or disabled.
CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  session_hash TEXT NOT NULL UNIQUE,
  account_id TEXT NOT NULL REFERENCES accounts(id),
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE INDEX sessions_account ON sessions(account_id);
CREATE INDEX sessions_expires ON sessions(expires_at);
