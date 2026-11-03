"""Completed new research queues consenting browser visits, with no network."""
from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from automatic_browser_verification import enqueue_for_completed_cart
from browser_companion_queue import CompanionQueue
from cart_research import CartResearchJobs
from tests.test_index_browser_parallel import indexed_report


class AutomaticBrowserVerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/"demo.sqlite3"
        self.cart=CartResearchJobs(self.db,runner=lambda x:{})
        self.queue=CompanionQueue(token="f"*64)
        self.server=Mock(cart_jobs=self.cart,companion=self.queue)
        self.job="autocart_123456789012345"
        self.urls,self.report=indexed_report()
        with self.cart._db() as db:
            db.execute("""INSERT INTO cart_research_jobs
              (id,item,state,created,result) VALUES (?,?,?,?,?)""",
              (self.job,json.dumps({"title":"Device ABC123 16GB",
                   "merchant_url":self.urls[0]}),"READY",
               datetime.now(timezone.utc).isoformat(),json.dumps(self.report)))

    def tearDown(self):
        self.cart.close()
        self.tmp.cleanup()

    def test_opt_in_required_and_one_click_enable_schedules_source_and_merchants(self):
        self.assertEqual(enqueue_for_completed_cart(self.server,self.job)["status"],
                         "DISABLED")
        self.assertEqual(self.queue.listed(),[])
        self.assertTrue(self.cart.set_browser_auto_enabled(True)["enabled"])
        result=enqueue_for_completed_cart(self.server,self.job)
        self.assertEqual(result["status"],"QUEUED")
        self.assertEqual(result["queued"],3)
        self.assertEqual({x["url"] for x in self.queue.listed()},set(self.urls))
        self.assertEqual(len(self.cart.index_browser_checks(self.job)),3)
        # Duplicate input URL and same index seller must not open two tabs.
        self.assertEqual(enqueue_for_completed_cart(self.server,self.job)["status"],
                         "ALREADY_QUEUED")
        self.assertEqual(len(self.queue.listed()),3)

    def test_each_auto_capture_updates_batch_without_permanent_waiting(self):
        self.cart.set_browser_auto_enabled(True)
        result=enqueue_for_completed_cart(self.server,self.job)
        self.assertEqual(result["queued"],3)
        tasks=[]
        for _ in range(3):
            task=self.queue.take()
            tasks.append(task)
            self.cart.finish_browser_auto_task(task["job_id"],
                "PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED" if len(tasks)!=3
                else "SITE_PERMISSION_REQUIRED")
        status=self.cart.browser_auto_batch_status(self.job)
        self.assertEqual(status["status"],"COMPLETE_WITH_FAILURES")
        self.assertEqual(status["queued_count"],3)
        self.assertEqual(self.cart.index_browser_checks(self.job)[0]["status"],
                         "QUEUED")  # indexed status has its own receipt pipeline

    def test_auto_queue_marks_interrupted_jobs_after_restart(self):
        self.cart.set_browser_auto_enabled(True)
        enqueue_for_completed_cart(self.server,self.job)
        self.cart.close()
        self.cart=CartResearchJobs(self.db,runner=lambda x:{})
        self.server.cart_jobs=self.cart
        self.assertEqual(self.cart.browser_auto_batch_status(self.job)["status"],
                         "INTERRUPTED_ON_RESTART")

    def test_auto_queues_original_product_even_if_no_competitor_discovery(self):
        with self.cart._db() as db:
            db.execute("UPDATE cart_research_jobs SET result=? WHERE id=?",
                       (json.dumps({"indexed_shopping":{
                            "indexed_offers":[],"search_result_groups":[]}}),
                        self.job))
        self.cart.set_browser_auto_enabled(True)
        result=enqueue_for_completed_cart(self.server,self.job)
        self.assertEqual(result["queued"],1)
        task=self.queue.take()
        self.assertEqual(task["url"],self.urls[0])
        self.assertEqual(self.cart.index_browser_checks(self.job),[])

    def test_auto_disabled_prevents_following_research_without_silent_grant(self):
        self.cart.set_browser_auto_enabled(True)
        self.cart.set_browser_auto_enabled(False)
        self.assertEqual(enqueue_for_completed_cart(self.server,self.job)["status"],
                         "DISABLED")
        self.assertEqual(self.queue.listed(),[])

    def test_new_research_completion_triggers_auto_queue_without_button(self):
        from time import sleep
        self.cart.set_browser_auto_enabled(True)
        self.cart.on_research_ready=lambda jid:enqueue_for_completed_cart(self.server,jid)
        item={"title":"A different real URL",
              "merchant_url":"https://shop.example.org/another-model",
              "price":None,"currency":None,"barcode":""}
        newjob=self.cart.submit(item)
        for i in range(100):
            if self.cart.read(newjob)["state"]=="READY" and any(
                    x["url"]==item["merchant_url"] for x in self.queue.listed()):
                break
            sleep(.03)
        self.assertEqual(self.cart.read(newjob)["state"],"READY")
        self.assertTrue(any(x["url"]==item["merchant_url"]
                            for x in self.queue.listed()))
        self.assertEqual(self.cart.browser_auto_batch_status(newjob)["status"],
                         "QUEUED")

    def test_no_auto_when_queue_already_full(self):
        for i in range(12):
            self.queue.enqueue("https://another.example.org/item/"+str(i))
        self.cart.set_browser_auto_enabled(True)
        result=enqueue_for_completed_cart(self.server,self.job)
        self.assertEqual(result["status"],"SKIPPED_QUEUE_FULL")
        self.assertEqual(self.cart.browser_auto_batch_status(self.job)["status"],
                         "SKIPPED_QUEUE_FULL")
        self.assertEqual(len(self.queue.listed()),12)
