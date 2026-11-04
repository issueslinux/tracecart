"""Isolated, no-network cart-click through risk plan and fake Sandbox gateway."""
import json
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import app
from core import CheckoutStore, CONSENT_TEXT
from demo_purchase import (DEMO_SKU, DEMO_SOURCE, DemoPurchaseOrders,
                           approved_sandbox_order, guarded_ai_plan,
                           mock_merchant_item)
from decision_tree import ReportStore
from cart_research import CartResearchJobs
from browser_companion_queue import CompanionQueue
from tests.test_http import MockPayPal


def model_success(research):
    assert research['state']=='READY'
    return {'risk_level':'HIGH','risk_note':'The merchant and stock are a fictional test fixture.',
            'buyer_checks':['Can the stock be independently verified?'],
            'model':'qwen2.5:1.5b-instruct','provider':'LOCAL_QWEN',
            'source_type':'UNTRUSTED_AI_COMMENTARY_ONLY'}


class ApprovedSandbox(MockPayPal):
    def __init__(self):
        super().__init__()
        self.approved=False

    def get_order(self, oid):
        result=super().get_order(oid)
        if self.approved:
            result['status']='APPROVED'
        return result


class DemoFlowHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.ready=threading.Event()
        self.done=threading.Event()
        self.thread=threading.Thread(target=self._host_server,daemon=True)
        self.thread.start()
        self.assertTrue(self.ready.wait(5))
        self.base='http://127.0.0.1:{}'.format(self.server.server_port)
        self.sandbox=ApprovedSandbox()

    def _host_server(self):
        db=Path(self.temp.name)/'checkout.sqlite3'
        server=app.StreamingHTTPServer(('127.0.0.1',0),app.TraceCartHandler)
        server.csrf=secrets.token_urlsafe(22)
        server.store=CheckoutStore(str(db))
        server.reports=ReportStore(server.store.db)
        server.cart_jobs=CartResearchJobs(db,runner=lambda item:{
            'root':{'children':[]},'research_note':'OFFLINE_TEST_NO_SOURCES'})
        server.companion=CompanionQueue(token='a'*64)
        server.demo_orders=DemoPurchaseOrders(db,planner=model_success)
        self.server=server
        self.ready.set()
        try:
            server.serve_forever(poll_interval=.03)
        finally:
            server.server_close();server.demo_orders.close()
            server.cart_jobs.close();server.store.db.close()
            self.done.set()

    def tearDown(self):
        self.server.shutdown();self.assertTrue(self.done.wait(5))
        self.thread.join(timeout=4)
        self.temp.cleanup()

    def read_quote(self, qid):
        with sqlite3.connect(str(Path(self.temp.name)/'checkout.sqlite3')) as db:
            db.row_factory=sqlite3.Row
            return dict(db.execute('SELECT * FROM quotes WHERE id=?',(qid,)).fetchone())

    def request(self,method,url,form=None):
        data=urlencode(form).encode() if form is not None else None
        req=Request(self.base+url,method=method,data=data,headers={
            'Origin':self.base,'Content-Type':'application/x-www-form-urlencoded'}
            if method=='POST' else {})
        try:
            with urlopen(req,timeout=9) as res:
                return res.status,res.read().decode('utf8'),res.geturl()
        except HTTPError as err:
            return err.code,err.read().decode('utf8'),err.url

    def add(self):
        status,html,_=self.request('GET','/demo/store')
        self.assertEqual(status,200)
        self.assertIn('Add to cart</button>',html)
        self.assertNotIn('Paste a product URL',html)
        csrf=re.search('name="csrf" value="([a-zA-Z0-9_-]+)"',html).group(1)
        code,page,url=self.request('POST','/demo/store/add',{
            'csrf':csrf,'sku':DEMO_SKU})
        self.assertEqual(code,200,page)
        self.assertIn('/demo/order/',url)
        jid=url.rsplit('/',1)[-1]
        for _ in range(120):
            self.request('GET','/demo/order/'+jid)
            state=self.server.demo_orders.get(jid)
            if state['ai_status']=='AI_READY':break
            time.sleep(.02)
        self.assertEqual(state['ai_status'],'AI_READY')
        return jid,csrf

    def test_one_add_to_cart_click_auto_research_ai_plan_and_fixed_quote(self):
        jid,csrf=self.add()
        record=self.server.cart_jobs.read(jid)
        self.assertEqual(record['state'],'READY')
        self.assertEqual(record['item'],mock_merchant_item(DEMO_SKU))
        self.assertEqual(record['item']['merchant_url'],DEMO_SOURCE)
        d=self.server.demo_orders.get(jid)
        quote=self.read_quote(d['quote_id'])
        self.assertEqual(quote['total'],'29.00')
        self.assertEqual(quote['state'],'QUOTED')
        self.assertEqual(d['simulated_state'],'NOT_ACCEPTED')
        code,html,_=self.request('GET','/demo/order/'+jid)
        self.assertEqual(code,200)
        self.assertIn('AI RISK PLAN',html)
        self.assertIn('LOCAL_QWEN' if False else 'qwen2.5:1.5b-instruct',html)
        self.assertIn('29.00 USD',html)
        self.assertIn('/cart/status/'+jid,html)
        self.assertIn('NOT payable to',html)
        self.assertNotIn('Open PayPal Sandbox for buyer approval',html)

    def test_wrong_consent_never_creates_sandbox_order(self):
        jid,csrf=self.add()
        with patch.object(app,'SandboxPayPal',return_value=self.sandbox):
            for wrong in ({'consent':CONSENT_TEXT,'expected_total':'0.01'},
                          {'consent':'NOT APPROVED','expected_total':'29.00'}):
                payload={'csrf':csrf,**wrong}
                code,_,_=self.request('POST','/demo/order/'+jid+'/approve',payload)
                self.assertEqual(code,400)
            self.assertEqual(self.sandbox.created,0)
            d=self.server.demo_orders.get(jid)
            self.assertEqual(self.read_quote(d['quote_id'])['state'],'QUOTED')
            self.assertEqual(d['simulated_state'],'NOT_ACCEPTED')

    def test_approved_sandbox_must_be_real_verified_before_simulated_accept(self):
        jid,csrf=self.add()
        with patch.object(app,'SandboxPayPal',return_value=self.sandbox):
            code,html,_=self.request('POST','/demo/order/'+jid+'/approve',{
                'csrf':csrf,'consent':CONSENT_TEXT,'expected_total':'29.00'})
            self.assertEqual(code,200,html)
            d=self.server.demo_orders.get(jid)
            quote=self.read_quote(d['quote_id'])
            self.assertEqual(quote['state'],'PAYER_ACTION_REQUIRED')
            self.assertEqual(self.sandbox.created,1)
            self.assertEqual(self.sandbox.record['total'],'29.00')
            self.assertEqual(d['simulated_state'],'NOT_ACCEPTED')
            self.assertIn('Open PayPal Sandbox for buyer approval',html)
            code,html,_=self.request('POST','/demo/order/'+jid+'/verify',{
                'csrf':csrf})
            self.assertEqual(code,200)
            self.assertEqual(self.server.demo_orders.get(jid)['simulated_state'],
                             'NOT_ACCEPTED')
            self.sandbox.approved=True
            code,html,_=self.request('POST','/demo/order/'+jid+'/verify',{
                'csrf':csrf})
            self.assertEqual(code,200,html)
            self.assertIn('Order accepted in simulation',html)
            self.assertIn('No payment capture',html)
            self.assertEqual(self.server.demo_orders.get(jid)['simulated_state'],
                             'SIMULATED_ACCEPTED')
            self.assertEqual(self.sandbox.created,1)

    def test_without_configured_sandbox_order_remains_approved(self):
        jid,csrf=self.add()
        with patch.object(app,'SandboxPayPal',side_effect=RuntimeError(
                'PayPal sandbox credentials missing; no order sent')):
            code,html,_=self.request('POST','/demo/order/'+jid+'/approve',{
                'csrf':csrf,'consent':CONSENT_TEXT,'expected_total':'29.00'})
        self.assertEqual(code,200,html)
        self.assertIn('Sandbox credentials',html)
        d=self.server.demo_orders.get(jid)
        self.assertEqual(self.read_quote(d['quote_id'])['state'],'APPROVED')
        self.assertEqual(d['simulated_state'],'NOT_ACCEPTED')

    def test_csrf_required_and_repeated_payment_creation_blocked(self):
        jid,csrf=self.add()
        with patch.object(app,'SandboxPayPal',return_value=self.sandbox):
            code,_,_=self.request('POST','/demo/order/'+jid+'/approve',{
                'csrf':'invalid','consent':CONSENT_TEXT,'expected_total':'29.00'})
            self.assertEqual(code,400)
            code,_,_=self.request('POST','/demo/order/'+jid+'/approve',{
                'csrf':csrf,'consent':CONSENT_TEXT,'expected_total':'29.00'})
            self.assertEqual(code,200)
            code,_,_=self.request('POST','/demo/order/'+jid+'/paypal',{'csrf':csrf})
            self.assertEqual(code,400)
            self.assertEqual(self.sandbox.created,1)

    def test_real_ai_unavailable_blocks_sandbox_checkout_instead_of_faking_plan(self):
        def no_ai(_):
            raise OSError('LOCAL_QWEN_UNAVAILABLE')
        self.server.demo_orders.planner=no_ai
        status,page,_=self.request('GET','/demo/store')
        csrf=re.search('name="csrf" value="([a-zA-Z0-9_-]+)"',page).group(1)
        code,page,url=self.request('POST','/demo/store/add',{
            'csrf':csrf,'sku':DEMO_SKU})
        self.assertEqual(code,200)
        jid=url.rsplit('/',1)[-1]
        for _ in range(100):
            _,page,_=self.request('GET','/demo/order/'+jid)
            if self.server.demo_orders.get(jid)['ai_status']=='AI_UNAVAILABLE':break
            time.sleep(.02)
        _,page,_=self.request('GET','/demo/order/'+jid)
        self.assertIn('Local AI unavailable',page)
        with patch.object(app,'SandboxPayPal',return_value=self.sandbox):
            code,_,_=self.request('POST','/demo/order/'+jid+'/approve',{
                'csrf':csrf,'consent':CONSENT_TEXT,'expected_total':'29.00'})
        self.assertEqual(code,400)
        self.assertEqual(self.sandbox.created,0)

    def test_cannot_create_payment_before_ai_research_and_no_url_input(self):
        code,html,_=self.request('GET','/demo/store')
        csrf=re.search('name="csrf" value="([a-zA-Z0-9_-]+)"',html).group(1)
        self.assertEqual(self.request('POST','/demo/store/add',{
            'csrf':csrf,'sku':'evil-injected-price'})[0],400)
        self.assertEqual(self.request('POST','/demo/store/add',{
            'csrf':'invalid','sku':DEMO_SKU})[0],400)
        self.assertEqual(self.sandbox.created,0)


class PlannerSafetyTests(unittest.TestCase):
    def test_ai_output_cannot_set_price_or_authorize(self):
        job={'state':'READY','item':mock_merchant_item(DEMO_SKU),
             'report':{'root':{}},'final_verdict':{'status':'PENDING'},
             'source_search':{'status':'NOT_STARTED'}}
        def gateway(*args,**kwargs):
            self.assertEqual(kwargs.get('timeout'),14)
            body=json.loads(args[2].decode())
            self.assertNotIn('29.00',str(body))
            return {'message':{'content':json.dumps({
                'risk_note':'This is a test retailer and unverified stock.',
                'buyer_checks':['Is the actual store verified?'],
                'price':'0.01', 'authorized':True})}}
        with self.assertRaisesRegex(ValueError,'INVALID_AI_PLAN_SCHEMA'):
            guarded_ai_plan(job,request=gateway)

    def test_paypal_approved_amount_and_reference_validation(self):
        q={'id':'quote_123','paypal_id':'FAKEORDER123','state':'PAYER_ACTION_REQUIRED','total':'29.00'}
        gateway=ApprovedSandbox();gateway.record={'id':q['id'],'total':'0.01'}
        gateway.approved=True
        with self.assertRaisesRegex(ValueError,'PAYPAL_APPROVED_AMOUNT_MISMATCH'):
            approved_sandbox_order(gateway,q)
