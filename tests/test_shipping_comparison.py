import copy
import unittest
from shipping_comparison import conditional_shipping_comparison
from test_live_offer_compare import BASE, META, SECOND, SELECTED
from live_offer_compare import compare_live_offer


def claim(cost, country="PL"):
    return {"status": "SELLER_DECLARED_DESTINATION_CONDITIONAL",
            "shipping_cost": cost, "currency": "PLN", "destination_country": country}


class ShippingComparisonTests(unittest.TestCase):
    def test_same_country_conditional_subtotals(self):
        left = {"structured_shipping_claim": claim("26.00")}
        right = {"structured_shipping_claim": claim("17.99")}
        r = conditional_shipping_comparison(SELECTED, SECOND, left, right, True, "PL")
        self.assertEqual(r["selected_product_plus_shipping"], "106.00")
        self.assertEqual(r["alternative_product_plus_shipping"], "89.99")
        self.assertEqual(r["difference"], "16.01")
        self.assertFalse(r["final_checkout_total_verified"])

    def test_country_required(self):
        r = conditional_shipping_comparison(SELECTED, SECOND, {}, {}, True)
        self.assertEqual(r["status"], "BUYER_COUNTRY_REQUIRED")

    def test_destination_mismatch(self):
        r = conditional_shipping_comparison(SELECTED, SECOND,
            {"structured_shipping_claim": claim("10", "DE")},
            {"structured_shipping_claim": claim("10")}, True, "PL")
        self.assertEqual(r["status"], "SHIPPING_UNKNOWN_OR_DESTINATION_MISMATCH")

    def test_equivalence_blocks_subtotals(self):
        r = conditional_shipping_comparison(SELECTED, SECOND, {}, {}, False, "PL")
        self.assertEqual(r["status"], "PRODUCT_EQUIVALENCE_NOT_ESTABLISHED")

    def test_live_comparison_requires_explicit_country(self):
        base = copy.deepcopy(BASE)
        base["source_intake"]["structured_shipping_claim"] = claim("26")
        meta = {**META, "structured_shipping_claim": claim("18")}
        args = (base, SELECTED, SECOND["merchant_url"])
        extractor = lambda _: (SECOND, meta)
        missing = compare_live_offer(*args, extractor=extractor)
        self.assertEqual(missing["live_competitor_comparison"]["conditional_shipping_comparison"]["status"], "BUYER_COUNTRY_REQUIRED")
        present = compare_live_offer(*args, extractor=extractor, buyer_country="PL")
        r = present["live_competitor_comparison"]["conditional_shipping_comparison"]
        self.assertEqual(r["status"], "SELLER_DECLARED_SUBTOTALS_NOT_CHECKOUT_VERIFIED")
        self.assertEqual(r["alternative_product_plus_shipping"], "90.00")


if __name__ == "__main__":
    unittest.main()
