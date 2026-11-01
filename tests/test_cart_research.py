"""Cart event -> genuinely async source attempts -> durable pre-checkout report."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cart_research as c

ITEM = {
    "title": "Persil Lessive Poudre Bouquet de Provence 45 Doses 3150 g",
    "price": "34.90", "currency": "PLN", "barcode": "8712561344494",
    "merchant_url": "https://example.org/demo/persil",
}


class CartTests(unittest.TestCase):
    def setUp(self):
        self.item = dict(ITEM)

    def fake_fetch(self, url, host, headers=None):
        if host == "world.openproductsfacts.org":
            return {"products": [
                {"code": "8712561344494",
                 "product_name": self.item["title"], "quantity": "3150 g"},
                {"code": "1234567890123", "product_name": "Persil Poudre 7 Doses", "quantity": "490 g"},
                {"code": "1234567890124", "product_name": "Persil liquide 40 lavages", "quantity": "1.8 L"},
                {"code": "1234567890125", "product_name": "Persil capsules 20", "quantity": "400 g"},
                {"code": "1234567890126", "product_name": "Persil Poudre 85 Doses", "quantity": "5950 g"},
                {"code": "1234567890127", "product_name": "Bouquet de Provence", "quantity": "3150 g"},
            ]}
        if host == "prices.openfoodfacts.org":
            return {"items": [], "total": 0}
        if host == "api.search.brave.com":
            return {"web": {"results": [
                {"title": "Online product price result", "url": "https://store.example.org/persil",
                 "description": "Seller says sale 30 PLN"}]}}
        raise AssertionError("Unexpected host " + host)

    @patch.object(c, "generate_local_ai_questions",
                  return_value=["Do independent tests cover the latest detergent formulation?"])
    def test_laundry_questions_and_live_catalog_are_product_specific(self, ai):
        with patch.dict(c.os.environ, {}, clear=True):
            r = c.research_cart(self.item, fetch=self.fake_fetch)
        self.assertEqual(r["root"]["details"]["category"], "laundry_detergent")
        self.assertEqual(r["root"]["details"]["local_ai_question_generation"], "OK")
        self.assertEqual(len(r["source_discovery"]["catalog"]), 2)
        titles = [x["name"] for x in r["source_discovery"]["catalog"]]
        self.assertTrue(all("Poudre" in x for x in titles))
        qs = [x["title"] for x in r["root"]["children"][1]["children"]]
        self.assertTrue(any("cost per wash" in x for x in qs))
        self.assertTrue(any("latest detergent formulation" in x for x in qs))
        self.assertFalse(any("RAM" in x for x in qs))
        self.assertEqual(r["root"]["children"][-1]["status"], "NO_FORCED_WINNER")
        self.assertFalse(r["root"]["children"][-1]["details"]["payment_authorized"])
        self.assertEqual(r["root"]["children"][-1]["details"]["current_competitor_offers_verified"], 0)
        self.assertIn("SKIPPED_NO_API_KEY", [x["status"]
                          for x in r["source_discovery"]["attempts"]])
        ai.assert_called_once()

    @patch.object(c, "generate_local_ai_questions", side_effect=ValueError("bad json"))
    def test_local_ai_failure_does_not_destroy_tree(self, unused):
        r = c.research_cart(self.item, fetch=self.fake_fetch)
        self.assertGreaterEqual(r["root"]["children"][1]["details"]["question_count"], 10)
        self.assertEqual(r["root"]["details"]["local_ai_question_generation"],
                         "UNAVAILABLE_ValueError")

    @patch.object(c, "generate_local_ai_questions", return_value=[])
    def test_brave_candidates_are_search_hits_not_verified_price(self, unused):
        with patch.dict(c.os.environ, {"BRAVE_API_KEY": "test-only"}, clear=True):
            r = c.research_cart(self.item, fetch=self.fake_fetch)
        self.assertEqual(len(r["source_discovery"]["web_hits"]), 1)
        self.assertEqual(r["source_discovery"]["web_hits"][0]["source_kind"],
                         "UNVERIFIED_SEARCH_RESULT_NOT_A_PRICE_OFFER")
        self.assertEqual(r["root"]["children"][-1]["details"]["current_competitor_offers_verified"], 0)
        self.assertNotIn("30 PLN", str(r["root"]["children"][-1]["details"]))

    def test_laptop_creates_a_different_research_model(self):
        item = {**self.item, "title": "Lenovo ThinkPad X1 laptop",
                "barcode": ""}
        with patch.object(c, "generate_local_ai_questions", return_value=[]):
            r = c.research_cart(item, fetch=lambda u, h, **k: {"products": []})
        q = " ".join(x["title"] for x in r["root"]["children"][1]["children"])
        self.assertIn("battery health", q)
        self.assertNotIn("stain removal", q)
        self.assertEqual(r["root"]["details"]["category"], "laptop")

    def test_cart_validation_blocks_bad_prices_and_urls(self):
        for key, value in [
            ("price", "-2"), ("price", "NaN"), ("currency", "XXX"),
            ("merchant_url", "http://localhost/"), ("merchant_url", "file:///etc/passwd"),
            ("barcode", "ABC12345"),
        ]:
            bad = dict(self.item)
            bad[key] = value
            with self.subTest(field=key, value=value), self.assertRaises(ValueError):
                c.validate_cart(bad)

    def test_model_response_only_questions(self):
        def fake_request(url, method, body, headers, timeout):
            self.assertEqual(url, "http://127.0.0.1:11435/api/chat")
            self.assertNotIn(self.item["merchant_url"], body.decode())
            self.assertNotIn(self.item["price"], body.decode())
            return {"message": {"content": json.dumps(
                {"questions": ["Can a third party measure cost per washing cycle?",
                               "Does the current formula perform at 30°C?"]})}}
        qs = c.generate_local_ai_questions(self.item, "laundry_detergent", [], request=fake_request)
        self.assertEqual(len(qs), 2)
        self.assertTrue(all(x.endswith("?") for x in qs))

    def test_job_starts_immediately_and_survives_status_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "cart.db")
            gate = threading.Event()
            started = threading.Event()
            def slow_runner(item):
                started.set()
                gate.wait(4)
                return {"root": {"status": "NO_FORCED_WINNER"}, "sha256": "abc"}
            jobs = c.CartResearchJobs(db, runner=slow_runner)
            try:
                t = time.monotonic()
                job_id = jobs.submit(self.item)
                self.assertLess(time.monotonic()-t, 0.5)
                self.assertTrue(started.wait(3))
                self.assertEqual(jobs.read(job_id)["state"], "RUNNING")
                gate.set()
                for _ in range(100):
                    if jobs.read(job_id)["state"] == "READY":
                        break
                    time.sleep(.02)
                self.assertEqual(jobs.read(job_id)["report"]["sha256"], "abc")
                with sqlite3.connect(db) as con:
                    self.assertEqual(con.execute(
                        "SELECT state FROM cart_research_jobs WHERE id=?", (job_id,)
                    ).fetchone()[0], "READY")
            finally:
                gate.set()
                jobs.close()

    def test_failed_job_retains_failure_type_without_leaking_error_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "cart.db")
            def fail(item):
                raise RuntimeError("secret-key-do-not-persist")
            jobs = c.CartResearchJobs(db, runner=fail)
            try:
                jid = jobs.submit(self.item)
                for _ in range(100):
                    if jobs.read(jid)["state"] == "FAILED":
                        break
                    time.sleep(.02)
                result = jobs.read(jid)
                self.assertEqual(result["error_type"], "RuntimeError")
                self.assertNotIn("secret-key", str(result))
            finally:
                jobs.close()

    def test_interrupted_job_on_process_restart_is_labeled(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "cart.db")
            jobs = c.CartResearchJobs(db, runner=lambda x: {"ok": True})
            jobs.close()
            with sqlite3.connect(db) as con:
                con.execute("INSERT INTO cart_research_jobs(id,item,state,created)"
                            " VALUES (?,?,?,?)", ("ABCDEF123456789012", json.dumps(self.item),
                                                    "RUNNING", "2026-11-01T00:00:00Z"))
            second = c.CartResearchJobs(db, runner=lambda x: {"ok": True})
            try:
                self.assertEqual(second.read("ABCDEF123456789012")["state"], "INTERRUPTED")
            finally:
                second.close()


if __name__ == "__main__":
    unittest.main()
