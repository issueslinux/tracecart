"""Paid source lookup has a hard per-job budget and never creates evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from source_search import (
    MAX_QUERIES,query_plan,search_source_urls,attach_discovery_leads,
    _clean_result,
)
from cart_research import CartResearchJobs
from guided_decision import build_decision_projection
from offer_knowledge_graph import build_offer_knowledge_graph

ROOT=Path(__file__).resolve().parents[1]
LAPTOP=json.loads((ROOT/"examples/live_lenovo_ideapad_index_evidence_2026-11-02.json").read_text())

def offers():
    return [{"id":"offer-0","title":"Rower elektryczny 250W 15Ah 100km"},
            {"id":"offer-1","title":"ALLGOBIKE AM27 250W 36V 15Ah"},
            {"id":"offer-2","title":"ALLGOBIKE AM27 250W 36V 15Ah 100km"},
            {"id":"offer-3","title":"Lenovo IdeaPad Slim 3 15Q8X10"},
            {"id":"offer-4","title":"Samsung Galaxy S24 128 GB"},
            {"id":"offer-5","title":"Kingston KC3000 1TB"},
            {"id":"offer-6","title":"Bosch GSR 18V drill"},
            {"id":"offer-7","title":"Garmin Forerunner 265"},
           ]

class SourceSearchTests(unittest.TestCase):
    def test_cost_budget_deduplicates_similar_indexed_variants(self):
        plan=query_plan(offers())
        self.assertEqual(len(plan),6)
        self.assertEqual(len({(x["identity"]["brand"],x["identity"]["model"])
            for x in plan}),3)
        self.assertEqual(plan[0]["identity"],
                         {"brand":"allgobike","model":"am27"})
        self.assertEqual(plan[0]["purpose"],"SPECIFICATIONS")
        self.assertEqual(plan[1]["purpose"],"REVIEWS")
        with self.assertRaises(ValueError):
            query_plan(offers(),MAX_QUERIES+1)

    def test_disabled_or_missing_key_makes_no_provider_calls(self):
        def fail(*args,**kwargs):
            self.fail("Provider request without explicit operator opt in")
        for enabled,key,status in ((False,"dummy","SKIPPED_NOT_ENABLED"),
                                   (True,"","SKIPPED_NO_API_KEY")):
            got=search_source_urls(offers(),request=fail,key=key,
                                   enabled=enabled)
            self.assertEqual(got["status"],status)
            self.assertEqual(got["queries_used"],0)
            self.assertEqual(got["leads"],[])

    def test_hits_require_brand_and_exact_model_in_search_result_title(self):
        identity={"brand":"allgobike","model":"am27"}
        for entry in [
            {"title":"Otherbrand AM27 specifications",
             "url":"https://reviews.example.com/otherbrand-am27"},
            {"title":"ALLGOBIKE AM28 review",
             "url":"https://reviews.example.com/am28"},
            {"title":"ALLGOBIKE AM27 review",
             "url":"http://reviews.example.com/am27"},
            {"title":"ALLGOBIKE AM27 test",
             "url":"https://127.0.0.1/secret"},
            {"title":"ALLGOBIKE AM27 on Allegro",
             "url":"https://www.allegro.pl/offer/am27"},
        ]:
            self.assertIsNone(_clean_result(entry,identity,"REVIEWS"))
        good=_clean_result({
            "title":"ALLGOBIKE AM27 review",
            "url":"https://review.example.org/bikes/allgobike-am27",
            "description":"A 100% proven test!"},identity,"REVIEWS")
        self.assertIsNotNone(good)
        self.assertEqual(good["source_status"],"UNVERIFIED_UNFETCHED")
        self.assertNotIn("description",good)
        self.assertNotIn("finding",good)

    def test_result_retrieval_bounded_and_model_attached_but_not_verified(self):
        calls=[]
        def provider(url,host,headers,timeout=12):
            calls.append((url,host,headers,timeout))
            return {"web":{"results":[
                {"title":"ALLGOBIKE AM27 review lab",
                 "url":"https://review.example.org/am27"},
                {"title":"ALLGOBIKE AM27 manufacturer specs",
                 "url":"https://allgobike.com/products/allgobike-am27"},
                {"title":"ALLGOBIKE AM28 different bicycle",
                 "url":"https://reviews.example.org/am28"},
                {"title":"ALLGOBIKE AM27 review duplicate",
                 "url":"https://review.example.org/am27"},
                {"title":"URL only and no model",
                 "url":"https://review.example.org/unrelated"},
            ]}}
        receipt=search_source_urls(offers()[:3],request=provider,
                                    key="DUMMY_TEST_KEY",enabled=True)
        self.assertEqual(len(calls),2)
        self.assertTrue(all(c[1]=="api.search.brave.com" for c in calls))
        self.assertTrue(all("DUMMY_TEST_KEY"==c[2]["X-Subscription-Token"]
                            for c in calls))
        self.assertEqual(receipt["queries_used"],2)
        self.assertEqual(receipt["status"],"COMPLETE")
        self.assertEqual(len(receipt["leads"]),2)
        self.assertNotIn("DUMMY_TEST_KEY",json.dumps(receipt))
        attached=attach_discovery_leads(offers()[:3],receipt)
        self.assertNotIn("discovered_source_urls",attached[0])
        self.assertEqual(len(attached[1]["discovered_source_urls"]),2)
        self.assertEqual(len(attached[2]["discovered_source_urls"]),2)
        self.assertEqual(attached[1]["discovered_source_urls"][0]["origin"],
                         "PAID_SEARCH_INDEX_LEAD_NOT_EVIDENCE")
        self.assertEqual(len(receipt["query_receipts"]),2)

    def test_sqlite_receipt_reused_after_restart_no_second_provider_charge(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=str(Path(tmp)/"jobs.sqlite")
            job="R"*24
            jobs=CartResearchJobs(db)
            with jobs._db() as conn:
                conn.execute("""INSERT INTO cart_research_jobs
                    (id,item,state,created,result,error_type)
                    VALUES (?,?,?,?,?,NULL)""",
                    (job,json.dumps(LAPTOP["item"]),"READY",
                     "2026-11-03T12:00:00Z",json.dumps(LAPTOP["report"])))
            original=jobs.read(job)["report"]
            n=[0]
            record={
                "status":"COMPLETE","queries_used":2,
                "leads":[{"url":"https://review.example.org/lenovo-15q8x10",
                  "title":"Lenovo 15Q8X10 tech review",
                  "model_identity":{"brand":"lenovo","model":"15q8x10"},
                  "origin":"PAID_SEARCH_INDEX_LEAD_NOT_EVIDENCE",
                  "source_status":"UNVERIFIED_UNFETCHED"}],
                "query_receipts":[]}
            def mocked(*args,**kwargs):
                n[0]+=1
                return record
            from evidence_execution import execute_reference_checks
            no_source=lambda offer,category,fetch=None:{
                "status":"NO_SOURCE","reference_answers":[],
                "verified_for_exact_offer":0,"sources_checked":0}
            with patch("source_search.search_source_urls",side_effect=mocked),patch(
                    "evidence_execution.execute_reference_checks",
                    side_effect=no_source):
                jobs._execute_source_evidence(job,jobs.read(job))
                self.assertEqual(n[0],1)
                jobs._execute_source_evidence(job,jobs.read(job))
                self.assertEqual(n[0],1)
            read=jobs.read(job)
            self.assertEqual(read["source_search"]["queries_used"],2)
            self.assertEqual(read["report"],original)
            self.assertEqual(read["evidence_progress"]["status"],"COMPLETE")
            graph=build_offer_knowledge_graph(build_decision_projection(read))
            self.assertEqual(graph["stats"]["source_discovery_leads"],1)
            self.assertEqual(sum(x["type"]=="source_lead"
                                 for x in graph["nodes"]),1)
            self.assertTrue(any(x["relation"]=="SOURCE_DISCOVERY_LEAD"
                                for x in graph["edges"]))
            self.assertEqual(graph["stats"]["independent_reference_measurements"],0)
            self.assertEqual(graph["stats"]["verified_exact_sku_answers"],0)
            jobs.close()

if __name__=="__main__":
    unittest.main()
