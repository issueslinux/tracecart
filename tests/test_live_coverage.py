import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'benchmarks'))
from live_coverage import probe

class LiveCoverageTests(unittest.TestCase):
    def test_fetched_claims(self):
        def fake(url):
            return ({'title': 'Sample', 'price': '5'},
                    {'structured_shipping_claims_by_country': {'DE': {}},
                     'structured_delivery_windows_by_country': {},
                     'page_sha256': 'a' * 64, 'retrieved_at': '2026-11-02T00:00:00Z'})
        result = probe(['https://example.org/product'], fake)
        self.assertEqual(result['fetched'], 1)
        self.assertEqual(result['counts']['shipping'], 1)
        self.assertEqual(result['counts']['delivery'], 0)

    def test_denied_is_not_success(self):
        def denied(url):
            raise ValueError('robots.txt denied')
        result = probe(['https://example.org/product'], denied)
        self.assertEqual(result['fetched'], 0)
        self.assertEqual(result['cases'][0]['status'], 'UNAVAILABLE_ValueError')
        self.assertEqual(result['counts']['price'], 0)

    def test_private_url_rejected_before_fetch(self):
        calls = []
        with self.assertRaises(ValueError):
            probe(['https://127.0.0.1/private'], lambda url: calls.append(url))
        self.assertEqual(calls, [])
