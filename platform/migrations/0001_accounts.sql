-- Accounts, API keys, roles.
-- Humans and agents are the same kind of citizen with the same capabilities;
-- `kind` is a label, never a permission switch.
-- `id` is the stable opaque identity (future wallets/ledger reference it);
-- `number` is the readable per-type display number.
CREATE TABLE accounts (
  number INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  handle TEXT NOT NULL UNIQUE COLLATE NOCASE,
  kind TEXT NOT NULL CHECK (kind IN ('human', 'agent')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'frozen', 'disabled')),
  trusted INTEGER NOT NULL DEFAULT 0 CHECK (trusted IN (0, 1)),
  frozen_batch_id TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX accounts_created ON accounts(created_at);
CREATE INDEX accounts_kind_status ON accounts(kind, status);

-- API keys are stored only as HMAC-SHA256(KEY_PEPPER, key). The plain key is
-- returned once at creation/rotation and never again.
CREATE TABLE api_keys (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id),
  key_hash TEXT NOT NULL UNIQUE,
  prefix TEXT NOT NULL,
  created_at TEXT NOT NULL,
  revoked_at TEXT
);
CREATE INDEX api_keys_account ON api_keys(account_id, revoked_at);

-- Roles live in the database (not in env handles), granted by an admin.
CREATE TABLE account_roles (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  role TEXT NOT NULL CHECK (role IN ('admin', 'moderator')),
  granted_at TEXT NOT NULL,
  granted_by TEXT,
  PRIMARY KEY (account_id, role)
);
