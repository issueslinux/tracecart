"""Allegro 403 regression: continue with URL-only identity, never fake evidence."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from product_intake import SourceAccessDenied,limited_allegro_identity
from cart_research import CartResearchJobs

ALLEGRO_URL = (
 "https://allegro.pl/produkt/persil-color-pulver-proszek-do-prania-kolor-"
 "4-5-kg-75-pran-niemcy-c57e870f-64f0-49db-91de-502a3f216264?"
 "offerId=18675491436&utm_source=google&utm_medium=product-carousel&"
 "utm_campaign=product-listing&utm_content=%2Flisting%3Fstring%3D"
 "proszek%2520persil%2520niemiec&dd_referrer="
 "https%3A%2F%2Fwww.google.com%2F"
)


class AllegroTests(unittest.TestCase):
    def test_exact_user_url_yields_only_explicitly_limited_identity(self):
        item, meta = limited_allegro_identity(ALLEGRO_URL, "HTTP_403")
        self.assertEqual(meta["allegro_product_id"],
                         "c57e870f-64f0-49db-91de-502a3f216264")
        self.assertEqual(meta["allegro_offer_id"], "18675491436")
        self.assertEqual(meta["intake_status"], "URL_ONLY_UNVERIFIED")
        self.assertIn("4,5 kg", item["title"])
        self.assertIn("75 pran", item["title"])
        self.assertIsNone(item["price"])
        self.assertIsNone(item["currency"])
        self.assertEqual(item["barcode"], "")
        self.assertIsNone(meta["retrieved_at"])
        self.assertIsNone(meta["page_sha256"])
        self.assertNotIn("utm_",item["merchant_url"])
        self.assertNotIn("dd_referrer",str(meta))
        self.assertIn("?offerId=18675491436",item["merchant_url"])
        self.assertIn("NOT downloaded",meta["extraction_method"])

    def test_unrelated_or_unsafe_urls_not_eligible(self):
        examples = [
            "https://example.com/produkt/persil-color-"
            "c57e870f-64f0-49db-91de-502a3f216264",
            "https://allegro.pl/oferta/persil-18675491436",
            "https://allegro.pl/produkt/anything",
            "https://allegro.pl/produkt/a-123-not-uuid",
            "http://allegro.pl/produkt/proszek-"
            "c57e870f-64f0-49db-91de-502a3f216264",
        ]
        for url in examples:
            with self.subTest(url=url),self.assertRaises(ValueError):
                limited_allegro_identity(url,"HTTP_403")

    def test_403_does_not_kill_legal_comparison(self):
        with tempfile.TemporaryDirectory() as root:
            def simulate_analysis(item):
                self.assertIsNone(item["price"])
                return {"root":{"details":{},
                                "children":[
                                    {"kind":"selected","title":"product"},
                                    {"kind":"questions","title":"research"},
                                    {"kind":"summary","title":"conditional",
                                     "status":"NO_FORCED_WINNER",
                                     "details":{"payment_authorized":False}}]},
                        "sha256":"initial"}
            jobs=CartResearchJobs(Path(root)/"cart.sqlite",runner=simulate_analysis)
            try:
                with patch("product_intake.extract_product_page",
                           side_effect=SourceAccessDenied(403)):
                    jid=jobs.submit_url(ALLEGRO_URL)
                    for _ in range(100):
                        x=jobs.read(jid)
                        if x["state"] in ("READY","FAILED"):break
                        time.sleep(.02)
                self.assertEqual(x["state"],"READY")
                self.assertEqual(x["report"]["source_intake"]["access_problem"],
                                 "HTTP_403")
                self.assertEqual(x["report"]["root"]["children"][2]["status"],
                                 "URL_ONLY_UNVERIFIED")
                self.assertFalse(x["report"]["root"]["children"][-1]
                                 ["details"]["payment_authorized"])
            finally:
                jobs.close()

    def test_robots_disallow_uses_only_user_link(self):
        with tempfile.TemporaryDirectory() as root:
            jobs=CartResearchJobs(Path(root)/"cart.sqlite",
                                  runner=lambda item: {"root":{
                                      "details":{},"children":[{}, {}, {}]},
                                      "sha256":"preliminary"})
            try:
                with patch("product_intake.extract_product_page",
                           side_effect=ValueError("Product source blocked by robots.txt")):
                    jid=jobs.submit_url(ALLEGRO_URL)
                    for _ in range(100):
                        x=jobs.read(jid)
                        if x["state"] in ("READY","FAILED"):break
                        time.sleep(.02)
                self.assertEqual(x["state"],"READY")
                self.assertEqual(x["report"]["source_intake"]["access_problem"],
                                 "ROBOTS_DISALLOW")
            finally:
                jobs.close()

    def test_403_on_non_allegro_stays_failed_not_fabricated(self):
        with tempfile.TemporaryDirectory() as root:
            jobs=CartResearchJobs(Path(root)/"cart.sqlite",
                                  runner=lambda item: {"not":"called"})
            try:
                with patch("product_intake.extract_product_page",
                           side_effect=SourceAccessDenied(403)):
                    jid=jobs.submit_url("https://example.org/product/482")
                    for _ in range(100):
                        x=jobs.read(jid)
                        if x["state"] in ("READY","FAILED"):break
                        time.sleep(.02)
                self.assertEqual(x["state"],"FAILED")
                self.assertEqual(x["error_type"],"ValueError")
                self.assertIsNone(x["report"])
            finally:
                jobs.close()


if __name__ == "__main__":
    unittest.main()
