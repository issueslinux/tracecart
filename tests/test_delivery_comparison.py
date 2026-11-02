import unittest
from delivery_comparison import compare_delivery_windows

def source(country, lo, hi):
    return {'structured_shipping_claim': {'status': 'SELLER_DECLARED_DESTINATION_CONDITIONAL', 'destination_country': country},
            'structured_delivery_window_claim': {'status': 'SELLER_DECLARED_HANDLING_PLUS_TRANSIT_DAYS', 'min_days': lo, 'max_days': hi}}

class DeliveryComparisonTests(unittest.TestCase):
    def test_qualified(self):
        r = compare_delivery_windows(source('PL', 3, 6), source('PL', 2, 4), True, 'PL')
        self.assertEqual(r['faster_declared_maximum'], 'alternative')
        self.assertEqual(r['status'], 'SELLER_DECLARED_WINDOWS_NOT_GUARANTEED')
    def test_country_mismatch(self):
        self.assertEqual(compare_delivery_windows(source('PL', 3, 6), source('DE', 2, 4), True, 'PL')['status'], 'DESTINATION_NOT_ESTABLISHED_FOR_BOTH')
    def test_unknown_country(self):
        self.assertEqual(compare_delivery_windows(source('PL', 1, 2), source('PL', 2, 3), True)['status'], 'BUYER_COUNTRY_REQUIRED')
    def test_non_equivalent(self):
        self.assertEqual(compare_delivery_windows(source('PL', 1, 2), source('PL', 2, 3), False, 'PL')['status'], 'PRODUCT_EQUIVALENCE_NOT_ESTABLISHED')
    def test_missing_window(self):
        a = source('PL', 1, 2)
        a['structured_delivery_window_claim']['status'] = 'UNKNOWN'
        self.assertEqual(compare_delivery_windows(a, source('PL', 2, 3), True, 'PL')['status'], 'COMPLETE_DELIVERY_WINDOWS_UNKNOWN')
