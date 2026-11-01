"""HTTP-level regression tests: real loopback server, no real AI or PayPal API."""
import json
from pathlib import Path
import re
import secrets
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from core import CheckoutStore, CONSENT_TEXT

class MockPayPal:
    def __init__(self):
        self.created = 0
        self.reads = 0
        self.timeout = False
        self.record = None

    def create_order(self, record):
        self.created += 1
        self.record = record.copy()
        if self.timeout:
            raise TimeoutError("simulated uncertain sandbox response")
        return self._response(record)

    def get_order(self, oid):
        self.reads += 1
        if oid != "FAKEORDER123":
            raise ValueError("order not found")
        return self._response(self.record)

    @staticmethod
    def _response(record):
        return {
            "id": "FAKEORDER123",
            "status": "CREATED",
            "purchase_units": [{"reference_id": record["id"],
                                "amount": {"currency_code": "USD", "value": record["total"]}}],
            "links": [{"rel": "approve",
                       "href": "https://www.sandbox.paypal.com/checkoutnow?token=FAKEORDER123"}],
        }


class WebFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ready = threading.Event()
        self.done = threading.Event()
        self.port = None
        self.host_thread = threading.Thread(target=self._host_server, daemon=True)
        self.host_thread.start()
        self.assertTrue(self.ready.wait(5))
        self.base = "http://127.0.0.1:{}".format(self.port)
        response = self.request("GET", "/")
        self.assertEqual(response[0], 200)
        self.csrf = re.search(r'name="csrf" value="([^"]+)"', response[1]).group(1)

    def _host_server(self):
        from http.server import HTTPServer
        server = HTTPServer(("127.0.0.1", 0), app.TraceCartHandler)
        server.store = CheckoutStore(str(Path(self.tmp.name) / "webquotes.sqlite"))
        server.csrf = secrets.token_urlsafe(24)
        self.server = server
        self.port = server.server_port
        self.ready.set()
        try:
            server.serve_forever(poll_interval=0.03)
        finally:
            server.server_close()
            server.store.db.close()
            self.done.set()

    def tearDown(self):
        self.server.shutdown()
        self.assertTrue(self.done.wait(5))
        self.host_thread.join(timeout=2)
        self.tmp.cleanup()

    def request(self, method, path, form=None, headers=None):
        h = {"Origin": self.base} if method == "POST" else {}
        if headers:
            h.update(headers)
        if form is not None:
            h["Content-Type"] = "application/x-www-form-urlencoded"
            data = urlencode(form).encode()
        else:
            data = b"" if method == "POST" else None
        req = Request(self.base + path, data=data, headers=h, method=method)
        try:
            with urlopen(req, timeout=15) as response:
                return response.status, response.read().decode()
        except HTTPError as exc:
            return exc.code, exc.read().decode()

    def quote(self):
        with patch.object(app, "ollama_suggestion", return_value=("ceramic-pendant", 2, "58.00")) as model:
            status, page = self.request("POST", "/propose", {
                "csrf": self.csrf, "description": "Two ceramic pendants please"
            })
            model.assert_called_once()
        self.assertEqual(status, 200)
        self.assertIn("58.00 USD", page)
        qid = re.search(r'name="quote_id" type="hidden" value="([^"]+)"', page).group(1)
        return qid

    def test_real_http_flow_blocked_without_consent_and_fake_gateway_only(self):
        qid = self.quote()
        paypal = MockPayPal()
        with patch.object(app, "SandboxPayPal", return_value=paypal):
            # POST without consent must fail and never invoke the gateway.
            status, _ = self.request("POST", "/create", {
                "csrf": self.csrf, "quote_id": qid
            })
            self.assertEqual(status, 400)
            self.assertEqual(paypal.created, 0)
            status, _ = self.request("POST", "/approve", {
                "csrf": self.csrf, "quote_id": qid,
                "consent": CONSENT_TEXT, "expected_total": "0.01"
            })
            self.assertEqual(status, 400)
            status, approved = self.request("POST", "/approve", {
                "csrf": self.csrf, "quote_id": qid,
                "consent": CONSENT_TEXT, "expected_total": "58.00"
            })
            self.assertEqual(status, 200)
            self.assertIn("APPROVED", approved)
            status, created = self.request("POST", "/create", {
                "csrf": self.csrf, "quote_id": qid
            })
            self.assertEqual(status, 200)
            self.assertIn("PAYER_ACTION_REQUIRED", created)
            self.assertIn("FAKEORDER123", created)
            self.assertEqual(paypal.created, 1)
            self.assertEqual(paypal.record["total"], "58.00")
            status, _ = self.request("POST", "/create", {
                "csrf": self.csrf, "quote_id": qid
            })
            self.assertEqual(status, 400)
            self.assertEqual(paypal.created, 1)
        status, _ = self.request("GET", "/quote/" + qid)
        self.assertEqual(status, 200)

    def test_timeout_recovery_is_get_only_from_web_ui(self):
        qid = self.quote()
        paypal = MockPayPal()
        paypal.timeout = True
        with patch.object(app, "SandboxPayPal", return_value=paypal):
            status, _ = self.request("POST", "/approve", {
                "csrf": self.csrf, "quote_id": qid,
                "consent": CONSENT_TEXT, "expected_total": "58.00"
            })
            self.assertEqual(status, 200)
            status, _ = self.request("POST", "/create", {
                "csrf": self.csrf, "quote_id": qid
            })
            self.assertEqual(status, 400)
            status, uncertain = self.request("GET", "/quote/" + qid)
            self.assertEqual(status, 200)
            self.assertIn("CREATE_UNCERTAIN", uncertain)
            self.assertIn("GET only", uncertain)
            paypal.timeout = False
            status, recovered = self.request("POST", "/reconcile", {
                "csrf": self.csrf, "quote_id": qid, "order_id": "FAKEORDER123"
            })
            self.assertEqual(status, 200)
            self.assertIn("PAYER_ACTION_REQUIRED", recovered)
            self.assertEqual(paypal.created, 1)
            self.assertEqual(paypal.reads, 1)

    def test_cross_origin_host_and_csrf_rejected(self):
        status, _ = self.request("GET", "/", headers={"Host": "malicious.example"})
        self.assertEqual(status, 403)
        status, _ = self.request("POST", "/propose", {
            "csrf": self.csrf, "description": "Two ceramic pendants please"
        }, headers={"Origin": "null"})
        self.assertEqual(status, 400)
        status, _ = self.request("POST", "/propose", {
            "csrf": "BAD", "description": "Two ceramic pendants please"
        })
        self.assertEqual(status, 400)
        status, _ = self.request("POST", "/propose", {
            "csrf": self.csrf, "description": "Two ceramic pendants please"
        }, headers={"Host": "malicious.example"})
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
