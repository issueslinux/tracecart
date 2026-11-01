import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import base64
from urllib.parse import urlparse
from unittest.mock import patch, call

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import (CATALOG, CONSENT_TEXT, CheckoutStore, SandboxPayPal,
                  parse_model_selection, validate_paypal_result, money)


class FakeSandbox:
    def __init__(self, fail=False, url="https://www.sandbox.paypal.com/checkoutnow?token=FAKEORDER123"):
        self.calls = []
        self.fail = fail
        self.url = url

    def create_order(self, record):
        self.calls.append(record.copy())
        if self.fail:
            raise TimeoutError("Simulated uncertain network timeout")
        return {"id": "FAKEORDER123", "status": "CREATED",
                "purchase_units": [{"reference_id": record.get("id", "dummy-id"),
                                    "amount": {"currency_code": "USD",
                                               "value": record.get("total", "29.00")}}],
                "links": [{"rel": "approve", "href": self.url}]}

    def get_order(self, order_id):
        if order_id != "FAKEORDER123":
            raise ValueError("Unknown sandbox order")
        return self.create_order(self.expected_record)


class CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CheckoutStore(str(Path(self.tmp.name) / "quotes.db"))

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def test_catalog_rejects_price_injection_and_unknown_product(self):
        with self.assertRaises(ValueError):
            parse_model_selection('{"sku":"ceramic-pendant","quantity":1,"amount":"0.01"}')
        with self.assertRaises(ValueError):
            parse_model_selection('{"sku":"custom-product","quantity":1}')
        with self.assertRaises(ValueError):
            parse_model_selection('{"sku":"ceramic-pendant","quantity":2.0}')
        with self.assertRaises(ValueError):
            parse_model_selection('{"sku":"ceramic-pendant","quantity":true}')
        self.assertEqual(parse_model_selection('{"sku":"ceramic-pendant","quantity":2}'),
                         ("ceramic-pendant", 2, "58.00"))

    def test_requires_exact_explicit_approval(self):
        q = self.store.quote("ceramic-pendant", 2)
        self.assertEqual(q["total"], "58.00")
        self.assertEqual(q["state"], "QUOTED")
        client = FakeSandbox()
        with self.assertRaises(ValueError):
            self.store.create_sandbox_order(q["id"], client)
        self.assertEqual(len(client.calls), 0)
        for phrase, total in [(CONSENT_TEXT, "29.00"), ("approve", "58.00")]:
            with self.assertRaises(ValueError):
                self.store.approve(q["id"], phrase, total)
        self.assertEqual(self.store.read(q["id"])["state"], "QUOTED")
        approved = self.store.approve(q["id"], CONSENT_TEXT, "58.00")
        self.assertEqual(approved["state"], "APPROVED")
        self.assertEqual(self.store.events(q["id"])[-1]["event"], "HUMAN_APPROVED")

    def test_create_sandbox_once_and_never_capture(self):
        q = self.store.quote("archive-consult", 1)
        self.store.approve(q["id"], CONSENT_TEXT, q["total"])
        client = FakeSandbox()
        row = self.store.create_sandbox_order(q["id"], client)
        self.assertEqual(row["state"], "PAYER_ACTION_REQUIRED")
        self.assertEqual(row["paypal_id"], "FAKEORDER123")
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["total"], "75.00")
        self.assertNotIn("request_id", row)
        with self.assertRaises(ValueError):
            self.store.create_sandbox_order(q["id"], client)
        self.assertEqual(len(client.calls), 1)

    def test_timeout_fail_closed_never_replayed(self):
        q = self.store.quote("restoration-kit", 1)
        self.store.approve(q["id"], CONSENT_TEXT, q["total"])
        client = FakeSandbox(fail=True)
        with self.assertRaises(TimeoutError):
            self.store.create_sandbox_order(q["id"], client)
        self.assertEqual(self.store.read(q["id"])["state"], "CREATE_UNCERTAIN")
        with self.assertRaises(ValueError):
            self.store.create_sandbox_order(q["id"], client)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(self.store.events(q["id"])[-1]["event"],
                         "CREATE_UNCERTAIN_NEEDS_RECONCILIATION")

    def test_expired_quote_blocks_approval(self):
        q = self.store.quote("ceramic-pendant", 1)
        self.store.db.execute("UPDATE quotes SET created=0 WHERE id=?", (q["id"],))
        with self.assertRaisesRegex(ValueError, "expired"):
            self.store.approve(q["id"], CONSENT_TEXT, "29.00")

    def test_expired_approval_blocks_payment(self):
        q = self.store.quote("ceramic-pendant", 1)
        self.store.approve(q["id"], CONSENT_TEXT, q["total"])
        self.store.db.execute("UPDATE quotes SET approved=0 WHERE id=?", (q["id"],))
        with self.assertRaisesRegex(ValueError, "expired"):
            self.store.create_sandbox_order(q["id"], FakeSandbox())
        self.assertEqual(self.store.read(q["id"])["state"], "APPROVED")

    def test_reject_live_or_untrusted_redirect(self):
        for u in ("https://www.paypal.com/checkoutnow?token=x",
                  "https://www.sandbox.paypal.com.evil.org/",
                  "http://www.sandbox.paypal.com/",
                  "https://attacker@www.sandbox.paypal.com/"):
            with self.subTest(url=u):
                with self.assertRaises(ValueError):
                    validate_paypal_result(FakeSandbox(url=u).create_order({}))

    def test_missing_credentials_fails_before_request(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "credentials missing"):
                SandboxPayPal()

    def test_audit_does_not_leak_idempotency(self):
        q = self.store.quote("ceramic-pendant", 1)
        self.assertNotIn("request_id", q)
        self.assertNotIn("request_id", json.dumps(self.store.events(q["id"])))


    def test_gateway_amount_mismatch_is_blocked_after_approval(self):
        for kind in ("amount", "currency", "reference", "missing"):
            with self.subTest(kind=kind):
                q = self.store.quote("ceramic-pendant", 2)
                self.store.approve(q["id"], CONSENT_TEXT, q["total"])
                fake = FakeSandbox()
                original = fake.create_order

                def corrupted(record):
                    response = original(record)
                    if kind == "amount":
                        response["purchase_units"][0]["amount"]["value"] = "0.01"
                    elif kind == "currency":
                        response["purchase_units"][0]["amount"]["currency_code"] = "EUR"
                    elif kind == "reference":
                        response["purchase_units"][0]["reference_id"] = "other-quote"
                    else:
                        response.pop("purchase_units")
                    return response

                fake.create_order = corrupted
                with self.assertRaisesRegex(ValueError, "purchase"):
                    self.store.create_sandbox_order(q["id"], fake)
                self.assertEqual(self.store.read(q["id"])["state"], "CREATE_UNCERTAIN")
                self.assertEqual(self.store.events(q["id"])[-1]["event"],
                                 "CREATE_UNCERTAIN_NEEDS_RECONCILIATION")

    def test_read_only_reconciliation_matches_purchase_and_never_posts(self):
        q = self.store.quote("restoration-kit", 2)
        self.store.approve(q["id"], CONSENT_TEXT, q["total"])
        fake = FakeSandbox(fail=True)
        with self.assertRaises(TimeoutError):
            self.store.create_sandbox_order(q["id"], fake)
        self.assertEqual(len(fake.calls), 1)
        fake.fail = False
        fake.expected_record = self.store._internal_read(q["id"])
        row = self.store.reconcile_sandbox_order(q["id"], "FAKEORDER123", fake)
        self.assertEqual(row["state"], "PAYER_ACTION_REQUIRED")
        self.assertEqual(row["paypal_id"], "FAKEORDER123")
        self.assertEqual(len(fake.calls), 2)  # second call only emulates a GET, not POST
        self.assertEqual(self.store.events(q["id"])[-1]["event"],
                         "MANUAL_READ_ONLY_ORDER_RECONCILIATION")
        with self.assertRaises(ValueError):
            self.store.reconcile_sandbox_order(q["id"], "FAKEORDER123", fake)

    def test_reconcile_rejects_wrong_order_and_keeps_uncertain_state(self):
        q = self.store.quote("ceramic-pendant", 1)
        self.store.approve(q["id"], CONSENT_TEXT, q["total"])
        fake = FakeSandbox(fail=True)
        with self.assertRaises(TimeoutError):
            self.store.create_sandbox_order(q["id"], fake)
        fake.fail = False
        fake.expected_record = self.store._internal_read(q["id"])
        for bad in ("OTHERORDER123", "FAKEORDER123/../", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.store.reconcile_sandbox_order(q["id"], bad, fake)
                self.assertEqual(self.store.read(q["id"])["state"], "CREATE_UNCERTAIN")

    @patch("core._request_json")
    def test_credential_auth_failure_does_not_consume_approval(self, request):
        request.return_value = {"error": "invalid_client"}
        q = self.store.quote("ceramic-pendant", 1)
        self.store.approve(q["id"], CONSENT_TEXT, q["total"])
        with self.assertRaisesRegex(ValueError, "token"):
            self.store.create_sandbox_order(q["id"], SandboxPayPal("bad-id", "bad-secret"))
        self.assertEqual(self.store.read(q["id"])["state"], "APPROVED")
        self.assertEqual(request.call_count, 1)

    @patch("core._request_json")
    def test_paypal_sandbox_http_contract(self, request):
        sandbox = SandboxPayPal("fake-id", "fake-secret")
        row = {"id": "quote-123", "sku": "ceramic-pendant",
               "total": "58.00", "quantity": 2, "request_id": "dedupe-123"}
        response = FakeSandbox().create_order(row)
        request.side_effect = [
            {"access_token": "sample-token", "token_type": "Bearer"},
            response,
            {"access_token": "second-token", "token_type": "Bearer"},
            response,
        ]
        returned = sandbox.create_order(row)
        self.assertEqual(returned, response)
        self.assertEqual(sandbox.get_order("FAKEORDER123"), response)
        self.assertEqual(request.call_count, 4)
        auth = request.call_args_list[0][0]
        self.assertEqual(auth[0], "https://api-m.sandbox.paypal.com/v1/oauth2/token")
        self.assertEqual(auth[1], "POST")
        self.assertEqual(auth[2], b"grant_type=client_credentials")
        self.assertEqual(base64.b64decode(auth[3]["Authorization"].split()[1]),
                         b"fake-id:fake-secret")
        create = request.call_args_list[1][0]
        self.assertEqual(create[0], "https://api-m.sandbox.paypal.com/v2/checkout/orders")
        self.assertEqual(create[1], "POST")
        self.assertEqual(create[3]["PayPal-Request-Id"], "dedupe-123")
        self.assertEqual(create[3]["Authorization"], "Bearer sample-token")
        body = json.loads(create[2])
        self.assertEqual(body["intent"], "CAPTURE")
        self.assertEqual(body["purchase_units"][0]["amount"],
                         {"currency_code": "USD", "value": "58.00"})
        self.assertEqual(body["purchase_units"][0]["reference_id"], "quote-123")
        self.assertNotIn("capture", create[0])
        read = request.call_args_list[3][0]
        self.assertEqual(read[1], "GET")
        self.assertIsNone(read[2])
        self.assertEqual(read[0],
                         "https://api-m.sandbox.paypal.com/v2/checkout/orders/FAKEORDER123")

    @patch("core._request_json")
    def test_broken_oauth_never_sends_order(self, request):
        request.return_value = {"access_token": "", "token_type": "Bearer"}
        client = SandboxPayPal("fake-id", "fake-secret")
        with self.assertRaises(ValueError):
            client.create_order({"id": "quote-123", "sku": "ceramic-pendant",
                                 "total": "29.00", "request_id": "dedupe-1"})
        self.assertEqual(request.call_count, 1)

    def test_redirect_order_token_mismatch_and_custom_port_blocked(self):
        fake = FakeSandbox()
        record = {"id": "quote-123", "total": "29.00"}
        response = fake.create_order(record)
        for url in ("https://www.sandbox.paypal.com:444/checkoutnow?token=FAKEORDER123",
                    "https://www.sandbox.paypal.com/checkoutnow?token=ATTACKER123",
                    "https://www.sandbox.paypal.com/checkoutnow"):
            with self.subTest(url=url):
                response["links"][0]["href"] = url
                with self.assertRaises(ValueError):
                    validate_paypal_result(response, record)

    def test_external_price_is_never_taken_from_model(self):
        self.assertEqual(money(CATALOG["restoration-kit"][1] * 3), "117.00")
        for bad in (0, 4, -1, True, "2", 0.5):
            with self.subTest(quantity=bad):
                with self.assertRaises(ValueError):
                    self.store.quote("restoration-kit", bad)


if __name__ == "__main__":
    unittest.main()
