"""atlas/site/screens.py: which atlas-screens commit a build uses (atlas/screens.lock, CW_SCREENS_SHA)."""
import os, re, sys, tempfile, unittest
from unittest import mock

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.join(ROOT, 'atlas', 'site'))
import screens  # noqa: E402

SHA = '0123456789abcdef0123456789abcdef01234567'


class Lock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lock = os.path.join(self.tmp.name, 'screens.lock')
        self.p = mock.patch.object(screens, 'LOCK', self.lock)
        self.p.start()
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop('CW_SCREENS_SHA', None)

    def tearDown(self):
        self.env.stop(); self.p.stop(); self.tmp.cleanup()

    def write(self, text):
        with open(self.lock, 'w', encoding='utf-8') as f:
            f.write(text)

    def test_committed_lock_is_a_full_sha(self):
        with open(os.path.join(ROOT, 'atlas', 'screens.lock'), encoding='utf-8') as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r'^[0-9a-f]{40}$')

    def test_lock_is_read(self):
        self.write(SHA + '\n')
        self.assertEqual(screens.pinned_sha(), SHA)

    def test_no_lock_follows_branch_head(self):
        self.assertIsNone(screens.pinned_sha())

    def test_env_overrides_lock(self):
        self.write(SHA + '\n')
        os.environ['CW_SCREENS_SHA'] = 'f' * 40
        self.assertEqual(screens.pinned_sha(), 'f' * 40)
        os.environ['CW_SCREENS_SHA'] = 'head'
        self.assertIsNone(screens.pinned_sha())

    def test_bad_values_stop_the_build(self):
        for bad in (SHA[:12], SHA.upper(), SHA + '\n' + SHA, '', 'main'):
            self.write(bad)
            with self.assertRaises(SystemExit, msg=bad):
                screens.pinned_sha()
        os.environ['CW_SCREENS_SHA'] = 'nope'
        with self.assertRaises(SystemExit):
            screens.pinned_sha()

    def test_pinned_tarball_url_uses_the_sha(self):
        seen = {}

        def fake(req, timeout):
            seen['url'] = req.full_url
            raise OSError('offline')
        with mock.patch.object(screens.urllib.request, 'urlopen', fake):
            self.assertIsNone(screens._from_tarball(self.tmp.name, SHA))
        self.assertTrue(re.fullmatch(r'https://codeload\.github\.com/commonworld-one/commonworld/tar\.gz/' + SHA, seen['url']))


if __name__ == '__main__':
    unittest.main()
