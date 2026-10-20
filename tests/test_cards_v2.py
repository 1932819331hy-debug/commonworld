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


TX = '0x' + 'a' * 64


def claim(url, kind='metric', outcome='supported', **kw):
    return {'kind': kind, 'statement': kw.pop('statement', 's'), 'source_url': url, 'outcome': outcome, 'quote': kw.pop('quote', 'q'), **kw}


class EvidenceLadder(unittest.TestCase):
    TX = '0x' + 'a' * 64
    SOL = '5VERv8NMvzbJMEkV8xnrLkEaWRtSz9CosKDYjCJjBRnbJLgp8uirBgmQpjKhoR4tjF3ZpRzrFmBV6UjKdiSZkQUW'

    def test_no_automatic_level_3(self):
        """Owner decision 2026-10-20: the URL rule never gives level 3. A concrete record on an explorer is level 2 by the rule;
        its format is what record_url_ok() checks for a curator's level-3 entry."""
        for u in ('https://basescan.org/tx/' + self.TX, 'https://etherscan.io/address/0x' + 'a' * 40, 'https://solscan.io/account/' + self.SOL[:44],
                  'https://explorer.solana.com/tx/' + self.SOL, 'https://optimistic.etherscan.io/tx/' + self.TX,
                  'https://kitescan.ai/tx/' + self.TX,
                  'https://mempool.space/tx/' + 'ab' * 32, 'https://mempool.space/block/840000', 'https://basescan.org/token/0x' + 'e' * 40,
                  'https://www.basescan.org/tx/' + self.TX):
            self.assertEqual(cv2.source_level(u), 2, u)
            self.assertTrue(cv2.record_url_ok(u), u)
        self.assertEqual(cv2.claim_level(claim('https://basescan.org/tx/' + TX, kind='economic_flow')), 2)

    def test_level_3_needs_https_and_an_exact_explorer_host(self):
        # a host that merely contains "scan" or "explorer" is no explorer; subdomains of a listed explorer are not included
        for u in ('https://evilscan.example/tx/' + self.TX, 'https://x402scan.example/tx/0x' + 'b' * 64,
                  'https://my-explorer.example/address/0x' + 'a' * 40, 'https://basescan.org.evil.example/tx/' + self.TX,
                  'https://evil.basescan.org/tx/' + self.TX, 'https://notbasescan.org/tx/' + self.TX):
            self.assertEqual(cv2.source_level(u), 1, u)
            self.assertFalse(cv2.record_url_ok(u), u)
        # the same record over http is no record format
        for u in ('http://basescan.org/tx/' + self.TX, 'http://etherscan.io/address/0x' + 'a' * 40):
            self.assertEqual(cv2.source_level(u), 2, u)
            self.assertFalse(cv2.record_url_ok(u), u)
        self.assertIn('kitescan.ai', cv2.EXPLORER_HOSTS)
        self.assertTrue(all(h == h.lower() and not h.startswith('www.') for h in cv2.EXPLORER_HOSTS))

    def test_record_path_is_case_sensitive(self):
        for u in ('https://basescan.org/TX/' + self.TX, 'https://etherscan.io/ADDRESS/0x' + 'a' * 40, 'https://etherscan.io/Address/0x' + 'a' * 40):
            self.assertEqual(cv2.source_level(u), 2, u)  # an explorer page, but no lowercase record path
            self.assertFalse(cv2.record_url_ok(u), u)

    def test_explorer_aggregates_are_level_2(self):
        # explorer stats, charts and home pages: views over many records, no single record to check
        for u in ('https://kitescan.ai/api/v2/stats', 'https://kitescan.ai/stats', 'https://etherscan.io/charts', 'https://basescan.org/',
                  'https://solscan.io/analytics', 'https://mempool.space/', 'https://basescan.org/tx/0x1', 'https://solscan.io/account/x'):
            self.assertEqual(cv2.source_level(u), 2, u)

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

    def test_record_format_needs_the_explorers_own_route_and_network_format(self):
        """A curator's level-3 source is one record: the whole path is one of the explorer's own record routes (RECORD_ROUTES) with an
        identifier of that explorer's network. Every explorer page is level 2 by the URL rule either way."""
        h64 = 'ab' * 32
        good = ('https://etherscan.io/tx/0x' + h64, 'https://mempool.space/tx/' + h64, 'https://explorer.solana.com/tx/' + self.SOL,
                'https://suiscan.xyz/mainnet/tx/' + self.SOL[:44], 'https://etherscan.io/address/0x' + 'A' * 40,
                'https://suiscan.xyz/mainnet/account/0x' + h64, 'https://solscan.io/account/' + self.SOL[:44],
                'https://mempool.space/address/bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq',
                'https://blockstream.info/address/1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa', 'https://tonviewer.com/EQ' + 'A' * 46,
                'https://tonscan.org/address/0:' + h64, 'https://basescan.org/token/0x' + 'e' * 40, 'https://solscan.io/token/' + self.SOL[:43],
                'https://etherscan.io/block/0', 'https://etherscan.io/block/19000000', 'https://mempool.space/block/' + '0' * 8 + 'ab' * 28,
                'https://explorer.aptoslabs.com/txn/123456', 'https://explorer.aptoslabs.com/account/0x' + h64,
                'https://kitescan.ai/address/0x' + 'd' * 40, 'https://etherscan.io/tx/0x' + h64 + '/')
        for u in good:
            self.assertTrue(cv2.record_url_ok(u), u)
            self.assertEqual(cv2.source_level(u), 2, u)
        bad = (# malformed identifiers (round 7)
               'https://etherscan.io/tx/1', 'https://etherscan.io/tx/0x1', 'https://etherscan.io/tx/0x' + 'a' * 63,
               'https://etherscan.io/tx/0x' + 'a' * 65, 'https://etherscan.io/tx/0x' + 'g' * 64, 'https://etherscan.io/tx/0x' + 'a' * 40,
               'https://etherscan.io/tx/12345678', 'https://explorer.solana.com/tx/' + self.SOL[:60],
               'https://etherscan.io/address/1', 'https://etherscan.io/address/0x' + 'a' * 39, 'https://etherscan.io/address/0x' + 'a' * 41,
               'https://solscan.io/account/x', 'https://solscan.io/account/' + '0' * 40, 'https://basescan.org/token/12345',
               'https://etherscan.io/block/01', 'https://etherscan.io/block/1234567890123', 'https://etherscan.io/block/0x12',
               # another network's format on this explorer (Codex round 8)
               'https://etherscan.io/tx/' + '1' * 44, 'https://etherscan.io/address/' + '1' * 44, 'https://basescan.org/address/' + 'A' * 32,
               'https://etherscan.io/tx/' + self.SOL, 'https://etherscan.io/tx/' + h64, 'https://solscan.io/tx/0x' + h64,
               'https://solscan.io/account/0x' + 'a' * 40, 'https://mempool.space/tx/0x' + h64, 'https://mempool.space/address/0x' + 'a' * 40,
               'https://tonscan.org/address/0x' + 'a' * 40,
               # not the explorer's own route: a prefix, a suffix, another route name, an API path (Codex round 8)
               'https://etherscan.io/unrelated/tx/0x' + h64, 'https://etherscan.io/en/address/0x' + 'a' * 40,
               'https://etherscan.io/address/0x' + 'a' * 40 + '/tokens', 'https://etherscan.io/tx/0x' + h64 + '//',
               'https://etherscan.io/transaction/0x' + h64, 'https://etherscan.io/account/0x' + 'a' * 40, 'https://solscan.io/address/' + self.SOL[:44],
               'https://kitescan.ai/api/v2/addresses/0x' + 'd' * 40, 'https://kitescan.ai/api/v2/transactions/0x' + h64,
               'https://etherscan.io/tx/0x' + h64 + '?a=1', 'https://suiscan.xyz/testnet/tx/' + self.SOL[:44],
               # explorers outside the explorer -> network map (multi-chain, or records in the fragment)
               'https://blockscout.com/tx/0x' + h64, 'https://blockchair.com/bitcoin/transaction/' + h64,
               'https://oklink.com/eth/tx/0x' + h64, 'https://tronscan.org/address/TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf',
               'https://explorer.hiro.so/txid/0x' + h64)
        for u in bad:
            self.assertFalse(cv2.record_url_ok(u), u)
            self.assertEqual(cv2.source_level(u), 2, u)
        # the map is part of the allowlist
        self.assertTrue(set(cv2.RECORD_ROUTES) <= set(cv2.EXPLORER_HOSTS))

    def test_no_source_no_level(self):
        self.assertIsNone(cv2.source_level(None))
        self.assertIsNone(cv2.source_level(''))
        self.assertIsNone(cv2.claim_level(claim(None)))

    def test_only_money_and_activity_claims(self):
        self.assertIsNone(cv2.claim_level(claim('https://basescan.org/tx/' + TX, kind='description')))
        for k in cv2.EVIDENCE_KINDS:
            self.assertEqual(cv2.claim_level(claim('https://basescan.org/tx/' + TX, kind=k)), 2)

    def test_card_level_is_highest_supported(self):
        c = {'slug': 'x', 'claims': [claim('https://a.example/'), claim('https://api.a.example/v1/stats', kind='economic_flow'),
                                     claim('https://basescan.org/tx/' + TX, outcome='contradicted')]}
        ev = cv2.card_evidence(c)
        self.assertEqual((ev['level'], ev['id'], ev['label'], ev['claims_counted']), (2, 'public_dashboard', 'public dashboard', 2))
        none = cv2.card_evidence({'slug': 'y', 'claims': [claim('https://a.example/', kind='description')]})
        self.assertEqual((none['level'], none['label']), (None, 'not recorded yet'))

    def test_annotate(self):
        x = cv2.annotate_claim(claim('https://basescan.org/tx/' + TX, kind='economic_flow'))
        self.assertEqual((x['evidence_level'], x['evidence_label']), (2, 'public dashboard'))
        self.assertNotIn('evidence_level', cv2.annotate_claim(claim('https://a.example/', kind='description')))


class CuratorReview(unittest.TestCase):
    """atlas/data/evidence-levels.json: a curator sets the level of a card's claims with one source URL after opening it."""
    LOG = 'https://demo.example/d/log'
    CARD = {'slug': 'demo', 'claims': [claim(LOG, kind='recent_activity'), claim('https://api.demo.example/v1/feed', kind='metric'),
                                       claim('https://demo.example/d/log', kind='description')]}
    OV = {'demo': [{'source_url': LOG, 'evidence_level': 2, 'evidence_note': 'Public JSON log with timestamps.', 'reviewed_on': '2026-10-19'},
                   {'source_url': 'https://api.demo.example/v1/feed', 'evidence_level': 1, 'evidence_note': 'Read as text: the feed lists zero items.',
                    'reviewed_on': '2026-10-19'}]}

    def test_override_sets_level_and_note(self):
        ov = cv2.card_overrides(self.CARD, self.OV)
        a, b, c = self.CARD['claims']
        self.assertEqual((cv2.claim_level(a, ov), cv2.claim_level(b, ov), cv2.claim_level(c, ov)), (2, 1, None))
        self.assertEqual((cv2.claim_level(a), cv2.claim_level(b)), (1, 2))  # without the file: the URL rule
        x = cv2.annotate_claim(a, ov)
        self.assertEqual((x['evidence_level'], x['evidence_label'], x['evidence_note']), (2, 'public dashboard', 'Public JSON log with timestamps.'))
        self.assertNotIn('evidence_note', cv2.annotate_claim(claim('https://other.example/'), ov))
        self.assertNotIn('evidence_note', cv2.annotate_claim(c, ov))  # only money/activity claims
        self.assertEqual(cv2.card_evidence(self.CARD, self.OV)['level'], 2)
        self.assertEqual(cv2.card_evidence({'slug': 'other', 'claims': self.CARD['claims']}, self.OV)['level'], 2)  # other slug: URL rule

    def test_lowered_money_flow_no_longer_opens_the_books(self):
        card = {'slug': 'demo', 'claims': [claim('https://api.demo.example/v1/feed', kind='economic_flow')]}
        self.assertEqual(cv2.keys_and_books(card, {})['books']['value'], 'public_dashboard')
        self.assertEqual(cv2.keys_and_books(card, {}, self.OV)['books']['state'], 'not_recorded')

    def test_validation(self):
        cards = {'demo': self.CARD}
        self.assertEqual(cv2.validate_evidence_overrides(self.OV, cards), [])
        base = self.OV['demo'][0]
        bad = {
            'unknown card': {'nope': [base]},
            'source is not on the card': {'demo': [base | {'source_url': 'https://demo.example/elsewhere'}]},
            'level outside 1-3': {'demo': [base | {'evidence_level': 4}]},
            'same as the URL rule': {'demo': [base | {'evidence_level': 1}]},
            'empty note': {'demo': [base | {'evidence_note': ' '}]},
            'long note': {'demo': [base | {'evidence_note': 'x' * 201}]},
            'negative note': {'demo': [base | {'evidence_note': 'This source is unverified'}]},
            'bad date': {'demo': [base | {'reviewed_on': '19.10.2026'}]},
            'extra key': {'demo': [base | {'level': 2}]},
            'twice': {'demo': [base, base]},
            'empty list': {'demo': []},
        }
        for why, ov in bad.items():
            self.assertTrue(cv2.validate_evidence_overrides(ov, cards), why)

    def test_curator_level_3_format_check(self):
        rec = 'https://basescan.org/tx/' + TX
        card = {'slug': 'demo', 'claims': [claim(rec, kind='economic_flow')]}
        e3 = {'source_url': rec, 'evidence_level': 3, 'evidence_note': 'Curator opened the transaction: a USDC payout.', 'reviewed_on': '2026-10-20'}
        self.assertEqual(cv2.validate_evidence_overrides({'demo': [e3]}, {'demo': card}), [])
        ov = cv2.card_overrides(card, {'demo': [e3]})
        self.assertEqual(cv2.claim_level(card['claims'][0], ov), 3)
        self.assertEqual(cv2.claim_level(card['claims'][0]), 2)  # without the curator entry: level 2
        self.assertEqual(cv2.card_evidence(card, {'demo': [e3]})['level'], 3)
        self.assertEqual(cv2.keys_and_books(card, {}, {'demo': [e3]})['books']['value'], 'public_transactions')
        self.assertEqual(cv2.annotate_claim(card['claims'][0], ov)['evidence_note'], e3['evidence_note'])
        # level 3 on anything that is not one explorer record fails, whatever the curator says
        for bad in ('https://demo.example/payouts', 'https://api.demo.example/v1/payouts', 'https://basescan.org/stats',
                    'http://basescan.org/tx/' + TX, 'https://evil.com@basescan.org/tx/' + TX, 'https://basescan.org:443/tx/' + TX,
                    'https://basescan.org/tx/0x1', 'https://basescan.org/tx/' + TX + '?a=1', 'https://basescan.org/en/tx/' + TX,
                    'https://blockchair.com/bitcoin/transaction/' + 'ab' * 32, 'https://basescan.org/tx/' + TX + '\u200b'):
            c = {'slug': 'demo', 'claims': [claim(bad, kind='economic_flow')]}
            errs = cv2.validate_evidence_overrides({'demo': [e3 | {'source_url': bad}]}, {'demo': c})
            self.assertTrue(any('evidence_level 3 needs one record' in e for e in errs), (bad, errs))
        # a curator level 2 on an explorer record equals the URL rule now
        self.assertTrue(cv2.validate_evidence_overrides({'demo': [e3 | {'evidence_level': 2}]}, {'demo': card}))

    def test_repo_file_is_valid(self):
        ov = cv2.load_evidence_overrides()
        self.assertEqual(cv2.validate_evidence_overrides(ov, CARDS), [])
        # reviewed on 2026-10-19: Touchstone's public JSON disclosure log is a public log (level 2); a dated report on a
        # dashboard host is read as text (level 1)
        t = cv2.card_overrides(CARDS['touchstone'], ov)
        x = next(c for c in CARDS['touchstone']['claims'] if c['kind'] == 'recent_activity')
        self.assertEqual(cv2.claim_level(x, t), 2)
        self.assertEqual(cv2.card_evidence(CARDS['touchstone'], ov)['level'], 2)
        self.assertEqual(cv2.card_evidence(CARDS['virtuals-agent-commerce-protocol'], ov)['level'], 1)


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
        errs = cv2.validate_keys_books(cur, {'demo': self.CARD}, orgs=['Demo Labs'])
        self.assertEqual(len(errs), 2)  # an unsupported claim, and a person's name instead of an organization
        self.assertTrue(all('people' in x for x in errs))

    def test_books_derived_from_dashboard_money_flow(self):
        kb = cv2.keys_and_books(self.CARD, {})
        self.assertEqual((kb['books']['state'], kb['books']['value'], kb['books']['source_url']),
                         ('recorded', 'public_dashboard', 'https://api.demo.example/v1/payouts'))
        self.assertEqual(kb['keys']['label'], 'not recorded yet')

    def test_books_cannot_be_curated(self):
        # owner decision 2026-10-20: open books come only from the evidence ladder; a curated `books` field is an error,
        # even with a supported claim behind it, and it is ignored by keys_and_books
        cur = {'demo': {'books': {'value': 'public_transactions', 'source_url': 'https://demo.example/', 'quote': 'on-chain escrow contract'}}}
        errs = cv2.validate_keys_books(cur, {'demo': self.CARD}, orgs=[])
        self.assertTrue(any('books cannot be curated' in e for e in errs), errs)
        self.assertEqual(cv2.keys_and_books(self.CARD, cur)['books']['value'], 'public_dashboard')  # the ladder, not the label
        card = {'slug': 'demo', 'claims': [claim('https://demo.example/', kind='description', quote='Funds sit in escrow.')]}
        self.assertEqual(cv2.keys_and_books(card, cur)['books']['state'], 'not_recorded')
        self.assertNotIn('books', cv2.KB_CURATED)
        for slug, ent in cv2.load_keys_books().items():
            self.assertNotIn('books', ent, slug)

    def test_bad_values_fail(self):
        self.assertTrue(cv2.validate_keys_books({'demo': {'keys': {'value': 'bank', 'source_url': 'https://demo.example/', 'quote': 'escrow'}}}, {'demo': self.CARD}))
        self.assertTrue(cv2.validate_keys_books({'nope': {}}, {'demo': self.CARD}))

    def test_custody_on_operator_words_is_attributed(self):
        cur = {'demo': {'keys': {'value': 'smart_contract', 'source_url': 'https://demo.example/', 'quote': 'on-chain escrow contract'}}}
        kb = cv2.keys_and_books(self.CARD, cur)
        self.assertEqual((kb['keys']['label'], kb['keys']['basis']), ('The operator says a smart contract holds the funds', 'operator_says'))
        self.assertNotIn('contract_url', kb['keys'])
        cur['demo']['keys']['basis'] = 'operator_says'
        self.assertEqual(cv2.keys_and_books(self.CARD, cur)['keys']['label'], 'The operator says a smart contract holds the funds')
        self.assertEqual(cv2.validate_keys_books(cur, {'demo': self.CARD}, orgs=[]), [])
        for v, label in (('operator', 'The operator says it holds the funds'), ('user_wallet', 'The operator says users hold their own wallet or keys')):
            c = {'demo': {'keys': {'value': v, 'source_url': 'https://demo.example/', 'quote': 'escrow'}}}
            self.assertEqual(cv2.keys_and_books(self.CARD, c)['keys']['label'], label)

    def test_custody_onchain_needs_an_explorer_record(self):
        addr = 'https://basescan.org/address/0x' + 'f' * 40
        ok = {'demo': {'keys': {'value': 'smart_contract', 'basis': 'onchain_verified', 'contract_url': addr,
                                'source_url': 'https://demo.example/', 'quote': 'on-chain escrow contract'}}}
        self.assertEqual(cv2.validate_keys_books(ok, {'demo': self.CARD}, orgs=[]), [])
        kb = cv2.keys_and_books(self.CARD, ok)['keys']
        self.assertEqual((kb['label'], kb['basis'], kb['contract_url']),
                         ('A smart contract holds the funds (contract on a public block explorer)', 'onchain_verified', addr))
        k = ok['demo']['keys']
        bad = {
            'no contract_url': k | {'contract_url': None},
            'explorer stats page': k | {'contract_url': 'https://basescan.org/stats'},
            'operator text page': k | {'contract_url': 'https://demo.example/contract'},
            'not a smart contract': k | {'value': 'operator'},
            'unknown basis': k | {'basis': 'trust_me'},
            'contract_url without onchain basis': k | {'basis': 'operator_says'},
            'explorer transaction page': k | {'contract_url': 'https://basescan.org/tx/' + TX},
            'explorer block page': k | {'contract_url': 'https://etherscan.io/block/19000000'},
            'address on a non-explorer host': k | {'contract_url': 'https://demo.example/address/0x' + 'f' * 40},
            'scan-named host': k | {'contract_url': 'https://evilscan.example/address/0x' + 'f' * 40},
            'http explorer': k | {'contract_url': 'http://basescan.org/address/0x' + 'f' * 40},
        }
        for why, v in bad.items():
            self.assertTrue(cv2.validate_keys_books({'demo': {'keys': v}}, {'demo': self.CARD}, orgs=[]), why)
        for good in (addr, 'https://basescan.org/token/0x' + 'e' * 40, 'https://etherscan.io/address/0x' + 'a' * 40 + '/',
                     'https://explorer.solana.com/address/' + EvidenceLadder.SOL[:44], 'https://tonviewer.com/EQ' + 'A' * 46,
                     'https://solscan.io/account/' + EvidenceLadder.SOL[:44]):
            self.assertTrue(cv2.contract_url_ok(good), good)
            self.assertEqual(cv2.validate_keys_books({'demo': {'keys': k | {'contract_url': good}}}, {'demo': self.CARD}, orgs=[]), [], good)
        for bad_url in ('https://basescan.org/tx/' + TX, 'https://etherscan.io/block/19000000', 'https://basescan.org/stats', None,
                        # the whole path must be /<address|addresses|account|token>/<id>[/]: no other segments, query or fragment
                        'https://basescan.org/tx/' + TX + '/address/0x' + 'a' * 40,
                        'https://etherscan.io/address/0x' + 'a' * 40 + '?a=1',
                        'https://etherscan.io/address/0x' + 'a' * 40 + '#code',
                        'https://etherscan.io/address/0x' + 'a' * 40 + '//',
                        'https://etherscan.io/address/0x' + 'a' * 40 + '/tokens',
                        'https://etherscan.io/en/address/0x' + 'a' * 40,
                        # an address of another network on this explorer (Codex round 8)
                        'https://basescan.org/address/' + 'A' * 32, 'https://solscan.io/account/0x' + 'a' * 40,
                        # https and an exact explorer host only
                        'https://evilscan.example/address/0x' + 'a' * 40, 'http://basescan.org/address/0x' + 'a' * 40,
                        'https://evil.basescan.org/address/0x' + 'a' * 40, 'https://explorer.evil.example/address/0x' + 'a' * 40,
                        # lowercase path segments only
                        'https://etherscan.io/ADDRESS/0x' + 'a' * 40, 'https://basescan.org/Token/0x' + 'e' * 40,
                        # printable ASCII only
                        'https://etherscan.io/address/0x' + 'a' * 40 + '\u200b', 'https://etherscan.io/address/0x' + 'a' * 40 + '\u2028',
                        'https://etherscan.io/address/0x' + 'a' * 40 + '\uff1b'):
            self.assertFalse(cv2.contract_url_ok(bad_url), repr(bad_url))
        self.assertTrue(cv2.validate_keys_books({'demo': {'books': {'value': 'public_dashboard', 'basis': 'operator_says',
                                                                    'source_url': 'https://api.demo.example/v1/payouts', 'quote': 'paid_usdc'}}},
                                                {'demo': self.CARD}, orgs=[]))

    def test_people_names_an_organization(self):
        card = {'slug': 'demo', 'claims': [claim('https://demo.example/about', kind='operator', quote='Operated by Demo Labs, built by Ada Lovelace')]}
        org = {'demo': {'people': {'value': 'named', 'names': 'Demo Labs', 'source_url': 'https://demo.example/about', 'quote': 'Operated by Demo Labs'}}}
        self.assertEqual(cv2.validate_keys_books(org, {'demo': card}, orgs=['Demo Labs']), [])
        self.assertTrue(cv2.org_name_ok('Meta', ['Meta']))
        # exact match only: a note after the name could carry an individual person's name
        for names in ('Meta (Jane Doe)', 'Meta (acquired)', 'Meta ', 'meta', 'Meta, Jane Doe'):
            self.assertFalse(cv2.org_name_ok(names, ['Meta']), names)
        for names in ('Demo Labs (founded by Jane Example)', 'Demo Labs (acquired by Big Co)'):
            note = {'demo': {'people': org['demo']['people'] | {'names': names}}}
            self.assertTrue(cv2.validate_keys_books(note, {'demo': card}, orgs=['Demo Labs']), names)
        # the relation goes in a separate role from a fixed list
        role = {'demo': {'people': org['demo']['people'] | {'role': 'acquired'}}}
        self.assertEqual(cv2.validate_keys_books(role, {'demo': card}, orgs=['Demo Labs']), [])
        self.assertEqual(cv2.keys_and_books(card, role)['people']['label'], 'Named: Demo Labs (acquired it)')
        self.assertEqual(cv2.keys_and_books(card, org)['people']['label'], 'Named: Demo Labs')
        for bad_role in ('founded by Jane Example', 'Jane Doe', ''):
            r = {'demo': {'people': org['demo']['people'] | {'role': bad_role}}}
            self.assertTrue(cv2.validate_keys_books(r, {'demo': card}, orgs=['Demo Labs']), bad_role)
        person = {'demo': {'people': {'value': 'named', 'names': 'Ada Lovelace', 'source_url': 'https://demo.example/about', 'quote': 'built by Ada Lovelace'}}}
        self.assertTrue(cv2.validate_keys_books(person, {'demo': card}, orgs=['Demo Labs']))
        self.assertTrue(cv2.validate_keys_books(org, {'demo': card}, orgs=[]))

    def test_repo_file_is_valid(self):
        self.assertEqual(cv2.validate_keys_books(cv2.load_keys_books(), CARDS), [])
        orgs = cv2.load_org_names()
        for slug, ent in cv2.load_keys_books().items():
            if 'people' in ent:
                self.assertTrue(cv2.org_name_ok(ent['people']['names'], orgs), slug)
            if 'keys' in ent and not ent['keys'].get('contract_url'):
                self.assertEqual(ent['keys'].get('basis', 'operator_says'), 'operator_says', slug)
        self.assertNotIn('freeq', {s for s, e in cv2.load_keys_books().items() if 'people' in e})  # named only a person


class FirstTask(unittest.TestCase):
    """Owner decision 2026-10-20: a first task has nothing to download or run (one fail-closed rule, task_text_errors)."""
    FEED = 'https://touchstone.cv/.well-known/touchstone/checkpoints/rec_01m1hbq666jjjyfw7s6tf7h2rd'

    def test_repo_file_is_valid_and_only_verified(self):
        tasks = cv2.load_first_tasks()
        self.assertEqual(cv2.validate_first_tasks(tasks, set(CARDS)), [])
        self.assertEqual(set(tasks), {'touchstone'})
        self.assertIsNone(cv2.first_task(CARDS['dealwork-ai'], tasks))

    def test_incomplete_task_fails(self):
        self.assertTrue(cv2.validate_first_tasks({'touchstone': {'title': 't', 'steps': ['a']}}, set(CARDS)))

    def test_touchstone_is_the_browser_path(self):
        t = cv2.load_first_tasks()['touchstone']
        self.assertNotIn('code', t)
        self.assertEqual(cv2.task_text_errors(t), [])
        pub = cv2.first_task(CARDS['touchstone'], cv2.load_first_tasks())
        self.assertNotIn('code', pub)
        self.assertIn(self.FEED, pub['steps'][0])
        self.assertIn('browser', pub['steps'][0])
        self.assertTrue(any('tsa' in x and 'created_at' in x for x in pub['steps']))
        self.assertTrue(pub['steps'][2].startswith("Check each checkpoint's anchors: an anchor with method \"tsa\""), pub['steps'][2])
        self.assertTrue(all(cv2.STEP_START.match(x) for x in pub['steps']))
        self.assertIn('which clock each checkpoint', pub['done_when'])
        self.assertEqual((pub['credit'], pub['contributed_by'], pub['verified_by']), ('Contributed by reticuli', 'reticuli', 'Hark'))
        self.assertEqual(pub['source_url'], 'https://thecolony.ai/post/2e482bca-592e-4061-afb0-f8b9d7f61f4a')

    def _task(self, **kw):
        return {'title': 'Read the open counter', 'steps': ['Open https://demo.example/stats in a browser.', 'Read the number of open jobs.'],
                'done_when': 'You can say how many jobs are open.', 'contributed_by': 'demo', 'contributed_via': 'The Colony',
                'source_url': 'https://thecolony.ai/post/x', 'verified_by': 'Hark', 'verified_on': '2026-10-20',
                'verification': 'Opened the page on 2026-10-20: HTTP 200, the counter is shown.'} | kw

    def test_plain_task_passes(self):
        self.assertEqual(cv2.validate_first_tasks({'touchstone': self._task()}, set(CARDS)), [])
        for step in ('Open https://demo.example/ and click Start', 'Read https://demo.example/docs/api.json in a browser',
                     'Open the evaluation page and read the score', 'Check which clock each checkpoint was measured on',
                     'Find the list "jobs".', 'Look at the first row.', 'Compare the two totals.', 'Count the open jobs.'):
            self.assertEqual(cv2.task_text_errors(self._task(steps=[step])), [], step)

    def test_steps_start_with_an_allowed_verb(self):
        for step in ('Run the provided executable locally.', 'For each checkpoint, look at its anchors.', 'open the page',
                     'Opening the page', 'Open', 'Open\tthe page', ' Open the page', 'Execute the file', 'Visit the page',
                     'Go to https://demo.example/', 'Click Start'):
            errs = cv2.validate_first_tasks({'touchstone': self._task(steps=[step])}, set(CARDS))
            self.assertTrue(errs, step)
        errs = cv2.task_text_errors(self._task(steps=['Run the provided executable locally.']))
        self.assertTrue(any('must start with one of Open, Find, Read, Look, Check, Compare, Count' in e for e in errs), errs)
        # control characters inside a step (Codex P2): a second line could carry a command
        for step in ('Open the page\n$ rm -rf /', 'Open the page\r\nrm -rf /', 'Open the page\x00', 'Read it\x7f'):
            errs = cv2.task_text_errors(self._task(steps=[step]))
            self.assertTrue(any('control characters' in e for e in errs), (step, errs))

    def test_source_url_is_a_plain_https_page(self):
        for good in ('https://thecolony.ai/post/2e482bca-592e-4061-afb0-f8b9d7f61f4a', 'https://example.test/', 'https://example.test/docs/page.html',
                     'https://github.com/demo/repo/issues/1', 'https://example.test/a?b=c'):
            self.assertTrue(cv2.source_url_ok(good), good)
            self.assertEqual(cv2.validate_first_tasks({'touchstone': self._task(source_url=good)}, set(CARDS)), [], good)
        for bad in ('https://example.test/payload.sh', 'https://example.test/payload.SH', 'https://example.test/tool.py',
                    'https://example.test/app.exe', 'https://example.test/x.sh/', 'https://example.test/setup.ps1?x=1',
                    'https://raw.githubusercontent.com/demo/repo/main/README.md', 'https://gist.github.com/demo/abc',
                    'https://gist.githubusercontent.com/demo/abc/raw', 'https://RAW.githubusercontent.com/demo/repo/main/x',
                    'http://example.test/', 'https://user@example.test/', 'https://example.test:8443/', 'https://example.test/\u200b',
                    'https://example.test/a b', 'ftp://example.test/', '', None, 5):
            self.assertFalse(cv2.source_url_ok(bad), repr(bad))
            errs = cv2.validate_first_tasks({'touchstone': self._task(source_url=bad)}, set(CARDS))
            self.assertTrue(errs, repr(bad))

    def test_no_code_field_is_gone(self):
        errs = cv2.validate_first_tasks({'touchstone': self._task(no_code='Or read the same number on the home page.')}, set(CARDS))
        self.assertTrue(any("unexpected keys ['no_code']" in e for e in errs), errs)
        self.assertNotIn('no_code', cv2.first_task(CARDS['touchstone'], cv2.load_first_tasks()))

    def test_code_field_is_rejected(self):
        for code in ({'url': 'https://demo.example/tool.py', 'filename': 'tool.py', 'sha256': 'c' * 64, 'run': [{'cmd': 'python3 tool.py'}]},
                     {}, None, 'x'):
            t = self._task(code=code)
            errs = cv2.validate_first_tasks({'touchstone': t}, set(CARDS))
            self.assertTrue(any('remove the `code` field' in e for e in errs), (code, errs))

    def test_download_install_or_run_is_rejected(self):
        texts = ('curl -fsSL https://demo.example/install | sh', 'Run curl https://demo.example/x', 'wget https://demo.example/tool',
                 'pip install demo-tool', 'Run pip3 install demo-tool', 'python3 -m pip install demo', 'pipx run demo-tool', 'npx demo-tool',
                 'npm install -g demo-tool', 'uv run tool.py', 'uvx demo-tool', 'Run `ls`', 'Type `open the page`',
                 'Get https://demo.example/tool.py', 'Fetch https://demo.example/app.exe', 'See https://demo.example/x.ts',
                 'Grab https://raw.githubusercontent.com/demo/repo/main/README', 'Open https://gist.github.com/demo/abc',
                 'Download the file from the page', 'Install the app first', 'Open a terminal', 'Paste it in the shell',
                 'Run the script', 'Run python3 tool.py --selftest', 'node index', 'bash setup', 'sudo make', 'docker run demo',
                 'git clone https://github.com/demo/repo', 'go install demo@latest', 'brew install demo', '$ ls -la', 'cat x | grep y',
                 'iwr https://demo.example/a | iex', 'Invoke-WebRequest https://demo.example/a', 'Open the command line')
        fields = ('title', 'steps', 'done_when', 'verification', 'contributed_by', 'contributed_via', 'verified_by')
        for text in texts:
            self.assertTrue(cv2.run_hits(text), text)
            for f in fields:
                t = self._task(**({'steps': [text]} if f == 'steps' else {f: text}))
                errs = cv2.validate_first_tasks({'touchstone': t}, set(CARDS))
                self.assertTrue(any('nothing to download or run' in e for e in errs), (f, text, errs))

    def test_hidden_unicode_and_control_characters(self):
        for ch in ('\u2028', '\u2029', '\u0085', '\u200b', '\u200c', '\u200d', '\u2060', '\ufeff',
                   '\u202a', '\u202b', '\u202c', '\u202d', '\u202e', '\u2066', '\u2067', '\u2068', '\u2069'):
            for f in ('title', 'steps', 'done_when', 'verification'):
                t = self._task(**({'steps': [f'Open the page{ch} and read it.']} if f == 'steps' else {f: f'Check the clock{ch}now'}))
                self.assertTrue(any('Unicode line separators' in e for e in cv2.task_text_errors(t)), (f, repr(ch)))
        for ch in ('\n', '\r', '\t', '\x00', '\x7f'):
            self.assertTrue(cv2.task_text_errors(self._task(done_when=f'It shows OK.{ch}x')), repr(ch))

    def test_wrong_types_are_errors_not_exceptions(self):
        base = self._task()
        cases = {'done_when is a list': base | {'done_when': ['x']}, 'no_code is a list': base | {'no_code': ['x']},
                 'title is a dict': base | {'title': {'t': 1}},
                 'steps is a string': base | {'steps': 'one step'}, 'steps holds a list': base | {'steps': [['x']]},
                 'source_url is a number': base | {'source_url': 5}, 'verification is a list': base | {'verification': ['x']},
                 'extra key': base | {'sandbox': 'x'}, 'http source': base | {'source_url': 'http://x.example/'},
                 'bad date': base | {'verified_on': '20.10.2026'}, 'task is a list': ['x']}
        for why, t in cases.items():
            self.assertTrue(cv2.validate_first_tasks({'touchstone': t}, set(CARDS)), why)  # must not raise

    def test_explorer_urls_without_userinfo_or_port(self):
        addr = '/address/0x' + 'f' * 40
        for bad in ('https://evil.com@basescan.org' + addr, 'https://user:pass@basescan.org' + addr, 'https://@basescan.org' + addr,
                    'https://basescan.org:444' + addr, 'https://basescan.org:443' + addr, 'https://basescan.org:' + addr):
            self.assertFalse(cv2.contract_url_ok(bad), bad)
            self.assertFalse(cv2.explorer_host(bad), bad)
            self.assertFalse(cv2.record_url_ok(bad), bad)
            self.assertFalse(cv2.record_url_ok(bad.replace(addr, '/tx/' + TX)), bad)
        self.assertTrue(cv2.contract_url_ok('https://basescan.org' + addr))
        self.assertEqual(cv2.source_level('https://basescan.org/tx/' + TX), 2)


class Wording(unittest.TestCase):
    def test_v2_vocabulary_is_positive(self):
        words = [cv2.NOT_RECORDED] + [x for lv in cv2.LEVELS.values() for x in lv[1:]] + \
                [t for t, vals in cv2.KB_FIELDS.values() for t in [t, *vals.values()]]
        self.assertEqual(cv2.negative_hits(' '.join(words)), [])
        self.assertEqual(cv2.negative_hits('This source is unverified'), ['unverified'])


class CurationEvents(unittest.TestCase):
    """Changes from the cards v2 curation files need their own events (they are not in the snapshot amendments)."""
    EV = [{'date': '2026-10-20', 'slug': 'a', 'type': 'relabelled'}, {'date': '2026-10-20', 'slug': 'b', 'type': 'corrected'},
          {'date': '2026-10-21', 'slug': 'c', 'type': 'corrected'}]

    def gaps(self, evo=None, kb=None, ft=None, events=None):
        return cv2.curation_event_gaps(evo or {}, kb or {}, ft or {}, self.EV if events is None else events, '2026-10-19')

    def test_covered_records_pass(self):
        self.assertEqual(self.gaps({'a': [{'source_url': 'https://a.example/', 'reviewed_on': '2026-10-20'}]},
                                   {'b': {'keys': {'value': 'operator', 'reviewed_on': '2026-10-20'}}},
                                   {'c': {'verified_on': '2026-10-21'}}), [])

    def test_changed_record_without_event_fails(self):
        g = self.gaps({'a': [{'source_url': 'https://a.example/', 'reviewed_on': '2026-10-22'}]})
        self.assertEqual(len(g), 1); self.assertIn('"relabelled" event for a on 2026-10-22', g[0])
        g = self.gaps(kb={'b': {'keys': {'value': 'operator', 'reviewed_on': '2026-10-22'}}})
        self.assertEqual(len(g), 1); self.assertIn('keys-and-books: b.keys', g[0])
        g = self.gaps(ft={'c': {'verified_on': '2026-10-20'}})
        self.assertEqual(len(g), 1); self.assertIn('first-tasks: c', g[0])

    def test_event_type_must_match(self):
        self.assertTrue(self.gaps(kb={'a': {'keys': {'value': 'operator', 'reviewed_on': '2026-10-20'}}}), 'a relabelled event is not a keys-and-books event')

    def test_keys_and_books_value_needs_a_date(self):
        g = self.gaps(kb={'b': {'keys': {'value': 'operator'}}})
        self.assertEqual(g, ['keys-and-books: b.keys reviewed_on: needs a YYYY-MM-DD date'])

    def test_records_before_the_log_start_need_no_event(self):
        self.assertEqual(self.gaps({'z': [{'source_url': 'https://z.example/', 'reviewed_on': '2026-10-18'}]}, events=[]), [])

    def test_published_curation_files_have_their_events(self):
        sys.path.insert(0, str(ROOT / 'atlas' / 'site'))
        import events as ev_
        self.assertEqual(cv2.curation_event_gaps(cv2.load_evidence_overrides(), cv2.load_keys_books(), cv2.load_first_tasks(),
                                                 ev_.load(), ev_.START), [])


if __name__ == '__main__':
    unittest.main()
