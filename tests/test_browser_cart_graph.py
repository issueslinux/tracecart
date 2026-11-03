"""Browser Companion receipts are read-only seller declarations in cart graph."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from browser_companion_queue import CompanionQueue
from cart_research import CartResearchJobs
from guided_decision import build_decision_projection
from offer_knowledge_graph import build_offer_knowledge_graph
from tests.test_browser_companion_queue import sample, receipt

URL = "https://store.example.org/item/sku-7"
OTHER = "https://store.example.org/item/different-variant"
JOB = "cartjob_123456789012345"


class BrowserCartGraphTests(unittest.TestCase):
    def setUp(self):
        self.dir = TemporaryDirectory()
        self.dbpath = Path(self.dir.name) / "research.sqlite"
        self.cart = CartResearchJobs(self.dbpath, runner=lambda item: {})
        self.queue = CompanionQueue(token="a"*64)

    def tearDown(self):
        self.cart.close()
        self.dir.cleanup()

    def cart_job(self, jobid=JOB, url=URL, price=None, sku=None,
                 barcode=None):
        item={"title":"Example SKU 7", "merchant_url":url,
              "price":price, "currency":"PLN" if price else None,
              "barcode":barcode}
        report={"source_intake":{"intake_status":"URL_ONLY_UNVERIFIED",
                                 "sku":sku},
                "indexed_shopping":{"indexed_offers":[],"search_result_groups":[]}}
        with self.cart._db() as db:
            db.execute("""INSERT INTO cart_research_jobs
                (id,item,state,created,result)
                VALUES (?,?,?,?,?)""",
                (jobid,json.dumps(item),"READY","2026-11-03T12:00:00Z",
                 json.dumps(report)))
        return jobid

    def capture(self, url=URL, modify=None):
        self.queue.enqueue(url)
        task=self.queue.take()
        product=sample()
        if modify:
            modify(product)
        ack=self.queue.report(receipt(task,snapshot=product))
        self.assertEqual(ack["status"],
                         "PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED")
        return self.queue.get_job(task["job_id"])

    def graph(self, jobid=JOB):
        record=self.cart.read(jobid)
        projection=build_decision_projection(record)
        graph=build_offer_knowledge_graph(projection)
        return record,projection,graph

    def test_observation_appears_in_graph_but_does_not_become_price_input(self):
        self.cart_job()
        version_before,_=self.cart.live_snapshot(JOB)
        capture=self.capture()
        saved=self.cart.store_browser_claim(capture)
        self.assertEqual(saved["cart_jobs_signalled"],1)
        version_after,snapshot=self.cart.live_snapshot(JOB)
        self.assertGreater(version_after,version_before)
        record,projection,graph=self.graph()
        self.assertIsNone(record["input_price"])
        self.assertIsNone(record["item"]["price"])
        self.assertEqual(projection["browser_claims"][0]["fields"]["price"],"34.90")
        browser_sources=[n for n in graph["nodes"] if
                         n.get("source_kind")=="USER_BROWSER_FILTERED_PROJECTION"]
        self.assertEqual(len(browser_sources),1)
        source=browser_sources[0]
        self.assertEqual(source["sha256"],capture["result"]["snapshot_sha256"])
        self.assertFalse(source["checkout_verified"])
        self.assertTrue(any(e["from"]=="offer-0" and e["to"]==source["id"] and
                            e["relation"]=="BROWSER_OBSERVED_SELECTED_URL"
                            for e in graph["edges"]))
        price_nodes=[n for n in graph["nodes"] if n.get("type")=="seller_declaration"
                     and n.get("provenance")=="BROWSER_SOURCE_CLAIM_NOT_CHECKOUT"
                     and n.get("parameter")=="price"]
        self.assertEqual(len(price_nodes),1)
        self.assertEqual(price_nodes[0]["value"],"34.90 PLN")
        self.assertFalse(price_nodes[0]["checkout_verified"])
        self.assertEqual(graph["stats"]["verified_checkout_prices"],0)
        self.assertIn("browser_claims_not_checkout_verified",graph["stats"])
        self.assertGreaterEqual(len(snapshot["graph"]["nodes"]),len(graph["nodes"]))

    def test_general_coupon_source_is_in_graph_without_promoting_checkout(self):
        self.cart_job()
        self.queue.enqueue(URL)
        task=self.queue.take()
        product=sample()
        product["offers"]["price"]="3499.99"
        payload=receipt(task,snapshot=product)
        payload["promotion"]={"price":"2799.00","currency":"PLN",
          "code":"SAVE2026","valid_until":"2026-12-01",
          "source":"VISIBLE_PRODUCT_PRICE_WITH_CODE"}
        self.queue.report(payload)
        self.cart.store_browser_claim(self.queue.get_job(task["job_id"]))
        _,_,graph=self.graph()
        coupon=[node for node in graph["nodes"] if node.get("parameter")==
                "coupon_price_with_code"]
        self.assertEqual(len(coupon),1)
        self.assertEqual(coupon[0]["value"],"2799.00")
        self.assertEqual(coupon[0]["promotion_code"],"SAVE2026")
        self.assertFalse(coupon[0]["code_applied"])
        self.assertFalse(coupon[0]["checkout_verified"])
        self.assertEqual(graph["stats"]["verified_checkout_prices"],0)

    def test_source_receipt_persists_across_restart_and_prior_capture_links(self):
        captured=self.capture()
        self.cart.store_browser_claim(captured)
        self.cart.close()
        self.cart=CartResearchJobs(self.dbpath,runner=lambda item: {})
        self.cart_job()
        record,_,graph=self.graph()
        self.assertEqual(len(record["browser_claims"]),1)
        self.assertTrue(any(n.get("source_kind")=="USER_BROWSER_FILTERED_PROJECTION"
                            for n in graph["nodes"]))

    def test_different_product_same_domain_does_not_attach(self):
        self.cart_job()
        captured=self.capture(OTHER)
        self.cart.store_browser_claim(captured)
        record,_,graph=self.graph()
        self.assertEqual(record["browser_claims"],[])
        self.assertFalse(any(n.get("source_kind")=="USER_BROWSER_FILTERED_PROJECTION"
                             for n in graph["nodes"]))
        self.assertEqual(graph["stats"]["verified_checkout_prices"],0)

    def test_sku_mismatch_blocks_field_price_link(self):
        self.cart_job(sku="DIFFERENT-SKU")
        capture=self.capture()
        self.cart.store_browser_claim(capture)
        _,_,graph=self.graph()
        self.assertEqual(graph["stats"]["browser_identity_conflicts"],1)
        self.assertFalse(any(
            node.get("parameter")=="price" and
            node.get("provenance")=="BROWSER_SOURCE_CLAIM_NOT_CHECKOUT"
            for node in graph["nodes"]))
        self.assertTrue(any(e["relation"]=="BROWSER_IDENTITY_DISAGREEMENT"
                            for e in graph["edges"]))

    def test_different_selected_price_shown_as_disagreement_not_overwritten(self):
        self.cart_job(price="29.00")
        self.cart.store_browser_claim(self.capture())
        record,_,graph=self.graph()
        self.assertEqual(record["item"]["price"],"29.00")
        self.assertIsNone(record["input_price"])
        self.assertTrue(any(node.get("status") ==
                            "SAME_URL_DIFFERENT_PRICE_RECHECK_VARIANT_OR_TIME"
                            for node in graph["nodes"]))
        self.assertEqual(graph["stats"]["verified_checkout_prices"],0)

    def test_persisted_claim_visible_in_read_only_receipt_browser(self):
        captured=self.capture()
        self.cart.store_browser_claim(captured)
        rows=self.cart.recent_browser_claim_receipts()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["id"],captured["id"])
        self.assertEqual(
            self.cart.browser_claim_receipt(captured["id"])["result"]["fields"]["price"],
            "34.90")
        with self.assertRaises(ValueError):
            self.cart.browser_claim_receipt("invalid")

    def test_gtin_mismatch_blocks_price_identity(self):
        self.cart_job(barcode="08712561344494")
        def wrong_gtin(product):
            product["gtin13"]="4006381333931"
        capture=self.capture(modify=wrong_gtin)
        self.cart.store_browser_claim(capture)
        _,_,graph=self.graph()
        self.assertEqual(graph["stats"]["browser_identity_conflicts"],1)

    def test_no_checkout_claim_accepted_and_repeated_receipt_idempotent(self):
        self.cart_job()
        capture=self.capture()
        invalid=json.loads(json.dumps(capture))
        invalid["result"]["checkout_verified"]=True
        with self.assertRaisesRegex(ValueError,"UNVERIFIED"):
            self.cart.store_browser_claim(invalid)
        self.cart.store_browser_claim(capture)
        self.cart.store_browser_claim(capture)
        with self.cart._db() as db:
            count=db.execute("SELECT COUNT(*) FROM cart_browser_observations").fetchone()[0]
        self.assertEqual(count,1)

    def test_variant_query_cannot_be_merged_with_same_product_path(self):
        self.cart_job()
        for variant in ("?variant=blue", "?size=L",
                        "?attribute_pa_color=black"):
            with self.subTest(variant=variant):
                capture=self.capture(URL+variant)
                result=self.cart.store_browser_claim(capture)
                self.assertEqual(result["cart_jobs_signalled"],0)
        record,_,graph=self.graph()
        self.assertEqual(record["browser_claims"],[])
        self.assertFalse(any(n.get("source_kind")=="USER_BROWSER_FILTERED_PROJECTION"
                             for n in graph["nodes"]))

    def test_tracking_query_may_match_but_numeric_offerid_is_identity(self):
        from browser_cart_identity import browser_cart_link_key
        self.assertEqual(browser_cart_link_key(URL+"?utm_source=email"),URL)
        self.assertEqual(browser_cart_link_key(URL+"?fbclid=xyz"),URL)
        self.assertIsNone(browser_cart_link_key(URL+"?variant=blue"))
        self.assertNotEqual(browser_cart_link_key(URL+"?offerId=123456"),
                            browser_cart_link_key(URL+"?offerId=789123"))
        self.cart_job()
        captured=self.capture(URL+"?utm_source=email")
        self.cart.store_browser_claim(captured)
        record,_,graph=self.graph()
        self.assertEqual(len(record["browser_claims"]),1)
        self.assertEqual(graph["stats"]["browser_identity_conflicts"],0)

    def test_graph_protects_projection_from_other_url(self):
        self.cart_job()
        capture=self.capture(OTHER)
        projection=build_decision_projection(self.cart.read(JOB))
        projection["browser_claims"]=[capture["result"]]
        graph=build_offer_knowledge_graph(projection)
        self.assertFalse(any(n.get("source_kind")=="USER_BROWSER_FILTERED_PROJECTION"
                             for n in graph["nodes"]))


if __name__ == "__main__":
    unittest.main()
