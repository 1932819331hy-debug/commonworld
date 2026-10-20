-- initial schema
CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX users_email ON users (email);
