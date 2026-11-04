"""Indexed seller URLs -> explicit parallel browser queue -> offer-specific graph."""
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest

import app
from browser_companion_queue import CompanionQueue
from cart_research import CartResearchJobs
from tests.test_browser_companion_http import CompanionHTTPTests
from tests.test_browser_companion_queue import sample


def indexed_report():
    urls=[
      "https://shop-one.example.org/item/device-abc123",
      "https://shop-two.example.org/item/device-abc123",
      "https://shop-three.example.org/item/device-abc123",
    ]
    return urls, {"indexed_shopping":{
        "provider":"SERPAPI_GOOGLE_SHOPPING",
        "indexed_offers":[{
            "title":"Device ABC123 16GB", "seller":seller,"merchant_url":url,
            "current_price_indexed":price,"currency":"PLN",
            "identity_status":"PRODUCT_IDENTITY_NOT_PROVEN_BY_SHOPPING_INDEX"
        } for url,seller,price in zip(urls,["First","Second","Third"],
                                      ["169.95","299.99","399.99"])],
        "search_result_groups":[{
          "title":"Device ABC123 16GB on Google",
          "source":"Search card only",
          "index_search_url":"https://www.google.com/search?tbm=shop&q=ABC123",
          "indexed_price":"190.00","indexed_currency":"PLN",
        }],
    }}


class ParallelIndexedHTTPTests(unittest.TestCase):
    call=CompanionHTTPTests.call

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.server=app.StreamingHTTPServer(("127.0.0.1",0),app.TraceCartHandler)
        self.server.csrf=secrets.token_urlsafe(24)
        self.server.companion=CompanionQueue(token=secrets.token_hex(32))
        self.db=Path(self.tmp.name)/"cart.sqlite"
        self.server.cart_jobs=CartResearchJobs(self.db,runner=lambda x:{})
        self.base="http://127.0.0.1:{}".format(self.server.server_port)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.job="indexedjob_123456789012345"
        self.urls,self.report=indexed_report()
        self.seed()

    def seed(self):
        item={"title":"Device ABC123 16GB","merchant_url":
              "https://original.example.org/product/ABC123",
              "price":None,"currency":None}
        with self.server.cart_jobs._db() as db:
            db.execute("""INSERT INTO cart_research_jobs
                (id,item,state,created,result) VALUES (?,?,?,?,?)""",
                (self.job,json.dumps(item),"READY",
                 datetime.now(timezone.utc).isoformat(),json.dumps(self.report)))

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.server.server_close()
        self.server.cart_jobs.close()
        self.tmp.cleanup()

    def start(self):
        code,body=self.call("/cart/status/"+self.job+"/verify-indexed",
            method="POST",payload={"csrf":self.server.csrf},origin=self.base)
        self.assertEqual(code,200,body[:200])
        return self.server.cart_jobs.index_browser_checks(self.job)

    def test_legacy_saved_job_can_enter_automatic_queue_without_new_search(self):
        self.server.cart_jobs.set_browser_auto_enabled(True)
        url="/cart/status/"+self.job+"/auto-verify"
        code,_=self.call(url,method="POST",
                         payload={"csrf":self.server.csrf},origin=self.base)
        self.assertEqual(code,200)
        queued=self.server.companion.listed()
        self.assertEqual(len(queued),4) # selected product + 3 index seller URLs
        self.assertEqual(len(self.server.cart_jobs.index_browser_checks(self.job)),3)
        self.assertEqual(self.server.cart_jobs.browser_auto_batch_status(self.job)
                         ["status"],"QUEUED")

    def test_three_direct_urls_queued_and_google_search_card_not_visited(self):
        pending=self.start()
        self.assertEqual(len(pending),3)
        self.assertEqual([x["url"] for x in pending],self.urls)
        self.assertTrue(all(x["status"]=="QUEUED" for x in pending))
        tasks=[json.loads(self.call("/api/browser-companion/next",
               token=self.server.companion.token)[1])["job"] for _ in range(3)]
        self.assertEqual({x["url"] for x in tasks},set(self.urls))
        self.assertIsNone(json.loads(self.call("/api/browser-companion/next",
               token=self.server.companion.token)[1])["job"])
        self.assertFalse(any("google.com" in x["url"] for x in pending))
        code,_=self.call("/cart/status/"+self.job+"/verify-indexed",
            method="POST",payload={"csrf":self.server.csrf},origin=self.base)
        self.assertEqual(code,400)
        self.assertEqual(len(self.server.companion.listed()),3)

    def test_two_captures_and_one_denied_status_link_to_correct_indexed_offers(self):
        self.start()
        token=self.server.companion.token
        for idx in range(3):
            task=json.loads(self.call("/api/browser-companion/next",
                  token=token)[1])["job"]
            self.assertEqual(task["url"],self.urls[idx])
            if idx==2:
                payload={"job_id":task["job_id"],"url":task["url"],
                         "captured_at":None,"snapshot":None,
                         "price_origin":None,"error":"SITE_PERMISSION_REQUIRED"}
            else:
                product=sample()
                product["name"]="Device ABC123 16GB"
                product["offers"]["price"]=["220.00","299.99"][idx]
                payload={"job_id":task["job_id"],"url":task["url"],
                         "captured_at":datetime.now(timezone.utc).isoformat(),
                         "snapshot":product,"price_origin":"DIRECT_OFFER_PRICE",
                         "error":None}
            code,body=self.call("/api/browser-companion/result",
                 method="POST",token=token,payload=payload,
                 content_type="application/json")
            self.assertEqual(code,200,body)
        checks=self.server.cart_jobs.index_browser_checks(self.job)
        self.assertEqual([x["status"] for x in checks],
            ["PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED"]*2+
            ["SITE_PERMISSION_REQUIRED"])
        graph=json.loads(self.call("/cart/status/"+self.job+
                      ".knowledge-graph.json")[1])
        self.assertEqual(graph["stats"]["offers"],5)  # input + three URLs + one card
        self.assertEqual(graph["stats"]["indexed_browser_checked"],2)
        self.assertEqual(graph["stats"]["indexed_browser_failed"],1)
        self.assertEqual(graph["stats"]["indexed_browser_price_disagreements"],1)
        self.assertEqual(graph["stats"]["verified_checkout_prices"],0)
        d=graph["offer_details"]
        self.assertEqual(d["offer-1"]["browser_observation"]["declared_price"],"220.00")
        self.assertEqual(d["offer-2"]["browser_observation"]["declared_price"],"299.99")
        self.assertEqual(d["offer-3"]["browser_observation"]["status"],
                         "SITE_PERMISSION_REQUIRED")
        self.assertIsNone(d["offer-4"]["browser_observation"])
        self.assertEqual(d["offer-1"]["indexed_price"]["value"],"169.95")
        self.assertTrue(any(e["from"]=="offer-1" and
            e["relation"]=="INDEXED_OFFER_VISITED_IN_BROWSER" for e in graph["edges"]))
        self.assertTrue(any(e["from"]=="offer-2" and
            e["relation"]=="INDEXED_OFFER_VISITED_IN_BROWSER" for e in graph["edges"]))
        self.assertFalse(any(e["from"]=="offer-4" and
            e["relation"]=="INDEXED_OFFER_VISITED_IN_BROWSER" for e in graph["edges"]))
        self.assertEqual(len(self.server.cart_jobs.recent_browser_claim_receipts()),2)
        # Complete receipts and indexed offer linkage survive process restart.
        self.server.cart_jobs.close()
        self.server.cart_jobs=CartResearchJobs(self.db,runner=lambda x:{})
        rerender=json.loads(self.call("/cart/status/"+self.job+
                      ".knowledge-graph.json")[1])
        self.assertEqual(rerender["stats"]["indexed_browser_checked"],2)

    def test_failed_store_can_be_manually_retried_without_revisiting_success(self):
        self.start()
        token=self.server.companion.token
        for i in range(3):
            task=json.loads(self.call("/api/browser-companion/next",
                  token=token)[1])["job"]
            if i==0:
                product=sample()
                product["name"]="Device ABC123 16GB"
                receipt={"job_id":task["job_id"],"url":task["url"],
                         "captured_at":datetime.now(timezone.utc).isoformat(),
                         "snapshot":product,"price_origin":"DIRECT_OFFER_PRICE",
                         "error":None}
            else:
                receipt={"job_id":task["job_id"],"url":task["url"],
                         "captured_at":None,"snapshot":None,"price_origin":None,
                         "error":"SITE_PERMISSION_REQUIRED"}
            self.assertEqual(self.call("/api/browser-companion/result",
                method="POST",token=token,payload=receipt,
                content_type="application/json")[0],200)
        code,_=self.call("/cart/status/"+self.job+"/verify-indexed",
                         method="POST",payload={"csrf":self.server.csrf},
                         origin=self.base)
        self.assertEqual(code,200)
        queued=[x for x in self.server.cart_jobs.index_browser_checks(self.job)
                if x["status"]=="QUEUED"]
        self.assertEqual([x["offer_idx"] for x in queued],[2,3])
        tasks=[json.loads(self.call("/api/browser-companion/next",
               token=token)[1])["job"] for _ in range(2)]
        self.assertEqual([x["url"] for x in tasks],self.urls[1:])
        self.assertEqual(self.server.cart_jobs.index_browser_checks(self.job)[0]
                         ["status"],
                         "PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED")

    def test_browser_conditional_coupon_stays_on_exact_indexed_offer(self):
        self.start()
        token=self.server.companion.token
        task=json.loads(self.call("/api/browser-companion/next",
             token=token)[1])["job"]
        product=sample()
        product["name"]="Device ABC123 16GB"
        product["offers"]["price"]="3499.99"
        request={"job_id":task["job_id"],"url":task["url"],
                 "captured_at":datetime.now(timezone.utc).isoformat(),
                 "snapshot":product,"price_origin":"DIRECT_OFFER_PRICE",
                 "error":None,
                 "promotion":{"price":"2799.00","currency":"PLN",
                  "code":"DEAL2026","valid_until":None,
                  "source":"VISIBLE_PRODUCT_PRICE_WITH_CODE"}}
        self.assertEqual(self.call("/api/browser-companion/result",
             method="POST",token=token,payload=request,
             content_type="application/json")[0],200)
        graph=json.loads(self.call("/cart/status/"+self.job+
             ".knowledge-graph.json")[1])
        promo=graph["offer_details"]["offer-1"]["browser_observation"]["promotion"]
        self.assertEqual(promo["price"],"2799.00")
        self.assertEqual(promo["code"],"DEAL2026")
        self.assertFalse(promo["checkout_verified"])
        self.assertEqual(graph["stats"]["verified_checkout_prices"],0)
        self.assertEqual(graph["offer_details"]["offer-2"]["browser_observation"]
                         ["status"],"QUEUED")

    def test_live_api_contains_individual_browser_check_statuses(self):
        self.start()
        snapshot=json.loads(self.call("/cart/status/"+self.job+"/live.json")[1])
        self.assertEqual(len(snapshot["indexed_browser_checks"]),3)
        self.assertEqual(len(snapshot["browser_claims"]),0)
        self.assertEqual({r["status"] for r in snapshot["indexed_browser_checks"]},
                         {"QUEUED"})
    def test_title_conflict_does_not_override_indexed_price(self):
        self.start()
        token=self.server.companion.token
        task=json.loads(self.call("/api/browser-companion/next",
              token=token)[1])["job"]
        product=sample()
        product["name"]="Brand ZZ99 different variant 8GB"
        product["offers"]["price"]="55.00"
        code,body=self.call("/api/browser-companion/result",
              method="POST",token=token,payload={
                "job_id":task["job_id"],"url":task["url"],
                "captured_at":datetime.now(timezone.utc).isoformat(),
                "snapshot":product,"price_origin":"DIRECT_OFFER_PRICE",
                "error":None},content_type="application/json")
        self.assertEqual(code,200,body)
        graph=json.loads(self.call("/cart/status/"+self.job+
                        ".knowledge-graph.json")[1])
        self.assertEqual(graph["stats"]["indexed_browser_identity_conflicts"],1)
        self.assertEqual(graph["offer_details"]["offer-1"]["indexed_price"]["value"],
                         "169.95")
        self.assertEqual(graph["offer_details"]["offer-1"]
                         ["browser_observation"]["status"],"BROWSER_VARIANT_CONFLICT")
        self.assertFalse(any(n.get("parameter")=="price" and
             n.get("source_url")==task["url"] and
             n.get("provenance")=="BROWSER_INDEXED_SELLER_NOT_CHECKOUT"
             for n in graph["nodes"]))

    def test_without_direct_seller_urls_does_not_queue_search_cards(self):
        self.report["indexed_shopping"]["indexed_offers"]=[]
        with self.server.cart_jobs._db() as db:
            db.execute("UPDATE cart_research_jobs SET result=? WHERE id=?",
                       (json.dumps(self.report),self.job))
        code,_=self.call("/cart/status/"+self.job+"/verify-indexed",
           method="POST",payload={"csrf":self.server.csrf},origin=self.base)
        self.assertEqual(code,400)
        self.assertEqual(self.server.companion.listed(),[])


if __name__=="__main__":
    unittest.main()
