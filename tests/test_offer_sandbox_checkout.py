"""Offline tests for recommendation-bound PayPal Sandbox approvals; no network."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import secrets
import threading

import app
import offer_sandbox_checkout as checkout


class FakeResearch:
    def __init__(self):
        self.state = "READY"
        self.price = "132.60"
    def read(self, jid):
        if jid != "researchJob1234567890":
            raise ValueError("UNKNOWN_JOB")
        return {"state":self.state}
    def live_snapshot(self, jid):
        self.read(jid)
        return 1,{
            "instant_assessment":{"purchase_insights":{"options":[{
                "offer_id":"offer-1","title":"Ryobi R18PI-0",
                "price":self.price,"currency":"PLN",
                "source_url":"https://www.example.com/ryobi",
            }],"tradeoffs":[]}},
            "graph":{"nodes":[{"id":"offer-1","type":"offer"}]},
        }


class FakeGateway:
    def __init__(self):
        self.preflights=0
        self.reads=0
        self.approved=False
        self.id="FAKEORDER123"
    def preflight(self):
        self.preflights+=1
    def _token(self):
        return "fake-token"
    def get_order(self, oid):
        self.reads+=1
        assert oid==self.id
        return {
            "id":self.id,
            "status":"APPROVED" if self.approved else "CREATED",
            "purchase_units":[{"reference_id":self.quote_id,
                               "amount":{"currency_code":"PLN","value":"132.60"}}],
        }


class OfferSandboxTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=str(Path(self.temp.name)/"quote.sqlite3")
        self.store=checkout.OfferSandboxOrders(self.path)
        self.research=FakeResearch()
    def tearDown(self):
        self.temp.cleanup()
    def select(self):
        return self.store.select(self.research,"researchJob1234567890","offer-1")

    def test_selected_offer_locked_to_server_evidence(self):
        qid=self.select()
        row=self.store.read(qid)
        self.assertEqual((row["total"],row["currency"],row["title"]),
                         ("132.60","PLN","Ryobi R18PI-0"))
        self.assertNotIn("request_id",row)
        with self.assertRaisesRegex(ValueError,"RECOMMENDATION_NOT_FOUND"):
            self.store.select(self.research,"researchJob1234567890","offer-2")
        self.research.price="0.001"
        with self.assertRaisesRegex(ValueError,"INVALID_INDEXED_AMOUNT"):
            self.select()
        self.research.price="132.60"
        self.research.state="RUNNING"
        with self.assertRaisesRegex(ValueError,"RESEARCH_NOT_READY"):
            self.select()

    def test_wrong_consent_and_amount_no_sandbox_order(self):
        qid=self.select()
        for consent, amount in (("wrong","132.60"),(checkout.CONSENT,"0.01")):
            with self.assertRaisesRegex(ValueError,"CONSENT_OR_AMOUNT_MISMATCH"):
                self.store.approve(qid,consent,amount)
        self.assertEqual(self.store.read(qid)["state"],"QUOTED")

    def test_one_shot_sandbox_order_no_capture_and_readonly_get(self):
        qid=self.select()
        self.store.approve(qid,checkout.CONSENT,"132.60")
        fake=FakeGateway()
        fake.quote_id=qid
        calls=[]
        def fake_request(url,method,body,headers,timeout=15):
            calls.append((url,method,body,headers))
            self.assertTrue(url.endswith("/v2/checkout/orders"))
            self.assertEqual(method,"POST")
            self.assertEqual(headers["PayPal-Request-Id"],
                             self.store.read(qid,internal=True)["request_id"])
            import json
            data=json.loads(body)
            expected_return="http://127.0.0.1:8810/cart/sandbox/"+qid
            self.assertEqual(
                data["payment_source"]["paypal"]["experience_context"]["return_url"],
                expected_return)
            self.assertEqual(
                data["payment_source"]["paypal"]["experience_context"]["cancel_url"],
                expected_return)
            self.assertEqual(data["purchase_units"][0]["amount"],
                             {"currency_code":"PLN","value":"132.60"})
            self.assertNotIn("capture",url)
            return {"id":fake.id,"status":"CREATED",
                    "purchase_units":[{"reference_id":qid,
                                       "amount":{"currency_code":"PLN","value":"132.60"}}],
                    "links":[{"rel":"approve",
                        "href":"https://www.sandbox.paypal.com/checkoutnow?token="+fake.id}]}
        with patch.object(checkout,"_request_json",side_effect=fake_request):
            row=self.store.create(qid,fake)
        self.assertEqual(row["state"],"PAYER_ACTION_REQUIRED")
        self.assertEqual(len(calls),1)
        with self.assertRaisesRegex(ValueError,"SANDBOX_ORDER_ALREADY_STARTED"):
            self.store.create(qid,fake)
        self.assertEqual(self.store.verify(qid,fake)["state"],"PAYER_ACTION_REQUIRED")
        fake.approved=True
        self.assertEqual(self.store.verify(qid,fake)["state"],"VERIFIED_APPROVED")
        self.assertEqual(len(calls),1)

    def test_tampered_paypal_reply_must_leave_create_uncertain(self):
        qid=self.select()
        self.store.approve(qid,checkout.CONSENT,"132.60")
        fake=FakeGateway()
        def tamper(*a,**kw):
            return {"id":"FAKEORDER123","status":"CREATED",
                    "purchase_units":[{"reference_id":qid,
                                       "amount":{"currency_code":"PLN","value":"0.01"}}],
                    "links":[]}
        with patch.object(checkout,"_request_json",side_effect=tamper):
            with self.assertRaisesRegex(ValueError,"PAYPAL_QUOTE_MISMATCH"):
                self.store.create(qid,fake)
        self.assertEqual(self.store.read(qid)["state"],"CREATE_UNCERTAIN")


class OfferHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.server=app.StreamingHTTPServer(("127.0.0.1",0),app.TraceCartHandler)
        self.server.csrf=secrets.token_urlsafe(20)
        self.server.cart_jobs=FakeResearch()
        self.server.offer_sandbox=checkout.OfferSandboxOrders(
            str(Path(self.temp.name)/"quotes.sqlite3"))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base="http://127.0.0.1:"+str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown()
        self.thread.join(5)
        self.server.server_close()
        self.temp.cleanup()
    def req(self,path,values=None,accept_json=False):
        data=urlencode(values).encode() if values is not None else None
        headers=({"Content-Type":"application/x-www-form-urlencoded",
                  "Origin":self.base} if data is not None else {})
        if accept_json:
            headers["Accept"]="application/json"
        req=Request(self.base+path,data=data,method="POST" if data is not None else "GET",
            headers=headers)
        try:
            with urlopen(req,timeout=5) as r:
                return r.status,r.read().decode(),r.geturl()
        except HTTPError as exc:
            return exc.code,exc.read().decode(),exc.url

    def test_paypal_return_verifies_only_matching_existing_order(self):
        qid=self.server.offer_sandbox.select(
            self.server.cart_jobs,"researchJob1234567890","offer-1")
        self.server.offer_sandbox.approve(qid,checkout.CONSENT,"132.60")
        with self.server.offer_sandbox.connect() as db:
            db.execute("""UPDATE offer_sandbox_orders
                SET state='PAYER_ACTION_REQUIRED',paypal_id='FAKEORDER123',
                approval_url='https://www.sandbox.paypal.com/checkoutnow?token=FAKEORDER123'
                WHERE id=?""",(qid,))
        base="/cart/sandbox/"+qid
        with patch.object(self.server.offer_sandbox,"verify") as verify:
            status,page,_=self.req(base+"?token=INVALIDORDER123")
            self.assertEqual(status,200)
            self.assertIn("does not match this Sandbox quote",page)
            verify.assert_not_called()
            status,page,_=self.req(base)
            self.assertEqual(status,200)
            verify.assert_not_called()
            verify.return_value={"state":"VERIFIED_APPROVED"}
            status,page,_=self.req(base+"?token=FAKEORDER123")
            self.assertEqual(status,200)
            verify.assert_called_once_with(qid)

    def test_paypal_return_shows_unapproved_status_without_capture(self):
        qid=self.server.offer_sandbox.select(
            self.server.cart_jobs,"researchJob1234567890","offer-1")
        self.server.offer_sandbox.approve(qid,checkout.CONSENT,"132.60")
        with self.server.offer_sandbox.connect() as db:
            db.execute("""UPDATE offer_sandbox_orders
                SET state='PAYER_ACTION_REQUIRED',paypal_id='FAKEORDER123',
                approval_url='https://www.sandbox.paypal.com/checkoutnow?token=FAKEORDER123'
                WHERE id=?""",(qid,))
        with patch.object(self.server.offer_sandbox,"verify",
                          return_value={"state":"PAYER_ACTION_REQUIRED"}) as check:
            status,page,_=self.req("/cart/sandbox/"+qid+"?token=FAKEORDER123")
            self.assertEqual(status,200)
            self.assertIn("payer approval is not yet confirmed",page)
            check.assert_called_once_with(qid)

    def test_one_click_paypal_starts_server_priced_quote_without_typing(self):
        import json
        action="/cart/status/researchJob1234567890/paypal/start"
        with patch.object(checkout,"_request_json") as gateway:
            status,body,_=self.req(
                action,{"csrf":self.server.csrf,"offer_id":"offer-1"},
                accept_json=True)
        self.assertEqual(status,200,body)
        data=json.loads(body)["quote"]
        self.assertEqual((data["amount"],data["currency"],data["state"]),
                         ("132.60","PLN","APPROVED"))
        self.assertFalse(data["payment_captured"])
        self.assertNotIn("request_id",data)
        self.assertFalse(data["merchant_checkout_verified"])
        self.assertEqual(self.server.offer_sandbox.read(data["id"])["state"],
                         "APPROVED")
        gateway.assert_not_called()  # creating PayPal requires a second, guarded API call
        # The clicked offer ID alone cannot override server price/currency.
        with patch.object(checkout,"_request_json") as gateway:
            status,body,_=self.req(action,
                {"csrf":self.server.csrf,"offer_id":"offer-2",
                 "expected_total":"0.01","currency":"USD",
                 "consent":"FAKE"},accept_json=True)
        self.assertEqual(status,400,body)
        self.assertEqual(json.loads(body)["error"],"SANDBOX_REQUEST_REJECTED")
        gateway.assert_not_called()
        # A missing or incorrect CSRF must not create any quote.
        with patch.object(checkout,"_request_json") as gateway:
            status,body,_=self.req(action,
                {"csrf":"wrong","offer_id":"offer-1"},accept_json=True)
        self.assertEqual(status,400,body)
        self.assertEqual(json.loads(body)["error"],"SANDBOX_REQUEST_REJECTED")
        gateway.assert_not_called()

    def test_one_click_no_browser_amount_and_one_create_with_readonly_verify(self):
        import json
        action="/cart/status/researchJob1234567890/paypal/start"
        status,body,_=self.req(action,
            {"csrf":self.server.csrf,"offer_id":"offer-1"},accept_json=True)
        self.assertEqual(status,200,body)
        quote=json.loads(body)["quote"]
        qid=quote["id"]
        path="/cart/sandbox/"+qid
        fake=FakeGateway()
        fake.quote_id=qid
        calls=[]
        def create(url,method,body,headers,timeout=15):
            calls.append(method)
            payload=json.loads(body)
            self.assertEqual(payload["purchase_units"][0]["amount"],
                             {"currency_code":"PLN","value":"132.60"})
            self.assertTrue(url.endswith("/v2/checkout/orders"))
            self.assertEqual(method,"POST")
            return {"id":fake.id,"status":"CREATED",
                    "purchase_units":[{"reference_id":qid,
                        "amount":{"currency_code":"PLN","value":"132.60"}}],
                    "links":[{"rel":"approve",
                        "href":"https://www.sandbox.paypal.com/checkoutnow?token="+fake.id}]}
        with patch.object(checkout,"SandboxPayPal",return_value=fake),patch.object(
                checkout,"_request_json",side_effect=create):
            status,body,_=self.req(path+"/create",
                {"csrf":self.server.csrf},accept_json=True)
            self.assertEqual(status,200,body)
            self.assertEqual(json.loads(body)["quote"]["state"],
                             "PAYER_ACTION_REQUIRED")
            status,body,_=self.req(path+"/create",
                {"csrf":self.server.csrf},accept_json=True)
            self.assertEqual(status,400,body)
            self.assertEqual(len(calls),1)
            fake.approved=True
            status,body,_=self.req(path+".json?verify=1",accept_json=True)
            self.assertEqual(status,200,body)
            self.assertEqual(json.loads(body)["quote"]["state"],
                             "VERIFIED_APPROVED")
            self.assertEqual(len(calls),1)

    def test_modal_json_create_and_read_only_verification(self):
        import json
        action="/cart/status/researchJob1234567890/paypal/select"
        code,body,_=self.req(action,
            {"csrf":self.server.csrf,"offer_id":"offer-1"},accept_json=True)
        self.assertEqual(code,200,body)
        data=json.loads(body)["quote"]
        qid=data["id"]
        self.assertEqual((data["state"],data["amount"],data["currency"]),
                         ("QUOTED","132.60","PLN"))
        self.assertFalse(data["payment_captured"])
        self.assertFalse(data["merchant_checkout_verified"])
        self.assertNotIn("request_id",data)
        self.assertGreater(data["expires_at"],data["id"] and __import__("time").time())
        path="/cart/sandbox/"+qid
        code,body,_=self.req(path+"/approve",
            {"csrf":self.server.csrf,"consent":checkout.CONSENT,
             "expected_total":"0.01"},accept_json=True)
        self.assertEqual(code,400)
        self.assertEqual(json.loads(body)["error"],"CONSENT_OR_AMOUNT_MISMATCH")
        self.assertEqual(json.loads(body)["quote"]["state"],"QUOTED")
        code,body,_=self.req(path+"/approve",
            {"csrf":self.server.csrf,"consent":checkout.CONSENT,
             "expected_total":"132.60"},accept_json=True)
        self.assertEqual(code,200,body)
        self.assertEqual(json.loads(body)["quote"]["state"],"APPROVED")
        fake=FakeGateway()
        fake.quote_id=qid
        requests=[]
        def fake_payment(url,method,body,headers,timeout=15):
            requests.append((url,method))
            self.assertTrue(url.endswith("/v2/checkout/orders"))
            self.assertEqual(method,"POST")
            payload=json.loads(body)
            self.assertEqual(payload["purchase_units"][0]["amount"],
                             {"currency_code":"PLN","value":"132.60"})
            self.assertNotIn("/capture",url)
            return {"id":fake.id,"status":"CREATED",
                    "purchase_units":[{"reference_id":qid,
                        "amount":{"currency_code":"PLN","value":"132.60"}}],
                    "links":[{"rel":"approve",
                        "href":"https://www.sandbox.paypal.com/checkoutnow?token="+fake.id}]}
        with patch.object(checkout,"SandboxPayPal",return_value=fake),patch.object(
                checkout,"_request_json",side_effect=fake_payment):
            code,body,_=self.req(path+"/create",
                {"csrf":self.server.csrf},accept_json=True)
            self.assertEqual(code,200,body)
            data=json.loads(body)["quote"]
            self.assertEqual(data["state"],"PAYER_ACTION_REQUIRED")
            self.assertEqual(data["paypal_order_id"],fake.id)
            self.assertTrue(data["approval_url"].startswith(
                "https://www.sandbox.paypal.com/checkoutnow"))
            self.assertEqual(len(requests),1)
            code,body,_=self.req(path+"/create",
                {"csrf":self.server.csrf},accept_json=True)
            self.assertEqual(code,400,body)
            self.assertEqual(json.loads(body)["error"],
                             "SANDBOX_ORDER_ALREADY_STARTED_OR_NOT_APPROVED")
            self.assertEqual(len(requests),1)
            code,body,_=self.req(path+".json?verify=1",accept_json=True)
            self.assertEqual(code,200,body)
            self.assertEqual(json.loads(body)["quote"]["state"],
                             "PAYER_ACTION_REQUIRED")
            fake.approved=True
            code,body,_=self.req(path+".json?verify=1",accept_json=True)
            self.assertEqual(code,200,body)
            self.assertEqual(json.loads(body)["quote"]["state"],
                             "VERIFIED_APPROVED")
            code,body,_=self.req(path+"?token=INVALIDORDER123")
            self.assertEqual(code,200)
            self.assertNotIn('paypal-popup-return.js',body)
            code,body,_=self.req(path+"?token="+fake.id)
            self.assertEqual(code,200)
            self.assertIn('paypal-popup-return.js',body)
            self.assertEqual(len(requests),1)

    def test_modal_json_csrf_and_uncertain_create_no_retry(self):
        import json
        action="/cart/status/researchJob1234567890/paypal/select"
        code,body,_=self.req(action,
            {"csrf":"wrong","offer_id":"offer-1"},accept_json=True)
        self.assertEqual(code,400)
        self.assertEqual(json.loads(body)["error"],"SANDBOX_REQUEST_REJECTED")
        self.assertNotIn("quote",json.loads(body))
        qid=self.server.offer_sandbox.select(
            self.server.cart_jobs,"researchJob1234567890","offer-1")
        self.server.offer_sandbox.approve(qid,checkout.CONSENT,"132.60")
        path="/cart/sandbox/"+qid
        fake=FakeGateway()
        with patch.object(checkout,"SandboxPayPal",return_value=fake), patch.object(
                 checkout,"_request_json",side_effect=OSError("simulated timeout")) as send:
            code,body,_=self.req(path+"/create",
                {"csrf":self.server.csrf},accept_json=True)
            self.assertEqual(code,503,body)
            data=json.loads(body)
            self.assertEqual(data["quote"]["state"],"CREATE_UNCERTAIN")
            self.assertEqual(data["error"],"SANDBOX_REQUEST_UNAVAILABLE")
            code,body,_=self.req(path+"/create",
                {"csrf":self.server.csrf},accept_json=True)
            self.assertEqual(code,400,body)
            self.assertEqual(json.loads(body)["quote"]["state"],"CREATE_UNCERTAIN")
            self.assertEqual(send.call_count,1)

    def test_existing_recommendation_to_sandbox_review(self):
        action="/cart/status/researchJob1234567890/paypal/select"
        code,body,_=self.req(action,{"csrf":"wrong","offer_id":"offer-1"})
        self.assertEqual(code,400)
        code,body,url=self.req(action,{"csrf":self.server.csrf,"offer_id":"offer-1"})
        self.assertEqual(code,200,body)
        self.assertIn("/cart/sandbox/",url)
        self.assertIn("UNVERIFIED LISTING PRICE",body)
        self.assertIn("132.60 PLN",body)
        self.assertIn("NOT the external retailer",body)
        qid=url.rsplit("/",1)[-1]
        code,body,_=self.req("/cart/sandbox/"+qid+"/approve",
            {"csrf":self.server.csrf,"consent":checkout.CONSENT,"expected_total":"0.01"})
        self.assertEqual(code,200,body)
        self.assertIn("Incorrect amount or consent phrase",body)
        self.assertEqual(self.server.offer_sandbox.read(qid)["state"],"QUOTED")
        code,body,_=self.req("/cart/sandbox/"+qid+"/approve",
            {"csrf":self.server.csrf,"consent":checkout.CONSENT,"expected_total":"132.60"})
        self.assertEqual(code,200,body)
        self.assertIn("Create ONE PayPal Sandbox order",body)
        self.assertEqual(self.server.offer_sandbox.read(qid)["state"],"APPROVED")


if __name__ == "__main__":
    unittest.main()
