import copy
import unittest
from multi_offer_compare import compare_live_offers
from test_live_offer_compare import BASE, META, SECOND, SELECTED


def claim(value):
    return {"status": "SELLER_DECLARED_DESTINATION_CONDITIONAL",
            "shipping_cost": value, "currency": "PLN", "destination_country": "PL"}


class BuyerCountryRoutingTests(unittest.TestCase):
    def test_single_offer_country_propagation(self):
        base = copy.deepcopy(BASE)
        base["source_intake"]["structured_shipping_claim"] = claim("10")
        meta = {**META, "structured_shipping_claim": claim("5")}
        result = compare_live_offers(base, SELECTED, [SECOND["merchant_url"]],
                                     extractor=lambda _: (SECOND, meta), buyer_country="PL")
        c = result["live_competitor_comparison"]["conditional_shipping_comparison"]
        self.assertEqual(c["status"], "SELLER_DECLARED_SUBTOTALS_NOT_CHECKOUT_VERIFIED")
        self.assertEqual(c["alternative_product_plus_shipping"], "77.00")

    def test_missing_country_does_not_assume_poland(self):
        base = copy.deepcopy(BASE)
        base["source_intake"]["structured_shipping_claim"] = claim("10")
        meta = {**META, "structured_shipping_claim": claim("5")}
        result = compare_live_offers(base, SELECTED, [SECOND["merchant_url"]],
                                     extractor=lambda _: (SECOND, meta))
        self.assertEqual(result["live_competitor_comparison"]["conditional_shipping_comparison"]["status"],
                         "BUYER_COUNTRY_REQUIRED")


if __name__ == "__main__":
    unittest.main()
