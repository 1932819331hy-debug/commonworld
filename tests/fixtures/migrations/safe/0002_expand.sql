/* expand only: new column with a default, backfill with WHERE, upsert */
ALTER TABLE users ADD COLUMN display_name TEXT DEFAULT '';
UPDATE users SET display_name = email WHERE display_name = '';
DELETE FROM users WHERE email = 'DROP TABLE users; DELETE FROM users';
INSERT INTO users (id, email, created_at) VALUES ('x', 'x@example.org', '2026-01-01')
  ON CONFLICT (id) DO UPDATE SET email = excluded.email;
-- DROP TABLE users;  (a comment, ignored)
CREATE TRIGGER users_touch AFTER DELETE ON users BEGIN
  UPDATE users SET created_at = created_at WHERE id = old.id;
END;
