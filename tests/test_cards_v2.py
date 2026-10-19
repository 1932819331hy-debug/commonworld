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
                  'https://kitescan.ai/api/v2/addresses/0x' + 'd' * 40, 'https://kitescan.ai/tx/' + self.TX,
                  'https://mempool.space/tx/' + 'ab' * 32, 'https://mempool.space/block/840000', 'https://basescan.org/token/0x' + 'e' * 40,
                  'https://x402scan.example/tx/0x' + 'b' * 64):
            self.assertEqual(cv2.source_level(u), 3, u)

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
        }
        for why, v in bad.items():
            self.assertTrue(cv2.validate_keys_books({'demo': {'keys': v}}, {'demo': self.CARD}, orgs=[]), why)
        self.assertTrue(cv2.validate_keys_books({'demo': {'books': {'value': 'public_dashboard', 'basis': 'operator_says',
                                                                    'source_url': 'https://api.demo.example/v1/payouts', 'quote': 'paid_usdc'}}},
                                                {'demo': self.CARD}, orgs=[]))

    def test_people_names_an_organization(self):
        card = {'slug': 'demo', 'claims': [claim('https://demo.example/about', kind='operator', quote='Operated by Demo Labs, built by Ada Lovelace')]}
        org = {'demo': {'people': {'value': 'named', 'names': 'Demo Labs', 'source_url': 'https://demo.example/about', 'quote': 'Operated by Demo Labs'}}}
        self.assertEqual(cv2.validate_keys_books(org, {'demo': card}, orgs=['Demo Labs']), [])
        note = {'demo': {'people': org['demo']['people'] | {'names': 'Demo Labs (acquired by Big Co)'}}}
        self.assertEqual(cv2.validate_keys_books(note, {'demo': card}, orgs=['Demo Labs']), [])
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

    def test_touchstone_checks_the_hash_before_running(self):
        t = cv2.load_first_tasks()['touchstone']
        steps = t['steps']
        dl = next(i for i, s in enumerate(steps) if cv2.DOWNLOAD_STEP.search(s))
        chk = next(i for i, s in enumerate(steps) if 'sha256sum -c' in s)
        run = next(i for i, s in enumerate(steps) if '--selftest' in s)
        self.assertLess(dl, chk)
        self.assertLess(chk, run)
        self.assertIn('8634b6564c8d6404987c5dfb3e380c6b39c6ebc81dcf8ae6224fe0cf3b50ba5f', steps[chk])
        self.assertIn('sandbox', steps[0].lower())
        self.assertTrue(t.get('no_code'))

    def test_download_and_run_needs_a_hash_step(self):
        sha = 'c' * 64
        dl, run = 'Download https://demo.example/tool.py', 'Run `python3 tool.py --selftest`.'
        chk = f'Check it: `echo "{sha}  tool.py" | sha256sum -c -`; go on only when it prints `tool.py: OK`.'
        ver = f'Script sha256 {sha}'
        self.assertEqual(cv2.code_safety_errors([dl, chk, run], ver), [])
        self.assertEqual(cv2.code_safety_errors(['Open https://demo.example/ and click Start'], ver), [])  # no code to run
        self.assertTrue(cv2.code_safety_errors([dl, run], ver))  # no hash check
        self.assertTrue(cv2.code_safety_errors([dl, run, chk], ver))  # hash check after the run
        self.assertTrue(cv2.code_safety_errors([chk, dl, run], ver))  # hash check before the download
        self.assertTrue(cv2.code_safety_errors([dl, chk, run], 'Script sha256 ' + 'd' * 64))  # a different hash than the verified one
        self.assertTrue(cv2.code_safety_errors(['`curl -fsSLO https://demo.example/x.sh`', '`bash x.sh`'], ver))
        base = cv2.load_first_tasks()['touchstone']
        no_check = base | {'steps': [s for s in base['steps'] if 'sha256sum' not in s]}
        self.assertTrue(cv2.validate_first_tasks({'touchstone': no_check}, set(CARDS)))


class Wording(unittest.TestCase):
    def test_v2_vocabulary_is_positive(self):
        words = [cv2.NOT_RECORDED] + [x for lv in cv2.LEVELS.values() for x in lv[1:]] + \
                [t for t, vals in cv2.KB_FIELDS.values() for t in [t, *vals.values()]]
        self.assertEqual(cv2.negative_hits(' '.join(words)), [])
        self.assertEqual(cv2.negative_hits('This source is unverified'), ['unverified'])


if __name__ == '__main__':
    unittest.main()
