"""Offer graph must preserve provenance; no equal-number identity or fake answers."""
import json
from pathlib import Path
import unittest

from guided_decision import build_decision_projection
from offer_knowledge_graph import build_offer_knowledge_graph
from offer_question_bank import offer_summaries

ROOT=Path(__file__).resolve().parents[1]
LENOVO=json.loads((ROOT/"examples"/"live_lenovo_ideapad_index_evidence_2026-11-02.json").read_text())
BIKE="rower elektryczny meski damski 250w 15ah 100km 27 5 ebike shimano 7s 25kmh"


def bike_record():
    item={"title":BIKE,"merchant_url":"https://allegro.pl/produkt/rower-example",
          "currency":None,"price":None}
    report={"indexed_shopping":{"indexed_offers":[],"search_result_groups":[
        {"title":"Rower elektryczny Męski Damski Allgobike AM27 250W 36V 15AH 100KM 27.5",
         "indexed_price":"2599.00","indexed_currency":"PLN","source":"shopping"},
        {"title":"Rower elektryczny Orzel C27 250W 15Ah 100km 25kmh",
         "indexed_price":"3399.00","indexed_currency":"PLN","source":"shopping"},
        {"title":"Rower elektryczny ek15 36V 12Ah 500W",
         "indexed_price":"3028.99","indexed_currency":"PLN","source":"shopping"},
    ]}}
    return {"state":"READY","item":item,"report":report}


class GraphTests(unittest.TestCase):
    def test_graph_contains_all_offers_no_unverified_sku_identity(self):
        g=build_offer_knowledge_graph(build_decision_projection(bike_record()))
        self.assertEqual(g["schema_version"],"tracecart.offer-knowledge-graph.v1")
        stats=g["stats"]
        self.assertEqual(stats["offers"],4)
        self.assertEqual(stats["high_priority_unanswered_check_links"],4*24)
        self.assertEqual(stats["total_planned_questions"],4*228)
        self.assertEqual(stats["verified_exact_sku_answers"],0)
        self.assertEqual(stats["verified_checkout_prices"],0)
        self.assertEqual(stats["unverified_index_quotes"],3)
        self.assertEqual(g["decision_status"],
                         "ABSTAIN_PENDING_EXACT_OFFER_AND_PRICE_VERIFICATION")
        self.assertFalse(g["provenance"]["shared_parameter_value_proves_identical_model"])
        self.assertTrue(all(n["claim_status"]=="UNVERIFIED_TITLE_LABEL"
                            for n in g["nodes"] if n["type"]=="title_claim"))
        self.assertFalse(any(e["relation"]=="SAME_PRODUCT" for e in g["edges"]))
        self.assertTrue(any(e["relation"]=="SIMILAR_INDEX_MODEL_NAME_LEAD" and
                            e["status"]=="NOT_VERIFIED_SAME_PRODUCT"
                            for e in g["edges"]))
        self.assertTrue(all(e["status"]=="PLANNED_NOT_INVESTIGATED" for e in
                            g["edges"] if e["relation"]=="EVIDENCE_NEEDED"))

    def test_shared_spec_node_does_not_erase_individual_offer_provenance(self):
        g=build_offer_knowledge_graph(build_decision_projection(bike_record()))
        claimed=[e for e in g["edges"] if e["relation"]=="TITLE_MENTIONS"]
        wheel=[n for n in g["nodes"] if n["type"]=="title_claim" and
               n["parameter"]=="power_w" and n["value"]==250]
        self.assertEqual(len(wheel),1)
        linked={x["from"] for x in claimed if x["to"]==wheel[0]["id"]}
        self.assertEqual(linked,{"offer-0","offer-1","offer-2"})
        self.assertTrue(all(e["status"]=="UNVERIFIED_TITLE_LABEL"
                            for e in claimed))
        self.assertTrue(all(x["claim_provenance"] in (
            "URL_TITLE_UNVERIFIED","SEARCH_INDEX_TITLE_UNVERIFIED")
                            for x in g["offer_details"].values()))

    def test_derived_battery_wh_is_offer_scoped_not_a_verified_label(self):
        g=build_offer_knowledge_graph(build_decision_projection(bike_record()))
        computed=[n for n in g["nodes"] if n["type"]=="derived_claim"]
        self.assertEqual(len(computed),2)
        wh=next(n for n in computed if n["id"].startswith("derived:offer-1:"))
        self.assertEqual(wh["parameter"],"battery_wh")
        self.assertEqual(wh["value"],540)
        self.assertIn("ARITHMETIC_FROM_UNVERIFIED",wh["claim_status"])
        self.assertTrue(wh["id"].startswith("derived:offer-1:"))
        formula=[e for e in g["edges"] if
                 e["relation"]=="ARITHMETIC_INPUT" and e["to"]==wh["id"]]
        self.assertEqual(len(formula),2)
        self.assertTrue(all(e["status"]==
            "V_MULTIPLIED_BY_AH_UNVERIFIED_OPERANDS" for e in formula))
        self.assertEqual(g["stats"]["derived_arithmetic_claims"],2)
        self.assertNotEqual(computed[0]["id"],computed[1]["id"])
        # Independent proof cannot arise from multiplication of title claims.
        self.assertEqual(g["stats"]["verified_exact_sku_answers"],0)

    def test_source_observations_distinct_from_exact_sku_answers(self):
        from evidence_execution import execute_reference_checks
        from tests.test_evidence_execution import ROBOTS, SAMPLE_HTML, SOURCE
        base={"state":"READY","item":LENOVO["item"],
              "report":LENOVO["report"]}
        projection=build_decision_projection(base)
        reviews={}
        from offer_question_bank import offer_summaries
        for offer in projection["offers"]:
            if "15Q8X10" not in offer["title"]:
                continue
            reviews[offer["id"]]=execute_reference_checks(offer,"LAPTOP",
                fetch=lambda url,*a,**k:
                    ROBOTS if url.endswith("/robots.txt") else SAMPLE_HTML)
        projection["evidence_offers"]=reviews
        g=build_offer_knowledge_graph(projection)
        self.assertEqual(g["stats"]["verified_exact_sku_answers"],0)
        self.assertTrue(g["stats"]["independent_reference_measurements"]>=2)
        self.assertGreaterEqual(g["stats"]["reference_offer_links"],2)
        sources=[n for n in g["nodes"] if n["type"]=="fetched_source"]
        self.assertEqual(len(sources),1)
        self.assertEqual(sources[0]["url"],SOURCE["url"])
        self.assertEqual(len(sources[0]["sha256"]),64)
        self.assertTrue(all(n["status"]=="REFERENCE_ONLY_NOT_THIS_OFFER"
                            for n in g["nodes"] if
                            n["type"]=="reference_observation"))
        self.assertTrue(all(e["relation"]!="PROVES_EXACT_SKU_IDENTITY"
                            for e in g["edges"]))

    def test_unsupported_identity_assertion_does_not_become_verified(self):
        p=build_decision_projection(bike_record())
        p["evidence_offers"]={
            "offer-0":{"status":"INDEPENDENT_REFERENCE_FETCHED_VARIANT_UNVERIFIED",
                "reference_answers":[{
                    "question_id":"offer-0-3","dimension":"manufacturer frame and variant identity",
                    "source_sha256":"a"*64,
                    "source_url":"https://example.com/review",
                    "publisher":"Independent lab",
                    "source_kind":"INDEPENDENT_TEST","value":"TEST",
                    "status":"REFERENCE_EVIDENCE_ONLY_EXACT_SKU_UNVERIFIED",
                    "verified_for_exact_offer":True
                }]}}
        g=build_offer_knowledge_graph(p)
        self.assertEqual(g["stats"]["verified_exact_sku_answers"],0)
        self.assertEqual(g["stats"]["independent_reference_measurements"],1)

    def test_graph_replay_is_deterministic_and_preserves_projection(self):
        p=build_decision_projection(bike_record())
        before=json.dumps(p,sort_keys=True,ensure_ascii=False)
        a=build_offer_knowledge_graph(p)
        b=build_offer_knowledge_graph(p)
        self.assertEqual(a,b)
        self.assertEqual(json.dumps(p,sort_keys=True,ensure_ascii=False),before)
        self.assertEqual(len(set(n["id"] for n in a["nodes"])),
                         len(a["nodes"]))
        self.assertEqual(len(set(e["id"] for e in a["edges"])),
                         len(a["edges"]))
        all_ids={n["id"] for n in a["nodes"]}
        self.assertTrue(all(e["from"] in all_ids and e["to"] in all_ids
                            for e in a["edges"]))


if __name__=="__main__":
    unittest.main()
