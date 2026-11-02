import unittest
from structured_delivery import delivery_windows_by_country
from delivery_comparison import compare_delivery_windows
from structured_shipping import shipping_claims


def detail(country, lo, hi):
    return {'shippingDestination': {'addressCountry': country},
            'shippingRate': {'value': '4', 'currency': 'EUR'},
            'deliveryTime': {'handlingTime': {'minValue': 1, 'maxValue': 2, 'unitCode': 'DAY'},
                             'transitTime': {'minValue': lo, 'maxValue': hi, 'unitCode': 'DAY'}}}


class MultiCountryDeliveryTests(unittest.TestCase):
    def test_distinct_country_windows(self):
        offer = {'shippingDetails': [detail('DE', 2, 3), detail('FR', 5, 7)]}
        windows = delivery_windows_by_country(offer)
        self.assertEqual((windows['DE']['min_days'], windows['DE']['max_days']), (3, 5))
        self.assertEqual((windows['FR']['min_days'], windows['FR']['max_days']), (6, 9))

    def test_country_array(self):
        self.assertEqual(set(delivery_windows_by_country({'shippingDetails': detail(['DE', 'AT'], 2, 3)})), {'DE', 'AT'})

    def test_ambiguous_method_excluded(self):
        windows = delivery_windows_by_country({'shippingDetails': [detail('DE', 2, 3), detail('DE', 4, 5), detail('FR', 1, 2)]})
        self.assertNotIn('DE', windows)
        self.assertIn('FR', windows)

    def test_missing_timing_excluded(self):
        d = detail('DE', 2, 3)
        del d['deliveryTime']['handlingTime']
        self.assertEqual(delivery_windows_by_country({'shippingDetails': d}), {})

    def test_comparison_uses_destination_window(self):
        def source(de, fr):
            offer = {'shippingDetails': [detail('DE', *de), detail('FR', *fr)]}
            return {'structured_shipping_claims_by_country': shipping_claims(offer),
                    'structured_delivery_windows_by_country': delivery_windows_by_country(offer)}
        a = source((2, 3), (5, 7))
        b = source((3, 4), (1, 2))
        self.assertEqual(compare_delivery_windows(a, b, True, 'DE')['faster_declared_maximum'], 'selected')
        self.assertEqual(compare_delivery_windows(a, b, True, 'FR')['faster_declared_maximum'], 'alternative')
