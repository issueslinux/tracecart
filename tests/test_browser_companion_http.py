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
from tests.test_browser_companion_queue import sample


class CompanionHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = app.StreamingHTTPServer(("127.0.0.1", 0), app.TraceCartHandler)
        self.server.csrf = secrets.token_urlsafe(24)
        self.server.companion = CompanionQueue(token_path=(
            Path(self.temp.name) / "companion.secret"))
        self.base = "http://127.0.0.1:{}".format(self.server.server_port)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.worker.join(timeout=3)
        self.server.server_close()
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
