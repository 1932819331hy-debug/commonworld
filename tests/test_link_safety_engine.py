"""atlas/tools/link_safety.py: per-source merge, the any-single-flag rule, auto-removal with a decision record, hold list."""
import json, os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'atlas' / 'tools'))
import link_safety as ls  # noqa: E402
import trust_check  # noqa: E402

AT = '2026-10-18T04:17:00Z'
SOURCES = [{'id': 'google_safe_browsing', 'name': 'Google Safe Browsing', 'covers': '', 'url': 'https://transparencyreport.google.com/safe-browsing/search', 'terms': ''},
           {'id': 'scamsniffer', 'name': 'ScamSniffer scam-database', 'covers': '', 'url': 'https://github.com/scamsniffer/scam-database', 'terms': ''}]


def src(name, verdict, **kw):
    return {'name': name, 'verdict': verdict, 'checked_at': AT, 'evidence_url': f'https://evidence.example/{name}', **kw}


def engine(results):
    return {'engine': 'Commonworld trust engine', 'engine_version': '0.1.0', 'run_started_at': AT, 'run_at': AT, 'sources': SOURCES,
            'results': {d: {'domain': d, 'status': 'x', 'sources': s} for d, s in results.items()}}


class Merge(unittest.TestCase):
    def test_any_single_flag_is_flagged(self):
        r = ls.merge_host({'sources': [src('google_safe_browsing', 'clean'), src('scamsniffer', 'flagged', detail='listed as bad.example')]}, None)
        self.assertEqual(r['status'], 'flagged')
        self.assertEqual(r['flagged_by'], ['scamsniffer'])

    def test_errored_source_keeps_previous_answer(self):
        prev = {'sources': [src('google_safe_browsing', 'flagged', detail='social_engineering'), src('scamsniffer', 'clean')]}
        r = ls.merge_host({'sources': [src('google_safe_browsing', 'no_data', error='HTTP 429'), src('scamsniffer', 'clean')]}, prev)
        self.assertEqual(r['status'], 'flagged', 'a network error must never hide an earlier flag')
        self.assertTrue(r['sources'][0]['stale'])
        self.assertIn('HTTP 429', r['error'])

    def test_no_answer_at_all_is_no_data(self):
        r = ls.merge_host({'sources': [src('google_safe_browsing', 'no_data', error='x'), src('scamsniffer', 'no_data', error='y')]}, None)
        self.assertEqual(r['status'], 'no_data')


class Apply(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        d = Path(self.td.name)
        self.snap, self.removed, self.tags, self.hold, self.out, self.eng, self.act = (d / n for n in
            ('snapshot-verified-x.json', 'removed.json', 'tags.json', 'hold.json', 'link-safety.json', 'eng.json', 'actions.json'))
        self.snap.write_text(json.dumps({'count': 3, 'platforms': [
            {'slug': 'good', 'canonical_url': 'https://good.example/'},
            {'slug': 'bad', 'canonical_url': 'https://bad.example/', 'claims': [{'source_url': 'https://good.example/doc'}]},
            {'slug': 'held', 'canonical_url': 'https://held.example/'}]}))
        self.removed.write_text(json.dumps({'removed': [], 'decisions': []}))
        self.tags.write_text(json.dumps({'tags': {'good': ['a'], 'bad': ['b'], 'held': ['c']}}))
        self.hold.write_text(json.dumps({'hold': ['held.example']}))
        self.eng.write_text(json.dumps(engine({
            'good.example': [src('google_safe_browsing', 'clean'), src('scamsniffer', 'clean')],
            'bad.example': [src('google_safe_browsing', 'clean'), src('scamsniffer', 'flagged', detail='listed as bad.example')],
            'held.example': [src('google_safe_browsing', 'flagged', detail='malware'), src('scamsniffer', 'clean')]})))

    def tearDown(self):
        self.td.cleanup()

    def run_tool(self, *extra):
        return ls.main(['--data', str(self.snap), '--removed', str(self.removed), '--tags', str(self.tags), '--hold', str(self.hold),
                        '--out', str(self.out), '--report-in', str(self.eng), '--actions-out', str(self.act), *extra])

    def test_report_only_without_apply(self):
        self.assertEqual(self.run_tool(), 1)
        rep = json.loads(self.out.read_text())
        self.assertEqual(rep['flagged'], ['bad.example', 'held.example'])
        self.assertEqual(len(json.loads(self.snap.read_text())['platforms']), 3, 'nothing removed without --apply')
        self.assertEqual(rep['hosts']['bad.example']['sources'][1]['evidence_url'], 'https://evidence.example/scamsniffer')

    def test_apply_removes_flagged_entry_with_decision_and_respects_hold(self):
        self.assertEqual(self.run_tool('--apply'), 1)
        snap = json.loads(self.snap.read_text())
        self.assertEqual([c['slug'] for c in snap['platforms']], ['good', 'held'])
        self.assertEqual(snap['count'], 2)
        rd = json.loads(self.removed.read_text())
        self.assertEqual(rd['removed'], [{'slug': 'bad', 'host': 'bad.example', 'removed_on': '2026-10-18', 'reason': 'scamsniffer'}])
        d = rd['decisions'][0]
        self.assertEqual((d['action'], d['slug'], d['host'], d['by'], d['on']), ('remove', 'bad', 'bad.example', 'hark', '2026-10-18'))
        self.assertEqual(d['reason'], 'ScamSniffer scam-database flagged the domain (listed)')
        self.assertNotIn('bad.example', d['reason'], 'the decision log never prints a removed host as text')
        self.assertEqual(d['evidence'], 'https://evidence.example/scamsniffer')
        self.assertNotIn('bad', json.loads(self.tags.read_text())['tags'])
        rep = json.loads(self.out.read_text())
        self.assertIn('bad.example', rep['removed_hosts'])
        self.assertNotIn('bad.example', rep['hosts'])
        self.assertEqual(rep['hosts']['good.example']['entries'], ['good'])
        self.assertEqual(rep['flagged'], ['held.example'], 'held host stays flagged and published, not removed')
        act = json.loads(self.act.read_text())
        self.assertEqual([a['slug'] for a in act['removed']], ['bad'])
        self.assertEqual(act['held'], ['held.example'])
        # the decision passes the existing trust contract
        roles = json.load(open(ROOT / 'atlas' / 'data' / 'trust-roles.json'))
        self.assertEqual(trust_check.check(roles, rd, rep), [])

    def test_apply_twice_is_idempotent(self):
        self.run_tool('--apply'); self.run_tool('--apply')
        self.assertEqual(len(json.loads(self.removed.read_text())['decisions']), 1)

    def test_clean_run_exits_0_and_changes_nothing(self):
        self.eng.write_text(json.dumps(engine({h: [src('google_safe_browsing', 'clean'), src('scamsniffer', 'clean')]
                                               for h in ('good.example', 'bad.example', 'held.example')})))
        self.assertEqual(self.run_tool('--apply'), 0)
        self.assertEqual(len(json.loads(self.snap.read_text())['platforms']), 3)


if __name__ == '__main__':
    unittest.main()
