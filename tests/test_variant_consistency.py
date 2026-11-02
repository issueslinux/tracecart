"""Prevent false savings when same seller-declared GTIN hides wrong variant."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from product_variant import check_variant_consistency
from live_offer_compare import compare_live_offer


class VariantGateTests(unittest.TestCase):
    def test_realistic_allegro_white_7kg_mislabeled_as_color_45kg(self):
        # Publicly visible marketplace listing can claim GTIN for Color 4.5kg
        # while its offer headline says WHITE 7kg. Never rank this as same SKU.
        first = "Persil Color Pulver proszek do prania 4,5 kg 75 prań"
        other = "PERSIL PROSZEK DO PRANIA BIAŁEGO 7kg"
        v = check_variant_consistency(first, other, "laundry_detergent")
        self.assertEqual(v["status"], "CONFLICTING_VARIANT_CLAIMS")
        self.assertEqual({c["attribute"] for c in v["conflicts"]},
                         {"fabric_use", "net_weight_grams"})
        self.assertFalse(v["equivalence_proven"])

    def test_brand_conflict_even_when_gtin_is_same(self):
        v = check_variant_consistency("Persil Color proszek 4,5kg",
                                      "Ariel Color proszek 4,5kg",
                                      "laundry_detergent")
        self.assertEqual(v["status"], "CONFLICTING_VARIANT_CLAIMS")
        self.assertEqual(v["conflicts"][0]["attribute"], "brand")

    def test_powder_vs_liquid(self):
        v = check_variant_consistency("Persil Color proszek 75 prań",
                                      "Persil Color płyn 75 prań",
                                      "laundry_detergent")
        self.assertEqual(v["status"], "CONFLICTING_VARIANT_CLAIMS")
        self.assertEqual(v["conflicts"][0]["attribute"], "form")

    def test_weight_unit_conversion(self):
        v = check_variant_consistency("Persil Color Pulver 4,5 kg",
                                      "Persil kolor proszek 4500 g",
                                      "laundry_detergent")
        self.assertEqual(v["status"], "NO_EXPLICIT_TITLE_CONTRADICTION")
        self.assertEqual(v["selected_signals"]["net_weight_grams"], "4500")
        self.assertEqual(v["alternative_signals"]["net_weight_grams"], "4500")

    def test_unknown_fields_are_not_fabricated(self):
        v = check_variant_consistency("Persil 75 prań",
                                      "Persil Color proszek 75 prań",
                                      "laundry_detergent")
        self.assertEqual(v["status"], "NO_EXPLICIT_TITLE_CONTRADICTION")
        self.assertFalse(v["equivalence_proven"])

    def test_ambiguous_seller_title_blocks_claim(self):
        v = check_variant_consistency("Persil Color White 4,5 kg",
                                      "Persil Color 4,5kg",
                                      "laundry_detergent")
        self.assertEqual(v["status"], "AMBIGUOUS_TITLE_VARIANT")
        self.assertIn("fabric_use", v["selected_ambiguous_fields"])

    def test_different_weight_blocks_even_same_wash_count(self):
        v = check_variant_consistency("Persil Color proszek 75 prań 4,5kg",
                                      "Persil Color proszek 75 prań 7kg",
                                      "laundry_detergent")
        self.assertEqual(v["status"], "CONFLICTING_VARIANT_CLAIMS")

    def test_non_detergent_unchanged(self):
        v = check_variant_consistency("Laptop Lenovo", "Laptop Dell", "laptop")
        self.assertEqual(v["status"], "NOT_APPLICABLE")

    def test_integration_matching_gtin_different_variant_no_delta(self):
        first = {"title": "Persil Color proszek 75 prań 4,5 kg",
                 "price": "89.26", "currency": "PLN",
                 "barcode": "4015200031828",
                 "merchant_url": "https://dma.example.com/p/persil"}
        other = {**first, "title": "PERSIL PROSZEK DO PRANIA BIAŁEGO 7kg",
                 "price": "65.99",
                 "merchant_url": "https://other.example.com/p/persil"}
        base = {"root": {"details": {"selected_cart_item": first},
                         "children": [{"kind": "selected_product", "details": {},
                                       "children": []},
                                      {"kind": "conditional_summary",
                                       "details": {"current_competitor_offers_verified": 0},
                                       "children": []}]},
                "source_intake": {"source_url": first["merchant_url"],
                                  "page_sha256": "a"*64,
                                  "intake_status": "PAGE_RETRIEVED",
                                  "price_status": "SELLER_DECLARED",
                                  "availability_claim": "https://schema.org/InStock"},
                "limitations": []}
        meta = {"source_url": other["merchant_url"], "page_sha256": "b"*64,
                "retrieved_at": "2026-11-02T04:00:00+00:00",
                "price_status": "SELLER_DECLARED",
                "availability_claim": "https://schema.org/InStock"}
        result = compare_live_offer(base, first, other["merchant_url"],
                                    extractor=lambda _: (other, meta))
        comparison = result["live_competitor_comparison"]
        self.assertTrue(comparison["same_gtin_claimed"])
        self.assertEqual(comparison["status"], "CONFLICTING_VARIANT_CLAIMS")
        self.assertIsNone(comparison["seller_listed_price_delta_pct_vs_selected"])
        self.assertIsNone(comparison["delivery_break_even"])
        self.assertEqual(result["root"]["children"][-1]["details"]
                         ["current_competitor_offers_verified"], 0)
        self.assertFalse(comparison["payment_authorized"])


if __name__ == "__main__":
    unittest.main()
