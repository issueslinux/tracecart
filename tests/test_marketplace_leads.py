"""Marketplace result leads survive restricted access without fake price verification."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import marketplace_lead_panel
from marketplace_leads import add_marketplace_leads
from multi_offer_compare import compare_live_offers
from product_intake import SourceAccessDenied
from test_live_offer_compare import BASE, SELECTED

ALLEGRO = ("https://allegro.pl/produkt/kompresor-bezolejowy-1100-w-stanley-air-kit-"
           "1-5km-8-bar-sprezarka-zestaw-e4cae746-3f65-411f-a748-e715e2d02305")

def observed(**kwargs):
    return {"url": "https://offer.example.org/product/stanley",
            "price": "30.00", "currency": "PLN",
            "origin": "USER_REPORTED_NOT_FETCHED", **kwargs}


class MarketplaceLeadTests(unittest.TestCase):
    def test_lower_external_price_is_visible_but_not_source_verified(self):
        original = deepcopy(BASE)
        result = add_marketplace_leads(original, SELECTED, [observed()])
        row = result["marketplace_leads"]["observations"][0]
        self.assertEqual(row["observed_price"], "30.00")
        self.assertEqual(row["difference_vs_selected_listed_price"], "50.00")
        self.assertEqual(row["comparison_status"], "OBSERVED_LOWER_LISTED_PRICE_NOT_VERIFIED")
        self.assertFalse(row["source_page_downloaded_by_tracecart"])
        self.assertFalse(row["stock_verified"])
        self.assertIsNone(row["same_gtin_claim_not_verified"])
        self.assertFalse(result["marketplace_leads"]["payment_authorized"])
        self.assertEqual(result["marketplace_leads"]["source_qualified_comparisons"], 0)
        self.assertEqual(result["root"]["children"][-2]["kind"], "marketplace_leads")
        self.assertEqual(len(result["root"]["children"][-2]["children"][0]["children"]), 3)
        self.assertEqual(result["root"]["children"][-1]["kind"], "conditional_summary")
        self.assertEqual(original["root"]["children"][-1]["details"]["current_competitor_offers_verified"], 0)
        self.assertNotIn("marketplace_leads", original)

    def test_blocked_marketplace_is_not_discarded(self):
        def blocked(_):
            raise SourceAccessDenied(403)
        report = compare_live_offers(BASE, SELECTED, [
            "https://allegro.pl/produkt/stanley-something-12345"],
            extractor=blocked, marketplace_observations=[{
                "url": "https://allegro.pl/produkt/stanley-something-12345",
                "price": "29.99", "currency": "PLN",
                "origin": "USER_REPORTED_NOT_FETCHED"}])
        self.assertEqual(report["live_competitor_comparison"]["status"],
                         "SECOND_PAGE_NOT_RETRIEVED")
        self.assertEqual(report["live_competitor_comparison"]["alternative_source"]["access_status"],
                         "HTTP_403")
        self.assertEqual(report["marketplace_leads"]["potential_lower_price_leads"], 1)
        self.assertEqual(report["marketplace_leads"]["source_qualified_comparisons"], 0)
        self.assertIn("29.99", marketplace_lead_panel(report))

    def test_mismatched_currency_or_unsourced_selected_price_is_not_compared(self):
        row = {**observed(), "currency": "EUR"}
        report = add_marketplace_leads(BASE, SELECTED, [row])
        self.assertIsNone(
            report["marketplace_leads"]["observations"][0]["difference_vs_selected_listed_price"])
        self.assertEqual(report["marketplace_leads"]["potential_lower_price_leads"], 0)
        without_source = deepcopy(BASE)
        without_source["source_intake"]["page_sha256"] = None
        result = add_marketplace_leads(without_source, SELECTED, [observed()])
        self.assertIsNone(result["marketplace_leads"]["observations"][0]["difference_vs_selected_listed_price"])

    def test_gtin_is_only_claimed_not_promoted_to_verified(self):
        report = add_marketplace_leads(BASE, SELECTED, [{
            **observed(), "gtin_claim": SELECTED["barcode"], "condition": "NEW_CLAIM"}])
        row = report["marketplace_leads"]["observations"][0]
        self.assertTrue(row["same_gtin_claim_not_verified"])
        self.assertFalse(row["source_page_downloaded_by_tracecart"])
        self.assertFalse(row["payment_authorized"])

    def test_invalid_price_and_urls_fail_closed(self):
        for raw in ("0.00", "-0.01", "NaN", "Infinity", "5.001", "1e4", ""):
            with self.subTest(price=raw), self.assertRaises(ValueError):
                add_marketplace_leads(BASE, SELECTED, [{**observed(), "price": raw}])
        for link in ("https://127.0.0.1/private", "https://user:pass@example.org/item",
                     "http://example.org/item", SELECTED["merchant_url"]):
            with self.subTest(url=link), self.assertRaises(ValueError):
                add_marketplace_leads(BASE, SELECTED, [{**observed(), "url": link}])
        with self.assertRaises(ValueError):
            add_marketplace_leads(BASE, SELECTED, [observed(), observed()])
        with self.assertRaises(ValueError):
            add_marketplace_leads(BASE, SELECTED, [{**observed(), "source_page_verified": True}])
        with self.assertRaises(ValueError):
            add_marketplace_leads(BASE, SELECTED, [{**observed(), "origin": "RETAILER_VERIFIED"}])

    def test_html_escapes_untrusted_observation_link(self):
        url = "https://example.org/product/%3Cscript%3E?utm_source=ads"
        report = add_marketplace_leads(BASE, SELECTED, [{**observed(), "url": url}])
        html = marketplace_lead_panel(report)
        self.assertIn("MARKETPLACE PRICE LEADS", html)
        self.assertNotIn("<script>", html)

    def test_public_allegro_observation_has_explicit_limited_provenance(self):
        example = add_marketplace_leads(BASE, SELECTED, [{
            "url": ALLEGRO, "price": "229.00", "currency": "PLN",
            "origin": "PUBLIC_PAGE_REVIEW_NOT_FETCHED_BY_TRACECART",
            "observed_at": "2026-11-02T16:49:00+00:00",
            "gtin_claim": "8016738753899",
            "condition": "NEW_CLAIM",
        }])
        row = example["marketplace_leads"]["observations"][0]
        self.assertEqual(row["origin"], "PUBLIC_PAGE_REVIEW_NOT_FETCHED_BY_TRACECART")
        self.assertEqual(row["observed_price"], "229.00")
        self.assertFalse(row["same_gtin_claim_not_verified"])  # unrelated synthetic selected barcode
        self.assertFalse(row["source_page_downloaded_by_tracecart"])


if __name__ == "__main__":
    unittest.main()


class MarketplaceDirectPriceCrosscheckTests(unittest.TestCase):
    def test_observed_price_conflicting_with_fetched_page_is_not_lower_price_lead(self):
        from test_live_offer_compare import SECOND, META
        observed_url = SECOND["merchant_url"]
        report = compare_live_offers(
            BASE, SELECTED, [observed_url],
            extractor=lambda u: (SECOND, META),
            marketplace_observations=[{
                "url": observed_url, "price": "20.00", "currency": "PLN",
                "origin": "USER_REPORTED_NOT_FETCHED",
            }])
        lead = report["marketplace_leads"]["observations"][0]
        self.assertEqual(lead["direct_seller_price_crosscheck"], "CONFLICTS_WITH_DIRECT_SELLER_PRICE")
        self.assertEqual(lead["comparison_status"], "CONFLICTING_OBSERVED_AND_DIRECT_PRICE")
        self.assertIsNone(lead["difference_vs_selected_listed_price"])
        self.assertEqual(report["marketplace_leads"]["potential_lower_price_leads"], 0)
        self.assertEqual(report["live_competitor_comparison"]["status"],
                         "SAME_GTIN_SELLER_LISTED_PRICE_COMPARISON")

    def test_direct_page_price_agreement_does_not_double_count(self):
        from test_live_offer_compare import SECOND, META
        report = compare_live_offers(
            BASE, SELECTED, [SECOND["merchant_url"]],
            extractor=lambda u: (SECOND, META),
            marketplace_observations=[{
                "url": SECOND["merchant_url"], "price": SECOND["price"],
                "currency": SECOND["currency"], "origin": "USER_REPORTED_NOT_FETCHED",
            }])
        self.assertEqual(report["marketplace_leads"]["potential_lower_price_leads"], 0)
        row = report["marketplace_leads"]["observations"][0]
        self.assertEqual(row["direct_seller_price_crosscheck"], "AGREES_WITH_DIRECT_SELLER_PRICE")
        self.assertIsNone(row["difference_vs_selected_listed_price"])
