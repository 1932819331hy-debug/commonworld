-- Account recovery via linked external proofs (src/recovery.ts, src/routes/recovery.ts).
-- linked_identities: external identities a citizen proved they control (GitHub, X, own domain). Verified rows are public
-- on the profile ("verified links"). The challenge is public by design (it is posted on the external resource).
CREATE TABLE linked_identities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id TEXT NOT NULL REFERENCES accounts(id),
  provider TEXT NOT NULL CHECK (provider IN ('github', 'x', 'domain')),
  subject TEXT NOT NULL,                 -- github login / x handle / domain, lower case
  challenge TEXT NOT NULL,               -- cw-citizen-<n>-<random>, posted by the citizen on the resource
  status TEXT NOT NULL CHECK (status IN ('pending', 'verified', 'removed')),
  method TEXT,                           -- where the code was found: bio | gist | dns | well-known
  proof_url TEXT,                        -- public page that showed the code
  created_at TEXT NOT NULL,
  verified_at TEXT,
  last_checked_at TEXT
);
CREATE INDEX linked_identities_account ON linked_identities (account_id, status);
-- one external identity proves one account
CREATE UNIQUE INDEX linked_identities_verified ON linked_identities (provider, subject) WHERE status = 'verified';

-- recovery_codes: one active one-time recovery code per account, stored only as HMAC(KEY_PEPPER).
CREATE TABLE recovery_codes (
  account_id TEXT PRIMARY KEY REFERENCES accounts(id),
  code_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  used_at TEXT
);

-- recovery_requests: lost-key requests. claim_hash = HMAC of the claim token given once to the requester.
-- status: pending (proof not seen yet) -> verified (proof seen or recovery code used) -> approved (admin; old keys and
-- sessions revoked) -> completed (new key collected once); or rejected / expired. No IPs, no secrets in clear.
CREATE TABLE recovery_requests (
  number INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id TEXT NOT NULL REFERENCES accounts(id),
  method TEXT NOT NULL CHECK (method IN ('proof', 'code')),
  challenge TEXT,
  claim_hash TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'verified', 'approved', 'completed', 'rejected', 'expired')),
  proof_identity_id INTEGER,
  proof_url TEXT,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  verified_at TEXT,
  decided_at TEXT,
  decided_by TEXT,
  decision_note TEXT,
  completed_at TEXT
);
CREATE INDEX recovery_requests_status ON recovery_requests (status, number);
CREATE INDEX recovery_requests_account ON recovery_requests (account_id, created_at);
