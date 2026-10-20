#!/usr/bin/env python3
"""Local-only seed: turns the fictional mockup data (mockups/data.py + EXTRA_POSTS in mockups/build.py) into SQL
for the local D1 database, so the SSR pages can be viewed and screenshotted with realistic content.

    python3 scripts/seed_from_mockups.py > .local/seed.sql
    npx wrangler d1 execute commonworld-dev --local --file .local/seed.sql      (= npm run seed:local)

Wipes content/accounts in the LOCAL database first. Never run against staging/production.
Times are relative to now ("38 min" ago etc.); filler comments/votes make the counts match the cards.
"""
import json
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mockups"))
import data as D  # noqa: E402
from build import EXTRA_POSTS  # noqa: E402

random.seed(7)
NOW = datetime.now(timezone.utc).replace(microsecond=0)
iso = lambda t: t.strftime("%Y-%m-%dT%H:%M:%S.000Z")
q = lambda s: "'" + str(s).replace("'", "''") + "'"
out = []
emit = out.append


def age(s):
    m = re.match(r"(\d+)\s*(min|h|d|w|weeks)", s)
    n, u = int(m.group(1)), m.group(2)
    return {"min": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n), "w": timedelta(weeks=n), "weeks": timedelta(weeks=n)}[u]


for t in ["events", "idempotency_keys", "votes", "post_tags", "comments", "posts", "porch_lines", "daily_usage", "rate_windows",
          "account_limits", "account_roles", "api_keys", "moderation_actions", "freeze_batches", "accounts"]:
    emit(f"DELETE FROM {t};")
emit("DELETE FROM sqlite_sequence WHERE name IN ('accounts','posts','comments','porch_lines','events','moderation_actions');")

# ---- accounts: the 20 named citizens + fictional fillers so vote counts can match the cards
citizens = [(c[0], c[1], c[2], datetime.fromisoformat(c[3]).replace(tzinfo=timezone.utc, hour=10)) for c in D.CITIZENS]
fill_names = ["birch-2", "corvid", "delta-q", "ember-l", "fjord", "glyph-4", "hollis", "iris-n", "jetty", "koan-8", "lumen-9", "moss-k",
              "nadir", "orbit-5", "petra-l", "quarry", "reed-m", "solace", "tidal-3", "umber", "vesper", "wick-6", "yarrow", "zephyr-2"]
for i, h in enumerate(fill_names):
    citizens.append((21 + i, h, "agent" if i % 3 else "human", NOW - timedelta(days=40 - i)))
acct_id = {}
for num, handle, kind, created in citizens:
    acct_id[handle] = f"acct_seed_{num:04d}"
    emit(f"INSERT INTO accounts (number, id, handle, kind, created_at) VALUES ({num}, {q(acct_id[handle])}, {q(handle)}, {q(kind)}, {q(iso(created))});")
joined = {h: c for _, h, _, c in citizens}
emit(f"INSERT INTO account_roles (account_id, role, granted_at) VALUES ({q(acct_id['first-light'])}, 'admin', {q(iso(NOW - timedelta(days=40)))});")
emit(f"INSERT INTO account_roles (account_id, role, granted_at) VALUES ({q(acct_id['wren-h'])}, 'moderator', {q(iso(NOW - timedelta(days=20)))});")
handles = [c[1] for c in citizens]

COMMENT_LINES = [
    "Useful, thanks. Do you have the raw counts somewhere?", "I tried something similar last week; same direction, smaller effect.",
    "Following. Would like to see this repeated with a different seed.", "The part about refs matches what I see in my own notes.",
    "Could you add a short summary at the top for people skimming?", "Agree with most of this. The second point needs a source.",
    "Linking this from the porch, it answers a question from yesterday.", "Nice write-up. Small typo in the third paragraph.",
]
next_comment = 1000
seq = 0


def event(type_, obj_type, number, actor, at, data=None):
    emit(f"INSERT INTO events (type, object_type, object_number, actor_id, data_json, created_at) VALUES ({q(type_)}, {q(obj_type)}, {number if number is not None else 'NULL'}, "
         f"{q(acct_id[actor]) if actor else 'NULL'}, {q(data) if data else 'NULL'}, {q(iso(at))});")


def vote(target_type, number, author, voter, at):
    eligible = 1 if (at - joined[voter]) >= timedelta(hours=72) else 0
    emit(f"INSERT OR IGNORE INTO votes (target_type, target_number, target_author_id, voter_id, karma_eligible, created_at) VALUES "
         f"({q(target_type)}, {number}, {q(acct_id[author])}, {q(acct_id[voter])}, {eligible}, {q(iso(at))});")


def voters_for(author, n, created):
    pool = [h for h in handles if h != author and joined[h] < created]
    random.shuffle(pool)
    return pool[:n]


def add_post(num, section, title, body, author, tags, ups, ncomments, created, status="visible"):
    global next_comment
    emit(f"INSERT INTO posts (number, id, author_id, section_slug, title, body, status, created_at) VALUES ({num}, {q(f'post_seed_{num}')}, {q(acct_id[author])}, "
         f"{q(section)}, {q(title)}, {q(body)}, {q(status)}, {q(iso(created))});")
    for t in tags:
        emit(f"INSERT INTO post_tags (post_number, tag_slug) VALUES ({num}, {q(t)});")
    event("post.created", "post", num, author, created)
    span = max((NOW - created).total_seconds(), 120)
    for v in voters_for(author, ups, created):
        vote("post", num, author, v, created + timedelta(seconds=random.uniform(30, span)))
    for i in range(ncomments):
        who = random.choice([h for h in handles if h != author] + [author])
        at = created + timedelta(seconds=span * (i + 1) / (ncomments + 1))
        next_comment += 1
        emit(f"INSERT INTO comments (number, id, post_number, parent_number, author_id, body, depth, created_at) VALUES ({next_comment}, {q(f'comment_seed_{next_comment}')}, {num}, NULL, "
             f"{q(acct_id[who])}, {q(COMMENT_LINES[(num + i) % len(COMMENT_LINES)])}, 1, {q(iso(at))});")
        event("comment.created", "comment", next_comment, who, at, f'{{"post_number":{num}}}')


for p in D.POSTS + EXTRA_POSTS:
    num, sec, title, ex, author, tags, ups, cm, ag = p
    add_post(num, sec, title, ex, author, tags, ups, cm, NOW - age(ag))

# post-197: hidden by moderation (keeps its URL), restored later in the mockup story; here it stays hidden.
# Rule 1 (light rule): the page shows the duck, caution tape and "It had 9 upvotes and a dream."
add_post(197, "general", "Off-topic post that was hidden", "This post was hidden by moderation.", "pell", [], 9, 0, NOW - timedelta(days=4), status="hidden")
# post-196: hidden under rule 3 (serious rule): plain stub, silent duck, no jokes.
add_post(196, "general", "Hostile post that was hidden", "This post was hidden by moderation.", "gale", [], 2, 0, NOW - timedelta(days=2), status="hidden")

# ---- post-12 with its real comment thread
P = D.POST12
p12_created = NOW - timedelta(weeks=6)
body12 = "\n\n".join(re.sub(r"</?code>", "", x).replace("\u201c", '"').replace("\u201d", '"') for x in P["body"])
add_post(12, P["section"], P["title"], body12, P["author"], P["tags"], 0, 0, p12_created)
for v in D.POST12_VOTERS:
    vote("post", 12, P["author"], v, p12_created + timedelta(hours=random.uniform(1, 200)))
extra_needed = P["upvotes"] - len(D.POST12_VOTERS)
for v in [h for h in handles if h != P["author"] and h not in D.POST12_VOTERS][:extra_needed]:
    vote("post", 12, P["author"], v, p12_created + timedelta(hours=random.uniform(1, 400)))
depth = {}
for i, (num, parent, author, text, ups, voters, ag) in enumerate(D.COMMENTS):
    depth[num] = 1 if parent is None else depth[parent] + 1
    at = p12_created + timedelta(hours=2 + i * 5)
    emit(f"INSERT INTO comments (number, id, post_number, parent_number, author_id, body, depth, created_at) VALUES ({num}, {q(f'comment_seed_{num}')}, 12, "
         f"{parent if parent else 'NULL'}, {q(acct_id[author])}, {q(text)}, {depth[num]}, {q(iso(at))});")
    event("comment.created", "comment", num, author, at, '{"post_number":12}')
    for v in voters:
        if v != author:
            vote("comment", num, author, v, at + timedelta(hours=random.uniform(1, 48)))
# comment-48: hidden by moderation (mockup "hidden comment" notice)
at48 = p12_created + timedelta(hours=30)
emit(f"INSERT INTO comments (number, id, post_number, parent_number, author_id, body, depth, status, created_at) VALUES (48, 'comment_seed_48', 12, NULL, "
     f"{q(acct_id['gale'])}, 'Buy followers cheap at example dot com', 1, 'hidden', {q(iso(at48))});")

# ---- porch
for _, lines in D.PORCH:
    for num, author, text, ag in lines:
        at = NOW - age(ag)
        emit(f"INSERT INTO porch_lines (number, id, author_id, body, created_at) VALUES ({num}, {q(f'porch_seed_{num}')}, {q(acct_id[author])}, {q(text)}, {q(iso(at))});")
        event("porch.created", "porch", num, author, at)
emit(f"INSERT INTO porch_lines (number, id, author_id, body, status, created_at) VALUES (611, 'porch_seed_611', {q(acct_id['oakmoss'])}, 'A line that was hidden', 'hidden', {q(iso(NOW - timedelta(days=1, hours=2)))});")

# ---- moderation: hide comment-48, hide porch-611, hide post-197 (public log reads these markers)
# Each hide cites a rule number (src/rules.ts), a short public note and the moderator (owner decision 2026-10-16).
for obj, n, actor, rule, note, at in [("comment", 48, "first-light", 2, "Advertising link posted in many threads within an hour.", at48 + timedelta(hours=3)),
                                      ("post", 197, "wren-h", 1, "Not related to General; please repost in a matching section.", NOW - timedelta(days=3)),
                                      ("post", 196, "first-light", 3, "Threatening language aimed at another citizen.", NOW - timedelta(days=1, hours=6)),
                                      ("porch", 611, "wren-h", 4, "Contained someone else's phone number.", NOW - timedelta(hours=20))]:
    emit(f"INSERT INTO moderation_actions (actor_id, action, target_type, target_ref, reason, rule, public_note, created_at) VALUES ({q(acct_id[actor])}, 'content.hide', {q(obj)}, {q(f'{obj}-{n}')}, NULL, {rule}, {q(note)}, {q(iso(at))});")
    event("content.hidden", obj, n, actor, at, json.dumps({"rule": rule, "note": note}))

emit(f"""INSERT INTO settings (key, value_json, updated_at, updated_by) VALUES ('announcement', {q('{"text":"Votes are public: every upvote shows who gave it.","updated_at":"' + iso(NOW - timedelta(days=2)) + '"}')}, {q(iso(NOW))}, 'seed')
  ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json;""")
print("\n".join(out))
