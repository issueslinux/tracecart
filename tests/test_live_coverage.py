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

class EvidenceDiagnosticsTests(unittest.TestCase):
    def test_missing_extraction_not_claimed_missing_from_page(self):
        result = probe(['https://example.org/item'], lambda url: (
            {'title': 'Example', 'price': '2'},
            {'structured_shipping_claims_by_country': {},
             'structured_delivery_windows_by_country': {}}))
        row = result['cases'][0]
        self.assertEqual(row['shipping_diagnosis'], 'UNDETERMINED_ABSENT_OR_UNRECOGNIZED')
        self.assertEqual(row['delivery_diagnosis'], 'UNDETERMINED_ABSENT_OR_UNRECOGNIZED')

    def test_unavailable_not_misclassified(self):
        def blocked(url):
            raise ValueError('Access denied')
        row = probe(['https://example.org/item'], blocked)['cases'][0]
        self.assertEqual(row['shipping_diagnosis'], 'NOT_ASSESSED_PAGE_UNAVAILABLE')

class MerchantDiversityTests(unittest.TestCase):
    def test_single_merchant_is_not_market_coverage(self):
        result = probe(['https://example.org/a', 'https://example.org/b'],
                       lambda url: ({'title': 'Product'}, {}))
        self.assertEqual(result['merchant_count'], 1)
        self.assertEqual(result['merchant_sample_sizes'], {'example.org': 2})
        self.assertEqual(result['sample_warning'], 'SINGLE_MERCHANT_NOT_MARKET_COVERAGE')

    def test_multiple_hosts_still_nonrandom(self):
        result = probe(['https://example.org/a', 'https://example.com/b'],
                       lambda url: ({'title': 'Product'}, {}))
        self.assertEqual(result['merchant_count'], 2)
        self.assertEqual(result['sample_warning'], 'NON_RANDOM_SAMPLE_NOT_MARKET_COVERAGE')

    def test_http_denial_status_is_preserved(self):
        from product_intake import SourceAccessDenied
        def denied(url):
            raise SourceAccessDenied(403)
        result = probe(['https://example.org/a'], denied)
        self.assertEqual(result['cases'][0]['status'], 'HTTP_403')
