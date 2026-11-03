"""Evidence-rich graph, real source facts and scoped unanswered checks."""
from copy import deepcopy
import unittest

from guided_decision import build_decision_projection
from offer_knowledge_graph import build_offer_knowledge_graph


SOURCE="https://maker.example.org/compressors/real-model/"
DIGEST="f"*64


def manufacturer_row(key,value,family="model"):
    return {
        "source_property":key,"value":value,
        "finding":key+": "+value+" (publisher specification)",
        "property_family":family,
        "source_kind":"BRAND_SITE_DECLARATIONS_NOT_INDEPENDENT_TESTS",
        "source_url":SOURCE,"source_sha256":DIGEST,
        "retrieved_at":"2026-11-03T12:00:00Z",
        "status":"DOCUMENT_DECLARATION_EXACT_SKU_UNVERIFIED",
        "variant_match":"SAME_MODEL_TOKEN_NOT_EXACT_SKU_OR_HARDWARE",
        "source_method":"JSON_LD_OR_VISIBLE_SPECIFICATION",
        "verified_for_exact_offer":False,
    }


def saved_job():
    return {
        "state":"READY",
        "item":{"title":"Kompresor bezprzewodowy 18V ONE+",
                "merchant_url":SOURCE,"price":"249.99",
                "currency":"PLN","barcode":"4892210230478"},
        "report":{"sha256":"saved-immutable-report-sha",
                  "source_intake":{
                    "source_url":SOURCE,"page_sha256":DIGEST,
                    "retrieved_at":"2026-11-03T12:00:00Z",
                    "brand":"Example Tools","sku":"COMP18-0",
                    "barcode_status":"FOUND_CHECKSUM_VALID",
                    "price_status":"SELLER_DECLARED",
                    "availability_claim":"https://schema.org/InStock",
                    "structured_shipping_claim":{
                        "status":"SELLER_DECLARED_DESTINATION_CONDITIONAL",
                        "shipping_cost":"0.00","currency":"PLN",
                        "destination_country":"PL"},
                  },
                  "indexed_shopping":{"indexed_offers":[],
                                      "search_result_groups":[]}},
        "evidence_progress":{"status":"COMPLETE","processed":1,"planned":1},
        "evidence_offers":{"offer-0":{
            "status":"GENERAL_DOCUMENT_DECLARATIONS_FETCHED_SKU_UNVERIFIED",
            "reference_answers":[
                manufacturer_row("sku","COMP18-0"),
                manufacturer_row("model","COMP18-0"),
                manufacturer_row("EAN","4892210230478","barcode"),
                manufacturer_row("Power","18V","voltage"),
                manufacturer_row("Weight","0.6 kg","weight"),
                manufacturer_row("Charger included","No","accessories"),
                manufacturer_row("Noise","84 dB","noise"),
            ],
        }},
    }


class EvidenceRichGraphTests(unittest.TestCase):
    def test_seller_snapshot_and_document_sources_are_visible_graph_facts(self):
        job=saved_job()
        before=deepcopy(job)
        proj=build_decision_projection(job)
        self.assertEqual(proj["selected_source_intake"]["sku"],"COMP18-0")
        graph=build_offer_knowledge_graph(proj)
        self.assertEqual(graph["stats"]["seller_page_declarations"],6)
        self.assertEqual(graph["stats"]["documented_product_declarations"],7)
        self.assertGreaterEqual(graph["stats"]["evidence_facets"],5)
        self.assertGreaterEqual(graph["stats"]["focused_verification_gaps"],3)
        self.assertEqual(graph["stats"]["verified_exact_sku_answers"],0)
        self.assertEqual(graph["stats"]["verified_checkout_prices"],0)
        self.assertEqual(job,before)
        seen={(x["parameter"],x["value"]) for x in graph["nodes"]
              if x["type"]=="seller_declaration"}
        self.assertIn(("sku","COMP18-0"),seen)
        self.assertIn(("listed_price","249.99 PLN"),seen)
        self.assertIn(("availability","InStock"),seen)
        document=[x for x in graph["nodes"] if x["type"]=="source_declaration"]
        self.assertTrue(any(x["source_property"]=="Charger included" and
                            x["value"]=="No" for x in document))
        self.assertTrue(all(x["status"]==
           "DOCUMENT_DECLARATION_EXACT_SKU_UNVERIFIED" for x in document))
        relations={x["relation"] for x in graph["edges"]}
        self.assertTrue({"HAS_DOCUMENTED_FACET","FACET_HAS_SOURCE_FACT",
                         "SELLER_PAGE_DECLARES","OBSERVED_IN_SOURCE",
                         "HAS_UNRESOLVED_VERIFICATION_GAP"}<=relations)
        self.assertTrue(any(x["type"]=="fetched_source" and
           x["sha256"]==DIGEST for x in graph["nodes"]))

    def test_research_questions_are_specific_and_do_not_repeat_documented_facts(self):
        graph=build_offer_knowledge_graph(
            build_decision_projection(saved_job()))
        detail=graph["offer_details"]["offer-0"]
        questions=detail["high_impact_questions"]
        text=" ".join(q["question"] for q in questions).casefold()
        self.assertLessEqual(len(questions),9)
        self.assertGreaterEqual(len(questions),3)
        self.assertNotIn("does the oem publish an exact-model specification",text)
        self.assertNotIn("what exact manufacturer model/sku is offered",text)
        self.assertNotIn("which accessories, batteries or chargers actually ship",text)
        self.assertIn("independent",text)
        self.assertIn("checkout",text)
        self.assertTrue(all(q["status"]=="OPEN_REQUIRES_NEW_EVIDENCE"
                            and q["reason"] for q in questions))
        self.assertEqual(detail["planned_question_count"],len(questions))
        self.assertEqual(detail["source_coverage"]["documented_field_count"],7)

    def test_unknown_product_still_has_actual_verification_gaps_not_facts(self):
        raw=saved_job()
        raw["item"]={"title":"Unmarked unknown device",
                     "merchant_url":"https://seller.example.org/listing"}
        raw["report"]["source_intake"]={
            "intake_status":"URL_ONLY_UNVERIFIED"}
        raw["evidence_offers"]={}
        graph=build_offer_knowledge_graph(
            build_decision_projection(raw))
        self.assertEqual(graph["stats"]["seller_page_declarations"],0)
        self.assertEqual(graph["stats"]["documented_product_declarations"],0)
        self.assertEqual(graph["stats"]["verified_exact_sku_answers"],0)
        questions=graph["offer_details"]["offer-0"]["high_impact_questions"]
        self.assertTrue(any(q["dimension"]=="identity" for q in questions))
        self.assertFalse(any(x["type"]=="source_declaration" for x in graph["nodes"]))

if __name__=="__main__":
    unittest.main()
