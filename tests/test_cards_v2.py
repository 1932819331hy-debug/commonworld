"""Cards v2 rules (atlas/site/cards_v2.py, atlas/CURATION.md#cards-v2): the evidence-ladder mapping from a source URL, the card
summary, keys and books filled only from supported claims on the card, first tasks, and the curated files in the repo.
check.py also verifies the built files in CI."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'atlas' / 'site'))
import cards_v2 as cv2  # noqa: E402

SNAP = json.load(open(ROOT / 'atlas' / 'data' / 'snapshot-verified-2026-10-15.json', encoding='utf-8'))
CARDS = {p['slug']: p for p in SNAP['platforms']}


def claim(url, kind='metric', outcome='supported', **kw):
    return {'kind': kind, 'statement': kw.pop('statement', 's'), 'source_url': url, 'outcome': outcome, 'quote': kw.pop('quote', 'q'), **kw}


class EvidenceLadder(unittest.TestCase):
    def test_level_3_public_transactions(self):
        for u in ('https://basescan.org/tx/0xabc123', 'https://etherscan.io/address/0x' + 'a' * 40, 'https://solscan.io/account/x',
                  'https://explorer.solana.com/tx/5abc', 'https://optimistic.etherscan.io/tx/0x1', 'https://kitescan.ai/api/v2/stats',
                  'https://mempool.space/tx/ab', 'https://x402scan.example/tx/0x' + 'b' * 64):
            self.assertEqual(cv2.source_level(u), 3, u)

    def test_level_2_public_dashboard(self):
        for u in ('https://api.moltjobs.io/v1/stats', 'https://www.openwork.bot/api/dashboard', 'https://thespawn.io/analytics',
                  'https://clawnews.io/stats', 'https://agenty.im/directory.json', 'https://x402-list.com/api/v1/services?per_page=100',
                  'https://www.clawbench.com/leaderboard', 'https://dune.com/q/1', 'https://chainward.ai/decodes/virtuals-top-dog',
                  'https://www.x402scan.com/', 'https://qevrulan.com/v1/public/pulse'):
            self.assertEqual(cv2.source_level(u), 2, u)

    def test_level_1_operator_says(self):
        for u in ('https://touchstone.cv/', 'https://dealwork.ai/jobs', 'https://x402-list.com/facilitators', 'https://github.com/a/b/commits',
                  'https://web.archive.org/web/2026/https://example.com/api/stats', 'https://example.com/statement', 'https://blog.example.com/apis-for-agents',
                  'https://example.com/tx/0x' + 'c' * 64):  # a tx-looking path on a host that is no explorer stays text
            self.assertEqual(cv2.source_level(u), 1, u)

    def test_no_source_no_level(self):
        self.assertIsNone(cv2.source_level(None))
        self.assertIsNone(cv2.source_level(''))
        self.assertIsNone(cv2.claim_level(claim(None)))

    def test_only_money_and_activity_claims(self):
        self.assertIsNone(cv2.claim_level(claim('https://basescan.org/tx/0x1', kind='description')))
        for k in cv2.EVIDENCE_KINDS:
            self.assertEqual(cv2.claim_level(claim('https://basescan.org/tx/0x1', kind=k)), 3)

    def test_card_level_is_highest_supported(self):
        c = {'slug': 'x', 'claims': [claim('https://a.example/'), claim('https://api.a.example/v1/stats', kind='economic_flow'),
                                     claim('https://basescan.org/tx/0x1', outcome='contradicted')]}
        ev = cv2.card_evidence(c)
        self.assertEqual((ev['level'], ev['id'], ev['label'], ev['claims_counted']), (2, 'public_dashboard', 'public dashboard', 2))
        none = cv2.card_evidence({'slug': 'y', 'claims': [claim('https://a.example/', kind='description')]})
        self.assertEqual((none['level'], none['label']), (None, 'not recorded yet'))

    def test_annotate(self):
        x = cv2.annotate_claim(claim('https://basescan.org/tx/0x1', kind='economic_flow'))
        self.assertEqual((x['evidence_level'], x['evidence_label']), (3, 'public transactions'))
        self.assertNotIn('evidence_level', cv2.annotate_claim(claim('https://a.example/', kind='description')))


class KeysAndBooks(unittest.TestCase):
    CARD = {'slug': 'demo', 'claims': [
        claim('https://demo.example/', kind='description', quote='Funds sit in an on-chain escrow contract.'),
        claim('https://api.demo.example/v1/payouts', kind='economic_flow', quote='"paid_usdc": 12'),
        claim('https://demo.example/about', kind='operator', outcome='contradicted', quote='Built by Ada')]}

    def test_curated_value_needs_a_supported_claim(self):
        cur = {'demo': {'keys': {'value': 'smart_contract', 'source_url': 'https://demo.example/', 'quote': 'on-chain escrow contract'},
                        'people': {'value': 'named', 'names': 'Ada', 'source_url': 'https://demo.example/about', 'quote': 'Built by Ada'}}}
        kb = cv2.keys_and_books(self.CARD, cur)
        self.assertEqual(kb['keys']['state'], 'recorded')
        self.assertEqual(kb['keys']['source_url'], 'https://demo.example/')
        self.assertEqual(kb['people'], {'state': 'not_recorded', 'value': None, 'label': 'not recorded yet', 'source_url': None, 'quote': None})
        errs = cv2.validate_keys_books(cur, {'demo': self.CARD})
        self.assertEqual(len(errs), 1)
        self.assertIn('people', errs[0])

    def test_books_derived_from_dashboard_money_flow(self):
        kb = cv2.keys_and_books(self.CARD, {})
        self.assertEqual((kb['books']['state'], kb['books']['value'], kb['books']['source_url']),
                         ('recorded', 'public_dashboard', 'https://api.demo.example/v1/payouts'))
        self.assertEqual(kb['keys']['label'], 'not recorded yet')

    def test_bad_values_fail(self):
        self.assertTrue(cv2.validate_keys_books({'demo': {'keys': {'value': 'bank', 'source_url': 'https://demo.example/', 'quote': 'escrow'}}}, {'demo': self.CARD}))
        self.assertTrue(cv2.validate_keys_books({'nope': {}}, {'demo': self.CARD}))

    def test_repo_file_is_valid(self):
        self.assertEqual(cv2.validate_keys_books(cv2.load_keys_books(), CARDS), [])


class FirstTask(unittest.TestCase):
    def test_repo_file_is_valid_and_only_verified(self):
        tasks = cv2.load_first_tasks()
        self.assertEqual(cv2.validate_first_tasks(tasks, set(CARDS)), [])
        self.assertEqual(set(tasks), {'touchstone'})
        t = cv2.first_task(CARDS['touchstone'], tasks)
        self.assertEqual(t['credit'], 'Contributed by reticuli')
        self.assertIn('SELFTEST OK', ' '.join(t['steps']))
        self.assertIsNone(cv2.first_task(CARDS['dealwork-ai'], tasks))

    def test_incomplete_task_fails(self):
        self.assertTrue(cv2.validate_first_tasks({'touchstone': {'title': 't', 'steps': ['a']}}, set(CARDS)))


class Wording(unittest.TestCase):
    def test_v2_vocabulary_is_positive(self):
        words = [cv2.NOT_RECORDED] + [x for lv in cv2.LEVELS.values() for x in lv[1:]] + \
                [t for t, vals in cv2.KB_FIELDS.values() for t in [t, *vals.values()]]
        self.assertEqual(cv2.negative_hits(' '.join(words)), [])
        self.assertEqual(cv2.negative_hits('This source is unverified'), ['unverified'])


if __name__ == '__main__':
    unittest.main()
