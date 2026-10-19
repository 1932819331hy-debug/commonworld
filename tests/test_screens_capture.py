"""atlas/tools/screens.py (weekly screenshot capture): the decisions that keep stored images safe, without a browser.
A failed capture never replaces a stored image, held cards are never stored without --force, a replacement needs a visible
change (dHash) on an image at least 28 days old, muse.ai is never opened, and only live cards are captured."""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# loaded by path: atlas/site/screens.py (the build-side reader) has the same module name
_spec = importlib.util.spec_from_file_location('atlas_tools_screens', ROOT / 'atlas' / 'tools' / 'screens.py')
screens = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(screens)

try:
    import PIL  # noqa: F401  (unit tests run before requirements.txt is installed in ci.yml)
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

NOW = screens.parse_iso('2026-10-19T12:00:00Z')
OLD = {'file': 'x.webp', 'dhash': '0000000000000000', 'captured_at': '2026-09-01T00:00:00Z'}
NEW_DIFF = {'ok': True, 'dhash': '00000000000000ff'}   # 8 bits differ
NEW_SAME = {'ok': True, 'dhash': '0000000000000003'}   # 2 bits differ


class Decide(unittest.TestCase):
    def test_failed_capture_keeps_stored_image(self):
        self.assertTrue(screens.decide('x', {'ok': False}, OLD, NOW, set()).startswith('keep'))
        self.assertTrue(screens.decide('x', {'ok': False}, None, NOW, set()).startswith('keep'))

    def test_new_card_is_added(self):
        self.assertEqual(screens.decide('x', dict(NEW_SAME), None, NOW, set()), 'add')

    def test_gate(self):
        self.assertEqual(screens.decide('x', dict(NEW_DIFF), OLD, NOW, set()), 'replace')
        self.assertTrue(screens.decide('x', dict(NEW_SAME), OLD, NOW, set()).startswith('keep:no visible change'))
        young = dict(OLD, captured_at='2026-10-10T00:00:00Z')
        self.assertTrue(screens.decide('x', dict(NEW_DIFF), young, NOW, set()).startswith('keep:stored image only'))
        self.assertEqual(screens.decide('x', dict(NEW_SAME), young, NOW, {'x'}), 'replace')

    def test_hold(self):
        self.assertTrue(screens.decide('x', dict(NEW_DIFF), None, NOW, set(), 'site data not loading').startswith('keep:held'))
        self.assertEqual(screens.decide('x', dict(NEW_DIFF), None, NOW, {'x'}, 'site data not loading'), 'add')


class Rules(unittest.TestCase):
    def test_muse_never_opened(self):
        for u in ('https://muse.ai/', 'https://auth.muse.ai/x', 'https://www.muse.ai'):
            self.assertTrue(screens.blocked(u))
        self.assertFalse(screens.blocked('https://amuse.ai/'))

    def test_honest_user_agent(self):
        self.assertIn('CommonworldAtlasBot/1.0', screens.UA)

    @unittest.skipUnless(HAVE_PIL, 'Pillow not installed')
    def test_classify(self):
        from PIL import Image
        img = Image.new('RGB', (1200, 750), 'white')
        busy = Image.effect_noise((1200, 750), 60).convert('RGB')
        ok = {'share': 0.0, 'loading_only': False}
        self.assertEqual(screens.classify(200, 'Just a moment...', '', busy, ok), 'challenge')
        self.assertEqual(screens.classify(404, 'Home', 'x' * 500, busy, ok), 'http_404')
        self.assertEqual(screens.classify(200, '', '', img, ok), 'blank_page')
        self.assertEqual(screens.classify(200, 'Home', 'Loading...', busy, {'share': 0.0, 'loading_only': True}), 'loading_placeholder')
        self.assertEqual(screens.classify(200, 'Home', 'x' * 500, busy, {'share': 0.3, 'loading_only': False}), 'loading_placeholder')
        self.assertIsNone(screens.classify(200, 'Home', 'x' * 500, busy, ok))

    def test_live_cards_only(self):
        cards = screens.live_cards()
        snap = sorted((ROOT / 'atlas' / 'data').glob('snapshot-verified-*.json'))[-1]
        closed = {p['slug'] for p in json.load(open(snap))['platforms'] if p['status'] != 'live'}
        self.assertTrue(cards)
        self.assertFalse(closed & set(cards))

    def test_overrides_file(self):
        o = json.load(open(ROOT / 'atlas' / 'tools' / 'screens-overrides.json'))['overrides']
        cards = screens.live_cards()
        for slug, v in o.items():
            self.assertIn(slug, cards, f'override for unknown/closed card {slug}')
            self.assertLessEqual(set(v), {'shot_url', 'wait', 'keys', 'click_text', 'gl', 'hold', 'why'})
            if 'shot_url' in v:
                self.assertTrue(v['shot_url'].startswith('https://'))

    @unittest.skipUnless(HAVE_PIL, 'Pillow not installed')
    def test_dhash_and_summary(self):
        from PIL import Image
        a = Image.effect_noise((1200, 750), 60).convert('RGB')
        self.assertEqual(screens.hamming(screens.dhash(a), screens.dhash(a)), 0)
        md = screens.summary_md({'a': {'action': 'add', 'ok': True, 'final_url': 'https://a.example/'},
                                 'b': {'action': 'keep:capture failed', 'ok': False, 'reason': 'challenge', 'website': 'https://b.example/'}}, ['zz'])
        self.assertIn('1 added', md)
        self.assertIn('`b` | challenge', md)
        self.assertIn('`zz`', md)


if __name__ == '__main__':
    unittest.main()
