"""Frozen receipt assertions for the 2026-11-03 Scrapling HTTP Allegro experiment."""
from pathlib import Path
import json
import unittest

DATA = (Path(__file__).resolve().parent.parent / "benchmarks" / "results" /
        "scrapling_http_allegro_20261103.jsonl")


class AllegroHttpExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = [json.loads(x) for x in DATA.read_text().splitlines()]
        cls.header, *cls.rows = raw
        cls.by_variant = {r["variant"]: r for r in cls.rows}

    def test_no_offer_page_was_retrieved(self):
        self.assertEqual(len(self.rows), 6)
        self.assertEqual(len(self.by_variant), 6)
        for row in self.rows:
            self.assertFalse(row.get("contains_product_reference", False))
            self.assertNotEqual(row["decision"], "PRODUCT_CONTENT")

    def test_four_chrome_profiles_are_blocked_by_datadome(self):
        variants = ("allegro_chrome142", "allegro_chrome131",
                    "allegro_chrome_android", "chrome142_session_after_robots")
        for variant in variants:
            with self.subTest(variant=variant):
                row = self.by_variant[variant]
                self.assertEqual(row["status"], 403)
                self.assertEqual(row["decision"], "ACCESS_DENIED")
                self.assertTrue(row["datadome_cookie_present"])
                self.assertTrue(row["datadome_cid_header"])
                self.assertEqual(row["jsonld_count"], 0)

    def test_session_cookies_not_claimed_as_clearance(self):
        row = self.by_variant["chrome142_session_after_robots"]
        self.assertEqual(row["prior_robots_http_status"], 200)
        self.assertEqual(row["status"], 403)

    def test_timeout_is_not_a_success(self):
        row = self.by_variant["allegro_firefox133"]
        self.assertEqual(row["decision"], "ERROR")
        self.assertIn("Timeout", row["error"])


if __name__ == "__main__":
    unittest.main()
