"""The text beside a refreshed number stays in step with it (atlas/refresh.py statement templates + note_drift)."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'atlas'))
import refresh

IDENT = {'id': 'agent-bounties-lifetime-identities', 'kind': 'metric', 'url': 'https://api.agentbounties.app/v1/metrics/platform',
         'path': 'platform_active_identities.lifetime', 'unit': 'identities', 'basis': 'operator_claim',
         'statement': 'Active identities: {platform_active_identities.latest_week} in last 7d, {value} lifetime',
         'quote_fields': ['platform_active_identities.lifetime', 'platform_active_identities.latest_week'],
         'match': {'source_url': 'https://api.agentbounties.app/v1/metrics/platform', 'unit': 'identities'}}


def doc(lifetime, week):
    return {'platform_active_identities': {'lifetime': lifetime, 'latest_week': week}}


def read(m, d):
    fields = {}
    with mock.patch.object(refresh, 'get_json', return_value=(d, None)):
        val, quote, methods, err = refresh.read_mapping(m, fields)
    assert err is None, err
    return val, quote, methods, fields


def claim(statement, value, quote):
    return {'kind': 'metric', 'statement': statement, 'value': value, 'unit': 'identities', 'basis': 'operator_claim',
            'source_url': IDENT['url'], 'quote': quote, 'observed_at': '2026-10-15T18:12Z', 'outcome': 'supported',
            'refresh_id': IDENT['id']}


class StatementTemplates(unittest.TestCase):
    def test_statement_is_rendered_from_the_same_fetch(self):
        val, quote, _m, fields = read(IDENT, doc(66, 3))
        self.assertEqual(val, 66)
        self.assertEqual(quote, '"lifetime":66,"latest_week":3')
        self.assertEqual(refresh.render_statement(IDENT['statement'], val, fields), ('Active identities: 3 in last 7d, 66 lifetime', []))

    def test_quote_round_trip_with_colliding_last_segments(self):
        m = {'id': 'x', 'url': 'https://example.org/m', 'path': 'v.lifetime.usdc',
             'quote_fields': ['v.lifetime.usdc', 'v.lifetime_settled_rounds', 'v.selected.usdc'],
             'statement': '{value} USDC across {v.lifetime_settled_rounds} rounds; {v.selected.usdc} USDC in the last 7d'}
        d = {'v': {'lifetime': {'usdc': '73.065000'}, 'selected': {'usdc': '0.000000'}, 'lifetime_settled_rounds': 57}}
        val, quote, _m, fields = read(m, d)
        self.assertIn('"v.lifetime.usdc":"73.065000"', quote)
        self.assertIn('"v.selected.usdc":"0.000000"', quote)
        self.assertEqual(refresh.fields_from_quote(quote, m['quote_fields']),
                         {'v.lifetime.usdc': 73.065, 'v.lifetime_settled_rounds': 57, 'v.selected.usdc': 0.0})
        self.assertEqual(refresh.render_statement(m['statement'], val, fields)[0], '73.065 USDC across 57 rounds; 0 USDC in the last 7d')

    def test_changed_value_regenerates_the_whole_statement(self):
        e = {'slug': 'agent-bounties', 'claims': [claim('Active identities: 4 in last 7d, 65 lifetime', 65, '"latest_week":4 … "lifetime":65')]}
        val, quote, methods, fields = read(IDENT, doc(66, 3))
        what, old = refresh.apply_number(e, IDENT, val, quote, methods, '2026-10-18T06:49:00Z', fields)
        c = e['claims'][0]
        self.assertEqual((what, old), ('changed', 65))
        self.assertEqual(c['statement'], 'Active identities: 3 in last 7d, 66 lifetime')
        self.assertEqual(c['history'][-1]['statement'], 'Active identities: 4 in last 7d, 65 lifetime')
        self.assertIsNone(refresh.note_drift(c, IDENT))

    def test_same_value_but_changed_side_number_is_a_note_re_observation(self):
        e = {'slug': 'agent-bounties', 'claims': [claim('Active identities: 4 in last 7d, 66 lifetime', 66, '"lifetime":66,"latest_week":4')]}
        val, quote, methods, fields = read(IDENT, doc(66, 3))
        what, old = refresh.apply_number(e, IDENT, val, quote, methods, '2026-10-19T08:00:00Z', fields)
        c = e['claims'][0]
        self.assertEqual((what, old), ('note', 66))
        self.assertEqual(c['statement'], 'Active identities: 3 in last 7d, 66 lifetime')
        self.assertEqual(c['quote'], '"lifetime":66,"latest_week":3')
        self.assertEqual(c['history'][-1]['statement'], 'Active identities: 4 in last 7d, 66 lifetime')
        self.assertIn('statement regenerated', c['history'][-1]['reason'])

    def test_unchanged_value_and_text_is_same(self):
        e = {'slug': 'agent-bounties', 'claims': [claim('Active identities: 3 in last 7d, 66 lifetime', 66, '"lifetime":66,"latest_week":3')]}
        val, quote, methods, fields = read(IDENT, doc(66, 3))
        self.assertEqual(refresh.apply_number(e, IDENT, val, quote, methods, '2026-10-19T08:00:00Z', fields), ('same', 66))
        self.assertNotIn('history', e['claims'][0])

    def test_missing_template_field_never_publishes_half_filled_text(self):
        e = {'slug': 'agent-bounties', 'claims': [claim('Active identities: 4 in last 7d, 65 lifetime', 65, '"lifetime":65,"latest_week":4')]}
        val, quote, methods, fields = read(IDENT, {'platform_active_identities': {'lifetime': 66}})
        refresh.apply_number(e, IDENT, val, quote, methods, '2026-10-19T08:00:00Z', fields)
        self.assertNotIn('{', e['claims'][0]['statement'])
        self.assertIsNotNone(refresh.note_drift(e['claims'][0], IDENT))


class NoteDrift(unittest.TestCase):
    STALE = claim('Active identities: 4 in last 7d, 65 lifetime', 66, '"lifetime":66,"latest_week":3')  # the 2026-10-18 card

    def test_stale_note_fails_with_template(self):
        self.assertIn('!=', refresh.note_drift(self.STALE, IDENT))

    def test_stale_note_fails_without_template(self):
        m = {k: v for k, v in IDENT.items() if k != 'statement'}
        self.assertIn('stale', refresh.note_drift(self.STALE, m))

    def test_window_tokens_are_not_numbers(self):
        ok = claim('Active identities: 3 in last 7d, 66 lifetime', 66, '"lifetime":66,"latest_week":3')
        self.assertIsNone(refresh.note_drift(ok, {k: v for k, v in IDENT.items() if k != 'statement'}))

    def test_text_without_numbers_passes_and_text_missing_the_value_fails(self):
        self.assertIsNone(refresh.note_drift(claim('Platform totals (operator API)', 66, '"lifetime":66'), {'id': 'x'}))
        self.assertIn('does not mention', refresh.note_drift(claim('3 active this week', 66, '"lifetime":66,"latest_week":3'), {'id': 'x'}))

    def test_mapping_lint(self):
        bad = dict(IDENT, quote_fields=['platform_active_identities.lifetime'])
        self.assertTrue(any('not in quote_fields' in p for p in refresh.mapping_problems(bad)))
        self.assertTrue(refresh.mapping_problems(dict(IDENT, verify={'url': 'https://evil.example/x', 'note': 'n'})))
        self.assertTrue(refresh.mapping_problems(dict(IDENT, verify={'url': 'http://api.agentbounties.app/x', 'note': 'n'})))
        self.assertEqual(refresh.mapping_problems(dict(IDENT, verify={'url': 'https://api.agentbounties.app/v1/x', 'note': 'n'})), [])


class CommittedData(unittest.TestCase):
    def test_committed_sources_and_refreshed_claims_agree(self):
        srcs = json.loads((ROOT / 'atlas' / 'refresh-sources.json').read_text(encoding='utf-8'))['sources']
        maps = {m['id']: m for v in srcs.values() for m in v.get('numbers', [])}
        probs = [p for m in maps.values() for p in refresh.mapping_problems(m)]
        snap = json.loads(Path(refresh.default_snapshot()).read_text(encoding='utf-8'))
        for e in snap['platforms']:
            for c in e.get('claims', []):
                if c.get('refresh_id'):
                    d = refresh.note_drift(c, maps.get(c['refresh_id']))
                    if d:
                        probs.append(f'{e["slug"]} {c["refresh_id"]}: {d}')
        self.assertEqual(probs, [])


if __name__ == '__main__':
    unittest.main()
