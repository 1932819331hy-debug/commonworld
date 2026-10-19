"""scripts/check-migrations.py: the expand -> deploy -> contract gate run before production D1 migrations."""
import contextlib, importlib.util, io, os, tempfile, unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
FIX = os.path.join(ROOT, 'tests', 'fixtures', 'migrations')
_spec = importlib.util.spec_from_file_location('check_migrations', os.path.join(ROOT, 'scripts', 'check-migrations.py'))
cm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cm)
SHA = 'a' * 40
# real output of wrangler 4.151.1 `d1 migrations list --local --env production` (captured, ANSI codes kept)
REAL_PENDING_3 = os.path.join(FIX, 'wrangler-4.151.1-pending-3.txt')   # 0001..0003 pending
REAL_PENDING_2 = os.path.join(FIX, 'wrangler-4.151.1-pending-2.txt')   # 0004, 0005 pending
REAL_NONE = os.path.join(FIX, 'wrangler-4.151.1-none.txt')
GARBAGE = os.path.join(FIX, 'wrangler-garbage.txt')                     # synthetic auth error line
SEQ_FILES = ['0001_init.sql', '0002_expand.sql', '0003_index.sql', '0004_more.sql', '0005_more.sql']


def run(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cm.main(list(args))
    return code, out.getvalue()


def rules(sql):
    return [r for r, _ in cm.findings(sql)]


def read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


class Findings(unittest.TestCase):
    def test_safe_file_has_no_findings(self):
        self.assertEqual(cm.findings(read(os.path.join(FIX, 'safe', '0002_expand.sql'))), [])
        self.assertEqual(cm.findings(read(os.path.join(FIX, 'safe', '0001_init.sql'))), [])

    def test_every_destructive_kind_is_found(self):
        self.assertEqual(rules(read(os.path.join(FIX, 'destructive', '0002_contract.sql'))), [
            'destructive: DROP TABLE', 'destructive: ALTER TABLE ... DROP', 'destructive: ALTER TABLE ... RENAME',
            'destructive: ALTER TABLE ... RENAME', 'destructive: DELETE FROM without WHERE',
            'destructive: UPDATE without WHERE'])

    def test_comments_and_strings_are_ignored(self):
        self.assertEqual(cm.findings("-- DROP TABLE x;\n/* DELETE FROM x; */ SELECT 'UPDATE x SET a=1; DROP TABLE y';"), [])
        self.assertEqual(cm.findings("INSERT INTO x (a) VALUES ('it''s; DELETE FROM x');"), [])

    def test_where_must_belong_to_the_statement(self):
        self.assertEqual(cm.findings('DELETE FROM x WHERE id = 1;'), [])
        self.assertEqual(cm.findings('DELETE FROM x WHERE id = 1 RETURNING id;'), [])
        self.assertEqual(rules('DELETE FROM x;'), ['destructive: DELETE FROM without WHERE'])
        self.assertEqual(rules('UPDATE OR IGNORE x SET a = 1;'), ['destructive: UPDATE without WHERE'])
        self.assertEqual(rules('UPDATE OR REPLACE x SET a = 1;'), ['destructive: UPDATE without WHERE'])
        self.assertEqual(rules('DELETE FROM x LIMIT 5;'), ['destructive: DELETE FROM without WHERE'])
        self.assertEqual(cm.findings('INSERT INTO x (a) VALUES (1) ON CONFLICT (a) DO UPDATE SET a = 2;'), [])

    def test_where_in_subquery_or_returning_is_a_bypass(self):
        for sql in ("UPDATE accounts SET status=(SELECT 'frozen' WHERE 1);",
                    'DELETE FROM accounts RETURNING (SELECT 1 WHERE 1);',
                    'UPDATE users SET is_admin=1, note=(SELECT value FROM config WHERE id=1);',
                    'UPDATE x SET a = 1 RETURNING (SELECT 1 FROM y WHERE y.id = x.id);',
                    'UPDATE x SET a = 1 FROM (SELECT id FROM y WHERE y.k = 2) AS s;'):
            self.assertEqual(len(rules(sql)), 1, sql)
            self.assertTrue(rules(sql)[0].startswith('destructive: '), sql)

    def test_trivially_true_where_counts_as_none(self):
        for cond in ('1', 'TRUE', '1=1', "'a'='a'", 'NOT 0', 'id=id', 'x.id = x.id', '"id" IS "id"', '[id] == [id]',
                     '(SELECT 1)', '(1)', 'id = 5 OR 1', '1 AND 2', 'id = id AND 1', 'EXISTS (SELECT 1)',
                     "'x' LIKE '%'", '2 > 1', 'NULL IS NULL'):
            for verb in ('DELETE FROM t WHERE ', 'UPDATE t SET a = 1 WHERE '):
                self.assertEqual(rules(verb + cond + ';'), [f'destructive: {verb.split()[0]}{" FROM" if verb.startswith("DELETE") else ""} with an always-true WHERE'], cond)

    def test_real_conditions_are_accepted(self):
        for cond in ('id = 5', 'id = 5 AND 1', 'a = b', 'id BETWEEN 1 AND 5', 'id IN (SELECT id FROM y)',
                     'email = lower(email)', "status = 'old'", '0', 'x.id = y.id', 'id = old.id'):
            self.assertEqual(cm.findings(f'DELETE FROM t WHERE {cond};'), [], cond)

    def test_cte(self):
        self.assertEqual(rules('WITH x AS (SELECT id FROM b WHERE 1) DELETE FROM a;'),
                         ['destructive: DELETE FROM without WHERE'])
        self.assertEqual(rules('WITH RECURSIVE x(n) AS (SELECT 1) UPDATE a SET v = 1;'),
                         ['destructive: UPDATE without WHERE'])
        self.assertEqual(cm.findings('WITH x AS (SELECT id FROM b) DELETE FROM a WHERE id IN (SELECT id FROM x);'), [])
        self.assertEqual(cm.findings('WITH x AS (SELECT 1) SELECT * FROM x;'), [])

    def test_review_required(self):
        self.assertEqual(rules('DROP INDEX IF EXISTS users_email;'), ['review-required: DROP INDEX'])
        self.assertEqual(rules('DROP TRIGGER t;'), ['review-required: DROP TRIGGER'])
        self.assertEqual(rules('DROP VIEW v;'), ['review-required: DROP VIEW'])
        self.assertEqual(rules('INSERT OR REPLACE INTO t VALUES (1);'), ['review-required: INSERT OR REPLACE (can overwrite rows)'])
        self.assertEqual(rules('REPLACE INTO t VALUES (1);'), ['review-required: REPLACE INTO (can overwrite rows)'])
        self.assertEqual(cm.findings('INSERT OR IGNORE INTO t VALUES (1);'), [])

    def test_unknown_or_unreadable_fails_closed(self):
        for sql in ('VACUUM;', 'ATTACH DATABASE x AS y;', 'PRAGMA writable_schema = 1;', "SELECT 'open;",
                    'SELECT (1;', '/* open', 'CREATE TRIGGER t AFTER INSERT ON a BEGIN SELECT 1;',
                    'ALTER TABLE t SOMETHING;', 'DROP SCHEMA x;'):
            r = rules(sql)
            self.assertTrue(r and r[0].startswith('unknown: '), (sql, r))

    def test_known_safe_statements(self):
        self.assertEqual(cm.findings('PRAGMA foreign_keys = ON; PRAGMA defer_foreign_keys = true; BEGIN; COMMIT;'
                                     'CREATE UNIQUE INDEX IF NOT EXISTS i ON t (a); CREATE VIEW v AS SELECT 1;'
                                     'CREATE VIRTUAL TABLE f USING fts5(a); ANALYZE;'), [])

    def test_trigger_body_is_checked(self):
        self.assertEqual(rules('CREATE TRIGGER t AFTER INSERT ON a BEGIN DELETE FROM b; END;'),
                         ['destructive: DELETE FROM without WHERE (in trigger body)'])
        self.assertEqual(cm.findings('CREATE TEMP TRIGGER t AFTER INSERT ON a BEGIN '
                                     'UPDATE c SET n = CASE WHEN new.k THEN 1 ELSE 2 END WHERE id = new.id; END;'
                                     'DELETE FROM a WHERE id = 1;'), [])

    def test_add_column_is_not_destructive(self):
        self.assertEqual(cm.findings('ALTER TABLE x ADD COLUMN y TEXT;'), [])
        self.assertEqual(cm.findings("ALTER TABLE x ADD COLUMN y TEXT NOT NULL DEFAULT '';"
                                     'ALTER TABLE x ADD y INTEGER NOT NULL DEFAULT 0 CHECK (y IS NOT NULL);'
                                     'ALTER TABLE x ADD COLUMN y INT NOT NULL DEFAULT -1;'
                                     'ALTER TABLE x ADD COLUMN y INT NOT NULL DEFAULT (2);'
                                     'ALTER TABLE x ADD COLUMN y TEXT CHECK (y NOT NULL);'
                                     'ALTER TABLE x ADD COLUMN g INT GENERATED ALWAYS AS (a + 1) VIRTUAL NOT NULL;'
                                     'ALTER TABLE main.x ADD COLUMN y TEXT DEFAULT NULL;'), [])

    def test_add_column_that_sqlite_refuses_is_flagged(self):
        nn = 'review-required: ADD COLUMN ... NOT NULL without a non-NULL DEFAULT (SQLite rejects it on a table that has rows)'
        for sql in ('ALTER TABLE x ADD COLUMN y TEXT NOT NULL;', 'ALTER TABLE x ADD y TEXT NOT NULL DEFAULT NULL;',
                    'alter table main.x add column y text constraint c not null;',
                    'ALTER TABLE x ADD COLUMN y TEXT NOT NULL DEFAULT (NULL);'):
            self.assertEqual(rules(sql), [nn], sql)
        self.assertTrue(rules('ALTER TABLE x ADD COLUMN y INTEGER PRIMARY KEY;')[0].startswith('review-required: ADD COLUMN ... PRIMARY KEY'))
        self.assertTrue(rules('ALTER TABLE x ADD COLUMN y TEXT UNIQUE;')[0].startswith('review-required: ADD COLUMN ... UNIQUE'))
        self.assertTrue(rules('ALTER TABLE x ADD COLUMN g INT AS (a + 1) STORED;')[0].startswith('review-required: ADD COLUMN ... STORED'))
        self.assertTrue(rules('ALTER TABLE x ADD COLUMN t TEXT DEFAULT CURRENT_TIMESTAMP;')[0].startswith(
            'review-required: ADD COLUMN ... DEFAULT CURRENT_TIMESTAMP'))

    def test_add_column_rules_match_sqlite(self):
        """Every flagged definition really fails in SQLite on a table with a row; every passing one really works."""
        import sqlite3
        for col, flagged in (('y TEXT NOT NULL', True), ('y TEXT NOT NULL DEFAULT NULL', True),
                             ('y INTEGER PRIMARY KEY', True), ('y TEXT UNIQUE', True),
                             ('g INT AS (a + 1) STORED', True), ('t TEXT DEFAULT CURRENT_TIMESTAMP', True),
                             ("y TEXT NOT NULL DEFAULT ''", False), ('y INT NOT NULL DEFAULT -1', False),
                             ('y TEXT', False)):
            sql = f'ALTER TABLE x ADD COLUMN {col};'
            self.assertEqual(bool(rules(sql)), flagged, sql)
            db = sqlite3.connect(':memory:')
            db.execute('CREATE TABLE x (a INT)'); db.execute('INSERT INTO x VALUES (1)')
            try:
                db.execute(sql); ok = True
            except sqlite3.OperationalError:
                ok = False
            self.assertEqual(ok, not flagged, sql)


class Pending(unittest.TestCase):
    def test_real_listing_all_pending(self):
        self.assertEqual(cm.pending_files(SEQ_FILES[:3], read(REAL_PENDING_3)), SEQ_FILES[:3])

    def test_real_listing_suffix(self):
        self.assertEqual(cm.pending_files(SEQ_FILES, read(REAL_PENDING_2)), ['0004_more.sql', '0005_more.sql'])

    def test_real_no_migrations_to_apply(self):
        self.assertEqual(cm.pending_files(SEQ_FILES, read(REAL_NONE)), [])

    def test_listed_name_missing_locally_fails(self):
        with self.assertRaisesRegex(cm.PendingError, 'not in the local directory'):
            cm.pending_files(SEQ_FILES[:4], read(REAL_PENDING_2))

    def test_not_a_suffix_fails(self):
        # 0004/0005 pending but a newer local 0006 is not: order broken
        with self.assertRaisesRegex(cm.PendingError, 'not the newest'):
            cm.pending_files(SEQ_FILES + ['0006_new.sql'], read(REAL_PENDING_2))
        # gap: 0002 applied-looking hole
        with self.assertRaisesRegex(cm.PendingError, 'not the newest'):
            cm.pending_files(SEQ_FILES[:3], read(REAL_PENDING_3).replace('0002_expand.sql', '0003_index.sql', 1)
                             .replace('│ 0003_index.sql  │', '│ 0002_expand.sql │'))

    def test_duplicate_fails(self):
        txt = read(REAL_PENDING_2).replace('0004_more.sql', '0005_more.sql')
        with self.assertRaisesRegex(cm.PendingError, 'twice'):
            cm.pending_files(SEQ_FILES, txt)

    def test_unknown_output_fails(self):
        for txt in (read(GARBAGE), '', 'something else entirely\n'):
            with self.assertRaises(cm.PendingError):
                cm.pending_files(SEQ_FILES, txt)

    def test_both_markers_fail(self):
        with self.assertRaises(cm.PendingError):
            cm.pending_files(SEQ_FILES, read(REAL_PENDING_2) + '\n✅ No migrations to apply!\n')

    def test_migration_name_outside_the_table_fails(self):
        with self.assertRaisesRegex(cm.PendingError, 'outside the table'):
            cm.pending_files(SEQ_FILES, read(REAL_NONE) + '\nalso 0005_more.sql\n')
        with self.assertRaisesRegex(cm.PendingError, 'outside the table'):
            cm.pending_files(SEQ_FILES, read(REAL_PENDING_2) + '0003_index.sql\n')

    def test_unreadable_table_row_fails(self):
        txt = read(REAL_PENDING_2).replace('│ 0004_more.sql │', '│ 0004 more.sql │')
        with self.assertRaises(cm.PendingError):
            cm.pending_files(SEQ_FILES, txt)
        txt = read(REAL_PENDING_2).replace('│ 0004_more.sql │', '  0004_more.sql  ')
        with self.assertRaises(cm.PendingError):
            cm.pending_files(SEQ_FILES, txt)

    def test_unclosed_or_empty_table_fails(self):
        txt = read(REAL_PENDING_2)
        with self.assertRaises(cm.PendingError):
            cm.pending_files(SEQ_FILES, txt[:txt.index('└')])
        head = txt[:txt.index('├')] + '└───────────────┘\n'
        with self.assertRaises(cm.PendingError):
            cm.pending_files(SEQ_FILES, head)

    def test_error_line_fails_even_with_a_table(self):
        with self.assertRaisesRegex(cm.PendingError, 'error'):
            cm.pending_files(SEQ_FILES, '✘ [ERROR] boom\n' + read(REAL_PENDING_2))

    def test_name_must_match_whole(self):
        txt = read(REAL_PENDING_2).replace('0004_more.sql', '10004_more.sql').replace('├───────────────┤', '├────────────────┤')
        with self.assertRaises(cm.PendingError):
            cm.pending_files(SEQ_FILES, txt)


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        for f in SEQ_FILES[:4]:
            self.write(f, 'CREATE TABLE IF NOT EXISTS t (id INTEGER);\n')
        self.write('0005_more.sql', 'DROP TABLE t;\n')

    def write(self, name, text):
        with open(os.path.join(self.d, name), 'w', encoding='utf-8') as fh:
            fh.write(text)

    def tearDown(self):
        self.tmp.cleanup()

    def test_pending_destructive_fails(self):
        code, out = run('--dir', self.d, '--pending-from', REAL_PENDING_2, '--sha', SHA)
        self.assertEqual(code, 1)
        self.assertIn('::error file=', out)
        self.assertIn('0005_more.sql::destructive: DROP TABLE', out)

    def test_review_required_also_needs_the_override(self):
        self.write('0005_more.sql', 'DROP INDEX i;\n')
        self.assertEqual(run('--dir', self.d, '--pending-from', REAL_PENDING_2, '--sha', SHA)[0], 1)
        self.assertEqual(run('--dir', self.d, '--pending-from', REAL_PENDING_2, '--sha', SHA, '--allow', SHA)[0], 0)

    def test_override_with_the_same_sha_passes(self):
        code, out = run('--dir', self.d, '--pending-from', REAL_PENDING_2, '--sha', SHA, '--allow', SHA)
        self.assertEqual(code, 0)
        self.assertIn('::warning file=', out)

    def test_override_with_another_value_still_fails(self):
        for allow in ('yes', 'b' * 40, SHA.upper(), SHA[:12]):
            code, _ = run('--dir', self.d, '--pending-from', REAL_PENDING_2, '--sha', SHA, '--allow', allow)
            self.assertEqual(code, 1, allow)

    def test_nothing_pending_passes(self):
        code, out = run('--dir', self.d, '--pending-from', REAL_NONE, '--sha', SHA)
        self.assertEqual(code, 0)
        self.assertIn('pending migrations: none', out)

    def test_unreadable_listing_fails_closed(self):
        self.assertEqual(run('--dir', self.d, '--pending-from', GARBAGE, '--sha', SHA)[0], 2)
        self.assertEqual(run('--dir', self.d, '--pending-from', os.path.join(FIX, 'does-not-exist.txt'))[0], 2)
        # listing names a file that is not here
        os.remove(os.path.join(self.d, '0005_more.sql'))
        self.assertEqual(run('--dir', self.d, '--pending-from', REAL_PENDING_2, '--sha', SHA)[0], 2)

    def test_missing_dir_fails(self):
        self.assertEqual(run('--dir', os.path.join(FIX, 'nope'), '--all')[0], 2)

    def test_all_safe_passes_and_warn_only_never_fails(self):
        self.assertEqual(run('--dir', os.path.join(FIX, 'safe'), '--all')[0], 0)
        self.assertEqual(run('--dir', os.path.join(FIX, 'sequence'), '--all')[0], 0)
        d = os.path.join(FIX, 'destructive')
        self.assertEqual(run('--dir', d, '--all')[0], 1)
        self.assertEqual(run('--dir', d, '--all', '--warn-only')[0], 0)


if __name__ == '__main__':
    unittest.main()
