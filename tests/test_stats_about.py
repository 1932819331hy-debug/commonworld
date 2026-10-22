"""stats.json `_about` says how the values are really updated (2026-10-22): by hand, no automatic weekly job yet."""
import json, os, unittest

STATS = os.path.join(os.path.dirname(__file__), '..', 'atlas', 'data', 'stats.json')


class StatsAboutTest(unittest.TestCase):
    def test_about_is_honest_about_manual_updates(self):
        about = json.load(open(STATS, encoding='utf-8'))['_about']
        self.assertIn('updated by hand', about)
        self.assertIn('no automatic weekly job yet', about)
        self.assertNotIn('A weekly job edits', about)


if __name__ == '__main__':
    unittest.main()
