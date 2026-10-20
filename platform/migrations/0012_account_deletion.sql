-- Account deletion by staff (Privacy "Deleting your data"; src/routes/deletion.ts, docs/ACCOUNT-DELETION.md).
-- deletion_requested_at: set by the owner with POST /v1/me/deletion-request (their own key = proof of ownership).
-- deleted_at: set when staff ran POST /v1/admin/accounts/{handle}/delete (handle is then deleted-<citizen number>).
ALTER TABLE accounts ADD COLUMN deletion_requested_at TEXT;
ALTER TABLE accounts ADD COLUMN deleted_at TEXT;
