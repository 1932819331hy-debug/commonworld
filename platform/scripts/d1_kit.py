#!/usr/bin/env python3
"""Helpers for scripts/d1-backup.sh and scripts/d1-restore.sh (Commonworld v1 D1 backup + restore kit).

A raw `wrangler d1 export` dump cannot be imported back as-is: it fails on foreign-key order (e.g. `sections`
REFERENCES `section_groups`, which the dump creates later), `PRAGMA defer_foreign_keys` does not help, and remote D1
commits each --file on its own. The method that works (restore drill 2026-10-18, staging, 32 tables / 698 rows):

  1. every CREATE TABLE first (one file),
  2. rows split per table, tables in FK-parent-first order (topological sort over PRAGMA foreign_key_list
     on a local sqlite load of the dump),
  3. indexes, triggers, views,
  4. sqlite_sequence last (keeps AUTOINCREMENT counters, e.g. citizen numbers, where they were).

Verification: one SELECT per chunk of tables with (SELECT count(*) FROM "t") AS "t" subqueries (D1 rejects big
UNION ALL compounds; PRAGMA table_info is not allowed remotely), compared with the manifest.

Subcommands (Python 3 standard library only):
  counts  <dump.sql>                     -> JSON: tables{name: rows}, sqlite_sequence{}, last_migration
  plan    <dump.sql> <outdir>            -> writes ordered .sql files into outdir, prints their paths in order
  verify-sql <expected.json>             -> prints the count SELECTs, one per line
  compare <expected.json> <result.json>... -> compares `wrangler d1 execute --json` outputs, prints PASS/FAIL
"""
import json
import os
import sqlite3
import sys

SKIP_PREFIXES = ("sqlite_", "_cf_")  # sqlite internals and Cloudflare-internal tables (_cf_KV, _cf_METADATA)
CHUNK_ROWS = int(os.environ.get("D1_RESTORE_CHUNK_ROWS", "5000"))  # rows per data file (big tables are split)
VERIFY_CHUNK = int(os.environ.get("D1_VERIFY_CHUNK", "25"))  # count subqueries per SELECT


def qi(name):
    return '"' + name.replace('"', '""') + '"'


def load(dump_path):
    db = sqlite3.connect(":memory:")  # foreign_keys is OFF by default in Python's sqlite3, so the raw dump loads
    with open(dump_path, encoding="utf-8") as f:
        db.executescript(f.read())
    return db


def user_tables(db):
    rows = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY rowid").fetchall()
    return [r[0] for r in rows if not r[0].startswith(SKIP_PREFIXES)]


def counts(db):
    tables = {t: db.execute(f"SELECT count(*) FROM {qi(t)}").fetchone()[0] for t in user_tables(db)}
    seq = {}
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
        seq = {n: s for n, s in db.execute("SELECT name, seq FROM sqlite_sequence ORDER BY name")}
    last = None
    if "d1_migrations" in tables:
        r = db.execute("SELECT id, name FROM d1_migrations ORDER BY id DESC LIMIT 1").fetchone()
        if r:
            last = {"id": r[0], "name": r[1]}
    return {"tables": tables, "sqlite_sequence": seq, "last_migration": last,
            "table_count": len(tables), "total_rows": sum(tables.values())}


def fk_order(db, tables):
    """Kahn's topological sort: a table comes after every table it references. Ties keep dump order.
    Returns (ordered, cyclic) - cyclic tables (if any) are imported together in one file at the end."""
    lower = {t.lower(): t for t in tables}
    parents = {}
    for t in tables:
        ps = set()
        for row in db.execute(f"PRAGMA foreign_key_list({qi(t)})"):
            p = lower.get(row[2].lower())
            if p and p != t:  # self-references are handled by defer_foreign_keys inside the table's own file
                ps.add(p)
        parents[t] = ps
    ordered, done = [], set()
    while True:
        ready = [t for t in tables if t not in done and parents[t] <= done]
        if not ready:
            break
        for t in ready:
            ordered.append(t)
            done.add(t)
    return ordered, [t for t in tables if t not in done]


def sql_value(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v != v:
            return "NULL"
        if v in (float("inf"), float("-inf")):
            return "9e999" if v > 0 else "-9e999"
        return repr(v)
    if isinstance(v, bytes):
        return "X'" + v.hex() + "'"
    return "'" + str(v).replace("'", "''") + "'"


def insert_lines(db, table):
    cols = [r[1] for r in db.execute(f"PRAGMA table_info({qi(table)})")]
    collist = ",".join(qi(c) for c in cols)
    for row in db.execute(f"SELECT * FROM {qi(table)} ORDER BY rowid" if has_rowid(db, table) else f"SELECT * FROM {qi(table)}"):
        yield f"INSERT INTO {qi(table)} ({collist}) VALUES({','.join(sql_value(v) for v in row)});"


def has_rowid(db, table):
    sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0] or ""
    return "WITHOUT ROWID" not in sql.upper()


def plan(dump_path, outdir):
    db = load(dump_path)
    os.makedirs(outdir, exist_ok=True)
    tables = user_tables(db)
    ordered, cyclic = fk_order(db, tables)
    files = []

    def write(name, lines):
        path = os.path.join(outdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        files.append(path)

    create = {n: s for n, s in db.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL")}
    write("000-schema.sql", [create[t].rstrip(";") + ";" for t in ordered + cyclic])

    n = 0
    groups = [[t] for t in ordered] + ([cyclic] if cyclic else [])
    for group in groups:
        buf = []
        part = 0
        label = group[0] if len(group) == 1 else "cycle"
        for t in group:
            for line in insert_lines(db, t):
                buf.append(line)
                if len(buf) >= CHUNK_ROWS:
                    n += 1
                    part += 1
                    write(f"{100 + n:03d}-data-{label}-{part}.sql", ["PRAGMA defer_foreign_keys = true;"] + buf)
                    buf = []
        if buf:
            n += 1
            part += 1
            write(f"{100 + n:03d}-data-{label}-{part}.sql", ["PRAGMA defer_foreign_keys = true;"] + buf)

    other = [s for (s,) in db.execute(
        "SELECT sql FROM sqlite_master WHERE type IN ('index','trigger','view') AND sql IS NOT NULL "
        "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '\\_cf\\_%' ESCAPE '\\' ORDER BY rowid")]
    if other:
        write("800-indexes-triggers-views.sql", [s.rstrip(";") + ";" for s in other])

    seq = counts(db)["sqlite_sequence"]
    if seq:
        write("900-sqlite_sequence.sql", ["DELETE FROM sqlite_sequence;"] + [
            f"INSERT INTO sqlite_sequence (name, seq) VALUES({sql_value(k)}, {int(v)});" for k, v in seq.items()])

    if cyclic:
        print("WARNING: FK cycle between tables " + ", ".join(cyclic) + " - imported together in one file",
              file=sys.stderr)
    for f in files:
        print(f)


def verify_sql(expected):
    tables = sorted(expected["tables"])
    for i in range(0, len(tables), VERIFY_CHUNK):
        chunk = tables[i:i + VERIFY_CHUNK]
        print("SELECT " + ", ".join(f"(SELECT count(*) FROM {qi(t)}) AS {qi(t)}" for t in chunk))
    print("SELECT name, seq FROM sqlite_sequence ORDER BY name")


def compare(expected, result_files):
    got_tables, got_seq = {}, {}
    for path in result_files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for block in data if isinstance(data, list) else [data]:
            for row in block.get("results", []):
                if set(row) == {"name", "seq"}:
                    got_seq[row["name"]] = row["seq"]
                else:
                    got_tables.update(row)
    bad = []
    for t, n in sorted(expected["tables"].items()):
        g = got_tables.get(t)
        mark = "ok " if g == n else "BAD"
        if g != n:
            bad.append(t)
        print(f"  {mark} {t}: expected {n}, got {g}")
    for name, s in sorted(expected.get("sqlite_sequence", {}).items()):
        if got_seq.get(name) != s:
            bad.append(f"sqlite_sequence[{name}]")
            print(f"  BAD sqlite_sequence {name}: expected {s}, got {got_seq.get(name)}")
    total = sum(expected["tables"].values())
    if bad:
        print(f"FAIL: {len(bad)} mismatch(es): {', '.join(bad)}")
        return 1
    print(f"PASS: {len(expected['tables'])} tables, {total} rows, {len(expected.get('sqlite_sequence', {}))} "
          f"sqlite_sequence counters match")
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    cmd = argv[1]
    if cmd == "counts" and len(argv) == 3:
        print(json.dumps(counts(load(argv[2])), indent=2, sort_keys=True))
    elif cmd == "plan" and len(argv) == 4:
        plan(argv[2], argv[3])
    elif cmd == "verify-sql" and len(argv) == 3:
        with open(argv[2], encoding="utf-8") as f:
            verify_sql(json.load(f))
    elif cmd == "compare" and len(argv) >= 4:
        with open(argv[2], encoding="utf-8") as f:
            return compare(json.load(f), argv[3:])
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
