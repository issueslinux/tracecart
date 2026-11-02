"""Fast research staging, 288 distinct planned source checks per actual offer."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from offer_question_bank import (offer_summaries, questions_for_offer,
                                  propose_offer_model_questions, PAGE_SIZE)
from guided_decision import build_decision_projection
from cart_research import CartResearchJobs

ROOT=Path(__file__).resolve().parents[1]
RECORD=json.loads((ROOT/"examples"/"live_lenovo_ideapad_index_evidence_2026-11-02.json").read_text())

class ProgressiveOfferResearchTests(unittest.TestCase):
    def test_every_indexed_offer_has_hundreds_of_distinct_questions(self):
        data=build_decision_projection(RECORD)
        offers=data["offers"]
        self.assertEqual(len(offers),16)
        self.assertEqual(sum(o["question_count"] for o in offers),4608)
        for offer in offers:
            self.assertEqual(offer["question_count"],288)
            seen=set()
            for offset in range(0,offer["question_count"],PAGE_SIZE):
                page=questions_for_offer(offer,"LAPTOP",offset)
                for q in page["questions"]:
                    self.assertNotIn(q["question"],seen)
                    seen.add(q["question"])
                    self.assertIsNone(q["finding"])
                    self.assertEqual(q["status"],"PLANNED_NOT_INVESTIGATED")
                    self.assertEqual(q["origin"],"STRUCTURED_RESEARCH_PLAN_NOT_LLM")
                    self.assertEqual(q["addressed_to"],"RESEARCH_AGENT_NOT_BUYER")
            self.assertEqual(len(seen),288)
        self.assertFalse(data["payment_authorized"])

    def test_fast_projection_from_queued_only_url_does_not_claim_identity(self):
        data=build_decision_projection({
            "state":"QUEUED","progress_stage":"SOURCE_FETCH",
            "item":{"merchant_url":RECORD["item"]["merchant_url"]}})
        self.assertEqual(data["progress_stage"],"SOURCE_FETCH")
        self.assertEqual(len(data["offers"]),1)
        self.assertEqual(data["offers"][0]["question_count"],288)
        self.assertNotIn("candidates",data)
        self.assertFalse(data["payment_authorized"])

    def test_boundaries_invalid_offsets_and_no_massive_response(self):
        offer=offer_summaries(RECORD,"LAPTOP")[1]
        for offset in (-1,289):
            with self.assertRaises(ValueError):
                questions_for_offer(offer,"LAPTOP",offset)
        for size in (0,25,1000000):
            with self.assertRaises(ValueError):
                questions_for_offer(offer,"LAPTOP",0,size)
        last=questions_for_offer(offer,"LAPTOP",264)
        self.assertEqual(last["next_offset"],None)
        self.assertEqual(len(last["questions"]),24)
        self.assertLess(len(json.dumps(last)),20000)

    def test_real_per_offer_llm_shape_does_not_send_urls_or_prices(self):
        observed=[]
        def fake(url, method, body, headers, timeout):
            payload=json.loads(body.decode("utf-8"))
            observed.append(payload)
            return {"message":{"content":json.dumps({"questions":[
                "What OEM panel identity is documented for this exact variant?",
                "Which independently measured battery results match the exact model?"]})}}
        offer=offer_summaries(RECORD,"LAPTOP")[1]
        proposed=propose_offer_model_questions(offer,"LAPTOP",request=fake)
        self.assertEqual(len(proposed),2)
        self.assertTrue(all(q["origin"]=="LOCAL_LLM_PER_OFFER" and
                            q["finding"] is None for q in proposed))
        text=json.dumps(observed)
        self.assertNotIn("merchant_url",text)
        self.assertNotIn("indexed_price",text)
        self.assertNotIn("allegro.pl",text)
        self.assertEqual(len(observed),1)

    def test_per_offer_llm_persists_outside_original_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs=CartResearchJobs(str(Path(tmp)/"jobs.sqlite"),
                                  runner=lambda x: deepcopy(RECORD["report"]))
            try:
                with patch("offer_question_bank.propose_offer_model_questions",
                           side_effect=lambda offer,cat: [{
                               "question":"Which lab test applies to "+offer["id"]+"?",
                               "finding":None,"origin":"LOCAL_LLM_PER_OFFER"}]):
                    jobs._generate_offer_questions("Z"*24,RECORD)
                with jobs._db() as db:
                    rows=db.execute("SELECT offer_idx,status,questions_json FROM cart_offer_model_questions WHERE job_id=? ORDER BY offer_idx",("Z"*24,)).fetchall()
                self.assertEqual(len(rows),16)
                self.assertTrue(all(r[1]=="OK" and len(json.loads(r[2]))==1 for r in rows))
                self.assertEqual(RECORD["report"]["root"]["details"].get(
                    "post_index_llm_question_generation"),None)
            finally:
                jobs.close()

    def test_snapshot_visible_while_local_llm_blocks_not_after_it(self):
        start=threading.Event()
        release=threading.Event()
        item=RECORD["item"]
        source={
            "price_status":"NOT_VERIFIED_PAGE_BLOCKED",
            "extraction_method":"Generic URL",
            "intake_status":"URL_ONLY_UNVERIFIED"
        }
        report=RECORD["report"]
        def slow_llm(r, clean):
            start.set()
            if not release.wait(8):
                raise RuntimeError("test timeout")
            return r
        with tempfile.TemporaryDirectory() as tmp:
            jobs=CartResearchJobs(str(Path(tmp)/"jobs.sqlite"),
                                  runner=lambda x: deepcopy(report))
            try:
                with patch("product_intake.extract_product_page",
                           return_value=(item,source)), patch.dict("os.environ",
                           {"SERPAPI_API_KEY": ""}), patch(
                           "autonomous_research.enrich_index_research_with_llm",
                           side_effect=slow_llm):
                    jid=jobs.submit_url(item["merchant_url"])
                    self.assertTrue(start.wait(3),"worker should begin model stage")
                    current=jobs.read(jid)
                    self.assertEqual(current["state"],"RUNNING")
                    self.assertEqual(current["progress_stage"],
                                     "LLM_SOURCE_QUESTIONS_IN_PROGRESS")
                    projected=build_decision_projection(current)
                    self.assertEqual(len(projected["offers"]),16)
                    self.assertEqual(projected["evidence"]["google_shopping_cards"],12)
                    self.assertEqual(projected["evidence"]["indexed_store_links"],3)
                    self.assertFalse(projected["payment_authorized"])
                    release.set()
                    for _ in range(80):
                        current=jobs.read(jid)
                        if current["state"] in ("READY","FAILED"):
                            break
                        time.sleep(.025)
                    self.assertEqual(current["state"],"READY",current["error_type"])
            finally:
                release.set()
                jobs.close()

if __name__=="__main__":
    unittest.main()
