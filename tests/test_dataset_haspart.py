"""Google Dataset structured data: hasPart / isPartOf take only a URL or a Dataset (with name and a 50..5000 char description).
GSC flagged "Invalid object type for field hasPart" on 2026-10-18 for the decision log's ItemList; check.py now fails on it."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'atlas' / 'site'))
import build  # noqa: E402
import check  # noqa: E402

DESC = 'A sub-dataset description that is long enough for Google Dataset Search rules.'


class FakeSite:
    base = '/atlas'
    cfg = {'data_licence': 'CC BY 4.0'}

    @staticmethod
    def abs(p):
        return 'https://commonworld.one' + p


def ds(**kw):
    return {'@context': 'https://schema.org', '@type': 'Dataset', 'name': 'X', 'description': DESC, **kw}


class DatasetHasPart(unittest.TestCase):
    def test_itemlist_fails(self):
        self.assertTrue(check.dataset_haspart_fails('/p/', [ds(hasPart={'@type': 'ItemList', 'itemListElement': []})]))

    def test_nested_dataset_inside_page_is_checked(self):
        page = {'@type': 'CollectionPage', 'mainEntity': ds(hasPart=[{'@type': 'WebPage', 'url': 'https://e.org/'}])}
        self.assertTrue(check.dataset_haspart_fails('/p/', [page]))

    def test_dataset_and_url_pass(self):
        ok = ds(hasPart=[{'@type': 'Dataset', 'name': 'Sub', 'description': DESC}, 'https://commonworld.one/atlas/'])
        self.assertEqual(check.dataset_haspart_fails('/p/', [ok]), [])

    def test_sub_dataset_needs_description(self):
        self.assertTrue(check.dataset_haspart_fails('/p/', [ds(hasPart={'@type': 'Dataset', 'name': 'Sub', 'description': 'short'})]))

    def test_no_haspart_passes(self):
        self.assertEqual(check.dataset_haspart_fails('/p/', [ds()]), [])

    def test_decision_log_ld_is_valid(self):
        rows = build.decisions_newest_first(build.load_decisions()[0])
        ld = build.decisions_ld(FakeSite, rows)
        self.assertEqual(check.dataset_haspart_fails('/atlas/decisions/', [ld]), [])
        self.assertEqual(ld['mainEntity']['@type'], 'Dataset')


if __name__ == '__main__':
    unittest.main()
