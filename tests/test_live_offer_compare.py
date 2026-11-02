"""Second public seller page: source-qualified conditional price comparison."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live_offer_compare import compare_live_offer
from product_intake import SourceAccessDenied

SELECTED = {
    "title": "Persil Color proszek do prania 100 prań",
    "price": "80.00", "currency": "PLN",
    "barcode": "8712561344494",
    "merchant_url": "https://first.example.com/p/persil-100",
}
SECOND = {**SELECTED, "price": "72.00",
          "merchant_url": "https://second.example.com/p/persil-100"}
META = {
    "source_url": SECOND["merchant_url"],
    "retrieved_at": "2026-11-02T00:00:00+00:00",
    "page_sha256": "b"*64,
    "price_status": "SELLER_DECLARED",
}
BASE = {
    "schema_version": 1, "root": {
        "details": {"selected_cart_item": SELECTED},
        "children": [
            {"kind": "selected_product", "status": "CART_CLAIM", "details": {},
             "children": []},
            {"kind": "conditional_summary", "status": "NO_FORCED_WINNER",
             "details": {"current_competitor_offers_verified": 0,
                         "payment_authorized": False}, "children": []}
        ],
    },
    "source_intake": {"page_sha256": "a"*64, "price_status": "SELLER_DECLARED",
                      "intake_status": "PAGE_RETRIEVED",
                      "retrieved_at": "2026-11-01T22:00:00+00:00",
                      "source_url": SELECTED["merchant_url"]},
    "limitations": [], "sha256": "old",
}


class LiveSecondOfferTests(unittest.TestCase):
    def compare(self, second=None, meta=None, **kw):
        second = copy.deepcopy(SECOND) if second is None else second
        meta = copy.deepcopy(META) if meta is None else meta
        return compare_live_offer(BASE, SELECTED, SECOND["merchant_url"],
                                  extractor=lambda url: (second, meta), **kw)

    def test_same_ean_second_retailer_listed_price_difference(self):
        report = self.compare()
        c = report["live_competitor_comparison"]
        self.assertEqual(c["status"], "SAME_GTIN_SELLER_LISTED_PRICE_COMPARISON")
        self.assertEqual(c["seller_listed_price_delta_pct_vs_selected"], "-10.00")
        self.assertEqual(c["selected_cost_per_wash"]["cost_per_wash"], "0.8000")
        self.assertEqual(c["alternative_cost_per_wash"]["cost_per_wash"], "0.7200")
        self.assertEqual(c["alternative_source"]["page_sha256"], "b"*64)
        self.assertEqual(report["root"]["children"][-1]["status"], "NO_FORCED_WINNER")
        self.assertEqual(report["root"]["children"][-1]["details"]
                         ["current_competitor_offers_verified"], 1)
        self.assertFalse(c["payment_authorized"])
        self.assertNotEqual(report["sha256"], "old")
        self.assertEqual(BASE["root"]["children"][-1]["details"]
                         ["current_competitor_offers_verified"], 0)

    def test_missing_gtin_must_not_rank_even_with_two_prices(self):
        second = {**SECOND, "barcode": ""}
        c = self.compare(second=second)["live_competitor_comparison"]
        self.assertEqual(c["status"], "GTIN_IDENTITY_NOT_ESTABLISHED")
        self.assertIsNone(c["seller_listed_price_delta_pct_vs_selected"])

    def test_conflicting_gtin_not_equivalent(self):
        second = {**SECOND, "barcode": "8700216908856"}
        c = self.compare(second=second)["live_competitor_comparison"]
        self.assertEqual(c["status"], "DIFFERENT_GTIN_NOT_EQUIVALENT")
        self.assertIsNone(c["seller_listed_price_delta_pct_vs_selected"])

    def test_invalid_gtin_claim_blocks_price_comparison(self):
        second = {**SECOND, "barcode": "1234567890123"}
        c = self.compare(second=second)["live_competitor_comparison"]
        self.assertEqual(c["status"], "INVALID_GTIN_CLAIM")
        self.assertTrue(c["invalid_gtin_claim"])
        self.assertIsNone(c["seller_listed_price_delta_pct_vs_selected"])

    def test_equivalent_upc_and_ean_leading_zero_match(self):
        selected = {**SELECTED, "barcode": "036000291452"}
        second = {**SECOND, "barcode": "0036000291452"}
        base = copy.deepcopy(BASE)
        base["root"]["details"]["selected_cart_item"] = selected
        report = compare_live_offer(
            base, selected, second["merchant_url"],
            extractor=lambda _: (second, META))
        self.assertEqual(report["live_competitor_comparison"]["status"],
                         "SAME_GTIN_SELLER_LISTED_PRICE_COMPARISON")
        self.assertTrue(report["live_competitor_comparison"]["same_gtin_claimed"])

    def test_conflicting_washes_same_ean_block_price_delta(self):
        second = {**SECOND, "title": "Persil Color 90 prań"}
        c = self.compare(second=second)["live_competitor_comparison"]
        self.assertEqual(c["status"], "CONFLICTING_WASH_COUNT")
        self.assertIsNone(c["seller_listed_price_delta_pct_vs_selected"])

    def test_unknown_competitor_price_is_unknown_not_free(self):
        second = {**SECOND, "price": None, "currency": None}
        c = self.compare(second=second)["live_competitor_comparison"]
        self.assertEqual(c["status"], "LISTED_PRICE_MISSING")
        self.assertIsNone(c["seller_listed_price_delta_pct_vs_selected"])
        self.assertIsNone(c["alternative_cost_per_wash"]["cost_per_wash"])

    def test_403_does_not_bypass_and_no_fake_offer(self):
        def denied(_):
            raise SourceAccessDenied(403)
        report = compare_live_offer(BASE, SELECTED, SECOND["merchant_url"],
                                    extractor=denied)
        c = report["live_competitor_comparison"]
        self.assertEqual(c["status"], "SECOND_PAGE_NOT_RETRIEVED")
        self.assertEqual(c["alternative_source"]["access_status"], "HTTP_403")
        self.assertIsNone(c["alternative"])
        self.assertEqual(report["root"]["children"][-1]["details"]
                         ["current_competitor_offers_verified"], 0)

    def test_no_selected_source_page_means_no_price_claim(self):
        original = copy.deepcopy(BASE)
        original["source_intake"]["intake_status"] = "URL_ONLY_UNVERIFIED"
        c = compare_live_offer(original, SELECTED, SECOND["merchant_url"],
                               extractor=lambda _: (SECOND, META))[
                                   "live_competitor_comparison"]
        self.assertEqual(c["status"], "SELECTED_PAGE_NOT_RETRIEVED")
        self.assertIsNone(c["seller_listed_price_delta_pct_vs_selected"])

    def test_reject_private_or_http_urls_before_network(self):
        extractor = Mock()
        for url in ("http://127.0.0.1/product", "https://localhost/p",
                    "https://user:pass@example.com/p"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                compare_live_offer(BASE, SELECTED, url, extractor=extractor)
        extractor.assert_not_called()

    def test_same_store_is_not_competing_retailer(self):
        other = {**SECOND, "merchant_url": "https://first.example.com/other"}
        meta = {**META, "source_url": other["merchant_url"]}
        c = compare_live_offer(BASE, SELECTED, other["merchant_url"],
                               extractor=lambda _: (other, meta))[
                                   "live_competitor_comparison"]
        self.assertEqual(c["status"], "SAME_STORE_NOT_COMPETITOR")
        self.assertIsNone(c["seller_listed_price_delta_pct_vs_selected"])

    def test_explicit_out_of_stock_blocks_savings_claim(self):
        meta = {**META, "availability_claim": "https://schema.org/OutOfStock"}
        c = self.compare(meta=meta)["live_competitor_comparison"]
        self.assertEqual(c["status"], "SECOND_OFFER_NOT_AVAILABLE")
        self.assertIsNone(c["seller_listed_price_delta_pct_vs_selected"])

    def test_selected_out_of_stock_is_not_a_comparable_offer(self):
        original = copy.deepcopy(BASE)
        original["source_intake"]["availability_claim"] = "https://schema.org/OutOfStock"
        c = compare_live_offer(original, SELECTED, SECOND["merchant_url"],
                               extractor=lambda _: (SECOND, META))[
                                   "live_competitor_comparison"]
        self.assertEqual(c["status"], "SELECTED_OFFER_NOT_AVAILABLE")
        self.assertTrue(c["selected_offer_not_available"])
        self.assertIsNone(c["seller_listed_price_delta_pct_vs_selected"])

    def test_selected_report_provenance_mismatch_blocks_price_delta(self):
        original = copy.deepcopy(BASE)
        original["source_intake"]["source_url"] = "https://other.example.org/p"
        c = compare_live_offer(original, SELECTED, SECOND["merchant_url"],
                               extractor=lambda _: (SECOND, META))[
                                   "live_competitor_comparison"]
        self.assertEqual(c["status"], "SELECTED_PAGE_NOT_RETRIEVED")
        self.assertIsNone(c["seller_listed_price_delta_pct_vs_selected"])

    def test_www_same_store_not_independent_retailer(self):
        selected = {**SELECTED, "merchant_url": "https://www.shop.example.org/a"}
        second = {**SECOND, "merchant_url": "https://shop.example.org/b"}
        original = copy.deepcopy(BASE)
        original["source_intake"]["source_url"] = selected["merchant_url"]
        original["root"]["details"]["selected_cart_item"] = selected
        meta = {**META, "source_url": second["merchant_url"]}
        c = compare_live_offer(original, selected, second["merchant_url"],
                               extractor=lambda _: (second, meta))[
                                   "live_competitor_comparison"]
        self.assertEqual(c["status"], "SAME_STORE_NOT_COMPETITOR")

    def test_no_cross_currency_without_fx_source(self):
        other = {**SECOND, "price": "20.00", "currency": "EUR"}
        c = self.compare(second=other)["live_competitor_comparison"]
        self.assertEqual(c["status"], "DIFFERENT_CURRENCY_NO_FX")
        self.assertIsNone(c["seller_listed_price_delta_pct_vs_selected"])


if __name__ == "__main__":
    unittest.main()
