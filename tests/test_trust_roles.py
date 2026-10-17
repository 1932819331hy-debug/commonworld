import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'atlas' / 'tools'))
import trust_check as tc

ROLES = {'actions': ['remove', 'restore'], 'actors': [{'id': 'nerd27dk'}, {'id': 'hark'}, {'id': 'codex'}, {'id': 'continuum'}]}
REMOVE = {'action': 'remove', 'slug': 'x', 'host': 'x.example', 'by': 'hark', 'on': '2026-10-17', 'reason': 'GSB flag', 'evidence': 'https://e.example/1'}
RESTORE = {'action': 'restore', 'slug': 'x', 'host': 'x.example', 'by': 'codex', 'on': '2026-10-20', 'reason': 'flag cleared', 'evidence': 'https://e.example/2', 'recheck': 'clean'}


def report(status):
    return {'hosts': {}, 'removed_hosts': {'x.example': {'status': status}}}


class TrustDecisions(unittest.TestCase):
    def test_repository_data_passes(self):
        self.assertEqual(tc.main(), [])

    def test_all_four_admins_can_act(self):
        roles = json.load(open(ROOT / 'atlas' / 'data' / 'trust-roles.json'))
        self.assertEqual({a['id'] for a in roles['actors']}, {'nerd27dk', 'hark', 'codex', 'continuum'})
        self.assertEqual(set(roles['actions']), {'remove', 'restore'})

    def test_removed_entry_needs_a_remove_decision(self):
        f = tc.check(ROLES, {'removed': [{'slug': 'x', 'host': 'x.example'}], 'decisions': []}, report('flagged'))
        self.assertTrue(any('no remove decision' in x for x in f))
        self.assertEqual(tc.check(ROLES, {'removed': [{'slug': 'x', 'host': 'x.example'}], 'decisions': [REMOVE]}, report('flagged')), [])

    def test_unknown_actor_fails(self):
        f = tc.check(ROLES, {'removed': [{'slug': 'x', 'host': 'x.example'}], 'decisions': [REMOVE | {'by': 'stranger'}]}, report('flagged'))
        self.assertTrue(any("'stranger' is not in trust-roles.json" in x for x in f))

    def test_restore_needs_clean_recheck_and_clean_report(self):
        ok = {'removed': [], 'decisions': [REMOVE, RESTORE]}
        self.assertEqual(tc.check(ROLES, ok, report('clean')), [])
        self.assertTrue(any('must be clean' in x for x in tc.check(ROLES, ok, report('flagged'))))
        self.assertTrue(any('recheck "clean"' in x for x in tc.check(ROLES, {'removed': [], 'decisions': [REMOVE, RESTORE | {'recheck': None}]}, report('clean'))))

    def test_restored_slug_must_leave_removed_list(self):
        f = tc.check(ROLES, {'removed': [{'slug': 'x', 'host': 'x.example'}], 'decisions': [REMOVE, RESTORE]}, report('clean'))
        self.assertTrue(any('still listed under removed' in x for x in f))

    def test_evidence_must_be_https(self):
        f = tc.check(ROLES, {'removed': [{'slug': 'x', 'host': 'x.example'}], 'decisions': [REMOVE | {'evidence': 'http://e.example'}]}, report('flagged'))
        self.assertTrue(any('https' in x for x in f))


if __name__ == '__main__':
    unittest.main()
