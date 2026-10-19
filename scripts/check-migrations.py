#!/usr/bin/env python3
"""Gate for D1 migrations before a production deploy (expand -> deploy -> contract, see docs/DEPLOY.md).

A migration runs BEFORE the new Worker is live, so while it runs (and after a Worker rollback) the database is used by
the OLD code. Every pending migration must therefore be backward compatible: add tables, add nullable/defaulted
columns, add indexes, backfill rows. Removing or renaming something the old code still reads ships in a later release,
after the code no longer uses it.

The SQL is read by a small tokenizer (comments dropped, '...' strings, "..."/`...`/[...] identifiers, parenthesis
depth, statements split on top-level ';', CREATE TRIGGER ... BEGIN ... END kept whole). Every statement is classified:

  destructive      DROP TABLE, ALTER TABLE ... DROP (COLUMN), ALTER TABLE ... RENAME (table or column),
                   DELETE / UPDATE without a top-level WHERE of their own (a WHERE inside a subquery, a SET value or
                   RETURNING does not count) or with a trivially true one (1, TRUE, 1=1, 'a'='a', NOT 0, x=x, a
                   constant subquery such as (SELECT 1) ...), also inside WITH ... and inside trigger bodies
  review-required  DROP INDEX, DROP TRIGGER, DROP VIEW, INSERT OR REPLACE / REPLACE INTO (can overwrite rows),
                   ALTER TABLE ... ADD of a column SQLite refuses at apply time: NOT NULL without a non-NULL DEFAULT,
                   PRIMARY KEY, UNIQUE, a STORED generated column, DEFAULT CURRENT_TIME/DATE/TIMESTAMP
  unknown          anything the tokenizer cannot read or a statement kind not on the known-safe list (fail closed)

Known safe: CREATE TABLE / INDEX / VIEW / TRIGGER / VIRTUAL TABLE, ALTER TABLE ... ADD (other column definitions), INSERT (plain, OR IGNORE /
ABORT / FAIL / ROLLBACK, ON CONFLICT DO ...), SELECT, VALUES, BEGIN / COMMIT / END / SAVEPOINT / RELEASE, ANALYZE,
REINDEX, PRAGMA foreign_keys / defer_foreign_keys / optimize. Every finding of any class blocks the deploy unless the
override is given. It is a safety net, not a SQL engine: a reviewer still reads every migration.

Pending = the output of
    npx wrangler d1 migrations list <db> --remote --env production
read strictly (format verified with wrangler 4.151.1, fixtures tests/fixtures/migrations/wrangler-4.151.1-*.txt):
either exactly "No migrations to apply!" or exactly one "Migrations to be applied:" box table with a "Name" header.
It fails when: both or neither marker is there, an error line is printed, a table line cannot be read, a listed name
is not a local file or is listed twice, any "*.sql" name appears outside the table, or the pending names are not a
suffix of the sorted local migration files (in that order).

Override: --allow must equal --sha (the release sha typed a second time, workflow input allow_destructive_migration),
then findings are printed as warnings and the gate passes.

Usage:
    check-migrations.py --dir platform/migrations --pending-from wrangler-list.txt [--sha SHA --allow SHA]
    check-migrations.py --dir platform/migrations --all          # scan every file (CI, report only with --warn-only)
Exit codes: 0 ok, 1 findings without override, 2 usage / unreadable input / pending list not understood.
"""
import argparse, os, re, sqlite3, sys

SHA40 = re.compile(r'[0-9a-f]{40}')

DESTRUCTIVE, REVIEW, UNKNOWN = 'destructive', 'review-required', 'unknown'


class SqlError(Exception):
    pass


# ---------------------------------------------------------------- tokenizer

class Tok:
    __slots__ = ('kind', 'text', 'depth')

    def __init__(self, kind, text, depth=0):
        self.kind, self.text, self.depth = kind, text, depth

    @property
    def up(self):
        return self.text.upper() if self.kind == 'word' else None

    def __repr__(self):
        return f'{self.kind}:{self.text}@{self.depth}'


_WORD = re.compile(r'[A-Za-z_\x80-\U0010ffff][\w$\x80-\U0010ffff]*')
_NUM = re.compile(r'(?:0[xX][0-9a-fA-F]+|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)')
_OPS = ('<<', '>>', '<=', '>=', '==', '!=', '<>', '||', '->>', '->')


def tokenize(text):
    """-> [Tok]; kinds: word, ident (quoted identifier, text without quotes), string, blob, number, param, op, ';'.
    Raises SqlError on an unterminated string / identifier / comment or unbalanced parentheses."""
    toks, i, n, depth = [], 0, len(text), 0
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif text.startswith('--', i):
            j = text.find('\n', i)
            i = n if j < 0 else j + 1
        elif text.startswith('/*', i):
            j = text.find('*/', i + 2)
            if j < 0:
                raise SqlError('unterminated /* comment')
            i = j + 2
        elif c in '\'"`' or (c in 'xX' and i + 1 < n and text[i + 1] == "'"):
            blob = c in 'xX'
            q = "'" if blob else c
            j, buf = i + (2 if blob else 1), []
            while True:
                if j >= n:
                    raise SqlError(f'unterminated {q} quote')
                if text[j] == q:
                    if j + 1 < n and text[j + 1] == q:
                        buf.append(q); j += 2; continue
                    break
                buf.append(text[j]); j += 1
            kind = 'blob' if blob else ('string' if q == "'" else 'ident')
            toks.append(Tok(kind, ''.join(buf), depth))
            i = j + 1
        elif c == '[':
            j = text.find(']', i + 1)
            if j < 0:
                raise SqlError('unterminated [ identifier')
            toks.append(Tok('ident', text[i + 1:j], depth))
            i = j + 1
        elif c == '(':
            toks.append(Tok('op', '(', depth)); depth += 1; i += 1
        elif c == ')':
            depth -= 1
            if depth < 0:
                raise SqlError('unbalanced )')
            toks.append(Tok('op', ')', depth)); i += 1
        elif c == ';':
            if depth:
                raise SqlError('; inside parentheses')
            toks.append(Tok(';', ';', 0)); i += 1
        elif c.isdigit() or (c == '.' and i + 1 < n and text[i + 1].isdigit()):
            m = _NUM.match(text, i)
            toks.append(Tok('number', m.group(), depth)); i = m.end()
        elif c in '?:@$':
            m = re.compile(r'[?:@$][\w]*').match(text, i)
            toks.append(Tok('param', m.group(), depth)); i = m.end()
        elif _WORD.match(text, i):
            m = _WORD.match(text, i)
            toks.append(Tok('word', m.group(), depth)); i = m.end()
        else:
            op = next((o for o in _OPS if text.startswith(o, i)), c)
            if op not in _OPS and op not in '=<>!+-*/%&|~,.':
                raise SqlError(f'unexpected character {op!r}')
            toks.append(Tok('op', op, depth)); i += len(op)
    if depth:
        raise SqlError('unbalanced (')
    return toks


def split_statements(toks):
    """Split on top-level ';'. A CREATE [TEMP] TRIGGER statement runs to its END (CASE ... END counted)."""
    out, cur, in_trigger, began, case = [], [], False, False, 0
    for t in toks:
        if t.kind == ';' and not (in_trigger and began):
            if cur:
                out.append(cur)
            cur, in_trigger, began, case = [], False, False, 0
            continue
        cur.append(t)
        if len(cur) <= 3 and t.up == 'TRIGGER' and cur[0].up == 'CREATE':
            in_trigger = True
        elif in_trigger and t.up == 'BEGIN' and not began:
            began = True
        elif in_trigger and began and t.up == 'CASE':
            case += 1
        elif in_trigger and began and t.up == 'END':
            if case:
                case -= 1
            else:
                began = False  # the next top-level ';' ends the statement
    if in_trigger and began:
        raise SqlError('CREATE TRIGGER without END')
    if cur:
        out.append(cur)
    return out


def show(toks):
    parts = []
    for t in toks:
        if t.kind == 'string':
            parts.append("'" + t.text.replace("'", "''") + "'")
        elif t.kind == 'ident':
            parts.append('"' + t.text.replace('"', '""') + '"')
        elif t.kind == 'blob':
            parts.append("X'" + t.text + "'")
        else:
            parts.append(t.text)
    return ' '.join(parts)[:200]


# ---------------------------------------------------------------- WHERE analysis

_CLAUSE_END = {'RETURNING', 'ORDER', 'LIMIT'}
_LITERAL_WORDS = {'TRUE', 'FALSE', 'NULL', 'NOT', 'AND', 'OR', 'IS', 'IN', 'BETWEEN', 'LIKE', 'GLOB', 'ESCAPE', 'CASE',
                  'WHEN', 'THEN', 'ELSE', 'END', 'CAST', 'AS', 'INTEGER', 'INT', 'TEXT', 'REAL', 'NUMERIC', 'BLOB',
                  'SELECT', 'WHERE', 'EXISTS', 'DISTINCT', 'ALL', 'UNION', 'INTERSECT', 'EXCEPT', 'VALUES',
                  'CURRENT_DATE', 'CURRENT_TIME', 'CURRENT_TIMESTAMP'}


def top_where(toks, start):
    """Condition tokens of the statement's own WHERE (depth of the verb), or None when there is none."""
    d = toks[start].depth
    for k in range(start + 1, len(toks)):
        t = toks[k]
        if t.depth != d:
            continue
        if t.up in _CLAUSE_END:
            return None
        if t.up == 'WHERE':
            cond = []
            for u in toks[k + 1:]:
                if u.depth == d and u.up in _CLAUSE_END:
                    break
                cond.append(u)
            return cond
    return None


def _strip_parens(toks):
    while len(toks) >= 2 and toks[0].text == '(' and toks[-1].text == ')' and toks[0].kind == 'op':
        d = toks[0].depth
        # outer pair only if the first '(' closes at the very end
        closes = [k for k, t in enumerate(toks) if t.kind == 'op' and t.text == ')' and t.depth == d]
        if closes and closes[0] == len(toks) - 1:
            toks = toks[1:-1]
        else:
            break
    return toks


def _split(toks, word):
    if not toks:
        return [toks]
    d = min(t.depth for t in toks)
    parts, cur, between = [], [], False
    for t in toks:
        if t.depth == d and t.up == 'BETWEEN':
            between = True
        if t.depth == d and t.up == word:
            if word == 'AND' and between:
                between = False  # the AND of BETWEEN x AND y
            else:
                parts.append(cur); cur = []; continue
        cur.append(t)
    parts.append(cur)
    return parts


def _name(t):
    return t.text.lower() if t.kind in ('word', 'ident') else None


def _self_compare(toks):
    """x = x, t.x == t.x, x IS x (same column on both sides)."""
    for k, t in enumerate(toks):
        if t.depth == toks[0].depth and (t.text in ('=', '==', '<=', '>=') or t.up == 'IS'):
            left, right = toks[:k], toks[k + 1:]
            names_l = [_name(u) if u.kind != 'op' else u.text for u in left]
            names_r = [_name(u) if u.kind != 'op' else u.text for u in right]
            return bool(left) and names_l == names_r and all(
                u.kind in ('word', 'ident') or u.text == '.' for u in left) and all(
                u.up not in _LITERAL_WORDS for u in left if u.kind == 'word')
    return False


def _constant_true(toks):
    """Literal-only condition (no column, table or function name) that SQLite evaluates to true (or cannot evaluate)."""
    if not toks:
        return True
    for t in toks:
        if t.kind in ('ident', 'param'):
            return False
        if t.kind == 'word' and t.up not in _LITERAL_WORDS:
            return False
    try:
        con = sqlite3.connect(':memory:')
        try:
            row = con.execute('SELECT CASE WHEN (' + show(toks) + ') THEN 1 ELSE 0 END').fetchone()
        finally:
            con.close()
        return bool(row and row[0])
    except sqlite3.Error:
        return True  # cannot tell: fail closed


def trivially_true(cond):
    cond = _strip_parens(cond)
    if not cond:
        return True
    ors = _split(cond, 'OR')
    if len(ors) > 1:
        return any(trivially_true(p) for p in ors)
    ands = _split(cond, 'AND')
    if len(ands) > 1:
        return all(trivially_true(p) for p in ands)
    return _constant_true(cond) or _self_compare(cond)


# ---------------------------------------------------------------- statement classification

_SAFE_PRAGMAS = {'foreign_keys', 'defer_foreign_keys', 'optimize'}


def _skip_with(toks):
    """Index of the main verb after WITH [RECURSIVE] name AS (...), ...; None when not found."""
    for k in range(1, len(toks)):
        t = toks[k]
        if t.depth == 0 and t.up in ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'REPLACE', 'VALUES') \
                and toks[k - 1].kind == 'op' and toks[k - 1].text == ')':
            return k
    return None


def _check_where(toks, k, verb):
    cond = top_where(toks, k)
    if cond is None:
        return [(DESTRUCTIVE, f'{verb} without WHERE')]
    if trivially_true(cond):
        return [(DESTRUCTIVE, f'{verb} with an always-true WHERE')]
    return []


def classify(st):
    """-> [(class, rule)] for one statement's tokens (empty = known safe)."""
    w = [t.up for t in st[:6]] + [None] * 6
    first = w[0]
    k = 0
    if first == 'WITH':
        k = _skip_with(st)
        if k is None:
            return [(UNKNOWN, 'WITH without a readable main statement')]
        first = st[k].up
        w = [t.up for t in st[k:k + 6]] + [None] * 6
    if first == 'UPDATE':
        return _check_where(st, k, 'UPDATE')
    if first == 'DELETE':
        return _check_where(st, k, 'DELETE FROM')
    if first == 'REPLACE':
        return [(REVIEW, 'REPLACE INTO (can overwrite rows)')]
    if first == 'INSERT':
        if w[1] == 'OR' and w[2] == 'REPLACE':
            return [(REVIEW, 'INSERT OR REPLACE (can overwrite rows)')]
        if w[1] == 'OR' and w[2] not in ('IGNORE', 'ABORT', 'FAIL', 'ROLLBACK'):
            return [(UNKNOWN, 'INSERT OR ' + str(w[2]))]
        return []
    if first in ('SELECT', 'VALUES'):
        return []
    if k:
        return [(UNKNOWN, 'WITH ... ' + str(first))]
    if first == 'DROP':
        what = w[1]
        if what == 'TABLE':
            return [(DESTRUCTIVE, 'DROP TABLE')]
        if what in ('INDEX', 'TRIGGER', 'VIEW'):
            return [(REVIEW, f'DROP {what}')]
        return [(UNKNOWN, f'DROP {what}')]
    if first == 'ALTER' and w[1] == 'TABLE':
        # ALTER TABLE [schema.]name <action>
        j = 2
        if j + 2 < len(st) and st[j + 1].text == '.':
            j += 2
        action = st[j + 1].up if j + 1 < len(st) else None
        if action == 'DROP':
            return [(DESTRUCTIVE, 'ALTER TABLE ... DROP')]
        if action == 'RENAME':
            return [(DESTRUCTIVE, 'ALTER TABLE ... RENAME')]
        if action == 'ADD':
            return _add_column(st[j + 2:])
        return [(UNKNOWN, f'ALTER TABLE ... {action}')]
    if first == 'CREATE':
        rest = [x for x in w[1:] if x not in ('TEMP', 'TEMPORARY', 'UNIQUE', 'VIRTUAL')]
        kind = rest[0] if rest else None
        if kind == 'TRIGGER':
            return _trigger_body(st)
        if kind in ('TABLE', 'INDEX', 'VIEW'):
            return []
        return [(UNKNOWN, f'CREATE {kind}')]
    if first in ('BEGIN', 'COMMIT', 'END', 'SAVEPOINT', 'RELEASE', 'ANALYZE', 'REINDEX'):
        return []
    if first == 'PRAGMA':
        name = st[1].text.lower() if len(st) > 1 else ''
        if len(st) > 3 and st[2].text == '.':
            name = st[3].text.lower()
        if name in _SAFE_PRAGMAS:
            return []
        return [(UNKNOWN, f'PRAGMA {name}')]
    return [(UNKNOWN, f'unknown statement {first or st[0].text}')]


_CONSTRAINT_START = {'CONSTRAINT', 'PRIMARY', 'NOT', 'NULL', 'UNIQUE', 'CHECK', 'DEFAULT', 'COLLATE', 'REFERENCES',
                     'GENERATED', 'AS'}


def _add_column(toks):
    """ALTER TABLE ... ADD [COLUMN] <column-def>: SQLite refuses some column definitions only when the statement runs
    (some only on a table that already has rows), which would stop `wrangler d1 migrations apply` half way through
    the pending list. Those are flagged review-required so the gate stops them before anything is applied."""
    if toks and toks[0].up == 'COLUMN':
        toks = toks[1:]
    top = [t for t in toks[1:] if t.depth == 0]   # constraints of the column; (...) contents are not constraints
    ups = [t.up for t in top] + [None]
    generated = 'GENERATED' in ups or 'AS' in ups
    res, default = [], None
    for i, u in enumerate(ups[:-1]):
        if u == 'PRIMARY' and ups[i + 1] == 'KEY':
            res.append((REVIEW, 'ADD COLUMN ... PRIMARY KEY (SQLite cannot add a PRIMARY KEY column)'))
        elif u == 'UNIQUE':
            res.append((REVIEW, 'ADD COLUMN ... UNIQUE (SQLite cannot add a UNIQUE column)'))
        elif u == 'STORED' and generated:
            res.append((REVIEW, 'ADD COLUMN ... STORED (SQLite cannot add a STORED generated column)'))
        elif u == 'DEFAULT' and i + 1 < len(top):
            nxt = top[i + 1]
            if nxt.kind == 'op' and nxt.text == '(':
                inner = [t for t in toks[toks.index(nxt) + 1:] if t.depth > 0]
                default = 'null' if [t.up for t in inner] == ['NULL'] else 'expr'
            else:
                default = 'null' if nxt.up == 'NULL' else 'value'
            if nxt.up in ('CURRENT_TIME', 'CURRENT_DATE', 'CURRENT_TIMESTAMP'):
                res.append((REVIEW, f'ADD COLUMN ... DEFAULT {nxt.up} (SQLite needs a constant default here)'))
    not_null = any(u == 'NOT' and ups[i + 1] == 'NULL' for i, u in enumerate(ups[:-1]))
    if not_null and not generated and default in (None, 'null'):
        res.append((REVIEW, 'ADD COLUMN ... NOT NULL without a non-NULL DEFAULT '
                            '(SQLite rejects it on a table that has rows)'))
    return res


def _trigger_body(st):
    b = next((k for k, t in enumerate(st) if t.up == 'BEGIN' and t.depth == 0), None)
    if b is None or st[-1].up != 'END':
        return [(UNKNOWN, 'CREATE TRIGGER without BEGIN ... END')]
    body = st[b + 1:-1]
    res = []
    for inner in split_statements(body + [Tok(';', ';', 0)]):
        for cls, rule in classify(inner):
            res.append((cls, rule + ' (in trigger body)'))
    return res


def findings(text):
    """-> [(rule, statement)] for one migration file's SQL; rule is '<class>: <what>'."""
    try:
        sts = split_statements(tokenize(text))
    except SqlError as ex:
        return [(f'{UNKNOWN}: cannot read the SQL ({ex})', text.strip()[:200])]
    res = []
    for st in sts:
        for cls, rule in classify(st):
            res.append((f'{cls}: {rule}', show(st)))
    return res


# ---------------------------------------------------------------- wrangler output

class PendingError(Exception):
    pass


ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
SQL_NAME = re.compile(r'[\w.-]+\.sql\b', re.I)
NO_PENDING = 'No migrations to apply!'
TABLE_HEAD = 'Migrations to be applied:'
BOX_RULE = re.compile(r'^[┌├└─┬┼┴┐┤┘\s]+$')


def parse_listing(listing):
    """Names wrangler lists as pending, in order. Raises PendingError when the output is not exactly understood."""
    lines = [ANSI.sub('', ln).rstrip() for ln in listing.splitlines()]
    if any(re.match(r'\s*(✘|X)\s*\[ERROR\]', ln) for ln in lines):
        raise PendingError('wrangler printed an error')
    none_at = [i for i, ln in enumerate(lines) if ln.strip().lstrip('✅').strip() == NO_PENDING]
    head_at = [i for i, ln in enumerate(lines) if ln.strip() == TABLE_HEAD]
    if len(none_at) + len(head_at) != 1:
        raise PendingError('expected exactly one of "No migrations to apply!" or "Migrations to be applied:"')
    names, table = [], set()
    if head_at:
        i = head_at[0] + 1
        if i >= len(lines) or not lines[i].strip().startswith('┌'):
            raise PendingError('no table after "Migrations to be applied:"')
        header = False
        while i < len(lines):
            ln = lines[i].strip()
            table.add(i)
            if BOX_RULE.match(ln) and ln:
                if ln.startswith('└'):
                    break
            elif ln.startswith('│') and ln.endswith('│'):
                cells = [c.strip() for c in ln[1:-1].split('│')]
                if not header:
                    if cells[0] != 'Name':
                        raise PendingError(f'unexpected table header {ln!r}')
                    header = True
                else:
                    if not re.fullmatch(r'[\w.-]+\.sql', cells[0]):
                        raise PendingError(f'cannot read table row {ln!r}')
                    names.append(cells[0])
            else:
                raise PendingError(f'cannot read table line {ln!r}')
            i += 1
        else:
            raise PendingError('table not closed')
        if not header or not names:
            raise PendingError('table without migration rows')
    stray = [ln for i, ln in enumerate(lines) if i not in table and SQL_NAME.search(ln)]
    if stray:
        raise PendingError(f'migration name outside the table: {stray[0].strip()!r}')
    return names


def pending_files(files, listing):
    """Validated pending list against the local files (sorted). Raises PendingError."""
    names = parse_listing(listing)
    if len(set(names)) != len(names):
        raise PendingError('a migration is listed twice')
    missing = [n for n in names if n not in files]
    if missing:
        raise PendingError(f'listed migration not in the local directory: {missing[0]}')
    if names and names != files[len(files) - len(names):]:
        raise PendingError('pending migrations are not the newest local files in order '
                           f'(pending {", ".join(names)}; local {", ".join(files)})')
    return names


# ---------------------------------------------------------------- CLI

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
            with open(a.pending_from, encoding='utf-8', errors='replace') as fh:
                listing = fh.read()
        except OSError as ex:
            print(f'::error::cannot read {a.pending_from}: {ex}'); return 2
        try:
            pending = pending_files(files, listing)
        except PendingError as ex:
            print(f'::error::could not tell which migrations are pending: {ex}')
            return 2
    print(f'pending migrations: {", ".join(pending) if pending else "none"}')

    hits = []
    for f in pending:
        try:
            with open(os.path.join(a.dir, f), encoding='utf-8') as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as ex:
            print(f'::error::cannot read {a.dir}/{f}: {ex}'); return 2
        for rule, st in findings(text):
            hits.append((f, rule, st))
    if not hits:
        print('no destructive or review-required SQL in pending migrations'); return 0

    override = bool(a.allow) and SHA40.fullmatch(a.sha or '') is not None and a.allow == a.sha
    level = 'warning' if (override or a.warn_only) else 'error'
    for f, rule, st in hits:
        print(f'::{level} file={a.dir}/{f}::{rule}: {st}')
    if override:
        print('migration findings allowed for this release: allow_destructive_migration equals the release sha')
        return 0
    if a.warn_only:
        return 0
    print('::error::migration blocked (destructive, review-required or unreadable SQL). Ship destructive changes in '
          'a later release, after the running Worker no longer uses what they remove (docs/DEPLOY.md). To override '
          'for this one release, type the release sha again in allow_destructive_migration.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
