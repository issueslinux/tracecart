"""SerpApi Shopping contract is limited to indexed pricing evidence."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, Mock
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cart_research
from app import shopping_search_panel
from search_first import search_serpapi_shopping, attach_shopping_evidence
from test_live_offer_compare import BASE, SELECTED


def response(engine):
    if engine == "google_shopping":
        return {
            "search_metadata": {"status": "Success", "id": "TEST_SEARCH_ID"},
            "shopping_results": [
                {"title": "Stanley Air Kit OL 195 Kompresor", "source": "Allegro",
                 "price": "229,00 zł", "extracted_price": 229.0,
                 "product_id": "987654321000111", "multiple_sources": True},
                {"title": "Stanley air kit OL 195 200l", "source": "Other",
                 "product_id": "987654321000112"},
            ],
        }
    return {
        "search_metadata": {"status": "Success"},
        "product_results": {
            "title": "Stanley Air Kit OL195 kompresor",
            "stores": [
                {"name": "Allegro", "title": "Stanley Air Kit OL 195",
                 "link": "https://allegro.pl/oferta/stanley-air-kit-18637535530?utm_source=google",
                 "price": "229,00 zł", "extracted_price": 229.0,
                 "original_price": "265,00 zł", "extracted_original_price": 265},
                {"name": "Narzedzia", "title": "Stanley Air Kit OL 195",
                 "link": "https://www.narzedzia.pl/kompresor-stanley-air-kit-123456.html",
                 "price": "367,99 zł", "extracted_price": 367.99},
                {"name": "Bad currency", "title": "Stanley Air Kit",
                 "link": "https://other.example.com/item/stanley-air-kit",
                 "price": "367.99", "extracted_price": 367.99},
                {"name": "Bad low-price", "title": "Stanley Air Kit",
                 "link": "https://bad.example.com/item/stanley-air-kit",
                 "price": "1,00 zł", "extracted_price": 0},
                {"name": "Different model", "title": "Stanley 8215190STN9991",
                 "link": "https://else.example.org/item/stanley",
                 "price": "100,00 zł", "extracted_price": 100},
                {"name": "Private IP", "title": "Stanley",
                 "link": "https://127.0.0.1/private",
                 "price": "1,00 zł", "extracted_price": 1},
            ],
        },
    }


class SearchFirstTests(unittest.TestCase):
    def setUp(self):
        self.item = {**SELECTED, "title": "Stanley Air Kit OL195 kompresor",
                     "currency": "PLN", "barcode": "8016738753899"}
        self.called = []

    def fetch(self, url, host):
        self.assertEqual(host, "serpapi.com")
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        self.assertEqual(params["gl"], ["pl"])
        self.assertEqual(params["hl"], ["pl"])
        self.assertEqual(params["api_key"], ["test-secret-key"])
        self.called.append(params["engine"][0])
        return response(params["engine"][0])

    def test_two_calls_and_marketplace_price_without_direct_http(self):
        result = search_serpapi_shopping(self.item, fetch=self.fetch,
                                        api_key="test-secret-key")
        self.assertEqual(self.called, ["google_shopping", "google_product"])
        self.assertEqual(result["provider_calls"], 2)
        self.assertEqual(result["status"], "INDEXED_STORES_WITHOUT_SELLER_VERIFICATION")
        self.assertEqual(result["marketplace_hosts_seen"], ["allegro.pl"])
        self.assertEqual(len(result["indexed_offers"]), 3)
        self.assertEqual(result["indexed_offers"][0]["seller"], "Different model")  # cheaper, but conflicted
        self.assertEqual(result["indexed_offers"][1]["seller"], "Allegro")
        self.assertEqual(result["indexed_offers"][1]["current_price_indexed"], "229.00")
        self.assertEqual(result["indexed_offers"][1]["previous_price_indexed"], "265.00")
        self.assertEqual(result["lowest_indexed_observation"]["price"], "229.00")
        self.assertTrue(result["lowest_indexed_observation"]["product_identity_unverified"])
        self.assertTrue(all(not x["source_page_retrieved"]
                            for x in result["indexed_offers"]))
        self.assertFalse(result["payment_authorized"])
        self.assertNotIn("test-secret-key", str(result))

    def test_result_tree_and_html_are_marked_unverified(self):
        result = search_serpapi_shopping(self.item, fetch=self.fetch,
                                        api_key="test-secret-key")
        original = deepcopy(BASE)
        report = attach_shopping_evidence(original, self.item, result)
        self.assertEqual(report["root"]["children"][-2]["kind"], "indexed_shopping")
        self.assertFalse(report["root"]["children"][-2]["details"]["payment_authorized"])
        self.assertEqual(report["root"]["children"][-1]["kind"], "conditional_summary")
        self.assertNotIn("indexed_shopping", original)
        self.assertEqual(report["root"]["children"][-1]["details"][
            "current_competitor_offers_verified"], 0)
        html = shopping_search_panel(report)
        self.assertIn("Allegro", html)
        self.assertIn("229.00", html)
        self.assertIn("SEARCH INDEX ONLY", html)

    def test_missing_key_zero_network(self):
        with patch.dict("os.environ", {"SERPAPI_API_KEY": ""}):
            obj = search_serpapi_shopping(self.item, fetch=Mock(
                side_effect=AssertionError("no network")))
        self.assertEqual(obj["status"], "SKIPPED_NO_SERPAPI_API_KEY")
        self.assertEqual(obj["provider_calls"], 0)
        self.assertFalse(obj["indexed_offers"])

    def test_no_google_group_no_second_call(self):
        def fetch(url, host):
            self.called.append(parse_qs(urlsplit(url).query)["engine"][0])
            return {"shopping_results": [{"title": "Accessory without ID"}]}
        obj = search_serpapi_shopping(self.item, fetch=fetch, api_key="secret")
        self.assertEqual(obj["status"], "NO_CANDIDATE_GOOGLE_PRODUCT_GROUP")
        self.assertEqual(self.called, ["google_shopping"])

    def test_provider_error_does_not_leak_credentials(self):
        def fail(url, host):
            raise ValueError("api_key=test-secret-key credential exposed")
        obj = search_serpapi_shopping(self.item, fetch=fail,
                                     api_key="test-secret-key")
        self.assertEqual(obj["status"], "FAILED_ValueError")
        self.assertEqual(obj["provider_calls"], 1)
        self.assertNotIn("test-secret-key", str(obj))

    def test_google_product_without_store_prices(self):
        def fetch(url, host):
            engine = parse_qs(urlsplit(url).query)["engine"][0]
            if engine == "google_shopping":
                return response(engine)
            return {"product_results": {"title": "Stanley", "stores": [
                {"name": "Allegro", "link": "https://allegro.pl/oferta/p",
                 "price": "299", "extracted_price": 299}]}}
        obj = search_serpapi_shopping(self.item, fetch=fetch, api_key="key")
        self.assertEqual(obj["status"], "ONLY_GOOGLE_SHOPPING_SEARCH_INDEX_PRICES")
        self.assertEqual(obj["lowest_indexed_observation"]["price"], "229.00")
        self.assertIsNone(obj["lowest_indexed_observation"]["merchant_url"])

    def test_blocked_selected_page_still_yields_indexed_pln_price(self):
        item = {**self.item, "price": None, "currency": None, "barcode": ""}
        result = search_serpapi_shopping(item, fetch=self.fetch,
                                        api_key="test-secret-key")
        self.assertEqual(result["lowest_indexed_observation"]["price"], "229.00")
        self.assertTrue(result["lowest_indexed_observation"]["checkout_price_unverified"])
        self.assertEqual(result["source_qualified_seller_offers"], 0)

    def test_variant_conflict_excludes_lowest_price_from_minimum(self):
        obj = search_serpapi_shopping(self.item, fetch=self.fetch,
                                     api_key="test-secret-key")
        conflicting = obj["indexed_offers"][0]
        self.assertEqual(conflicting["identity_status"], "MODEL_TOKEN_CONFLICT_NEEDS_REVIEW")
        self.assertEqual(conflicting["current_price_indexed"], "100.00")
        self.assertEqual(obj["lowest_indexed_observation"]["price"], "229.00")

    def test_limits_and_input_validation(self):
        for max_stores in (0, 13, True):
            with self.assertRaises(ValueError):
                search_serpapi_shopping(self.item, api_key="x",
                                       max_stores=max_stores)
        with self.assertRaises(ValueError):
            search_serpapi_shopping({}, api_key="x")

    def test_no_direct_seller_credential_leak_when_url_has_tracking(self):
        obj = search_serpapi_shopping(self.item, fetch=self.fetch,
                                     api_key="test-secret-key")
        allegro = [x for x in obj["indexed_offers"] if x["merchant_host"] == "allegro.pl"][0]
        self.assertEqual(allegro["merchant_url"],
                         "https://allegro.pl/oferta/stanley-air-kit-18637535530")
        self.assertNotIn("api_key", json.dumps(obj))

    def test_job_includes_provider_result_even_with_blocked_initial_marketplace(self):
        from product_intake import SourceAccessDenied
        from test_live_offer_compare import BASE
        import tempfile
        item = {**self.item, "merchant_url": "https://allegro.pl/oferta/stanley-test-model-10000"}
        def selected_source(url):
            raise SourceAccessDenied(403)
        research = deepcopy(BASE)
        research["root"]["children"] = [
            {"id": "start", "kind": "selected", "details": {}, "children": []},
            {"id": "mid", "kind": "summary", "details": {"payment_authorized": False},
             "children": []}]
        research["source_discovery"] = {"web_hits": []}
        output = search_serpapi_shopping(item, fetch=self.fetch,
                                        api_key="test-secret-key")
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
                "os.environ", {"SERPAPI_API_KEY": "test-secret-key"}):
            jobs = cart_research.CartResearchJobs(
                str(Path(tmp)/"test.sqlite"), runner=lambda x: deepcopy(research))
            try:
                with patch("product_intake.extract_product_page",
                           side_effect=SourceAccessDenied(403)), patch(
                           "search_first.search_serpapi_shopping", return_value=output):
                    jid = jobs.submit_url(item["merchant_url"])
                    for _ in range(150):
                        row = jobs.read(jid)
                        if row["state"] in ("READY", "FAILED"):
                            break
                        time.sleep(0.02)
                self.assertEqual(row["state"], "READY", row.get("error_type"))
                self.assertEqual(row["report"]["indexed_shopping"]["indexed_offers"][1][
                    "merchant_host"], "allegro.pl")
                self.assertEqual(row["report"]["indexed_shopping"][
                    "source_qualified_seller_offers"], 0)
            finally:
                jobs.close()


if __name__ == "__main__":
    unittest.main()
