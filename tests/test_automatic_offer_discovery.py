"""Live-source discovery should not convert search hits into verified offers."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cart_research
from app import automatic_discovery_panel
from automatic_offer_discovery import enrich_with_discovered_offers
from product_intake import SourceAccessDenied
from test_live_offer_compare import BASE, SELECTED, SECOND, META


def hit(url, title="Product", snippet="Cheapest 1.00 PLN", **kwargs):
    return {"title": title, "url": url, "snippet": snippet,
            "source_kind": "UNVERIFIED_SEARCH_RESULT_NOT_A_PRICE_OFFER",
            **kwargs}


class AutomaticDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.allegro = "https://allegro.pl/oferta/persil-proszek-100-123456"
        self.shop = "https://second.example.net/product/persil-100"
        self.ceneo = "https://www.ceneo.pl/37745332"

    def report(self, hits):
        root = deepcopy(BASE)
        root["source_discovery"] = {"web_hits": hits, "attempts": []}
        return root

    def extractor(self, url):
        if "allegro.pl" in url:
            raise SourceAccessDenied(403)
        return ({**SECOND, "merchant_url": url, "price": "72.00"},
                {**META, "source_url": url})

    def test_marketplace_priority_failed_403_preserved_and_live_seller_verified(self):
        original = self.report([
            hit(self.shop), hit(self.ceneo), hit(self.allegro),
            hit("https://evil.example.org/"),
            hit("https://127.0.0.1/private"), hit(self.shop),
            hit(SELECTED["merchant_url"]), hit("https://www.second.example.net/product/persil-other"),
        ])
        extra = enrich_with_discovered_offers(original, SELECTED,
                                             extractor=self.extractor, max_checks=2)
        audit = extra["automatic_offer_discovery"]
        self.assertEqual(audit["counts"]["candidates_checked"], 2)
        self.assertEqual(audit["counts"]["seller_pages_retrieved"], 1)
        self.assertEqual(audit["counts"]["source_qualified_competing_offers"], 1)
        self.assertEqual(audit["counts"]["marketplace_leads_found"], 1)
        self.assertEqual([r["url"] for r in audit["page_checks"]],
                         [self.allegro, self.shop])
        self.assertEqual(audit["page_checks"][0]["source_http_status"], "HTTP_403")
        self.assertEqual(audit["page_checks"][1]["status"],
                         "SAME_GTIN_SELLER_LISTED_PRICE_COMPARISON")
        statuses = [row["decision"] for row in audit["candidate_audit"]]
        self.assertIn("DEFERRED_AGGREGATOR_NOT_SELLER", statuses)
        self.assertIn("REJECTED_UNSAFE_URL", statuses)
        self.assertIn("REJECTED_NON_PRODUCT_PATH", statuses)
        self.assertIn("REJECTED_DUPLICATE_URL", statuses)
        self.assertIn("REJECTED_ORIGINAL_SELLER", statuses)
        self.assertIn("REJECTED_DUPLICATE_MERCHANT", statuses)
        self.assertIn("SOURCE_CHECK_INCOMPLETE", statuses)
        self.assertIn("SOURCE_VERIFIED_COMPARABLE", statuses)
        self.assertEqual(extra["root"]["children"][-2]["kind"], "automatic_offer_discovery")
        self.assertFalse(extra["automatic_offer_discovery"]["payment_authorized"])
        self.assertFalse(extra["automatic_offer_discovery"]["search_hit_price_used"])
        self.assertNotIn("1.00", str(extra["live_competitor_comparisons"]))
        self.assertNotIn("automatic_offer_discovery", original)
        self.assertIn("HTTP_403", automatic_discovery_panel(extra))
        self.assertIn("Search hits: <b>8</b>", automatic_discovery_panel(extra))

    def test_no_hits_or_no_selected_provenance_means_zero_network(self):
        extractor = Mock(side_effect=AssertionError("must not fetch"))
        empty = enrich_with_discovered_offers(self.report([]), SELECTED, extractor=extractor)
        self.assertEqual(empty["automatic_offer_discovery"]["status"], "SEARCH_NO_CANDIDATES")
        missing = self.report([hit(self.allegro)])
        missing["source_intake"]["page_sha256"] = None
        audit = enrich_with_discovered_offers(missing, SELECTED, extractor=extractor)
        self.assertEqual(audit["automatic_offer_discovery"]["status"],
                         "SELECTED_SOURCE_UNVERIFIED_NO_FETCH")
        self.assertEqual(audit["automatic_offer_discovery"]["candidate_audit"][0]["decision"],
                         "SKIPPED_SELECTED_SOURCE_UNVERIFIED")
        extractor.assert_not_called()

    def test_rejects_bad_schema_limits(self):
        for count in (0, 4, True):
            with self.subTest(count=count), self.assertRaises(ValueError):
                enrich_with_discovered_offers(self.report([]), SELECTED,
                                             max_checks=count)
        with self.assertRaises(ValueError):
            enrich_with_discovered_offers(self.report([hit(self.shop)] * 13),
                                         SELECTED)

    def test_single_candidate_keeps_single_offer_api_and_discovery_branch(self):
        report = enrich_with_discovered_offers(
            self.report([hit(self.shop)]), SELECTED, extractor=self.extractor)
        self.assertIn("live_competitor_comparison", report)
        self.assertEqual(report["automatic_offer_discovery"]["counts"][
            "source_qualified_competing_offers"], 1)
        self.assertEqual(report["root"]["children"][-2]["kind"],
                         "automatic_offer_discovery")

    def test_search_snippet_does_not_become_price_even_if_seller_unavailable(self):
        report = enrich_with_discovered_offers(
            self.report([hit(self.allegro, snippet="Only 9,99 PLN!")]),
            SELECTED, extractor=self.extractor)
        self.assertEqual(report["automatic_offer_discovery"]["counts"][
            "source_qualified_competing_offers"], 0)
        self.assertEqual(report["live_competitor_comparison"]["status"],
                         "SECOND_PAGE_NOT_RETRIEVED")
        self.assertNotIn("9,99", str(report["live_competitor_comparison"]))
        self.assertEqual(report["automatic_offer_discovery"]["candidate_audit"][0][
            "search_snippet_unverified"], "Only 9,99 PLN!")

    def test_html_escapes_search_result_title_and_html(self):
        report = enrich_with_discovered_offers(
            self.report([hit(self.allegro, title="<script>hijack()</script>")]),
            SELECTED, extractor=self.extractor)
        html = automatic_discovery_panel(report)
        self.assertNotIn("<script>", html)

    def test_brave_makes_broad_and_allegro_queries_but_never_verifies_snippets(self):
        calls = []
        def fake(url, host, headers=None):
            if host == "api.search.brave.com":
                from urllib.parse import parse_qs, urlsplit
                q = parse_qs(urlsplit(url).query)["q"][0]
                calls.append(q)
                result_url = self.allegro if q.startswith("site:") else self.shop
                return {"web": {"results": [{
                    "title": "9,99 PLN sale",
                    "url": result_url, "description": "Cheapest 9,99 PLN"}]}}
            return {"products": []} if host == "world.openproductsfacts.org" else {"items": []}
        with patch.dict(cart_research.os.environ, {"BRAVE_API_KEY": "DUMMY"}), patch.object(
                cart_research, "generate_local_ai_questions", return_value=[]):
            report = cart_research.research_cart(SELECTED, fetch=fake)
        self.assertEqual(len(calls), 2)
        self.assertTrue(any("site:allegro.pl" in query for query in calls))
        self.assertEqual(len(report["source_discovery"]["web_hits"]), 2)
        self.assertTrue(all(x["source_kind"] ==
                            "UNVERIFIED_SEARCH_RESULT_NOT_A_PRICE_OFFER"
                            for x in report["source_discovery"]["web_hits"]))
        self.assertEqual(report["root"]["children"][-1]["details"][
            "current_competitor_offers_verified"], 0)
        self.assertNotIn("9,99", str(report["root"]["children"][-1]["details"]))


class BackgroundAutoDiscoveryTests(unittest.TestCase):
    def test_cart_url_background_job_auto_checks_authorized_search_hit(self):
        import tempfile
        import time
        selected = deepcopy(SELECTED)
        source = {**BASE["source_intake"], "extraction_method": "Product JSON-LD",
                  "barcode_status": "FOUND_CHECKSUM_VALID"}
        candidate_url = "https://second.example.net/product/persil-100"
        research = deepcopy(BASE)
        research["source_discovery"] = {"web_hits": [hit(candidate_url)],
                                        "catalog": [], "prices": [], "attempts": []}
        with tempfile.TemporaryDirectory() as folder:
            db = str(Path(folder) / "cart-discovery.sqlite")
            jobs = cart_research.CartResearchJobs(db, runner=lambda item: deepcopy(research))
            try:
                with patch("product_intake.extract_product_page",
                           return_value=(selected, source)), patch(
                        "live_offer_compare.extract_product_page",
                        return_value=({**SECOND, "merchant_url": candidate_url},
                                      {**META, "source_url": candidate_url})):
                    jid = jobs.submit_url(selected["merchant_url"])
                    for _ in range(150):
                        record = jobs.read(jid)
                        if record["state"] in ("READY", "FAILED"):
                            break
                        time.sleep(.02)
                self.assertEqual(record["state"], "READY", record["error_type"])
                report = record["report"]
                self.assertEqual(report["automatic_offer_discovery"]["counts"][
                    "source_qualified_competing_offers"], 1)
                self.assertEqual(report["live_competitor_comparison"]["status"],
                                 "SAME_GTIN_SELLER_LISTED_PRICE_COMPARISON")
                self.assertFalse(report["automatic_offer_discovery"]["payment_authorized"])
            finally:
                jobs.close()


if __name__ == "__main__":
    unittest.main()
