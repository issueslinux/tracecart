"""HTTP integration: browser companion is separate from cart and checkout."""
from contextlib import closing
import json
from pathlib import Path
import re
import secrets
import tempfile
import threading
import unittest
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import app
from browser_companion_queue import CompanionQueue
from cart_research import CartResearchJobs
from tests.test_browser_companion_queue import sample


class CompanionHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = app.StreamingHTTPServer(("127.0.0.1", 0), app.TraceCartHandler)
        self.server.csrf = secrets.token_urlsafe(24)
        self.server.cart_jobs = CartResearchJobs(
            Path(self.temp.name) / "staging.sqlite",
            runner=lambda item: {})
        self.server.companion = CompanionQueue(token_path=(
            Path(self.temp.name) / "companion.secret"))
        self.base = "http://127.0.0.1:{}".format(self.server.server_port)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.worker.join(timeout=3)
        self.server.server_close()
        self.server.cart_jobs.close()
        self.temp.cleanup()

    def call(self, path, method="GET", payload=None, token=None, origin=None,
             host=None, content_type=None):
        headers = {}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        if origin:
            headers["Origin"] = origin
        if host:
            headers["Host"] = host
        if content_type:
            headers["Content-Type"] = content_type
        body = None
        if payload is not None:
            if content_type == "application/json":
                body = json.dumps(payload).encode("utf8")
            else:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                body = urlencode(payload).encode("utf8")
        try:
            with urlopen(Request(self.base + path, data=body, method=method,
                                 headers=headers), timeout=5) as response:
                return response.status, response.read().decode("utf8")
        except HTTPError as e:
            return e.code, e.read().decode("utf8")

    def test_queue_ui_has_csrf_and_no_auto_checkout(self):
        code, page = self.call("/research/companion")
        self.assertEqual(code, 200)
        self.assertIn("companion/queue", page)
        self.assertIn(self.server.companion.token, page)
        self.assertIn("not seller/checkout verified", page)
        self.assertNotIn("/create</", page)

    def test_cross_origin_enqueue_rejected_and_auth_required(self):
        url = "https://store.example.org/p/123"
        self.assertEqual(self.call("/research/companion/queue", method="POST",
            payload={"csrf": "bad", "product_urls": url},
            origin=self.base)[0], 400)
        self.assertEqual(self.call("/research/companion/queue", method="POST",
            payload={"csrf": self.server.csrf, "product_urls": url},
            origin="https://evil.example.org")[0], 400)
        self.assertEqual(self.call("/api/browser-companion/next")[0], 401)
        self.assertEqual(self.call("/api/browser-companion/next",
                                   token="bad")[0], 401)
        self.assertEqual(self.call("/research/companion",
            host="evil.example.org")[0], 403)
        self.assertEqual(self.server.companion.listed(), [])

    def test_full_explicit_queue_poll_and_post_unverified_result(self):
        url = "https://store.example.org/p/123"
        code, _ = self.call("/research/companion/queue", method="POST",
            payload={"csrf": self.server.csrf, "product_urls": url},
            origin=self.base)
        self.assertEqual(code, 200)  # urllib follows 303 to the UI
        token = self.server.companion.token
        code, body = self.call("/api/browser-companion/next", token=token)
        self.assertEqual(code, 200)
        task = json.loads(body)["job"]
        self.assertEqual(task["url"], url)
        self.assertNotIn("token", task)
        self.assertIsNone(json.loads(self.call("/api/browser-companion/next",
                                              token=token)[1])["job"])
        from datetime import datetime, timezone
        receipt = {"job_id": task["job_id"], "url": task["url"],
                   "captured_at": datetime.now(timezone.utc).isoformat(),
                   "snapshot": sample(), "price_origin":"DIRECT_OFFER_PRICE",
                   "error": None}
        code, body = self.call("/api/browser-companion/result", method="POST",
            token=token, payload=receipt, content_type="application/json",
            origin="chrome-extension://test")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["status"],
                         "PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED")
        rows = self.server.companion.listed()
        self.assertEqual(rows[0]["result"]["fields"]["price"], "34.90")
        self.assertFalse(rows[0]["result"]["seller_verified"])
        code, raw = self.call("/research/companion/"+task["job_id"]+".json")
        self.assertEqual(code, 200)
        evidence = json.loads(raw)
        self.assertEqual(evidence["result"]["fields"]["price"], "34.90")
        self.assertFalse(evidence["result"]["checkout_verified"])
        # Receipt is durable, independent of in-memory queue state.
        latest=self.server.cart_jobs.recent_browser_claim_receipts()
        self.assertEqual(len(latest),1)
        self.assertEqual(latest[0]["result"]["fields"]["price"],"34.90")

    def test_real_http_cart_graph_updates_from_browser_claim_and_survives_queue_reset(self):
        url="https://store.example.org/p/123"
        cart_id="test_browser_graph_12345678"
        item={"title":"Example SKU 7","merchant_url":url,"price":None,
              "currency":None,"barcode":None}
        report={"indexed_shopping":{"indexed_offers":[],"search_result_groups":[]},
                "source_intake":{"intake_status":"URL_ONLY_UNVERIFIED"}}
        with self.server.cart_jobs._db() as db:
            db.execute("""INSERT INTO cart_research_jobs(id,item,state,created,result)
                VALUES (?,?,?,?,?)""",
                (cart_id,json.dumps(item),"READY","2026-11-03T12:00:00+00:00",
                 json.dumps(report)))
        start_code, start_body=self.call("/cart/status/"+cart_id+".knowledge-graph.json")
        self.assertEqual(start_code,200)
        before=json.loads(start_body)
        self.assertEqual(before["stats"]["browser_claims_not_checkout_verified"],0)
        csrf=self.server.csrf
        code,_=self.call("/research/companion/queue",method="POST",
                         payload={"csrf":csrf,"product_urls":url},origin=self.base)
        self.assertEqual(code,200)
        token=self.server.companion.token
        task=json.loads(self.call("/api/browser-companion/next",token=token)[1])["job"]
        from datetime import datetime, timezone
        payload={"job_id":task["job_id"],"url":url,
                 "captured_at":datetime.now(timezone.utc).isoformat(),
                 "snapshot":sample(),"price_origin":"DIRECT_OFFER_PRICE",
                 "error":None}
        code,body=self.call("/api/browser-companion/result",method="POST",
                             token=token,payload=payload,content_type="application/json")
        self.assertEqual(code,200)
        after=json.loads(self.call("/cart/status/"+cart_id+".knowledge-graph.json")[1])
        self.assertGreater(after["stats"]["browser_claims_not_checkout_verified"],0)
        self.assertEqual(after["stats"]["verified_checkout_prices"],0)
        source=[n for n in after["nodes"] if
                n.get("source_kind")=="USER_BROWSER_FILTERED_PROJECTION"]
        self.assertEqual(len(source),1)
        self.assertFalse(source[0]["checkout_verified"])
        live=json.loads(self.call("/cart/status/"+cart_id+"/live.json")[1])
        self.assertEqual(live["graph"]["stats"]["verified_checkout_prices"],0)
        self.assertGreater(live["graph"]["stats"]["browser_claims_not_checkout_verified"],0)
        main_html=self.call("/cart/status/"+cart_id)[1]
        self.assertIn("companion-research-link",main_html)
        self.assertIn("product_url=https%3A%2F%2Fstore.example.org%2Fp%2F123",main_html)
        prefilled=self.call("/research/companion?product_url="+
                            "https%3A%2F%2Fstore.example.org%2Fp%2F123")[1]
        self.assertIn("https://store.example.org/p/123</textarea>",prefilled)
        # Discard only the ephemeral queue; persisted evidence remains
        # in browser page and cart graph.
        self.server.companion=CompanionQueue(token="c"*64)
        page=self.call("/research/companion")[1]
        self.assertIn("34.90 PLN",page)
        saved=json.loads(self.call("/research/companion/"+
                                    task["job_id"]+".json")[1])
        self.assertEqual(saved["result"]["fields"]["price"],"34.90")
        replay=json.loads(self.call("/cart/status/"+cart_id+".knowledge-graph.json")[1])
        self.assertGreater(replay["stats"]["browser_claims_not_checkout_verified"],0)

    def test_bad_receipt_type_and_token_denied(self):
        token = self.server.companion.token
        self.assertEqual(self.call("/api/browser-companion/result",method="POST",
            token="invalid",payload={},content_type="application/json")[0], 401)
        self.assertEqual(self.call("/api/browser-companion/result",method="POST",
            token=token,payload={"html":"<html>"},content_type="application/json")[0], 400)
        self.assertEqual(self.call("/api/browser-companion/result",method="POST",
            token=token,payload={"foo":"bar"})[0], 400)


if __name__ == "__main__":
    unittest.main()
