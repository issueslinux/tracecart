"""Offline assertions for real 2026-11-03 Tavily keyless Allegro receipts."""
import json
from pathlib import Path
import unittest

from tavily_allegro_index import (
    _identifiable_url, _search_plan, normalize_index_result,
    search_tavily_allegro,
)

ROOT = Path(__file__).resolve().parents[1]
RECEIPTS = ROOT / "benchmarks/results/tavily_keyless_allegro_20261103.jsonl"
MODEL = "RPI18-0"
OFFER = "18457369262"
BRAND = "Ryobi"


class TavilyKeylessAllegroTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipts = {
            x["variant"]: x
            for x in (json.loads(line) for line in RECEIPTS.read_text().splitlines())
        }

    def test_four_real_searches_responded_without_credentials(self):
        for query in ("offer_id_exact", "model_allegro", "ean_allegro", "model_merchant"):
            r = self.receipts[query]
            self.assertEqual(r["http_status"], 200)
            self.assertEqual(r["result_count"], 7)

    def test_external_mirrors_do_not_count_as_allegro_offer(self):
        exact = self.receipts["offer_id_exact"]
        self.assertEqual(exact["exact_offer_url_hits"], 2)
        candidates = [
            normalize_index_result(
                {"url": r["url"], "title": r["title"], "content": r["excerpt"]},
                BRAND, MODEL, OFFER)
            for r in exact["results"]
        ]
        self.assertTrue(any(x for x in candidates))
        self.assertTrue(all(
            x["offer_id_from_url"] != OFFER
            for x in candidates if x))
        self.assertEqual(sum(bool(x) for x in candidates), 1)
        self.assertTrue(any("spolshy.com.ua" in r["url"] for r in exact["results"]))

    def test_live_search_index_prices_have_no_seller_or_checkout_proof(self):
        data = self.receipts["model_allegro"]["results"]
        candidates = [
            normalize_index_result(
                {"url":r["url"],"title":r["title"],"content":r["excerpt"]},
                BRAND, MODEL, OFFER)
            for r in data
        ]
        by_price = {x["indexed_price_claim"]:x for x in candidates
                    if x and x["indexed_price_claim"]}
        self.assertEqual(set(by_price), {"197.90","89.00","249.90"})
        self.assertEqual(by_price["197.90"]["offer_relation"],
                         "PRODUCT_PAGE_WITHOUT_SINGLE_OFFER_ID")
        self.assertEqual(by_price["89.00"]["indexed_condition_claim"], "USED_CLAIM")
        self.assertEqual(by_price["89.00"]["offer_id_from_url"], "18928160412")
        self.assertEqual(by_price["249.90"]["offer_id_from_url"], "18740910894")
        for result in by_price.values():
            self.assertFalse(result["price_verified_by_seller"])
            self.assertFalse(result["seller_verified"])
            self.assertFalse(result["payment_authorized"])

    def test_direct_extract_on_allegro_failed_but_official_page_succeeded(self):
        receipt = self.receipts["direct_extract_offer_and_official"]
        self.assertEqual(receipt["http_status"], 200)
        self.assertEqual(receipt["success_count"], 1)
        self.assertEqual(len(receipt["failed_results"]), 1)
        self.assertIn("allegro.pl", receipt["failed_results"][0]["url"])
        self.assertIn("timed out", receipt["failed_results"][0]["error"])

    def test_disabled_default_makes_zero_remote_requests(self):
        def unexpected(*args,**kwargs):
            self.fail("No automatic public API call is allowed")
        got = search_tavily_allegro(BRAND, MODEL, OFFER, enabled=False, provider=unexpected)
        self.assertEqual(got["status"], "SKIPPED_NOT_ENABLED")
        self.assertEqual(got["queries_used"], 0)

    def test_index_receipts_are_classified_and_deduplicated_without_price_promotion(self):
        calls = []
        case_to_receipt = {
            "18457369262":"offer_id_exact", "4892210230478":"ean_allegro",
        }
        def fixture_provider(payload,key):
            self.assertIsNone(key)
            calls.append(payload)
            tag = (case_to_receipt["18457369262"] if
                   "18457369262" in payload["query"] else
                   case_to_receipt["4892210230478"] if "4892210230478" in payload["query"]
                   else "model_allegro")
            frozen = self.receipts[tag]["results"]
            return {"results":[{"url":r["url"],"title":r["title"],
                                "content":r["excerpt"],"published_date":r["published_date"]}
                               for r in frozen]}
        got = search_tavily_allegro(BRAND, MODEL, OFFER,
                                  "4892210230478", enabled=True,
                                  provider=fixture_provider)
        self.assertEqual(got["queries_used"],3)
        self.assertEqual(len(calls),3)
        self.assertEqual(got["source_qualified_seller_offers"],0)
        self.assertFalse(got["payment_authorized"])
        self.assertEqual(got["status"],"INDEX_LEADS_FOUND")
        self.assertTrue(all("allegro.pl" in x["url"] for x in got["leads"]))
        self.assertFalse(any(x["offer_id_from_url"]==OFFER for x in got["leads"]))
        self.assertTrue(any(x["indexed_price_claim"]=="197.90" and
                            x["offer_relation"]=="PRODUCT_PAGE_WITHOUT_SINGLE_OFFER_ID"
                            for x in got["leads"]))
        self.assertTrue(any(x["indexed_price_claim"]=="89.00" and
                            x["indexed_condition_claim"]=="USED_CLAIM"
                            for x in got["leads"]))

    def test_reject_unrelated_and_unsafe_hosts_and_search_listing_prices(self):
        bad = [
            "http://allegro.pl/oferta/ryobi-rpi18-0-18457369262",
            "https://allegro.pl.evil.test/oferta/ryobi-rpi18-0-18457369262",
            "https://127.0.0.1/oferta/ryobi-rpi18-0-18457369262",
            "https://spolshy.com.ua/product/18457369262",
            "https://allegro.pl/listing?string=RPI18-0",
        ]
        for url in bad:
            with self.subTest(url=url):
                self.assertIsNone(_identifiable_url(url))
        self.assertIsNone(normalize_index_result({
            "url":"https://allegro.pl/produkt/ryobi-rpi18-0",
            "title":"Ryobi RPI18-1",
            "content":"Ryobi RPI18-1 za 197.90PLN"},BRAND,MODEL,OFFER))

    def test_search_plan_validates_input(self):
        self.assertEqual(len(_search_plan(BRAND, MODEL, OFFER,"4892210230478")),3)
        for model in ("", "RPI18-0?p=1", "/../", "RPI18-0  "):
            with self.subTest(model=model):
                with self.assertRaises(ValueError):
                    _search_plan(BRAND,model,OFFER)
        with self.assertRaises(ValueError):
            _search_plan(BRAND,MODEL,"not-a-real-offer-id")

    def test_cannot_derive_price_from_unrelated_list_or_billing_amount(self):
        self.assertIsNone(normalize_index_result({
            "url":"https://allegro.pl/listing?string=RPI18-0",
            "title":"Ryobi RPI18-0 kompresor",
            "content":"RPI18-0 89.00 PLN 197.90 PLN"}, BRAND, MODEL, OFFER))
        out = normalize_index_result({
            "url":"https://allegro.pl/produkt/ryobi-rpi18-0",
            "title":"Ryobi RPI18-0",
            "content":"10 rat po 19,79 zł, dostawa 10,49 zł"}, BRAND, MODEL, OFFER)
        self.assertIsNotNone(out)
        self.assertIsNone(out["indexed_price_claim"])


if __name__ == "__main__":
    unittest.main()
