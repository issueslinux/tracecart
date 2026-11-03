"""Detect declared-value conflicts without claiming lab proof or seller fraud."""
import hashlib
import json
import unittest

from source_discrepancies import (find_source_discrepancies,source_attribute)
from generic_source_research import execute_generic_sources
from guided_decision import build_decision_projection
from offer_knowledge_graph import build_offer_knowledge_graph

def evidence(field,value,url="https://manufacturer.example.org/products/sku",digest="a"*64):
    return {"source_property":field,"value":value,
            "source_sha256":digest,"source_url":url,
            "finding":field+": "+value+" (publisher declaration)",
            "source_kind":"BRAND_SITE_DECLARATIONS_NOT_INDEPENDENT_TESTS",
            "source_method":"VISIBLE_SPECIFICATION",
            "verified_for_exact_offer":False,
            "status":"DOCUMENT_DECLARATION_EXACT_SKU_UNVERIFIED"}

class SourceDiscrepancyTests(unittest.TestCase):
    def test_electric_bike_100km_title_vs_published_assisted_range_50_to_85(self):
        rows=[evidence("Max Pedal-Assist Range (km)","50–85")]
        offer={"title":"Rower elektryczny ALLGOBIKE AM27 250W 36V 15Ah 100km"}
        conflicts=find_source_discrepancies(offer,"E_BIKE",rows)
        self.assertEqual(len(conflicts),1)
        c=conflicts[0]
        self.assertEqual(c["type"],"TITLE_VS_PUBLISHED_SPECIFICATION")
        self.assertEqual(c["listing_value"],"100.0 km")
        self.assertEqual(c["source_value"],"50–85")
        self.assertTrue(c["not_fraud_or_exact_sku_proof"])
        self.assertEqual(c["status"],
                         "POTENTIAL_DIFFERENT_VARIANT_OR_TEST_CONDITIONS")

    def test_range_modes_are_not_wrongly_compared(self):
        for label in ("Pure Electric Range (km) [65kg rider]",
                      "Throttle-only range","Battery Range",
                      "Power assistance time"):
            with self.subTest(label=label):
                claims=find_source_discrepancies(
                    {"title":"ALLGOBIKE AM27 rower elektryczny 100km"},
                    "E_BIKE",[evidence(label,"40–50")])
                self.assertEqual(claims,[])

    def test_multi_category_normalizes_comparable_units_and_rounding(self):
        examples=[
            ("LAPTOP","Lenovo Thinkpad X13 16GB RAM",
             "RAM memory","32 GB",True),
            ("SSD","Kingston KC3000 1TB",
             "Storage capacity","1024 GB",False),
            ("SSD","Kingston KC3000 1TB",
             "Storage capacity","2 TB",True),
            ("E_BIKE","ALLGOBIKE AM27 rower elektryczny 250W",
             "Motor rated power","350W",True),
            ("COMPRESSOR","Kompresor 8bar 50L",
             "Pressure","8 bar",False),
        ]
        for cat,title,key,val,want in examples:
            with self.subTest(category=cat,key=key,val=val):
                mismatches=find_source_discrepancies(
                    {"title":title},cat,[evidence(key,val)])
                self.assertEqual(bool(mismatches),want)

    def test_two_independent_hosts_different_declarations_not_independent_tests(self):
        rows=[
            evidence("RAM memory","16 GB","https://brand.example.org/model",digest="a"*64),
            evidence("RAM memory","32 GB","https://review.example.net/model",digest="b"*64),
        ]
        result=find_source_discrepancies(
            {"title":"Lenovo Thinkpad X13 laptop"},"LAPTOP",rows)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["type"],"PUBLISHED_SOURCES_DISAGREE")
        self.assertEqual(result[0]["source_a_value"],"16 GB")
        self.assertEqual(result[0]["source_b_value"],"32 GB")
        self.assertTrue(result[0]["not_fraud_or_exact_sku_proof"])
        same_host=rows.copy()
        same_host[1]={**same_host[1],"source_url":"https://brand.example.org/other"}
        self.assertEqual(find_source_discrepancies(
            {"title":"Lenovo Thinkpad X13 laptop"},"LAPTOP",same_host),[])

    def test_real_source_discrepancy_graph_has_traceable_provenance(self):
        title="Rower elektryczny ALLGOBIKE AM27 250W 36V 15Ah 100km"
        url="https://manufacturer.example.org/products/am27"
        rows=[evidence("Max Pedal-Assist Range (km)","50–85",url)]
        mismatch=find_source_discrepancies({"title":title},"E_BIKE",rows)
        report={"state":"READY",
          "item":{"title":title,"merchant_url":"https://seller.example.net/offer"},
          "report":{"indexed_shopping":{"indexed_offers":[],
                                        "search_result_groups":[]}},
          "evidence_offers":{"offer-0":{
              "status":"GENERAL_DOCUMENT_DECLARATIONS_FETCHED_SKU_UNVERIFIED",
              "reference_answers":rows,"declared_claim_conflicts":mismatch,
              "verified_for_exact_offer":0}}}
        graph=build_offer_knowledge_graph(build_decision_projection(report))
        self.assertEqual(graph["stats"]["unresolved_source_discrepancies"],1)
        self.assertEqual(graph["stats"]["independent_reference_measurements"],0)
        self.assertEqual(graph["stats"]["documented_product_declarations"],1)
        self.assertEqual(graph["stats"]["verified_exact_sku_answers"],0)
        self.assertEqual(len([x for x in graph["nodes"]
                              if x["type"]=="source_disagreement"]),1)
        linked=[x for x in graph["edges"]
                if x["relation"]=="DISCREPANCY_REQUIRES_SOURCE_REVIEW"]
        self.assertEqual(len(linked),1)
        self.assertTrue(linked[0]["to"].startswith("source:"))
        self.assertEqual(graph["offer_details"]["offer-0"]
                             ["declared_claim_conflicts"],mismatch)
        self.assertNotIn("EXACT_SKU_INDEPENDENTLY_VERIFIED",
                         json.dumps(graph))

if __name__=="__main__":
    unittest.main()
