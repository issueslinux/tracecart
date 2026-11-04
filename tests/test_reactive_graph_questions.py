"""Local source-anchored graph questions never become verified claims."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from graph_question_review import (
    graph_context,eligible,ask_local_llm,attach_model_questions)
from cart_research import CartResearchJobs

ROOT=Path(__file__).resolve().parents[1]
SAMPLE=json.loads((ROOT/"examples"/"live_lenovo_ideapad_index_evidence_2026-11-02.json").read_text())


def graph():
    return {"nodes":[
        {"id":"offer-0","type":"offer","label":"Dell DC15250"},
        {"id":"seller:known","type":"seller_declaration",
         "label":"Seller claims 16 GB RAM","value":"16 GB"},
        {"id":"verification:offer-0:sku","type":"verification_gap",
         "label":"Is exact SKU confirmed?","offer_id":"offer-0"},
        {"id":"price:offer-0","type":"indexed_quote",
         "label":"Unverified 99.99 PLN"},
    ],"edges":[],"stats":{"verified_checkout_prices":0},
    "offer_details":{"offer-0":{"title":"Dell DC15250"}}}


def projection():
    return {"title":"Dell DC15250","category":"LAPTOP",
            "offers":[{"id":"offer-0","title":"Dell DC15250",
                       "indexed_price":"2799.00","currency":"PLN"}]}


class ReactiveGraphTests(unittest.TestCase):
    def test_context_is_bounded_and_ignores_layout_and_index_quote(self):
        state,digest=graph_context(projection(),graph())
        self.assertTrue(eligible(state))
        self.assertEqual(len(state["source_claims_not_verified"]),1)
        self.assertNotIn("99.99",json.dumps(state))
        altered=graph()
        altered["layout"]={"zoom":55}
        self.assertEqual(graph_context(projection(),altered)[1],digest)

    def test_model_question_is_source_anchored(self):
        state,_=graph_context(projection(),graph())
        def response(*args,**kwargs):
            payload=json.loads(args[2].decode())
            self.assertEqual(payload["model"],"qwen2.5:1.5b-instruct")
            self.assertIn("question",payload["format"]["required"])
            return {"message":{"content":json.dumps({
                "question":"Which manufacturer document confirms the RAM on this exact SKU?"
            })}}
        accepted=ask_local_llm(state,request=response)
        self.assertEqual(len(accepted),1)
        self.assertFalse(accepted[0]["evidence_confirmed"])
        self.assertEqual(accepted[0]["anchor_id"],"seller:known")

    def test_proposal_nodes_are_unverified_and_source_linked(self):
        g=graph()
        q={"offer_id":"offer-0","anchor_id":"seller:known",
           "question":"Which OEM document supports the RAM declaration?"}
        out=attach_model_questions(g,{"status":"COMPLETE","questions":[q]})
        self.assertEqual(len(out["nodes"]),len(g["nodes"])+1)
        self.assertEqual(out["stats"]["verified_checkout_prices"],0)
        self.assertEqual(out["stats"]["model_proposed_unverified_questions"],1)
        node=out["nodes"][-1]
        self.assertEqual(node["status"],"OPEN_UNVERIFIED_MODEL_QUESTION")
        self.assertTrue(any(e["from"]=="seller:known" and
                            e["to"]==node["id"] for e in out["edges"]))
        self.assertEqual(len(g["nodes"]),4)
        self.assertIs(attach_model_questions(g,{"status":"STALE_AFTER_GRAPH_CHANGE",
                                                "questions":[q]}),g)

    def test_stale_and_hallucinated_refs_are_not_rendered(self):
        g=graph()
        q={"offer_id":"offer-0","anchor_id":"source:invented",
           "question":"Is this fake evidence independently verifiable?"}
        self.assertIs(attach_model_questions(g,{"status":"COMPLETE",
                                               "questions":[q]}),g)

    def test_priced_coupon_and_index_anomaly_are_prioritized_without_model(self):
        from instant_evidence import priority_actions
        info={"suspicious_price_quotes":[
                  {"offer_id":"offer-1","indexed_price":"139.95"}],
              "promotion_code":"BW1610-0112","options":[]}
        result=priority_actions(projection(),graph(),info)
        self.assertEqual([x["kind"] for x in result],
                         ["INDEX_PRICE_ANOMALY","CONDITIONAL_COUPON",
                          "DELIVERED_TOTAL"])
        self.assertTrue(all(x["verified"] is False for x in result))
        self.assertIn("139.95",result[0]["question"])
        self.assertIn("BW1610-0112",result[1]["question"])

    def test_durable_budget_and_digest_dedup(self):
        with tempfile.TemporaryDirectory() as folder:
            jobs=CartResearchJobs(str(Path(folder)/"research.sqlite3"),
                                  runner=lambda _:SAMPLE["report"])
            jid="M"*24
            with jobs._db() as db:
                db.execute("""INSERT INTO cart_research_jobs
                    (id,item,state,created,result,error_type)
                    VALUES (?,?,?,?,?,NULL)""",
                    (jid,json.dumps(SAMPLE["item"]),"READY",
                     "2026-11-04T00:00:00Z",json.dumps(SAMPLE["report"])))
            state={"offers":[{"id":"offer-0"}],
                   "existing_open_gaps":[{"id":"gap:1"}],
                   "source_claims_not_verified":[{"id":"source:1"}]}
            value={"digest":"abc","calls":0}
            def fake_context(*args):return state,value["digest"]
            def fake_questions(state):
                value["calls"]+=1
                return [{"offer_id":"offer-0","anchor_id":"source:1",
                         "question":"Which independent test confirms the claim?"}]
            try:
                with patch("graph_question_review.graph_context",
                           side_effect=fake_context),patch(
                           "graph_question_review.ask_local_llm",
                           side_effect=fake_questions):
                    jobs._graph_question_worker(jid)
                    jobs._graph_question_worker(jid)
                    self.assertEqual(value["calls"],1)
                    value["digest"]="xyz"
                    jobs._graph_question_worker(jid)
                    value["digest"]="third"
                    jobs._graph_question_worker(jid)
                    self.assertEqual(value["calls"],2)
                    self.assertEqual(jobs.graph_question_review(jid)["runs"],2)
                    self.assertEqual(jobs.graph_question_review(
                        jid,"third")["questions"],[])
            finally:
                jobs.close()

    def test_changed_graph_discards_inflight_proposal(self):
        with tempfile.TemporaryDirectory() as folder:
            jobs=CartResearchJobs(str(Path(folder)/"research.sqlite3"),
                                  runner=lambda _:SAMPLE["report"])
            jid="K"*24
            with jobs._db() as db:
                db.execute("""INSERT INTO cart_research_jobs
                    (id,item,state,created,result,error_type)
                    VALUES (?,?,?,?,?,NULL)""",
                    (jid,json.dumps(SAMPLE["item"]),"READY",
                     "2026-11-04T00:00:00Z",json.dumps(SAMPLE["report"])))
            state={"offers":[{"id":"offer-0"}],
                   "existing_open_gaps":[{"id":"gap:1"}],
                   "source_claims_not_verified":[{"id":"source:1"}]}
            try:
                with patch("graph_question_review.graph_context",
                           side_effect=[(state,"before"),(state,"after")]),patch(
                           "graph_question_review.ask_local_llm",
                           return_value=[{"offer_id":"offer-0",
                           "anchor_id":"source:1",
                           "question":"Can an independent source prove this?"}]):
                    jobs._graph_question_worker(jid)
                review=jobs.graph_question_review(jid)
                self.assertEqual(review["status"],"STALE_AFTER_GRAPH_CHANGE")
                self.assertEqual(review["questions"],[])
            finally:
                jobs.close()


if __name__=="__main__":
    unittest.main()
