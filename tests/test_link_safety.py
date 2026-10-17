import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'atlas' / 'tools'))
import safebrowsing_check as sb


class ParseAnswer(unittest.TestCase):
    def test_social_engineering_is_flagged(self):
        st, code, threats, upd = sb.parse_answer(')]}\'\n\n[["sb.ssr",3,false,false,true,false,false,1792259421202,"x.example",false]]')
        self.assertEqual((st, code), ('flagged', 3))
        self.assertEqual(threats, ['social_engineering'])
        self.assertTrue(upd.endswith('Z'))

    def test_clean_and_no_data(self):
        self.assertEqual(sb.parse_answer(')]}\'\n[["sb.ssr",1,false,false,false,false,false,1,"a.example",false]]')[0], 'clean')
        self.assertEqual(sb.parse_answer(')]}\'\n[["sb.ssr",4,false,false,false,false,false,1,"big.example",false]]')[0], 'clean')
        self.assertEqual(sb.parse_answer(')]}\'\n[["sb.ssr",6,false,false,false,false,false,0,"new.example",false]]')[0], 'no_data')

    def test_html_or_garbage_raises(self):
        with self.assertRaises(Exception):
            sb.parse_answer('<html>rate limited</html>')


class Hosts(unittest.TestCase):
    def test_extract_hosts_normalises_and_skips_own_site(self):
        snap = {'platforms': [
            {'slug': 'a', 'canonical_url': 'https://www.A.example/', 'claims': [{'source_url': 'https://api.b.example/x?y=1'}, {'note': 'not a url'}]},
            {'slug': 'b', 'canonical_url': 'https://a.example', 'claims': [{'source_url': 'https://commonworld.one/atlas/'}]}]}
        self.assertEqual(sb.extract_hosts(snap), {'a.example': ['a', 'b'], 'api.b.example': ['a']})

    def test_failed_query_keeps_previous_result(self):
        orig = sb.query
        sb.query = lambda h, t, r: {'status': None, 'error': 'HTTP 429'}
        try:
            prev = {'a.example': {'status': 'clean', 'checked_at': '2026-10-16T00:00:00Z'}}
            res = sb.run(['a.example', 'b.example'], prev, 4, 1, 0)
        finally:
            sb.query = orig
        self.assertEqual(res['a.example']['status'], 'clean')
        self.assertTrue(res['a.example']['stale'])
        self.assertEqual(res['b.example']['status'], 'no_data')
        self.assertIsNone(res['b.example']['checked_at'])


if __name__ == '__main__':
    unittest.main()
