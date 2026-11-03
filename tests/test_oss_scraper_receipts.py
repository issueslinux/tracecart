"""Offline contract checks for the frozen 2026-11-03 OSS scraper experiment."""
import json
from pathlib import Path
import unittest

DATA = (Path(__file__).resolve().parents[1] /
        "benchmarks/results/oss_scraper_20261103.jsonl")
ENGINES = {"scrapling_http", "scrapling_browser", "crawl4ai",
           "pricestalker_browser"}
PRODUCTS = {"ryobi_r18pi": ("R18PI-0", "239.99"),
            "ryobi_rpi18": ("RPI18-0", "249.99"),
            "mediaexpert_rpi18": ("1259301", "243.71")}


class ScraperEvidenceReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = [json.loads(line) for line in DATA.read_text().splitlines()]
        cls.map = {(row["target"], row["engine"]): row for row in cls.rows}

    def test_all_20_cases_executed(self):
        self.assertEqual(len(self.rows), 20)
        self.assertEqual(len(self.map), 20)
        for target in (*PRODUCTS, "allegro_rpi18", "js_control"):
            for engine in ENGINES:
                self.assertIn((target, engine), self.map)

    def test_product_prices_are_declared_not_checkout(self):
        for target, (sku, price) in PRODUCTS.items():
            for engine in ENGINES:
                row = self.map[(target, engine)]
                with self.subTest(target=target, engine=engine):
                    self.assertEqual(row["result"], "PRODUCT_STRUCTURED")
                    self.assertEqual(row["structured_products"][0]["sku"], sku)
                    self.assertEqual(row["structured_products"][0]["offers"][0]["price"], price)
                    self.assertTrue(row["sha256"] and len(row["sha256"]) == 64)
                    self.assertGreater(row["html_bytes"], 1000)
                    self.assertNotIn("checkout_verified", row)

    def test_allegro_refused_all_engines(self):
        for engine in ENGINES:
            row = self.map[("allegro_rpi18", engine)]
            with self.subTest(engine=engine):
                self.assertIn(row["result"], ("HTTP_BLOCKED", "BLOCKED_CHALLENGE"))
                self.assertFalse(row["structured_products"])
                self.assertEqual(row["price_evidence_count"], 0)
                self.assertIsNone(row["error"])

    def test_js_rendering_requires_browser(self):
        self.assertEqual(self.map[("js_control", "scrapling_http")]["rendered_quote_count"], 0)
        for engine in ENGINES - {"scrapling_http"}:
            self.assertEqual(self.map[("js_control", engine)]["rendered_quote_count"], 10)


if __name__ == "__main__":
    unittest.main()
