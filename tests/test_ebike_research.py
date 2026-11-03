"""E-bike source-research plans must be relevant, dynamic, and provenance-safe."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from ebike_research import (FACETS, FOLLOWUPS, ebike_question_count,
                            offer_title_diagnostics, questions_for_ebike)
from offer_question_bank import (offer_summaries, questions_for_offer,
                                 propose_offer_model_questions)
from evidence_execution import execute_reference_checks

BIKE="rower elektryczny meski damski 250w 15ah 100km 27 5 ebike shimano 7s 25kmh"
URL="https://allegro.pl/produkt/example-bike-12345"


def sample_record():
    return {
        "item":{"title":BIKE, "price":None, "currency":None,
                "barcode":"","merchant_url":URL},
        "report":{"indexed_shopping":{"indexed_offers":[],
            "search_result_groups":[
                {"title":"Rower elektryczny Męski/Damski Allgobike AM27 250W 36V 15AH 100KM 27.5",
                 "indexed_price":"2599", "indexed_currency":"PLN",
                 "source":"Google Shopping card"},
                {"title":"Orzel C27 Rower Elektryczny 27,5 250W 15Ah 25km/h 100km",
                 "indexed_price":"3399", "indexed_currency":"PLN",
                 "source":"Google Shopping card"},
                {"title":"Evercross EK15 250W 36V bike no matching battery",
                 "indexed_price":"3028", "indexed_currency":"PLN",
                 "source":"Google Shopping card"}
            ]}}
    }


class EBikePlanTests(unittest.TestCase):
    def test_first_page_is_relevant_cross_dimension_research(self):
        offer=offer_summaries(sample_record(),"E_BIKE")[0]
        page=questions_for_offer(offer,"E_BIKE",0,24)
        qs=page["questions"]
        self.assertEqual(len(qs),24)
        self.assertEqual(len({q["dimension"] for q in qs}),24)
        self.assertTrue(all(q["priority"]=="P0" for q in qs))
        self.assertIn("15 Ah",qs[1]["question"])
        self.assertIn("100 km",qs[2]["question"])
        self.assertIn("25 km/h",qs[3]["question"])
        self.assertIn("250 W",qs[4]["question"])
        self.assertFalse(any("laboratory measured manufacturer frame" in
                             q["question"] for q in qs))
        self.assertTrue(all(q["origin"]=="DOMAIN_SPECIFIC_RESEARCH_PLAN_NOT_LLM"
                            and q["finding"] is None
                            and q["status"]=="PLANNED_NOT_INVESTIGATED"
                            for q in qs))

    def test_at_least_two_hundred_valid_nonduplicate_checks_per_offer(self):
        offers=offer_summaries(sample_record(),"E_BIKE")
        self.assertEqual(ebike_question_count(),228)
        for offer in offers:
            seen=set()
            for start in range(0,offer["question_count"],24):
                page=questions_for_offer(offer,"E_BIKE",start,24)
                for q in page["questions"]:
                    self.assertNotIn(q["question"],seen)
                    seen.add(q["question"])
                    self.assertTrue(q["question"].endswith("?"))
                self.assertEqual(page["next_offset"],min(start+24,228)
                                 if start+24<228 else None)
            self.assertEqual(len(seen),228)
        self.assertEqual(len(FACETS),24)
        self.assertTrue(all(len(x)==8 for x in FOLLOWUPS.values()))

    def test_other_bicycle_does_not_inherit_unrelated_numeric_claims(self):
        offer={"id":"offer-0","title":"Electric bicycle folding adult 500W 36V 12Ah"}
        text=" ".join(q["question"] for off in range(0,48,24)
                      for q in questions_for_ebike(offer,off)["questions"])
        for invalid in ("100 km","15 Ah","250 W","7-speed","27.5-inch"):
            self.assertNotIn(invalid,text)
        self.assertIn("500 W",text)
        self.assertIn("12 Ah",text)

    def test_title_only_values_are_signals_not_verified_findings(self):
        offer=offer_summaries(sample_record(),"E_BIKE")[0]
        self.assertEqual(offer["question_count"],228)
        self.assertTrue(all(x["status"] in (
            "UNVERIFIED_LISTING_TITLE","NOT_DECLARED_IN_TITLE")
            for x in offer["listing_title_claims"]))
        diagnostic=offer["research_diagnostics"]
        self.assertEqual(diagnostic["status"],"UNVERIFIED_TITLE_ONLY")
        self.assertEqual([(x["energy_wh"],x["implied_wh_per_km"]) for x in
                          diagnostic["scenarios"]],
                         [(540.0,5.4),(720.0,7.2)])
        self.assertTrue(all(x["status"]=="HYPOTHETICAL_NOT_PRODUCT_EVIDENCE"
                            for x in diagnostic["scenarios"]))
        self.assertTrue(any("voltage" in x.lower() for x in
                            diagnostic["missing_evidence"]))
        self.assertEqual([x["model_hint"] for x in offer["index_model_hints"]],
                         ["Allgobike AM27","Orzel C27"])
        self.assertTrue(all(not x["exact_seller_sku_verified"]
                            for x in offer["index_model_hints"]))

    def test_title_and_index_cannot_count_as_independent_tests(self):
        offer=offer_summaries(sample_record(),"E_BIKE")[0]
        result=execute_reference_checks(offer,"E_BIKE",
                    fetch=lambda *a,**k: b"User-agent: *\nDisallow: /\n")
        self.assertEqual(result["status"],"NO_MATCHED_INDEPENDENT_EBIKE_REVIEW")
        self.assertEqual(result["sources_checked"],0)
        self.assertEqual(result["verified_for_exact_offer"],0)
        self.assertEqual(result["reference_answers"],[])
        self.assertTrue(result["pending_high_impact"])

    def test_qwen_fallback_retries_malformed_json_shorter(self):
        calls=[]
        def requester(url,method,body,headers,timeout):
            payload=json.loads(body)
            calls.append(payload)
            if len(calls)==1:
                return {"message":{"content":'{"questions":["What is the maker of the motor?","What battery'}}
            return {"message":{"content":json.dumps({"questions":[
                "What is the independently verified motor model?",
                "Which certified battery manufacturer supplies this pack?"]})}}
        offer=offer_summaries(sample_record(),"E_BIKE")[0]
        questions=propose_offer_model_questions(offer,"E_BIKE",
                                               request=requester)
        self.assertEqual(len(calls),2)
        self.assertEqual(len(questions),2)
        self.assertTrue(all(q["origin"]=="LOCAL_LLM_PER_OFFER" for q in questions))
        self.assertEqual(calls[0]["options"]["num_predict"],340)
        self.assertEqual(calls[1]["options"]["num_predict"],220)
        serialized=json.dumps(calls)
        self.assertNotIn("merchant_url",serialized)
        self.assertNotIn(URL,serialized)
        self.assertNotIn("indexed_price",serialized)

    def test_bad_both_qwen_replies_do_not_invent_questions(self):
        offer=offer_summaries(sample_record(),"E_BIKE")[0]
        def bad(*a,**k):
            return {"message":{"content":'{"questions":["incomplete?'}}
        with self.assertRaises(ValueError):
            propose_offer_model_questions(offer,"E_BIKE",request=bad)

    def test_pagination_rejects_extreme_values(self):
        offer=offer_summaries(sample_record(),"E_BIKE")[0]
        for offset,limit in ((-1,24),(229,24),(0,0),(0,25)):
            with self.assertRaises(ValueError):
                questions_for_offer(offer,"E_BIKE",offset,limit)


if __name__=="__main__":
    unittest.main()
