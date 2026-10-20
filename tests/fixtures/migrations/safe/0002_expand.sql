/* expand only: new column with a default, new table, insert-only upsert, trigger that only inserts */
ALTER TABLE users ADD COLUMN display_name TEXT DEFAULT '';
CREATE TABLE audit (id INTEGER PRIMARY KEY, user_id TEXT, note TEXT);
INSERT INTO users (id, email, created_at) VALUES ('x', 'x@example.org', '2026-01-01')
  ON CONFLICT (id) DO NOTHING;
-- DROP TABLE users; DELETE FROM users;  (a comment, ignored)
CREATE TRIGGER users_audit AFTER DELETE ON users BEGIN
  INSERT INTO audit (user_id, note) VALUES (old.id, 'DELETE FROM users');
END;
