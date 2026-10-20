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

    def test_level_3_public_transactions(self):
        # concrete public records with a checkable identifier: transaction hash, address or account, token contract, block
        for u in ('https://basescan.org/tx/' + self.TX, 'https://etherscan.io/address/0x' + 'a' * 40, 'https://solscan.io/account/' + self.SOL[:44],
                  'https://explorer.solana.com/tx/' + self.SOL, 'https://optimistic.etherscan.io/tx/' + self.TX,
                  'https://kitescan.ai/tx/' + self.TX,
                  'https://mempool.space/tx/' + 'ab' * 32, 'https://mempool.space/block/840000', 'https://basescan.org/token/0x' + 'e' * 40,
                  'https://www.basescan.org/tx/' + self.TX):
            self.assertEqual(cv2.source_level(u), 3, u)

    def test_level_3_needs_https_and_an_exact_explorer_host(self):
        # a host that merely contains "scan" or "explorer" is no explorer; subdomains of a listed explorer are not included
        for u in ('https://evilscan.example/tx/' + self.TX, 'https://x402scan.example/tx/0x' + 'b' * 64,
                  'https://my-explorer.example/address/0x' + 'a' * 40, 'https://basescan.org.evil.example/tx/' + self.TX,
                  'https://evil.basescan.org/tx/' + self.TX, 'https://notbasescan.org/tx/' + self.TX):
            self.assertLess(cv2.source_level(u), 3, u)
            self.assertEqual(cv2.source_level(u), 1, u)
        # the same record over http is not level 3
        for u in ('http://basescan.org/tx/' + self.TX, 'http://etherscan.io/address/0x' + 'a' * 40):
            self.assertLess(cv2.source_level(u), 3, u)
        self.assertIn('kitescan.ai', cv2.EXPLORER_HOSTS)
        self.assertTrue(all(h == h.lower() and not h.startswith('www.') for h in cv2.EXPLORER_HOSTS))

    def test_record_path_is_case_sensitive(self):
        for u in ('https://basescan.org/TX/' + self.TX, 'https://etherscan.io/ADDRESS/0x' + 'a' * 40, 'https://etherscan.io/Address/0x' + 'a' * 40):
            self.assertEqual(cv2.source_level(u), 2, u)  # an explorer page, but no lowercase record path: aggregate view

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

    def test_level_3_needs_the_explorers_own_route_and_network_format(self):
        """Round 8: level 3 only when the whole path is one of the explorer's own record routes (RECORD_ROUTES) with an identifier
        of that explorer's network; everything else on an explorer is level 2."""
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
            self.assertEqual(cv2.source_level(u), 3, u)
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
            self.assertEqual(cv2.claim_level(claim('https://basescan.org/tx/' + TX, kind=k)), 3)

    def test_card_level_is_highest_supported(self):
        c = {'slug': 'x', 'claims': [claim('https://a.example/'), claim('https://api.a.example/v1/stats', kind='economic_flow'),
                                     claim('https://basescan.org/tx/' + TX, outcome='contradicted')]}
        ev = cv2.card_evidence(c)
        self.assertEqual((ev['level'], ev['id'], ev['label'], ev['claims_counted']), (2, 'public_dashboard', 'public dashboard', 2))
        none = cv2.card_evidence({'slug': 'y', 'claims': [claim('https://a.example/', kind='description')]})
        self.assertEqual((none['level'], none['label']), (None, 'not recorded yet'))

    def test_annotate(self):
        x = cv2.annotate_claim(claim('https://basescan.org/tx/' + TX, kind='economic_flow'))
        self.assertEqual((x['evidence_level'], x['evidence_label']), (3, 'public transactions'))
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

    TOUCHSTONE_SHA = '8634b6564c8d6404987c5dfb3e380c6b39c6ebc81dcf8ae6224fe0cf3b50ba5f'

    def test_touchstone_checks_the_hash_before_running(self):
        t = cv2.load_first_tasks()['touchstone']
        self.assertNotIn('steps', t)  # its steps come from the structured code block
        self.assertEqual((t['code']['filename'], t['code']['sha256']), ('liveness-verify.py', self.TOUCHSTONE_SHA))
        self.assertEqual(cv2.code_safety_errors(t), [])
        steps = cv2.first_task(CARDS['touchstone'], cv2.load_first_tasks())['steps']
        self.assertIn('sandbox', steps[0].lower())                                      # 1 sandbox
        self.assertIn('curl -fsSLO https://touchstone.cv/liveness-verify.py', steps[1])  # 2 download
        self.assertIn(f'`echo "{self.TOUCHSTONE_SHA}  liveness-verify.py" | sha256sum -c -`', steps[2])  # 3 verify
        self.assertTrue(steps[3].startswith('Run `python3 liveness-verify.py --selftest`'))  # 4 run
        self.assertIn('rec_01m1hbq666jjjyfw7s6tf7h2rd', steps[4])
        self.assertEqual(len(steps), 5)
        pub = cv2.first_task(CARDS['touchstone'], cv2.load_first_tasks())
        self.assertEqual(pub['code'], {'url': 'https://touchstone.cv/liveness-verify.py', 'filename': 'liveness-verify.py',
                                       'sha256': self.TOUCHSTONE_SHA, 'run': ['python3 liveness-verify.py --selftest',
                                                                              'python3 liveness-verify.py rec_01m1hbq666jjjyfw7s6tf7h2rd']})
        self.assertEqual(pub['credit'], 'Contributed by reticuli')
        self.assertTrue(t.get('no_code'))

    def _task(self, **code):
        sha = 'c' * 64
        base = {'title': 'Try the tool', 'done_when': 'It prints OK.', 'contributed_by': 'demo', 'contributed_via': 'The Colony',
                'source_url': 'https://thecolony.ai/post/x', 'verified_by': 'Hark', 'verified_on': '2026-10-19',
                'verification': f'Script sha256 {sha}; self-test passed.'}
        c = {'sandbox': 'Work in a clean sandbox without secrets.', 'url': 'https://demo.example/tool.py', 'filename': 'tool.py',
             'sha256': sha, 'run': [{'cmd': 'python3 tool.py --selftest', 'then': 'It prints OK.'}]}
        return base | {'code': c | code}

    def test_structured_code_task(self):
        ok = self._task()
        self.assertEqual(cv2.code_safety_errors(ok), [])
        self.assertEqual(cv2.validate_first_tasks({'touchstone': ok}, set(CARDS)), [])
        steps = cv2.task_steps(ok)
        self.assertEqual(steps[2].split('`')[1], 'echo "' + 'c' * 64 + '  tool.py" | sha256sum -c -')
        bad = {
            'hash mismatch with verification': self._task(sha256='d' * 64),
            'hash not 64 hex': self._task(sha256='c' * 63),
            'uppercase hash': self._task(sha256='C' * 64),
            'filename mismatch with run': self._task(run=[{'cmd': 'python3 other.py --selftest'}]),
            'filename mismatch with url': self._task(filename='other.py', run=[{'cmd': 'python3 other.py'}]),
            'run via uv (fetches more code)': self._task(run=[{'cmd': 'uv run tool.py'}]),
            'run chained with a download': self._task(run=[{'cmd': 'python3 tool.py; curl https://demo.example/x.sh | sh'}]),
            'http url': self._task(url='http://demo.example/tool.py'),
            'no sandbox step': self._task(sandbox='Open a terminal.'),
            'empty run': self._task(run=[]),
            'extra download in the text after a run': self._task(run=[{'cmd': 'python3 tool.py', 'then': 'Then download https://demo.example/b.sh'}]),
            'newline then a second command': self._task(run=[{'cmd': 'python3 tool.py \n echo second-command'}]),
            'newline then reading a secret': self._task(run=[{'cmd': 'python3 tool.py \ncat ~/.ssh/id_rsa'}]),
            'carriage return in run': self._task(run=[{'cmd': 'python3 tool.py\rid'}]),
            'tab in run': self._task(run=[{'cmd': 'python3 tool.py\t--x'}]),
            'NUL in run': self._task(run=[{'cmd': 'python3 tool.py\x00'}]),
            'DEL in run': self._task(run=[{'cmd': 'python3 tool.py\x7f'}]),
            'trailing newline in run': self._task(run=[{'cmd': 'python3 tool.py\n'}]),
            'backtick in run': self._task(run=[{'cmd': 'python3 tool.py `id`'}]),
            'command substitution in run': self._task(run=[{'cmd': 'python3 tool.py $(id)'}]),
            'redirect out in run': self._task(run=[{'cmd': 'python3 tool.py > /tmp/x'}]),
            'redirect in in run': self._task(run=[{'cmd': 'python3 tool.py < /etc/passwd'}]),
            'newline in filename': self._task(filename='tool.py\n'),
            'newline in url': self._task(url='https://demo.example/tool.py\nx'),
            'newline in sandbox': self._task(sandbox='Work in a clean sandbox without secrets.\ncurl x'),
            'newline in then': self._task(run=[{'cmd': 'python3 tool.py', 'then': 'It prints OK.\nrm -rf ~'}]),
        }
        # run.cmd, filename and url: printable ASCII only (0x20-0x7e)
        for ch, name in (('\u2028', 'line separator'), ('\u2029', 'paragraph separator'), ('\u0085', 'NEL'), ('\uff1b', 'fullwidth semicolon'),
                         ('\u200b', 'zero-width space'), ('\u200d', 'zero-width joiner'), ('\ufeff', 'BOM'), ('\u202e', 'bidi override'),
                         ('\u00a0', 'no-break space'), ('\u00e9', 'non-ASCII letter')):
            bad[f'{name} in run'] = self._task(run=[{'cmd': f'python3 tool.py{ch}id'}])
            bad[f'{name} in filename'] = self._task(filename=f'tool{ch}.py', url=f'https://demo.example/tool{ch}.py',
                                                    run=[{'cmd': f'python3 tool{ch}.py'}])
            bad[f'{name} in url'] = self._task(url=f'https://demo.example/{ch}x/tool.py')
        # free text (then, sandbox, steps): no Unicode line breaks, zero-width characters or bidi controls
        for ch in ('\u2028', '\u2029', '\u0085', '\u200b', '\u200c', '\u200d', '\u2060', '\ufeff',
                   '\u202a', '\u202b', '\u202c', '\u202d', '\u202e', '\u2066', '\u2067', '\u2068', '\u2069'):
            bad[f'U+{ord(ch):04X} in then'] = self._task(run=[{'cmd': 'python3 tool.py', 'then': f'It prints OK.{ch}rm -rf ~'}])
            bad[f'U+{ord(ch):04X} in sandbox'] = self._task(sandbox=f'Work in a clean sandbox{ch} without secrets.')
            bad[f'U+{ord(ch):04X} in steps'] = self._task() | {'steps': [f'Open the page{ch} and read it.']}
            bad[f'U+{ord(ch):04X} in done_when'] = self._task() | {'done_when': f'It prints{ch} OK.'}
        for why, t in bad.items():
            self.assertTrue(cv2.code_safety_errors(t), why)
        two_hashes = self._task()
        two_hashes['verification'] += ' other file sha256 ' + 'd' * 64
        self.assertTrue(cv2.code_safety_errors(two_hashes))  # the hash of another file next to it is not accepted

    def test_wrong_types_are_errors_not_exceptions(self):
        cases = {
            'then is a list': self._task(run=[{'cmd': 'python3 tool.py', 'then': ['unexpected']}]),
            'then is a number': self._task(run=[{'cmd': 'python3 tool.py', 'then': 1}]),
            'cmd is a list': self._task(run=[{'cmd': ['python3', 'tool.py']}]),
            'run is a dict': self._task(run={'cmd': 'python3 tool.py'}),
            'run item is a string': self._task(run=['python3 tool.py']),
            'sandbox is a list': self._task(sandbox=['sandbox']),
            'url is a dict': self._task(url={'u': 'https://demo.example/tool.py'}),
            'filename is a number': self._task(filename=7),
            'sha256 is a list': self._task(sha256=['c' * 64]),
        }
        base = self._task()
        cases |= {
            'code is a list': base | {'code': ['x']},
            'code is a string': base | {'code': 'curl x'},
            'verification is a list': base | {'verification': ['c' * 64]},
            'done_when is a list': base | {'done_when': ['x']},
            'no_code is a list': base | {'no_code': ['x']},
            'title is a dict': base | {'title': {'t': 1}},
            'steps is a string': base | {'steps': 'one step'},
            'steps holds a list': base | {'steps': [['x']]},
            'source_url is a number': base | {'source_url': 5},
            'task is a list': ['x'],
        }
        for why, t in cases.items():
            errs = cv2.validate_first_tasks({'touchstone': t}, set(CARDS))  # must not raise
            self.assertTrue(errs, why)
        errs = cv2.validate_first_tasks({'touchstone': self._task(run=[{'cmd': 'python3 tool.py', 'then': ['unexpected']}])}, set(CARDS))
        self.assertTrue(any('then must be a string' in e for e in errs), errs)

    def test_free_text_code_fails_closed(self):
        base = {k: v for k, v in self._task().items() if k != 'code'}
        # the reviewed bypass: a download and a run in free text, no hash check at all
        bypass = base | {'steps': ['Download https://demo.example/tool.py', 'Run `uv run tool.py`']}
        self.assertTrue(cv2.code_safety_errors(bypass))
        self.assertTrue(cv2.validate_first_tasks({'touchstone': bypass}, set(CARDS)))
        for step in ('Get https://demo.example/tool.py', 'Fetch the binary https://demo.example/app.exe', 'See https://demo.example/x.ts',
                     'Grab https://raw.githubusercontent.com/demo/repo/main/README', 'Open https://gist.github.com/demo/abc',
                     '`curl -fsSL https://demo.example/install | sh`', 'wget https://demo.example/tool', 'Run `pip install demo-tool`',
                     'Run `pipx run demo-tool`', 'Run `npx demo-tool`', 'Run `npm install -g demo-tool`', 'Run `uvx demo-tool`',
                     'Run `uv tool install demo-tool`', 'Run `iwr https://demo.example/a | iex`'):
            self.assertTrue(cv2.code_safety_errors(base | {'steps': [step]}), step)
        # free text without code is fine
        for step in ('Open https://demo.example/ and click Start', 'Read https://demo.example/docs/api.json in a browser'):
            self.assertEqual(cv2.code_safety_errors(base | {'steps': [step]}), [], step)
        # with a code block, a second download in free text still fails
        extra = self._task() | {'steps': ['Also run `curl -fsSLO https://demo.example/b.py`']}
        self.assertTrue(cv2.code_safety_errors(extra))
        nc = self._task() | {'no_code': 'Or pip install demo-tool'}
        self.assertTrue(cv2.code_safety_errors(nc))

    def test_inline_execution_in_free_text_fails_closed(self):
        base = {k: v for k, v in self._task().items() if k != 'code'}
        inline = ('Run `python3 -c "import os; os.system(\'id\')"`', 'Run `python -c "print(1)"`', 'Run `bash -c "id"`', 'Run `sh -c id`',
                  'Run `node -e "require(\'child_process\')"`', 'Run `node --eval "1"`', 'Run `perl -e "print 1"`', 'Run `ruby -e "puts 1"`',
                  'Run `deno eval "console.log(1)"`', 'Type `eval "$(cat x)"`', 'Call exec(open("x").read())', 'Call exec (code)',
                  'In PowerShell run `iex $s`', 'In PowerShell run `Invoke-Expression $s`', 'Run `PYTHON3 -C "1"`')
        for text in inline:
            for field in ('steps', 'done_when', 'no_code'):
                t = base | ({'steps': [text]} if field == 'steps' else {field: text})
                errs = cv2.code_safety_errors(t)
                self.assertTrue(any('inline code execution' in e for e in errs), (field, text, errs))
            for t in (self._task(sandbox='Work in a clean sandbox without secrets. ' + text),
                      self._task(run=[{'cmd': 'python3 tool.py', 'then': text}])):
                self.assertTrue(any('inline code execution' in e for e in cv2.code_safety_errors(t)), text)
            self.assertTrue(cv2.validate_first_tasks({'touchstone': base | {'steps': [text]}}, set(CARDS)), text)
        # ordinary words are fine
        for text in ('Open the evaluation page and read the score', 'The executor prints OK', 'Read the shell section of the docs',
                     'Check the node list on the page'):
            self.assertEqual(cv2.code_safety_errors(base | {'steps': [text]}), [], text)

    def test_inline_execution_is_one_structural_rule(self):
        """Round 5: interpreter or shell (path, env, version, .exe) + whitespace + inline-code flag, in every human-text field."""
        base = {k: v for k, v in self._task().items() if k != 'code'}
        inline = ('Run `python3.12 -c "1"`', 'Run `pwsh -c "1"`', 'Run `powershell -Command "1"`', 'Run `/usr/bin/env python3 -c "1"`',
                  'Run `zsh -c id`', 'Run `python3\t-c "1"`', 'Run `bash  -c id`', 'Run `/usr/bin/python3 -c 1`',
                  'Run `C:\\Python312\\python.exe -c 1`', 'Run `cmd /c dir`', 'Run `cmd.exe /K dir`', 'Run `php -r "echo 1;"`',
                  'Run `osascript -e "beep"`', 'Run `Rscript -e 1`', 'Run `lua5.4 -e "print(1)"`', 'Run `bun -e 1`', 'Run `deno eval 1`',
                  'Run `pwsh -NoProfile -EncodedCommand ZQBjAGgAbwA=`', 'Run `powershell -enc ZQBjAGgAbwA=`', 'Run `nodejs --eval 1`',
                  'Run `pypy3 -c 1`', 'Run `py -c 1`', 'Run `ksh -c id`', 'Run `fish -c id`', 'Run `dash -c id`', 'Run `tclsh -c 1`',
                  'Run `perl -E "say 1"`', 'Run `PwSh -COMMAND 1`', 'Run `python3 -u -c 1`', 'Call exec(code)')
        fields = ('title', 'verification', 'steps', 'done_when', 'no_code', 'contributed_by', 'contributed_via', 'verified_by')
        for text in inline:
            for field in fields:
                t = base | ({'steps': [text]} if field == 'steps' else {field: text})
                errs = cv2.code_safety_errors(t)
                self.assertTrue(any('inline code execution' in e for e in errs), (field, text, errs))
                self.assertTrue(cv2.validate_first_tasks({'touchstone': t}, set(CARDS)), (field, text))
            for t in (self._task(sandbox='Work in a clean sandbox without secrets. ' + text),
                      self._task(run=[{'cmd': 'python3 tool.py', 'then': text}])):
                self.assertTrue(any('inline code execution' in e for e in cv2.code_safety_errors(t)), text)
        # prose that names a tool, a flag or a word alone is fine
        for text in ('The executor prints OK', 'Calling exec() is not needed here', 'An exec( ) call is not needed', 'Evaluate the result',
                     'Python is used for the check', 'The -c flag of the checker is optional', 'Open the evaluation page',
                     'Check it with sha256sum -c and read the output', 'A bash script is not needed', 'Use the node list',
                     'Run `python3 tool.py --selftest`', 'Read the cmd output'):
            for field in fields:
                t = base | ({'steps': [text]} if field == 'steps' else {field: text})
                self.assertEqual(cv2.code_safety_errors(t), [], (field, text))

    def test_inline_execution_without_option_parsing(self):
        """Round 7: an interpreter token and an inline-code flag ANYWHERE in the same field fail, whatever stands between them."""
        base = {k: v for k, v in self._task().items() if k != 'code'}
        inline = ('Run `python -W ignore -c "1"`', 'Run `python3 -X dev -W error -c 1`', 'Run `node --input-type module -e "1"`',
                  'Run `powershell -ExecutionPolicy Bypass -Command "1"`', 'Run `pwsh -NoLogo -NonInteractive -NoProfile -c 1`',
                  'Run `bash -lc id`', 'Run `sh -ec id`', 'Run `python -cprint(1)`', 'Run `python3 -c"1"`', "Run `php -r'echo 1;'`",
                  'Run `node -p 1`', 'Run `node --eval=1`', 'Run `perl -pe 1 file`', 'Run `ruby -rjson -e 1`', 'Run `cmd.exe /c dir`',
                  'Run `python3 - <<EOF` and paste the code', 'Use -c with python3', '-e is the flag; the interpreter is node',
                  'Run `"/usr/bin/python3" "-c" "1"`', 'Run `env -i python3 -I -c 1`', 'Run `PYTHON3.12.EXE -W ignore -C 1`',
                  'Run `deno run -A --eval 1`', 'Run `C:\\Python312\\python.exe -B -c 1`')
        fields = ('title', 'verification', 'steps', 'done_when', 'no_code', 'contributed_by', 'contributed_via', 'verified_by')
        for text in inline:
            self.assertTrue(cv2.inline_exec(text), text)
            for field in fields:
                t = base | ({'steps': [text]} if field == 'steps' else {field: text})
                self.assertTrue(any('inline code execution' in e for e in cv2.code_safety_errors(t)), (field, text))
            for t in (self._task(sandbox='Work in a clean sandbox without secrets. ' + text),
                      self._task(run=[{'cmd': 'python3 tool.py', 'then': text}])):
                self.assertTrue(any('inline code execution' in e for e in cv2.code_safety_errors(t)), text)
        # fail closed by design: prose naming an interpreter and an inline-code flag in one field is rejected too
        for text in ('The php page shows -c as an option', 'Python is fine; the checker takes -e'):
            self.assertTrue(cv2.inline_exec(text), text)
        # a flag without an interpreter, an interpreter without a flag, and look-alike words pass
        for text in ('Check it with sha256sum -c and read the output', 'Run `python3 tool.py --selftest`', 'Read python.org and node.js docs',
                     'Open the dashboard', 'The -c flag of the checker is optional', 'Install Python 3 in a fresh venv',
                     'Run `python3 tool.py rec_01m1hbq666jjjyfw7s6tf7h2rd`', 'Use a .py file', 'Send an e-mail to the cmd-line team'):
            self.assertFalse(cv2.inline_exec(text), text)

    def test_inline_execution_eval_and_stdin(self):
        """Round 8: `eval` in any form, and an interpreter token with a pipe, an input redirect or `exec` anywhere, fail."""
        base = {k: v for k, v in self._task().items() if k != 'code'}
        inline = ('Call eval("print(1)")', 'Call eval(code)', "Type `eval('1')`", 'Use EVAL(x)', "Run `printf 'puts 1' | ruby`",
                  'Run `echo 1 | perl`', 'Run `cat x.php | php`', 'Run `echo 1|lua`', 'Run `ruby < script.txt`', 'Run `perl <x`',
                  'Run `cat x | /usr/bin/env tclsh`', 'Run `Rscript < x.R`', 'Run `osascript < x`', 'Run `echo 1 | deno`',
                  'Run `python3` then exec the pasted text', 'Pipe the text into node: `| node`')
        fields = ('title', 'verification', 'steps', 'done_when', 'no_code', 'contributed_by', 'contributed_via', 'verified_by')
        for text in inline:
            self.assertTrue(cv2.inline_exec(text), text)
            for field in fields:
                t = base | ({'steps': [text]} if field == 'steps' else {field: text})
                self.assertTrue(any('inline code execution' in e for e in cv2.code_safety_errors(t)), (field, text))
            for t in (self._task(sandbox='Work in a clean sandbox without secrets. ' + text),
                      self._task(run=[{'cmd': 'python3 tool.py', 'then': text}])):
                self.assertTrue(any('inline code execution' in e for e in cv2.code_safety_errors(t)), text)
        # fail closed by design: prose with an interpreter name and a pipe or "<" in one field is rejected too
        for text in ('Python | fine', 'The ruby page lists a < b'):
            self.assertTrue(cv2.inline_exec(text), text)
        # a pipe or redirect without an interpreter, and evaluate/executor words, pass
        for text in ('Check it with `sha256sum -c` | read the output', 'Open the page < 1 minute', 'Evaluate the result',
                     'The executor prints OK', 'Read the medieval page', 'Run `python3 tool.py --selftest`'):
            self.assertFalse(cv2.inline_exec(text), text)

    def test_published_first_tasks_still_pass(self):
        tasks = cv2.load_first_tasks()
        self.assertTrue(tasks)
        for slug, t in tasks.items():
            self.assertEqual(cv2.code_safety_errors(t), [], slug)
            texts = [*(t.get('steps') or []), t['code']['sandbox'], *[r.get('then', '') for r in t['code']['run']]] if t.get('code') else []
            texts += [t.get(k) or '' for k in cv2.TEXT_FIELDS]
            self.assertFalse(any(cv2.inline_exec(x) for x in texts), slug)

    def test_hidden_unicode_in_title_and_verification(self):
        base = {k: v for k, v in self._task().items() if k != 'code'}
        for field in ('title', 'verification'):
            for ch in ('\u2028', '\u2029', '\u0085', '\u200b', '\u200d', '\u2060', '\ufeff', '\u202e', '\u2066'):
                errs = cv2.code_safety_errors(base | {field: 'Check the clock' + ch + 'now'})
                self.assertTrue(any('Unicode line separators' in e for e in errs), (field, repr(ch)))
        self.assertEqual(cv2.code_safety_errors(base | {'title': 'Check the clock', 'verification': 'Ran to exit code 0'}), [])

    def test_explorer_urls_without_userinfo_or_port(self):
        addr = '/address/0x' + 'f' * 40
        for bad in ('https://evil.com@basescan.org' + addr, 'https://user:pass@basescan.org' + addr, 'https://@basescan.org' + addr,
                    'https://basescan.org:444' + addr, 'https://basescan.org:443' + addr, 'https://basescan.org:' + addr):
            self.assertFalse(cv2.contract_url_ok(bad), bad)
            self.assertFalse(cv2.explorer_host(bad), bad)
            self.assertNotEqual(cv2.source_level(bad), 3, bad)
            self.assertNotEqual(cv2.source_level(bad.replace(addr, '/tx/' + TX)), 3, bad)
        self.assertTrue(cv2.contract_url_ok('https://basescan.org' + addr))
        self.assertEqual(cv2.source_level('https://basescan.org/tx/' + TX), 3)


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
        g = self.gaps(kb={'b': {'books': {'value': 'public_dashboard', 'reviewed_on': '2026-10-22'}}})
        self.assertEqual(len(g), 1); self.assertIn('keys-and-books: b.books', g[0])
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
