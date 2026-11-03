"""Universal extraction fixtures: no network, browser or API credentials."""
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from universal_product_extract import extract_snapshot, MAX_PAGE_BYTES

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks/fixtures/universal_product_extract_v1.json"
STAMP = "2026-11-03T20:00:00+00:00"


class UniversalProductExtractTests(unittest.TestCase):
    def setUp(self):
        self.dataset = json.loads(CORPUS.read_text(encoding="utf-8"))
        self.cases = {c["id"]: c for c in self.dataset["cases"]}

    def extract(self, case_id):
        c = self.cases[case_id]
        return extract_snapshot(
            c["url"], c["body"].encode("utf-8"), c["mime"],
            c["method"], http_status=c.get("http_status", 200),
            acquired_at=STAMP)

    def test_immutable_offline_fixtures(self):
        self.assertEqual(self.dataset["provenance"],
                         "synthetic_offline_cases_not_retailer_live_data")
        self.assertEqual(len(self.cases), 18)
        self.assertEqual(len({c["url"] for c in self.cases.values()}), 18)
        for case_id, case in self.cases.items():
            with self.subTest(case_id=case_id):
                result = self.extract(case_id)
                self.assertEqual(result["status"], case["status"])
                self.assertEqual(result["fields"]["title"], case.get("title"))
                self.assertEqual(result["fields"]["price"], case.get("price"))
                self.assertEqual(result["fields"]["currency"], case.get("currency"))
                self.assertFalse(result["seller_verified"])
                self.assertFalse(result["checkout_verified"])
                self.assertEqual(len(result["snapshot_sha256"]), 64)
                self.assertEqual(result["acquired_at"], STAMP)
                self.assertEqual(result["source_url"], case["url"])
                for row in result["evidence"]:
                    self.assertFalse(row["seller_verified"])
                    self.assertEqual(row["snapshot_sha256"], result["snapshot_sha256"])
                    self.assertEqual(row["source_url"], case["url"])

    def test_gtin_normalization_and_explicit_shipping_scope(self):
        r = self.extract("jsonld_full")
        self.assertEqual(r["fields"]["gtin"], "08712561344494")
        self.assertEqual(r["fields"]["model"], "TB-18")
        self.assertEqual(r["fields"]["sku"], "TB18-001")
        self.assertEqual(r["fields"]["seller"], "Przykładowy Sklep")
        self.assertEqual(r["fields"]["condition"], "https://schema.org/NewCondition")
        self.assertEqual(r["fields"]["availability"], "https://schema.org/InStock")
        self.assertEqual(r["shipping_claims"][0]["country"], "PL")
        self.assertEqual(r["shipping_claims"][0]["cost"], "12.99")
        self.assertFalse(r["shipping_claims"][0]["seller_verified"])

    def test_jsonld_sale_not_reference_price(self):
        r = self.extract("jsonld_graph_sale")
        self.assertEqual(r["fields"]["price"], "119.00")
        price_evidence = [e for e in r["evidence"] if e["field"] == "price"]
        self.assertNotIn("199.00", [e["value"] for e in price_evidence])
        self.assertIn("/priceSpecification/1/price", price_evidence[0]["pointer"])

    def test_visible_sale_not_regular_price(self):
        r = self.extract("woocommerce")
        self.assertEqual(r["fields"]["price"], "80.00")

    def test_jsonld_visible_conflict_blocks_money(self):
        r = self.extract("jsonld_visible_conflict")
        self.assertIsNone(r["fields"]["price"])
        self.assertIsNone(r["fields"]["currency"])
        self.assertIn("price", r["conflicts"])

    def test_multiple_product_and_offer_fail_closed(self):
        self.assertEqual(self.extract("multiple_products")["evidence"], [])
        self.assertIsNone(self.extract("multiple_offers")["fields"]["price"])

    def test_rendered_dom_is_snapshot_not_js_execution(self):
        r = self.extract("rendered_dom")
        self.assertEqual(r["fields"]["title"], "Produkt po renderowaniu JS")
        self.assertEqual(r["acquisition_method"], "RENDERED_DOM")

    def test_index_source_is_not_seller_confirmation(self):
        r = self.extract("index_only")
        self.assertTrue(r["index_only"])
        self.assertEqual(r["fields"]["price"], "95.50")
        self.assertFalse(r["seller_verified"])
        self.assertEqual(r["status"], "INDEX_ONLY_UNVERIFIED")

    def test_http_200_with_challenge_is_not_success(self):
        r = self.extract("captcha_200")
        self.assertEqual(r["status"], "ACCESS_CHALLENGE")
        self.assertEqual(r["evidence"], [])

    def test_unstructured_numeric_text_never_establishes_price(self):
        r = self.extract("unrelated_page")
        self.assertIsNone(r["fields"]["price"])
        self.assertEqual(r["status"], "PRODUCT_NOT_IDENTIFIED")

    def test_invalid_gtin_invalidates_identity(self):
        r = self.extract("invalid_gtin")
        self.assertEqual(r["status"], "IDENTITY_CONFLICT")
        self.assertIsNone(r["fields"]["gtin"])

    def test_input_guardrails_no_fetch_and_safe_urls(self):
        for url in ("http://store.example.org/item", "https://127.0.0.1/x",
                    "https://user:pass@store.example.org/x", "file:///tmp/test",
                    "https://store.example.org:8443/item"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                extract_snapshot(url, b"<html>Hi</html>")
        with self.assertRaises(ValueError):
            extract_snapshot("https://store.example.org/item", b"x"*(MAX_PAGE_BYTES+1))
        with self.assertRaisesRegex(ValueError, "UNKNOWN_ACQUISITION_METHOD"):
            extract_snapshot("https://store.example.org/item", b"x",
                             acquisition_method="PAID_API")
        with self.assertRaisesRegex(ValueError, "INVALID_ACQUISITION_TIME"):
            extract_snapshot("https://store.example.org/item", b"x",
                             acquired_at="2026-11-03")
        with self.assertRaisesRegex(ValueError, "SNAPSHOT_MUST_BE_BOUNDED_BYTES"):
            extract_snapshot("https://store.example.org/item", "str not bytes")


if __name__ == "__main__":
    unittest.main()
