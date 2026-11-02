"""Transport is a seller claim, not a checked-out delivered price."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comparison import compare

SAMPLE = json.loads((Path(__file__).resolve().parents[1] / "examples" /
                     "comparison_three_laptops_FICTIONAL.json").read_text())


def claim(cost, method="courier", eta=(1, 3), url="https://example.org/shipping"):
    return {"method": method, "cost": cost,
            "currency": "PLN" if cost is not None else None,
            "eta_min_days": eta[0] if eta else None,
            "eta_max_days": eta[1] if eta else None,
            "source_url": url, "evidence_status": "SELLER_DECLARED"}


class FulfillmentTests(unittest.TestCase):
    def test_known_shipping_changes_conditional_comparison_not_payment(self):
        p = deepcopy(SAMPLE)
        p["offers"][0]["fulfillment"] = claim("25.00")
        p["offers"][1]["fulfillment"] = claim("0.00", eta=(0, 1))
        r = compare(p)
        a, b = r["comparison_summary"]["options"][:2]
        self.assertEqual(a["fulfillment"]["product_plus_shipping"], "925.00")
        self.assertEqual(b["fulfillment"]["product_plus_shipping"], "990.00")
        pair = r["comparison_summary"]["pairwise"][0]
        self.assertEqual(pair["right_minus_left_product_plus_shipping"], "65.00")
        self.assertEqual(pair["transport_comparison_status"],
                         "CONDITIONAL_SELLER_DECLARED_PRODUCT_PLUS_SHIPPING")
        self.assertEqual(pair["delivery_time_comparison"]["right_eta_days"], [0, 1])
        self.assertTrue(r["comparison_summary"]["no_forced_winner"])
        self.assertFalse(a["fulfillment"]["final_checkout_total_verified"])
        self.assertFalse(r["root"]["children"][-1]["details"]["eligible_for_payment"])
        self.assertTrue(any(n["kind"] == "fulfillment" for n in
                            r["root"]["children"][0]["children"]))

    def test_missing_cost_blocks_transport_ranking_even_with_eta(self):
        p = deepcopy(SAMPLE)
        p["offers"][0]["fulfillment"] = claim(None)
        p["offers"][1]["fulfillment"] = claim("0.00")
        pair = compare(p)["comparison_summary"]["pairwise"][0]
        self.assertIsNone(pair["right_minus_left_product_plus_shipping"])
        self.assertEqual(pair["transport_comparison_status"], "UNKNOWN_TRANSPORT_COST")

    def test_unidentified_shipping_method_can_be_declared_without_guessing(self):
        p = deepcopy(SAMPLE)
        p["offers"][0]["fulfillment"] = claim("17.99", method="unspecified_delivery")
        self.assertEqual(compare(p)["comparison_summary"]["options"][0]
                         ["fulfillment"]["product_plus_shipping"], "917.99")

    def test_pickup_never_assumes_free_travel(self):
        p = deepcopy(SAMPLE)
        p["offers"][0]["fulfillment"] = claim(None, method="pickup", eta=None)
        result = compare(p)["comparison_summary"]["options"][0]["fulfillment"]
        self.assertIsNone(result["product_plus_shipping"])
        self.assertIn("travel", result["interpretation"])

    def test_invalid_shipping_evidence_is_rejected(self):
        bad = [claim("-1"), claim("1.001"), claim("NaN"),
               {**claim("2.00"), "currency": "EUR"},
               {**claim("2.00"), "eta_min_days": 5, "eta_max_days": 2},
               {**claim("2.00"), "eta_min_days": None},
               {**claim("2.00"), "source_url": "http://127.0.0.1/"},
               {**claim("2.00"), "source_url": "https://user:pass@example.org"},
               {**claim("2.00"), "source_url": "https://127.0.0.1/shipping"},
               {**claim("2.00"), "evidence_status": "VERIFIED"},
               {**claim("0.00", method="pickup")},
               {**claim(None), "currency": "PLN"},
               {**claim("2.00"), "extra": "surprise"}]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                p = deepcopy(SAMPLE)
                p["offers"][0]["fulfillment"] = value
                compare(p)

    def test_absent_shipping_is_unknown_not_zero(self):
        r = compare(SAMPLE)
        self.assertTrue(all(o["fulfillment"]["shipping_cost"] is None
                            for o in r["comparison_summary"]["options"]))
        self.assertTrue(all(p["right_minus_left_product_plus_shipping"] is None
                            for p in r["comparison_summary"]["pairwise"]))


if __name__ == "__main__":
    unittest.main()
