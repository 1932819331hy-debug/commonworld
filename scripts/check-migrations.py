#!/usr/bin/env python3
"""Gate for D1 migrations before a production deploy (expand -> deploy -> contract, see docs/DEPLOY.md).

A migration runs BEFORE the new Worker is live, so while it runs (and after a Worker rollback) the database is used by
the OLD code. Every pending migration must therefore be backward compatible: add tables, add nullable/defaulted
columns, add indexes, backfill rows. Removing or renaming something the old code still reads ships in a later release,
after the code no longer uses it.

This script finds the pending migrations and fails when one of them contains destructive SQL:
  DROP TABLE, ALTER TABLE ... DROP (COLUMN), ALTER TABLE ... RENAME (table or column),
  DELETE FROM without WHERE, UPDATE ... SET without WHERE.
Comments and string literals are ignored. It is a safety net, not a SQL parser: a reviewer still reads every migration.

Pending = the migration files whose names appear in the output of
    npx wrangler d1 migrations list <db> --remote --env production
(the table of migrations not yet applied). Output that says "No migrations to apply" means none are pending; output that
names none of the files and does not say that is treated as an error (fail closed: wrangler changed its format,
wrong directory, auth error...).

Override: --allow must equal --sha (the release sha typed a second time, workflow input allow_destructive_migration),
then destructive findings are printed as warnings and the gate passes.

Usage:
    check-migrations.py --dir platform/migrations --pending-from wrangler-list.txt [--sha SHA --allow SHA]
    check-migrations.py --dir platform/migrations --all          # scan every file (CI, report only with --warn-only)
Exit codes: 0 ok, 1 destructive SQL without override, 2 usage / unreadable input.
"""
import argparse, os, re, sys

NO_PENDING = re.compile(r'no migrations to apply', re.I)
SHA40 = re.compile(r'[0-9a-f]{40}')


def strip_sql(text):
    """Drop -- and /* */ comments and blank out '...' string literals (quoted identifiers are kept)."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith('--', i):
            j = text.find('\n', i)
            i = n if j < 0 else j
        elif text.startswith('/*', i):
            j = text.find('*/', i + 2)
            i = n if j < 0 else j + 2
            out.append(' ')
        elif c == "'":
            j = i + 1
            while j < n:
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        j += 2; continue
                    break
                j += 1
            out.append("''")
            i = j + 1
        else:
            out.append(c); i += 1
    return ''.join(out)


def statements(text):
    for st in strip_sql(text).split(';'):
        st = ' '.join(st.split())
        if st:
            yield st


IDENT = r'(?:"[^"]*"|`[^`]*`|\[[^\]]*\]|[\w.]+)'
RULES = [
    ('DROP TABLE', re.compile(r'\bDROP\s+TABLE\b', re.I), None),
    ('ALTER TABLE ... DROP', re.compile(r'\bALTER\s+TABLE\s+' + IDENT + r'\s+DROP\b', re.I), None),
    ('ALTER TABLE ... RENAME', re.compile(r'\bALTER\s+TABLE\s+' + IDENT + r'\s+RENAME\b', re.I), None),
    ('DELETE FROM without WHERE', re.compile(r'\bDELETE\s+FROM\b', re.I), 'where'),
    ('UPDATE without WHERE', re.compile(r'(?<!\bDO )\bUPDATE\s+(?:OR\s+\w+\s+)?' + IDENT + r'\s+SET\b', re.I), 'where'),
]
WHERE = re.compile(r'\bWHERE\b', re.I)


def findings(text):
    """-> [(rule, statement)] for one migration file's SQL."""
    res = []
    for st in statements(text):
        for name, rx, need in RULES:
            m = rx.search(st)
            if not m:
                continue
            if need == 'where' and WHERE.search(st, m.end()):
                continue
            res.append((name, st[:200]))
    return res


def pending_files(files, listing):
    """Names (from files) that wrangler lists as not applied. None when the listing cannot be understood."""
    named = [f for f in files if re.search(r'(?<![\w.-])' + re.escape(f) + r'(?![\w.-])', listing)]
    if named:
        return named
    if NO_PENDING.search(listing):
        return []
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--dir', required=True, help='migrations directory (wrangler migrations_dir)')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--pending-from', help='file with the output of `wrangler d1 migrations list --remote`')
    g.add_argument('--all', action='store_true', help='scan every migration file')
    ap.add_argument('--sha', default='', help='release sha')
    ap.add_argument('--allow', default='', help='override: must equal --sha exactly')
    ap.add_argument('--warn-only', action='store_true', help='report findings as warnings, never fail on them')
    a = ap.parse_args(argv)

    if not os.path.isdir(a.dir):
        print(f'::error::migrations directory {a.dir} not found'); return 2
    files = sorted(f for f in os.listdir(a.dir) if f.endswith('.sql'))
    if a.all:
        pending = files
    else:
        try:
            listing = open(a.pending_from, encoding='utf-8', errors='replace').read()
        except OSError as ex:
            print(f'::error::cannot read {a.pending_from}: {ex}'); return 2
        pending = pending_files(files, listing)
        if pending is None:
            print('::error::could not tell which migrations are pending: the wrangler output names no file in '
                  f'{a.dir} and does not say "No migrations to apply"')
            return 2
    print(f'pending migrations: {", ".join(pending) if pending else "none"}')

    hits = []
    for f in pending:
        for rule, st in findings(open(os.path.join(a.dir, f), encoding='utf-8').read()):
            hits.append((f, rule, st))
    if not hits:
        print('no destructive SQL in pending migrations'); return 0

    override = bool(a.allow) and SHA40.fullmatch(a.sha or '') is not None and a.allow == a.sha
    level = 'warning' if (override or a.warn_only) else 'error'
    for f, rule, st in hits:
        print(f'::{level} file={a.dir}/{f}::{rule}: {st}')
    if override:
        print('destructive migration allowed for this release: allow_destructive_migration equals the release sha')
        return 0
    if a.warn_only:
        return 0
    print('::error::destructive migration blocked. Ship it in a later release, after the running Worker no longer '
          'uses what it removes (docs/DEPLOY.md). To override for this one release, type the release sha again in '
          'allow_destructive_migration.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
