-- backfill: changes existing rows, so the owner reviewed it in the PR
-- reviewed-by-owner: #42
UPDATE users SET email = lower(email) WHERE email <> lower(email);
DELETE FROM users WHERE email = '';
