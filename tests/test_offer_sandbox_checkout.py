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
    def req(self,path,values=None):
        data=urlencode(values).encode() if values is not None else None
        req=Request(self.base+path,data=data,method="POST" if data is not None else "GET",
            headers={"Content-Type":"application/x-www-form-urlencoded",
                     "Origin":self.base} if data is not None else {})
        try:
            with urlopen(req,timeout=5) as r:
                return r.status,r.read().decode(),r.geturl()
        except HTTPError as exc:
            return exc.code,exc.read().decode(),exc.url

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
