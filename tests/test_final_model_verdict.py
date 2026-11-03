"""Final local-model verdict: attributed facts, bounded context and durable state."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cart_research import CartResearchJobs
from model_verdict import (generate_final_verdict,insufficient_verdict,
                           verdict_context,compact_verdict_context,RECORD_LIMIT)

ROOT=Path(__file__).resolve().parents[1]
EXAMPLE=json.loads((ROOT/"examples"/"live_lenovo_ideapad_index_evidence_2026-11-02.json").read_text())


def source_graph():
    return {"stats":{"offers":2,"documented_product_declarations":1,
                     "seller_page_declarations":0,
                     "independent_reference_measurements":0,
                     "verified_exact_sku_answers":0,
                     "verified_checkout_prices":0},
      "nodes":[
        {"id":"offer-0","type":"offer","label":"Maker ZX-12 laptop",
         "offer_kind":"INPUT_PRODUCT","provenance":"URL_TITLE_UNVERIFIED"},
        {"id":"offer-1","type":"offer","label":"Maker ZX-13 laptop",
         "offer_kind":"INDEXED_SELLER_LINK",
         "provenance":"SEARCH_INDEX_TITLE_UNVERIFIED"},
        {"id":"price:offer-1","type":"indexed_quote","label":"400 PLN",
         "value":"400","currency":"PLN"},
        {"id":"spec:1","type":"title_claim","label":"16 GB RAM"},
        {"id":"declared:1","type":"source_declaration","label":"RAM: 16 GB",
         "source_kind":"BRAND_SITE_DECLARATIONS_NOT_INDEPENDENT_TESTS",
         "value":"16 GB"},
        {"id":"gap:1","type":"verification_gap","label":"Independent tests?"},
      ]}


def projection():
    return {"title":"Maker ZX-12 laptop","category":"LAPTOP",
      "selected_source_intake":{"access_problem":"HTTP_403",
                                "intake_status":"URL_ONLY_UNVERIFIED"},
      "evidence_offers":{"offer-0":{"status":"NO_MATCHED_INDEPENDENT_SOURCE"}},
    }


class FinalVerdictTests(unittest.TestCase):
    def test_context_includes_two_offers_with_distinct_provenance(self):
        context=verdict_context(projection(),source_graph())
        self.assertEqual(len(context["offers"]),2)
        self.assertEqual(context["offers"][1]["indexed_quote"]["status"],
                         "UNVERIFIED_INDEX_NOT_CHECKOUT")
        self.assertEqual(context["source_observations"][0]["id"],"declared:1")
        self.assertEqual(context["selected_page"]["access"],"HTTP_403")
        self.assertNotIn("gap:1",json.dumps(context))
        self.assertLessEqual(len(json.dumps(context,ensure_ascii=False)),RECORD_LIMIT)
        compact=compact_verdict_context(context)
        self.assertEqual(len(compact["offer_rows_id_title_price_status"]),2)
        self.assertEqual(len(compact["published_specs_not_independent_tests"]),1)
        self.assertEqual(compact["indexed_prices"],"UNVERIFIED_INDEX_NOT_CHECKOUT")
        self.assertLess(len(json.dumps(compact)),len(json.dumps(context)))

    def test_local_llm_returns_sourced_conditional_interpretation(self):
        def response(url,method,data,headers,timeout):
            payload=json.loads(data.decode())
            self.assertEqual(url,"http://127.0.0.1:11435/api/chat")
            self.assertEqual(payload["model"],"qwen2.5:1.5b-instruct")
            self.assertIn("UNVERIFIED_INDEX_NOT_CHECKOUT",
                          payload["messages"][1]["content"])
            self.assertNotIn("Independent tests?",payload["messages"][1]["content"])
            return {"message":{"content":json.dumps({
                "verdict":"COMPARE_WITH_CAUTION"
            })}}
        result=generate_final_verdict(projection(),source_graph(),request=response)
        self.assertEqual(result["status"],"COMPLETE")
        self.assertEqual(result["observations"][0]["evidence_ids"],["declared:1"])
        self.assertEqual(result["verification"],"NO_VERIFIED_BEST_BUY")
        self.assertFalse(result["payment_authorized"])

    def test_extra_model_provenance_fields_are_not_accepted(self):
        def fake(*args,**kwargs):
            return {"message":{"content":json.dumps({
                "verdict":"COMPARE_WITH_CAUTION",
                "summary":"A proposed claim that has not actually been evidenced by any page.",
                "observations":[{"text":"Independent test proves quality",
                                 "evidence_ids":["invented-evidence"]}],
                "next_step":"Check seller terms before buying."
            })}}
        with self.assertRaisesRegex(ValueError,"INVALID_VERDICT_FIELDS"):
            generate_final_verdict(projection(),source_graph(),request=fake)

    def test_fallback_does_not_claim_local_model_success(self):
        result=insufficient_verdict(source_graph(),"TimeoutError")
        self.assertEqual(result["origin"],"DETERMINISTIC_FALLBACK_NOT_LLM")
        self.assertEqual(result["status"],"UNAVAILABLE")
        self.assertFalse(result["payment_authorized"])

    def test_final_result_persists_independently_without_rewriting_saved_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            jobs=CartResearchJobs(str(Path(temp)/"evidence.sqlite3"),
                                  runner=lambda _:EXAMPLE["report"])
            job_id="W"*24
            try:
                with jobs._db() as db:
                    db.execute("""INSERT INTO cart_research_jobs
                        (id,item,state,created,result,error_type)
                        VALUES (?,?,?,?,?,NULL)""",
                        (job_id,json.dumps(EXAMPLE["item"]),"READY",
                         "2026-11-03T00:00:00Z",json.dumps(EXAMPLE["report"])))
                    db.execute("""INSERT INTO cart_evidence_runs
                        (job_id,status,processed,planned) VALUES (?,'COMPLETE',1,1)""",
                        (job_id,))
                    db.execute("""INSERT INTO cart_final_verdict
                        (job_id,status,result_json,error_type)
                        VALUES (?,'QUEUED',NULL,NULL)""",(job_id,))
                original=jobs.read(job_id)["report"]
                with patch("model_verdict.generate_final_verdict",
                           side_effect=TimeoutError("test only")):
                    jobs._generate_final_verdict(job_id)
                result=jobs.read(job_id)
                self.assertEqual(result["final_verdict"]["status"],"UNAVAILABLE")
                self.assertEqual(result["final_verdict"]["origin"],
                                 "DETERMINISTIC_FALLBACK_NOT_LLM")
                self.assertEqual(result["progress_stage"],"FINAL_VERDICT_UNAVAILABLE")
                self.assertEqual(result["report"],original)
                self.assertEqual(jobs.live_snapshot(job_id)[1]["final_verdict"]["status"],
                                 "UNAVAILABLE")
            finally:
                jobs.close()


if __name__=="__main__":
    unittest.main()
