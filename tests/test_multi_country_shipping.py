import unittest
from structured_shipping import shipping_claims
from shipping_comparison import conditional_shipping_comparison
from delivery_comparison import compare_delivery_windows


def detail(country, amount):
    return {'shippingDestination': {'addressCountry': country},
            'shippingRate': {'value': amount, 'currency': 'EUR'}}


class MultiCountryShippingTests(unittest.TestCase):
    def test_independent_country_rates(self):
        rates = shipping_claims({'shippingDetails': [detail('DE', '4'), detail('FR', '8')]})
        self.assertEqual(rates['DE']['shipping_cost'], '4.00')
        self.assertEqual(rates['FR']['shipping_cost'], '8.00')

    def test_country_list_same_rate(self):
        rates = shipping_claims({'shippingDetails': [detail(['DE', 'AT'], '5')]})
        self.assertEqual(set(rates), {'DE', 'AT'})

    def test_ambiguous_methods_rejected_for_country(self):
        rates = shipping_claims({'shippingDetails': [detail('DE', '4'), detail('DE', '5'), detail('FR', '8')]})
        self.assertNotIn('DE', rates)
        self.assertIn('FR', rates)

    def test_selected_country_controls_subtotal(self):
        first = {'price': '20', 'currency': 'EUR'}
        second = {'price': '18', 'currency': 'EUR'}
        a = {'structured_shipping_claims_by_country': shipping_claims({'shippingDetails': [detail('DE', '4'), detail('FR', '8')]})}
        b = {'structured_shipping_claims_by_country': shipping_claims({'shippingDetails': [detail('DE', '5'), detail('FR', '2')]})}
        de = conditional_shipping_comparison(first, second, a, b, True, 'DE')
        fr = conditional_shipping_comparison(first, second, a, b, True, 'FR')
        self.assertEqual(de['lower_declared_subtotal'], 'alternative')
        self.assertEqual(fr['lower_declared_subtotal'], 'alternative')
        self.assertEqual(de['selected_product_plus_shipping'], '24.00')
        self.assertEqual(fr['selected_product_plus_shipping'], '28.00')

    def test_delivery_country_gate_uses_rate_map(self):
        a = {'structured_shipping_claims_by_country': shipping_claims({'shippingDetails': [detail('DE', '4'), detail('FR', '8')]}),
             'structured_delivery_window_claim': {'status': 'SELLER_DECLARED_HANDLING_PLUS_TRANSIT_DAYS', 'min_days': 2, 'max_days': 4}}
        b = {'structured_shipping_claims_by_country': shipping_claims({'shippingDetails': [detail('DE', '5')]}),
             'structured_delivery_window_claim': {'status': 'SELLER_DECLARED_HANDLING_PLUS_TRANSIT_DAYS', 'min_days': 3, 'max_days': 5}}
        self.assertEqual(compare_delivery_windows(a, b, True, 'DE')['status'], 'SELLER_DECLARED_WINDOWS_NOT_GUARANTEED')
        self.assertEqual(compare_delivery_windows(a, b, True, 'FR')['status'], 'DESTINATION_NOT_ESTABLISHED_FOR_BOTH')
