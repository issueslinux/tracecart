"""Multi-merchant user outcome: bounded, auditable source checks, no false winner."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from multi_offer_compare import compare_live_offers
from product_intake import SourceAccessDenied
from test_live_offer_compare import BASE, SELECTED, SECOND, META


class MultiRetailerTests(unittest.TestCase):
    def setUp(self):
        self.urls = [
            "https://shop2.example.net/p/persil",
            "https://shop3.example.net/p/persil",
            "https://shop4.example.net/p/persil",
        ]

    def extractor(self, url):
        if "shop4" in url:
            raise SourceAccessDenied(403)
        price = "72.00" if "shop2" in url else "76.00"
        product = {**SECOND, "merchant_url": url, "price": price}
        metadata = {**META, "source_url": url}
        if "shop3" in url:
            metadata["availability_claim"] = "https://schema.org/OutOfStock"
        return product, metadata

    def test_three_sources_preserve_rejected_and_failed_evidence(self):
        base = copy.deepcopy(BASE)
        r = compare_live_offers(base, SELECTED, self.urls,
                                extractor=self.extractor)
        summary = r["multi_offer_summary"]
        self.assertEqual(summary["requested"], 3)
        self.assertEqual(summary["pages_retrieved"], 2)
        self.assertEqual(summary["source_qualified_comparisons"], 1)
        self.assertEqual([x["status"] for x in r["live_competitor_comparisons"]],
                         ["SAME_GTIN_SELLER_LISTED_PRICE_COMPARISON",
                          "SECOND_OFFER_NOT_AVAILABLE", "SECOND_PAGE_NOT_RETRIEVED"])
        self.assertEqual(len(r["root"]["children"]), len(base["root"]["children"]) + 4)
        self.assertEqual(len(set(x["id"] for x in r["root"]["children"] if "id" in x)), 4)
        self.assertEqual(r["root"]["children"][-1]["details"]
                         ["current_competitor_offers_verified"], 1)
        self.assertTrue(summary["no_shipping_inclusive_winner"])
        self.assertFalse(summary["payment_authorized"])
        self.assertFalse(summary["price_ranked_as_delivered"])
        self.assertNotEqual(r["sha256"], base["sha256"])
        self.assertEqual(base["root"]["children"][-1]["details"]
                         ["current_competitor_offers_verified"], 0)
        self.assertEqual(r["live_competitor_comparisons"][-1]
                         ["alternative_source"]["access_status"], "HTTP_403")

    def test_duplicate_urls_fail_before_network(self):
        calls = []
        def spy(url):
            calls.append(url)
            return self.extractor(url)
        for urls in ([self.urls[0], self.urls[0]],
                     [self.urls[0], self.urls[0] + "?utm_source=test"],
                     [SELECTED["merchant_url"], self.urls[0]],
                     [self.urls[0], "https://www.shop2.example.net/other"]):
            with self.subTest(urls=urls), self.assertRaises(ValueError):
                compare_live_offers(BASE, SELECTED, urls, extractor=spy)
        self.assertEqual(calls, [])

    def test_bad_input_and_private_urls_fail_before_network(self):
        for urls in ([], self.urls + [self.urls[0], self.urls[1]],
                     ["http://shop2.example.net/p"],
                     ["https://127.0.0.1/private"],
                     ["https://user:pass@shop2.example.net/p"],
                     ["https://localhost/p"],
                     "https://shop2.example.net/p"):
            with self.subTest(urls=urls), self.assertRaises(ValueError):
                compare_live_offers(BASE, SELECTED, urls,
                                    extractor=lambda _: self.fail("network called"))

    def test_one_url_keeps_existing_single_offer_api(self):
        r = compare_live_offers(BASE, SELECTED, [self.urls[0]],
                                extractor=self.extractor)
        self.assertIn("live_competitor_comparison", r)
        self.assertNotIn("live_competitor_comparisons", r)
        self.assertEqual(r["live_competitor_comparison"]["status"],
                         "SAME_GTIN_SELLER_LISTED_PRICE_COMPARISON")

    def test_cross_currency_not_ranked_even_with_matching_ean(self):
        def euro(url):
            item, meta = self.extractor(url)
            item["currency"] = "EUR"
            item["price"] = "22.00"
            return item, meta
        r = compare_live_offers(BASE, SELECTED, self.urls[:2], extractor=euro)
        self.assertEqual(r["multi_offer_summary"]["source_qualified_comparisons"], 0)
        self.assertEqual(r["live_competitor_comparisons"][0]["status"],
                         "DIFFERENT_CURRENCY_NO_FX")
        self.assertIsNone(r["live_competitor_comparisons"][0]
                          ["seller_listed_price_delta_pct_vs_selected"])


if __name__ == "__main__":
    unittest.main()
