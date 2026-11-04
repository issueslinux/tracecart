"""Offline tests for automatic Chromium transport and durable cart integration."""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
import json
import os
import time
import unittest
from unittest.mock import patch

from automatic_browser_verification import enqueue_for_completed_cart
from browser_companion_queue import CompanionQueue
from cart_research import CartResearchJobs
from managed_browser_verification import (
    capture_public_product, ManagedBrowserWorker,
    _CAPTURABLE)
from tests.test_browser_companion_queue import sample

URL = "https://store.example.org/item/sku-7"


def response(status, capture=None):
    return json.dumps({
        "source_url": URL, "status": status, "capture": capture,
        "browser_request_scope": "SAME_ORIGIN_HTTPS_ONLY_PINNED_PUBLIC_IP",
        "render_method": "ISOLATED_MANAGED_CHROMIUM_NO_EXTENSION",
    }).encode("utf8")


def captured(url=URL):
    return {"status": _CAPTURABLE, "capture": {
        "url": url, "snapshot": sample(),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "price_origin": "DIRECT_OFFER_PRICE", "promotion": None}}


class ManagedBrowserCaptureTests(unittest.TestCase):
    def setUp(self):
        self.robots=lambda *args: b"User-agent: *\nAllow: /\n"
        self.resolver=lambda *args: "1.1.1.1"

    def test_real_source_claim_checked_without_per_host_permissions(self):
        recorded=[]
        def runner(args, **kwargs):
            recorded.append((args,kwargs))
            return SimpleNamespace(returncode=0, stdout=response(
                _CAPTURABLE, captured()["capture"]))
        with patch.dict(os.environ,{"PAYPAL_CLIENT_SECRET":"secret123",
                                "SERPAPI_API_KEY":"expensive"}):
            got=capture_public_product(URL,runner=runner,
                robots_getter=self.robots,resolver=self.resolver)
        self.assertEqual(got["status"],_CAPTURABLE)
        self.assertEqual(got["capture"]["snapshot"]["offers"]["price"],"34.90")
        command,opts=recorded[0]
        self.assertEqual(command[-3:], [URL,"store.example.org","1.1.1.1"])
        self.assertNotIn("PAYPAL_CLIENT_SECRET",opts["env"])
        self.assertNotIn("SERPAPI_API_KEY",opts["env"])
        self.assertLessEqual(opts["timeout"],23)

    def test_robots_denial_prevents_any_chromium_launch(self):
        def denied(*args):return b"User-agent: *\nDisallow: /item/\n"
        def not_called(*args,**kwargs):raise AssertionError("Chromium was launched")
        got=capture_public_product(URL, runner=not_called,
            robots_getter=denied,resolver=self.resolver)
        self.assertEqual(got["status"],"ROBOTS_DISALLOWED")

    def test_robots_failure_and_private_ip_are_rejected(self):
        def missing(*args):raise OSError("no robots")
        def not_called(*args,**kwargs):raise AssertionError("Chromium was launched")
        self.assertEqual(capture_public_product(URL,runner=not_called,
            robots_getter=missing,resolver=self.resolver)["status"],
            "ROBOTS_UNAVAILABLE")
        self.assertEqual(capture_public_product(URL,runner=not_called,
            robots_getter=self.robots,resolver=lambda x:"127.0.0.1")["status"],
            "UNSAFE_BROWSER_DESTINATION")

    def test_wrong_url_and_unverified_output_are_discarded(self):
        for raw in (response("ACCESS_CHALLENGE",captured()["capture"]),
                    response(_CAPTURABLE,{**captured()["capture"],"url":"https://evil.example.org/"}),
                    b"<html>not json</html>"):
            def runner(*args,**kwargs):return SimpleNamespace(returncode=0,stdout=raw)
            got=capture_public_product(URL,runner=runner,
                robots_getter=self.robots,resolver=self.resolver)
            self.assertEqual(got["status"],"BROWSER_ERROR")

    def test_challenge_is_a_terminal_outcome_not_a_price(self):
        def runner(*args,**kwargs):
            return SimpleNamespace(returncode=0,stdout=response("ACCESS_CHALLENGE"))
        got=capture_public_product(URL,runner=runner,
            robots_getter=self.robots,resolver=self.resolver)
        self.assertEqual(got,{"status":"ACCESS_CHALLENGE"})


class ManagedBrowserWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.cart=CartResearchJobs(Path(self.temp.name)/"cart.sqlite3",
            runner=lambda item:{})
        self.queue=CompanionQueue(token="a"*64)
        self.server=SimpleNamespace(cart_jobs=self.cart,companion=self.queue)
        self.cart.set_browser_auto_enabled(True)
        self.jid="managedjob_123456789012345"
        with self.cart._db() as db:
            db.execute("""INSERT INTO cart_research_jobs
              (id,item,state,created,result) VALUES (?,?,?,?,?)""", (
                self.jid,json.dumps({"title":"Example SKU 7", "price":None,
                  "currency":None,"barcode":"","merchant_url":URL}),"READY",
                datetime.now(timezone.utc).isoformat(),json.dumps({
                  "indexed_shopping":{"indexed_offers":[],"search_result_groups":[]}})))

    def tearDown(self):
        self.cart.close()
        self.temp.cleanup()

    def _run(self,capture):
        self.server.managed_browser=True
        worker=ManagedBrowserWorker(self.server,capture=capture,concurrency=1)
        enqueued=enqueue_for_completed_cart(self.server,self.jid)
        self.assertEqual(enqueued["status"],"QUEUED")
        self.assertEqual(enqueued["queued"],1)
        self.assertFalse(enqueued["requires_site_host_permissions"])
        worker.start()
        for _ in range(100):
            batch=self.cart.browser_auto_batch_status(self.jid)
            if batch["status"] in ("COMPLETE","COMPLETE_WITH_FAILURES"):
                break
            time.sleep(.02)
        worker.close()
        self.assertNotEqual(batch["status"],"QUEUED")
        return batch

    def test_app_worker_uses_existing_receipt_and_graph_without_extension(self):
        result=self._run(captured)
        self.assertEqual(result["status"],"COMPLETE")
        self.assertEqual(result["tasks"][0]["status"],_CAPTURABLE)
        record=self.cart.read(self.jid)
        self.assertIsNone(record.get("input_price"))
        self.assertIsNone(record["item"]["price"])
        _,snapshot=self.cart.live_snapshot(self.jid)
        self.assertTrue(snapshot["graph"]["stats"]["browser_claims_not_checkout_verified"])
        self.assertEqual(snapshot["graph"]["stats"]["verified_checkout_prices"],0)
        self.assertEqual(len(snapshot.get("browser_claims") or []),1)
        self.assertEqual(snapshot["browser_claims"][0]["browser_execution_mode"],
                         "ISOLATED_MANAGED_CHROMIUM")

    def test_access_challenge_is_terminal_and_no_price_fabricated(self):
        batch=self._run(lambda url:{"status":"ACCESS_CHALLENGE"})
        self.assertEqual(batch["status"],"COMPLETE_WITH_FAILURES")
        self.assertEqual(batch["tasks"][0]["status"],"ACCESS_CHALLENGE")
        self.assertEqual(len(self.cart.recent_browser_claim_receipts()),0)
        _,snapshot=self.cart.live_snapshot(self.jid)
        self.assertEqual(snapshot["graph"]["stats"]["verified_checkout_prices"],0)

    def test_robots_failure_propagates_to_cart_without_checkout(self):
        batch=self._run(lambda url:{"status":"ROBOTS_DISALLOWED"})
        self.assertEqual(batch["status"],"COMPLETE_WITH_FAILURES")
        self.assertEqual(batch["tasks"][0]["status"],"ROBOTS_DISALLOWED")
