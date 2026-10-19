"""scripts/check-migrations.py: the expand -> deploy -> contract gate run before production D1 migrations."""
import contextlib, importlib.util, io, os, unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
FIX = os.path.join(ROOT, 'tests', 'fixtures', 'migrations')
_spec = importlib.util.spec_from_file_location('check_migrations', os.path.join(ROOT, 'scripts', 'check-migrations.py'))
cm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cm)
SHA = 'a' * 40


def run(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cm.main(list(args))
    return code, out.getvalue()


class Findings(unittest.TestCase):
    def test_safe_file_has_no_findings(self):
        text = open(os.path.join(FIX, 'safe', '0002_expand.sql'), encoding='utf-8').read()
        self.assertEqual(cm.findings(text), [])

    def test_every_destructive_kind_is_found(self):
        text = open(os.path.join(FIX, 'destructive', '0002_contract.sql'), encoding='utf-8').read()
        rules = [r for r, _ in cm.findings(text)]
        self.assertEqual(rules, ['DROP TABLE', 'ALTER TABLE ... DROP', 'ALTER TABLE ... RENAME', 'ALTER TABLE ... RENAME',
                                 'DELETE FROM without WHERE', 'UPDATE without WHERE'])

    def test_comments_and_strings_are_ignored(self):
        self.assertEqual(cm.findings("-- DROP TABLE x;\n/* DELETE FROM x; */ SELECT 'UPDATE x SET a=1';"), [])

    def test_where_must_follow_the_statement(self):
        self.assertEqual(cm.findings('DELETE FROM x WHERE id = 1;'), [])
        self.assertEqual(len(cm.findings('DELETE FROM x;')), 1)
        self.assertEqual(len(cm.findings('UPDATE OR IGNORE x SET a = 1;')), 1)
        self.assertEqual(cm.findings('INSERT INTO x (a) VALUES (1) ON CONFLICT (a) DO UPDATE SET a = 2;'), [])

    def test_add_column_is_not_destructive(self):
        self.assertEqual(cm.findings('ALTER TABLE x ADD COLUMN y TEXT;'), [])


class Pending(unittest.TestCase):
    files = ['0001_init.sql', '0002_contract.sql']

    def test_listing_names_pending_files(self):
        listing = open(os.path.join(FIX, 'wrangler-pending-0002.txt'), encoding='utf-8').read()
        self.assertEqual(cm.pending_files(self.files, listing), ['0002_contract.sql'])

    def test_no_migrations_to_apply(self):
        listing = open(os.path.join(FIX, 'wrangler-none.txt'), encoding='utf-8').read()
        self.assertEqual(cm.pending_files(self.files, listing), [])

    def test_unknown_output_is_none(self):
        listing = open(os.path.join(FIX, 'wrangler-garbage.txt'), encoding='utf-8').read()
        self.assertIsNone(cm.pending_files(self.files, listing))

    def test_name_must_match_whole(self):
        self.assertEqual(cm.pending_files(['0001_init.sql'], '10001_init.sql'), None)


class Cli(unittest.TestCase):
    d = os.path.join(FIX, 'destructive')

    def test_pending_destructive_fails(self):
        code, out = run('--dir', self.d, '--pending-from', os.path.join(FIX, 'wrangler-pending-0002.txt'), '--sha', SHA)
        self.assertEqual(code, 1)
        self.assertIn('::error file=', out)

    def test_override_with_the_same_sha_passes(self):
        code, out = run('--dir', self.d, '--pending-from', os.path.join(FIX, 'wrangler-pending-0002.txt'),
                        '--sha', SHA, '--allow', SHA)
        self.assertEqual(code, 0)
        self.assertIn('::warning file=', out)

    def test_override_with_another_value_still_fails(self):
        for allow in ('yes', 'b' * 40, SHA.upper(), SHA[:12]):
            code, _ = run('--dir', self.d, '--pending-from', os.path.join(FIX, 'wrangler-pending-0002.txt'),
                          '--sha', SHA, '--allow', allow)
            self.assertEqual(code, 1, allow)

    def test_nothing_pending_passes(self):
        code, out = run('--dir', self.d, '--pending-from', os.path.join(FIX, 'wrangler-none.txt'), '--sha', SHA)
        self.assertEqual(code, 0)
        self.assertIn('pending migrations: none', out)

    def test_unreadable_listing_fails_closed(self):
        code, _ = run('--dir', self.d, '--pending-from', os.path.join(FIX, 'wrangler-garbage.txt'), '--sha', SHA)
        self.assertEqual(code, 2)
        code, _ = run('--dir', self.d, '--pending-from', os.path.join(FIX, 'does-not-exist.txt'))
        self.assertEqual(code, 2)

    def test_missing_dir_fails(self):
        code, _ = run('--dir', os.path.join(FIX, 'nope'), '--all')
        self.assertEqual(code, 2)

    def test_all_safe_passes_and_warn_only_never_fails(self):
        self.assertEqual(run('--dir', os.path.join(FIX, 'safe'), '--all')[0], 0)
        self.assertEqual(run('--dir', self.d, '--all')[0], 1)
        self.assertEqual(run('--dir', self.d, '--all', '--warn-only')[0], 0)


if __name__ == '__main__':
    unittest.main()
