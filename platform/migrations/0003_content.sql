-- Content: posts, comments, porch lines, upvotes, idempotency, change feed.
-- Each content table has its own readable display number (`number`,
-- never reused) plus an opaque `id`.
CREATE TABLE posts (
  number INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  author_id TEXT NOT NULL REFERENCES accounts(id),
  section_slug TEXT NOT NULL REFERENCES sections(slug),
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'visible' CHECK (status IN ('visible', 'hidden')),
  created_at TEXT NOT NULL
);
CREATE INDEX posts_section ON posts(section_slug, status, number DESC);
CREATE INDEX posts_author ON posts(author_id, created_at);
CREATE INDEX posts_created ON posts(created_at);

CREATE TABLE post_tags (
  post_number INTEGER NOT NULL REFERENCES posts(number),
  tag_slug TEXT NOT NULL REFERENCES tags(slug),
  PRIMARY KEY (post_number, tag_slug)
);
CREATE INDEX post_tags_tag ON post_tags(tag_slug, post_number DESC);

CREATE TABLE comments (
  number INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  post_number INTEGER NOT NULL REFERENCES posts(number),
  parent_number INTEGER REFERENCES comments(number),
  author_id TEXT NOT NULL REFERENCES accounts(id),
  body TEXT NOT NULL,
  depth INTEGER NOT NULL CHECK (depth BETWEEN 1 AND 6),
  status TEXT NOT NULL DEFAULT 'visible' CHECK (status IN ('visible', 'hidden')),
  created_at TEXT NOT NULL
);
CREATE INDEX comments_post ON comments(post_number, number);
CREATE INDEX comments_author ON comments(author_id, created_at);

-- Plain porch: short public lines, no threading, no post citations (v1).
CREATE TABLE porch_lines (
  number INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  author_id TEXT NOT NULL REFERENCES accounts(id),
  body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'visible' CHECK (status IN ('visible', 'hidden')),
  created_at TEXT NOT NULL
);
CREATE INDEX porch_author ON porch_lines(author_id, created_at);

-- Upvotes only. `karma_eligible` is fixed at vote time: 1 when the voter's
-- account was at least `karma.min_voter_age_hours` old when voting.
CREATE TABLE votes (
  target_type TEXT NOT NULL CHECK (target_type IN ('post', 'comment')),
  target_number INTEGER NOT NULL,
  target_author_id TEXT NOT NULL REFERENCES accounts(id),
  voter_id TEXT NOT NULL REFERENCES accounts(id),
  karma_eligible INTEGER NOT NULL CHECK (karma_eligible IN (0, 1)),
  created_at TEXT NOT NULL,
  PRIMARY KEY (target_type, target_number, voter_id),
  CHECK (target_author_id <> voter_id)
);
CREATE INDEX votes_author ON votes(target_author_id, created_at);
CREATE INDEX votes_voter ON votes(voter_id, created_at);

CREATE TABLE idempotency_keys (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  idem_key TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  object_type TEXT NOT NULL,
  object_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (account_id, idem_key)
);

-- Change feed: append-only, `seq` is the cursor.
CREATE TABLE events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL,
  object_type TEXT NOT NULL,
  object_number INTEGER,
  actor_id TEXT,
  data_json TEXT,
  created_at TEXT NOT NULL
);
