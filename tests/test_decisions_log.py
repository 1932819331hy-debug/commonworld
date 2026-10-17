"""Link safety decision log (/atlas/decisions/, index.md, /atlas/decisions.json): every decision in atlas/data/removed.json
is published, newest first, hosts as defanged plain text, and the removed-host scan allows only the exact evidence URL of a
recorded decision to a third-party checker, only in the decision log files. check.py also verifies the built page in CI."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'atlas' / 'site'))
import build  # noqa: E402
import check  # noqa: E402

ORIGIN = 'https://commonworld.one'
DATA = json.load(open(ROOT / 'atlas' / 'data' / 'removed.json'))
ROLES = json.load(open(ROOT / 'atlas' / 'data' / 'trust-roles.json'))


class FakeSite:
    base = '/atlas'
    cfg = {'data_licence': 'CC BY 4.0'}

    @staticmethod
    def abs(p):
        return ORIGIN + p


class DecisionLog(unittest.TestCase):
    def test_every_decision_is_in_markdown_and_json(self):
        decs = DATA.get('decisions') or []
        self.assertTrue(decs, 'removed.json has decisions')
        md = build.build_decisions_md(FakeSite)
        doc = build.decisions_doc(FakeSite)
        self.assertEqual(doc['count'], len(decs))
        self.assertEqual(len(doc['decisions']), len(decs))
        for d in decs:
            for need in (d['slug'], d['on'], d['by'], d['evidence'], build.defang(d['host'])):
                self.assertIn(need, md)
            self.assertIn({'on': d['on'], 'action': d['action'], 'slug': d['slug'], 'by': d['by'], 'evidence': d['evidence']},
                          [{k: r[k] for k in ('on', 'action', 'slug', 'by', 'evidence')} for r in doc['decisions']])
        self.assertEqual([a['id'] for a in doc['trust_roles']['actors']], [a['id'] for a in ROLES['actors']])
        self.assertTrue(md.startswith('# '))
        self.assertIn(ORIGIN + '/atlas/decisions/', md)

    def test_newest_first(self):
        decs = [{'on': '2026-10-17', 'slug': 'a'}, {'on': '2026-10-20', 'slug': 'b'}, {'on': '2026-10-20', 'slug': 'c'}]
        self.assertEqual([d['slug'] for d in build.decisions_newest_first(decs)], ['c', 'b', 'a'])

    def test_host_is_defanged(self):
        self.assertEqual(build.defang('venice.ai'), 'venice[.]ai')
        doc = build.decisions_doc(FakeSite)
        for r in doc['decisions']:
            self.assertNotIn('.', r['host'].replace('[.]', ''))

    def test_generated_at_is_utc(self):
        self.assertRegex(build.decisions_doc(FakeSite)['generated_at'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')


class RemovedHostScan(unittest.TestCase):
    REM = [{'slug': 'x', 'host': 'bad.example'}]
    EV = 'https://transparencyreport.google.com/safe-browsing/search?url=bad.example'
    DECS = [{'action': 'remove', 'slug': 'x', 'host': 'bad.example', 'evidence': EV}]

    def hit(self, txt, rel='atlas/decisions/index.html', decs=None):
        return check.removed_host_hit(txt, rel, self.REM, self.DECS if decs is None else decs)

    def test_evidence_link_allowed_in_decision_log(self):
        for rel in check.DECISION_FILES:
            self.assertIsNone(self.hit(f'<a href="{self.EV}">x</a> bad[.]example', rel))

    def test_bare_host_still_fails_in_decision_log(self):
        self.assertEqual(self.hit(f'<a href="{self.EV}">x</a> bad.example'), 'bad.example')
        self.assertEqual(self.hit('<a href="https://bad.example/">x</a>'), 'bad.example')

    def test_evidence_link_fails_elsewhere(self):
        self.assertEqual(self.hit(f'<a href="{self.EV}">x</a>', 'atlas/about/index.html'), 'bad.example')

    def test_other_checker_or_unrecorded_url_fails(self):
        other = 'https://checker.example/?url=bad.example'
        self.assertEqual(self.hit(other, decs=[{'evidence': other}]), 'bad.example')
        self.assertEqual(self.hit(self.EV + '&x=1', decs=[]), 'bad.example')


if __name__ == '__main__':
    unittest.main()
