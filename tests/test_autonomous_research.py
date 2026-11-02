"""Source-scope regression: no invented exact SKU or independent OLED benchmark."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from autonomous_research import build_research_path, enrich_index_research_with_llm
from guided_decision import build_decision_projection

ROOT=Path(__file__).resolve().parents[1]
CASE=json.loads((ROOT/"examples"/"live_lenovo_ideapad_index_evidence_2026-11-02.json").read_text())

class AutonomousResearchTests(unittest.TestCase):
    def test_lenovo_sources_are_real_but_not_submitted_sku_claims(self):
        projection=build_decision_projection(CASE)
        research=projection["research"]
        self.assertEqual(len(research["sources"]),4)
        self.assertEqual(research["llm_question_generation"],"NOT_RECORDED")
        self.assertTrue(all(s["url"].startswith("https://") and
                            not s["verified_for_submitted_sku"]
                            for s in research["sources"]))
        self.assertIn("IPS/60Wh",research["questions"][2]["finding"])
        self.assertIn("OLED",research["questions"][0]["finding"])
        self.assertIn("16IPH11",research["questions"][2]["finding"])
        self.assertTrue(all(q["addressed_to"]=="RESEARCH_AGENT_NOT_BUYER"
                            for q in research["questions"]))
        self.assertFalse(research["conclusion"]["auto_payment"])
        self.assertEqual(projection["questions"],[])

    def test_not_generic_knowledge_for_unrelated_products(self):
        r=build_research_path({},{"title":"Raspberry Pi 5 8GB"},[],{})
        self.assertEqual(r["sources"],[])
        self.assertEqual(r["conclusion"]["status"],"ABSTAIN_UNVERIFIED_PRICE_AND_VARIANT")
        self.assertFalse(any("Notebookcheck" in str(q) for q in r["questions"]))

    def test_actual_saved_llm_question_preserved_without_generated_answer(self):
        report={"root":{"details":{"local_ai_question_generation":"OK"},
            "children":[{"kind":"category_model","children":[{"kind":"question_group",
                "children":[{"kind":"question",
                "title":"Which independent repairability measurements apply?",
                "details":{"question_origin":"LOCAL_LLM"}}]}]}]}}
        r=build_research_path(report,{"title":"Unrelated kettle"},[],{})
        found=[x for x in r["questions"] if x["origin"]=="LOCAL_LLM"]
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]["verdict"],"OPEN_RESEARCH_GAP")
        self.assertIn("No independent",found[0]["finding"])

    def test_bounded_post_shopping_llm_writes_questions_not_answers(self):
        seen=[]
        def fake_request(url, method, body, headers, timeout):
            seen.append(json.loads(body.decode("utf-8")))
            return {"message":{"content":json.dumps({"questions":[
                "Which Lenovo PSREF machine type matches the retailer listing?",
                "What independent measured battery test used this exact panel?"]})}}
        source=json.loads(json.dumps(CASE["report"]))
        result=enrich_index_research_with_llm(source,CASE["item"],request=fake_request)
        self.assertEqual(result["root"]["details"]["post_index_llm_question_generation"],"OK")
        self.assertNotIn("post_index_llm_question_generation",source["root"]["details"])
        self.assertEqual(len(seen),1)
        self.assertNotIn("indexed_price",json.dumps(seen[0]))
        self.assertNotIn("merchant_url",json.dumps(seen[0]))
        branch=[x for x in result["root"]["children"] if x.get("kind")=="category_model"]
        self.assertTrue(branch)
        model=[g for g in branch[0]["children"] if g.get("title")=="Post-index model questions"]
        self.assertEqual(len(model[0]["children"]),2)
        self.assertTrue(all(x["details"]["question_origin"]=="LOCAL_LLM_SHOPPING_FOLLOWUP"
                            and x["status"]=="OPEN" for x in model[0]["children"]))
        path=build_research_path(result,CASE["item"],[],{})
        self.assertEqual(path["llm_question_generation"],"POST_INDEX_LLM_OK")
        self.assertTrue(any(x["origin"]=="LOCAL_LLM_SHOPPING_FOLLOWUP"
                            for x in path["questions"]))

    def test_local_model_failure_is_recorded_without_fake_answer(self):
        def down(*args,**kwargs):
            raise TimeoutError("no local model")
        result=enrich_index_research_with_llm(CASE["report"],CASE["item"],request=down)
        self.assertEqual(result["root"]["details"]["post_index_llm_question_generation"],
                         "UNAVAILABLE_TimeoutError")
        self.assertNotIn("post_index_llm_question_generation",
                         CASE["report"]["root"]["details"])

    def test_no_experimental_data_leaks_into_other_intel_variant(self):
        r=build_research_path({},{"title":"Lenovo IdeaPad Slim 3 Intel Core Ultra 5 322 16IPH11"},[],{})
        self.assertFalse(r["sources"])
        self.assertNotIn("19h01m",str(r))

if __name__=="__main__":
    unittest.main()
