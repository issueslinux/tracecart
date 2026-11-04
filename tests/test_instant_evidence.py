"""Live evidence must appear before any LLM and update after source changes."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cart_research import CartResearchJobs
from guided_decision import build_decision_projection
from instant_evidence import current_assessment, semantic_review_needed
from offer_knowledge_graph import build_offer_knowledge_graph

ROOT=Path(__file__).resolve().parents[1]
EXAMPLE=json.loads((ROOT/"examples"/"live_lenovo_ideapad_index_evidence_2026-11-02.json").read_text())


class LiveAssessmentTests(unittest.TestCase):
    def fixture(self,job_id="E"*24,progress="RUNNING"):
        temp=tempfile.TemporaryDirectory()
        jobs=CartResearchJobs(str(Path(temp.name)/"jobs.sqlite3"),
                              runner=lambda _:EXAMPLE["report"])
        with jobs._db() as db:
            db.execute("""INSERT INTO cart_research_jobs
                (id,item,state,created,result,error_type)
                VALUES (?,?,?,?,?,NULL)""",
                (job_id,json.dumps(EXAMPLE["item"]),"READY",
                 "2026-11-03T00:00:00Z",json.dumps(EXAMPLE["report"])))
            db.execute("""INSERT INTO cart_evidence_runs
                (job_id,status,processed,planned)
                VALUES (?,?,?,?)""",(job_id,progress,1,16))
            db.execute("""INSERT INTO cart_final_verdict
                (job_id,status,result_json,error_type)
                VALUES (?,'QUEUED',NULL,NULL)""",(job_id,))
        return temp,jobs,job_id

    def test_ready_research_has_immediate_assessment_while_model_is_queued(self):
        temp,jobs,jid=self.fixture()
        try:
            _,snapshot=jobs.live_snapshot(jid)
            live=snapshot["instant_assessment"]
            self.assertEqual(snapshot["final_verdict"]["status"],"QUEUED")
            self.assertEqual(live["status"],"PRELIMINARY")
            self.assertEqual(live["origin"],
                             "DETERMINISTIC_CURRENT_EVIDENCE_NOT_LLM")
            self.assertEqual(live["verification"],"NO_VERIFIED_BEST_BUY")
            self.assertFalse(live["payment_authorized"])
            self.assertTrue(live["purchase_insights"]["status"])
            self.assertEqual(jobs.live_snapshot(jid)[1],snapshot)
        finally:
            jobs.close()
            temp.cleanup()

    def test_preview_during_running_source_research_is_not_blocked(self):
        temp,jobs,jid=self.fixture()
        try:
            with jobs._db() as db:
                db.execute("""UPDATE cart_research_jobs SET state='RUNNING',
                    result=NULL WHERE id=?""",(jid,))
                db.execute("""INSERT INTO cart_research_progress
                    (job_id,stage,revision,preview) VALUES (?,?,1,?)""",
                    (jid,"BASE_RESEARCH_AVAILABLE",
                     json.dumps(EXAMPLE["report"])))
            jobs.live_bus.signal(jid)
            live=jobs.live_snapshot(jid)[1]
            self.assertEqual(live["state"],"RUNNING")
            self.assertEqual(live["instant_assessment"]["status"],"PRELIMINARY")
            self.assertEqual(live["final_verdict"]["status"],"QUEUED")
            self.assertFalse(live["instant_assessment"]["payment_authorized"])
        finally:
            jobs.close()
            temp.cleanup()

    def test_selected_price_change_refreshes_live_assessment_even_with_old_model(self):
        temp,jobs,jid=self.fixture(progress="COMPLETE")
        try:
            before_rev,before=jobs.live_snapshot(jid)
            self.assertEqual(before["instant_assessment"]["status"],"CURRENT")
            jobs.set_input_price(jid,"2799.00",promotion_code="EXAMPLECODE")
            after_rev,after=jobs.live_snapshot(jid)
            self.assertGreater(after_rev,before_rev)
            observed=after["instant_assessment"]["purchase_insights"]
            self.assertEqual(observed["selected_price"],"2799.00 PLN")
            self.assertEqual(observed["promotion_code"],"EXAMPLECODE")
            self.assertEqual(after["final_verdict"]["status"],"QUEUED")
            self.assertFalse(after["instant_assessment"]["payment_authorized"])
            # Model verdict did not need to be persisted again.
        finally:
            jobs.close()
            temp.cleanup()

    def test_no_model_request_when_missing_receipt_is_only_unknown(self):
        temp,jobs,jid=self.fixture(progress="COMPLETE")
        try:
            with patch("instant_evidence.semantic_review_needed",
                       return_value=False), patch(
                       "model_verdict.generate_final_verdict",
                       side_effect=AssertionError("Qwen must not run")):
                jobs._generate_final_verdict(jid)
            result=jobs.read(jid)["final_verdict"]
            self.assertEqual(result["status"],"SKIPPED_NOT_NEEDED")
            self.assertEqual(result["origin"],
                             "DETERMINISTIC_NO_SEMANTIC_REVIEW_NEEDED")
            self.assertIsNone(result["model"])
            self.assertFalse(result["payment_authorized"])
            self.assertEqual(jobs.read(jid)["progress_stage"],
                             "FINAL_VERDICT_SKIPPED_NOT_NEEDED")
            self.assertEqual(jobs.live_snapshot(jid)[1][
                "instant_assessment"]["status"],"CURRENT")
        finally:
            jobs.close()
            temp.cleanup()

    def test_documented_semantic_conflict_allows_optional_model(self):
        projection={"offers":[{"id":"offer-0","title":"Sample",
                               "indexed_price":"300","currency":"PLN"}]}
        graph={"stats":{"unresolved_source_discrepancies":2}}
        self.assertTrue(semantic_review_needed(projection,graph))
        graph={"stats":{"unresolved_source_discrepancies":0,
                        "documented_product_declarations":0,
                        "seller_page_declarations":0}}
        self.assertFalse(semantic_review_needed(projection,graph))

    def test_incomplete_checkout_not_promoted_to_verified(self):
        temp,jobs,jid=self.fixture(progress="COMPLETE")
        try:
            record=jobs.read(jid)
            graph=build_offer_knowledge_graph(build_decision_projection(record))
            res=current_assessment(build_decision_projection(record),graph,
                                   "COMPLETE")
            self.assertEqual(res["verification"],"NO_VERIFIED_BEST_BUY")
            self.assertFalse(res["payment_authorized"])
            self.assertNotIn("model",res)
        finally:
            jobs.close()
            temp.cleanup()


if __name__=="__main__":
    unittest.main()
