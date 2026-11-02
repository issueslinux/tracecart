"""DataForSEO explicit paid tasks and asynchronous result interpretation."""
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dataforseo_shopping import (queue_dataforseo_products,
                                  collect_dataforseo_products,
                                  parse_dataforseo_products_result)
from benchmarks.shopping_search_eval import (comparison_report, load_dataset,
                                               report_serpapi, report_dataforseo_enqueue)


IDS = ["4b733bb2-4555-4af5-8561-b62718ca1c11",
       "4b733bb2-4555-4af5-8561-b62718ca1c12"]


def post_response():
    return {
        "status_code": 20000,
        "tasks": [{"id": i, "status_code": 20100} for i in IDS],
    }


def get_response(task_id, pending=False):
    return {
        "status_code": 20000,
        "tasks": [{"id": task_id, "status_code": 20100 if pending else 20000,
                   "result": None if pending else [{
                       "items": [
                           {"type": "google_shopping_serp", "seller": "Allegro",
                            "title": "Stanley Air Kit OL195", "price": 229.0,
                            "currency": "PLN", "url": None},
                           {"type": "google_shopping_serp", "seller": "Other",
                            "title": "Stanley Air Kit OL195", "price": 360.0,
                            "currency": "PLN", "url": "https://shop.example.org/product/stanley"},
                           {"type": "google_shopping_serp", "seller": "Broken",
                            "title": "Stanley", "price": 99.0,
                            "currency": "WRONG"},
                       ],
                   }]}],
    }


class DataForSEOTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            {"id": "P01", "title": "Stanley Air Kit OL 195", "barcode": "8016738753899"},
            {"id": "P02", "title": "Sony WH-1000XM5", "barcode": ""},
        ]

    def test_queued_explicitly_without_credentials_leak(self):
        called = []
        def request(url, method, credentials, body=None):
            called.append((url, method, body))
            self.assertEqual(method, "POST")
            self.assertEqual(len(body), 2)
            self.assertEqual(body[0]["language_code"], "pl")
            self.assertEqual(body[0]["location_name"], "Poland")
            self.assertIn("8016738753899", body[0]["keyword"])
            self.assertFalse("api_secret" in url)
            return post_response()
        queued = queue_dataforseo_products(
            self.items, ("login", "password"), requester=request,
            allow_paid=True)
        self.assertEqual(queued["sample_count"], 2)
        self.assertEqual(queued["status"], "QUEUED_PROVIDER_ASYNC_NOT_PRICE_RESULTS")
        self.assertEqual([r["task_id"] for r in queued["task_ids"]], IDS)
        self.assertNotIn("password", json.dumps(queued))
        self.assertEqual(len(called), 1)

    def test_queue_never_starts_without_explicit_paid_gate(self):
        with self.assertRaises(ValueError):
            queue_dataforseo_products(self.items, ("a", "b"),
                                      requester=lambda *x: self.fail("paid call"))
        for bad in ([], self.items * 11):
            with self.assertRaises(ValueError):
                queue_dataforseo_products(bad, ("a", "b"), allow_paid=True)

    def test_collect_finished_and_pending_without_reposting_tasks(self):
        queued = queue_dataforseo_products(
            self.items, ("a", "b"), requester=lambda *a: post_response(),
            allow_paid=True)
        methods = []
        def request(url, method, credentials):
            methods.append(method)
            return get_response(url.split("/")[-1], pending=url.endswith(IDS[1]))
        collected = collect_dataforseo_products(
            queued, ("a", "b"), requester=request)
        self.assertEqual(methods, ["GET", "GET"])
        self.assertEqual(collected["completed_count"], 1)
        self.assertEqual(collected["results"][0]["status"], "INDEXED_OFFERS_AVAILABLE")
        self.assertEqual(collected["results"][0]["offers"][0]["seller"], "Allegro")
        self.assertIsNone(collected["results"][0]["offers"][0]["merchant_url"])
        self.assertEqual(collected["results"][0]["offers"][0]["indexed_price"], "229.00")
        self.assertEqual(collected["results"][1]["status"], "PENDING_OR_NO_RESULT")
        self.assertEqual(collected["results"][1]["offers"], [])
        self.assertFalse(collected["payment_authorized"])

    def test_search_provider_comparison_is_explicit_about_missing_truth(self):
        indexed_a = {"results": [
            {"sample_id": "P01", "status": "INDEXED_STORES_WITHOUT_SELLER_VERIFICATION",
             "marketplace_hosts_seen": ["allegro.pl"], "indexed_store_count": 2},
        ]}
        indexed_b = {"results": [
            {"sample_id": "P01", "status": "INDEXED_OFFERS_AVAILABLE",
             "marketplace_sellers": ["Allegro"],
             "offers": [{"seller": "Allegro", "indexed_price": "229.00"}]},
        ]}
        report = comparison_report(indexed_a, indexed_b)
        self.assertEqual(report["products_with_both_provider_results"], 1)
        self.assertEqual(report["independently_verified_price_accuracy"], "NOT_MEASURED")
        self.assertTrue(report["provider_coverage_not_market_completeness"])

    def test_real_sample_dataset_has_20_named_products_but_no_fake_results(self):
        data = load_dataset(str(Path(__file__).resolve().parents[1] /
                                "benchmarks/shopping_20_products.json"))
        self.assertEqual(len(data["products"]), 20)
        self.assertEqual(sum(bool(x["barcode"]) for x in data["products"]), 1)


if __name__ == "__main__":
    unittest.main()
