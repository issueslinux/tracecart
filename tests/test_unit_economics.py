"""Meaningful result: normalized wash economics from source-declared facts."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unit_economics import unit_cost, extract_wash_count


class UnitEconomicsTests(unittest.TestCase):
    def test_actual_amazon_ariel_selected_price_and_100_washes(self):
        # Source snapshot retrieved from Amazon, not a fabricated merchant.
        report=json.loads((Path(__file__).resolve().parents[1] /
            "examples/live_amazon_ariel_url_only_2026-11-01.json").read_text())
        product=report["root"]["details"]["selected_cart_item"]
        self.assertEqual(product["price"],"76.99")
        calc=unit_cost(product, "laundry_detergent")
        self.assertEqual(calc["washes_declared_in_title"],100)
        self.assertEqual(calc["cost_per_wash"],"0.7699")
        self.assertEqual(calc["currency"],"PLN")
        self.assertEqual(calc["status"],"CALCULATED_FROM_SELLER_CLAIMS")

    def test_actual_allegro_url_has_count_but_no_price(self):
        product={"title":"persil color pulver proszek do prania 4,5 kg 75 pran niemcy",
                 "price":None,"currency":None}
        calc=unit_cost(product,"laundry_detergent")
        self.assertEqual(calc["washes_declared_in_title"],75)
        self.assertIsNone(calc["cost_per_wash"])
        self.assertEqual(calc["status"],"COUNT_FROM_TITLE_UNVERIFIED")

    def test_no_synthetic_conclusions_from_pack_weight(self):
        c=unit_cost({"title":"Proszek do prania 5 kg","price":"56.90",
                     "currency":"PLN"},"laundry_detergent")
        self.assertIsNone(c["cost_per_wash"])
        self.assertEqual(c["status"],"NOT_DECLARED")

    def test_other_laundry_languages(self):
        for title,n in [
            ("Persil 75 prań",75),("Ariel 100 washes",100),
            ("Persil 30 wash loads",30),("Persil 45 Doses 3150g",45),
            ("Ariel 42 lavages",42),("Powder 55 Waschgänge",55)
        ]:
            with self.subTest(title=title):
                self.assertEqual(extract_wash_count(title)["washes"],n)

    def test_ambiguous_claims_not_used_to_create_price(self):
        c=unit_cost({"title":"Persil 30 prań, promo 40 prań",
                     "price":"49.99","currency":"PLN"},"laundry_detergent")
        self.assertIsNone(c["cost_per_wash"])
        self.assertEqual(c["status"],"AMBIGUOUS_DECLARATION")

    def test_laptop_not_laundering_economics(self):
        self.assertEqual(unit_cost({"title":"ThinkPad 100 loads",
            "price":"999","currency":"PLN"},"laptop")["status"],"NOT_APPLICABLE")

    def test_nonfinite_negative_price_denied(self):
        for v in ["NaN","-5","Infinity","oops"]:
            with self.subTest(v=v):
                c=unit_cost({"title":"Ariel 100 prań","price":v,
                             "currency":"PLN"},"laundry_detergent")
                self.assertIsNone(c["cost_per_wash"])

    def test_illustrative_75_wash_pack_cost_is_not_verified_comparison(self):
        c=unit_cost({"title":"Powder 75 prań","price":"75.00",
                     "currency":"PLN"},"laundry_detergent")
        self.assertEqual(c["cost_per_wash"],"1.0000")
        self.assertIn("delivery",c["does_not_include"])
        self.assertIn("NOT",c["price_evidence"])
