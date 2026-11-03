"""Regression: an Allegro bicycle URL must retain Shopping price cards if Product API fails."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from product_intake import generic_url_identity
from search_first import search_serpapi_shopping, attach_shopping_evidence
from app import shopping_search_panel
from test_live_offer_compare import BASE

BIKE_URL = (
    "https://allegro.pl/produkt/"
    "rower-elektryczny-meski-damski-250w-15ah-100km-27-5-ebike-shimano-7s-25kmh-"
    "d0481fa2-8a35-4009-871d-108ca1cc1d78?offerId=18482612668"
)


def shopping_rows():
    return {"search_metadata": {"status": "Success"},
            "shopping_results": [
                {
                    "title": "Rower elektryczny Męski/Damski 250W 15AH 100KM 27,5 Ebike Shimano-7S 25KMH",
                    "source": "Allegro", "price": "2469,05 zł",
                    "extracted_price": 2469.05, "product_id": "3596139955979354983",
                    "product_link": "https://www.google.com/search?ibp=oshop&prds=productid:3596139955979354983",
                },
                {
                    "title": "Nowy rower elektryczny męski/damski 250W 15AH 100KM 27.5",
                    "source": "Allegro", "price": "2469,00 zł",
                    "extracted_price": 2469, "product_id": "1386235594007492322",
                },
                {
                    "title": "Rower elektryczny Evercross 250W 27.5",
                    "source": "Decathlon", "price": "3028,99 zł",
                    "extracted_price": 3028.99, "product_id": "10185102918436742219",
                },
            ]}


class BikeSearchFallbackTests(unittest.TestCase):
    def test_detail_provider_error_does_not_erase_search_priced_cards(self):
        item, meta = generic_url_identity(BIKE_URL, "HTTP_403")
        calls = []
        def fetch(url, host):
            params = parse_qs(urlsplit(url).query)
            calls.append(params["engine"][0])
            if params["engine"] == ["google_shopping"]:
                return shopping_rows()
            # Mirrors a real Google Product call returning a provider 'error'.
            return {"search_metadata": {"status": "Success"},
                    "error": "The Google Product page was unavailable"}
        result = search_serpapi_shopping(item, fetch=fetch, api_key="fake")
        self.assertEqual(calls, ["google_shopping", "google_product"])
        self.assertEqual(result["provider_calls"], 2)
        self.assertEqual(result["status"], "ONLY_GOOGLE_SHOPPING_CARDS_DETAIL_FAILED")
        self.assertEqual(result["product_detail_failure_type"], "ValueError")
        self.assertEqual(len(result["search_result_groups"]), 3)
        self.assertEqual(result["indexed_offers"], [])
        self.assertEqual(result["lowest_indexed_observation"]["price"], "2469.00")
        self.assertIsNone(result["lowest_indexed_observation"]["merchant_url"])
        self.assertEqual(result["indexed_marketplace_names_seen"], ["Allegro"])
        self.assertEqual(result["marketplace_hosts_seen"], [])
        self.assertTrue(all(x["search_card_only_not_direct_offer"]
                            for x in result["search_result_groups"]))
        self.assertTrue(all(x["index_search_url"].startswith("https://www.google.com/search?")
                            for x in result["search_result_groups"]))
        self.assertFalse(result["payment_authorized"])
        self.assertNotIn("api_key", json.dumps(result))
        self.assertNotIn("The Google Product page was unavailable", json.dumps(result))
        report = attach_shopping_evidence(deepcopy(BASE), item, result)
        root = next(x for x in report["root"]["children"]
                    if x["kind"] == "indexed_shopping")
        self.assertEqual(len(root["children"]), 3)
        self.assertTrue(all(x["kind"] == "indexed_search_card"
                            for x in root["children"]))
        html = shopping_search_panel(report)
        self.assertIn("2469.05", html)
        self.assertIn("2469.00", html)
        self.assertIn("Search Google Shopping", html)
        self.assertIn("ONLY_GOOGLE_SHOPPING_CARDS_DETAIL_FAILED", html)
        self.assertIn("SEARCH INDEX ONLY", html)

    def test_failed_search_itself_still_reports_error_without_fabrication(self):
        item, _ = generic_url_identity(BIKE_URL, "HTTP_403")
        def fail(url,host):
            raise ValueError("API key abc ...")
        result=search_serpapi_shopping(item,fetch=fail,api_key="secret")
        self.assertEqual(result["status"],"FAILED_ValueError")
        self.assertFalse(result["search_result_groups"])
        self.assertFalse(result["indexed_offers"])
        self.assertEqual(result["provider_calls"],1)
        self.assertNotIn("secret",json.dumps(result))

    def test_no_details_no_price_remains_a_bounded_result_not_fake_price(self):
        item, _ = generic_url_identity(BIKE_URL,"HTTP_403")
        def fetch(url,host):
            engine=parse_qs(urlsplit(url).query)["engine"][0]
            if engine=="google_shopping":
                return {"shopping_results":[{
                    "title":"Rower elektryczny 250W 15AH Shimano",
                    "source":"Allegro",
                    "product_id":"3596139955979354983"}]}
            raise ValueError("unavailable")
        result=search_serpapi_shopping(item,fetch=fetch,api_key="fake")
        self.assertEqual(result["status"],"ONLY_GOOGLE_SHOPPING_CARDS_DETAIL_FAILED")
        self.assertIsNone(result["lowest_indexed_observation"])
        self.assertEqual(len(result["search_result_groups"]),1)
        self.assertFalse(result["indexed_offers"])


if __name__ == "__main__":
    unittest.main()
