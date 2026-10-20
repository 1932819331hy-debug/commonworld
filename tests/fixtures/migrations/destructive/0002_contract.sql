DROP TABLE IF EXISTS old_sessions;
ALTER TABLE users DROP COLUMN name;
alter table "users" rename column email to mail;
ALTER TABLE users RENAME TO accounts;
delete
  from accounts;
UPDATE accounts SET mail = lower(mail);
