"""Cross-category specs and readable graph tests; factual input only."""
import json
import unittest

from title_facts import title_facts,unit_price
from generic_value import generic_unit_value
from offer_knowledge_graph import build_offer_knowledge_graph
from guided_decision import build_decision_projection

BASE="proszek do prania bryza 4w1 color 8 45 kg do kolorowych tkanin"


def _record():
    items=[
        ("Proszek do prania Bryza 4w1 Color 8.45 kg","59.99"),
        ("Proszek Bryza 4w1 COLOR 8.45kg 130 prań","69.99"),
        ("BRYZA 4w1 Color 2 x 8.45 kg","109.99"),
        ("Bryza 4w1 Proszek White 8.45kg 130 prań","89.99"),
        ("BRYZA 4w1 Color 3 x 8.45 kg","201.57"),
    ]
    report={"indexed_shopping":{"indexed_offers":[],
             "search_result_groups":[{"title":title,"indexed_price":price,
                 "indexed_currency":"PLN","source":"Test index"}
                 for title,price in items]}}
    return {"state":"READY",
            "item":{"title":BASE,"price":None,"currency":None,
                    "merchant_url":"https://example.org/product/bryza"},
            "report":report}


class UniversalTitleValueTests(unittest.TestCase):
    def test_quantity_845kg_and_two_pack_normalization(self):
        a=title_facts("BRYZA Color 8,45 kg 130 prań")
        b=title_facts("BRYZA Color 2 x 8.45kg 260 prań")
        self.assertEqual(next(x["value"] for x in a
                              if x["key"]=="quantity_kg"),"8.45")
        self.assertEqual(next(x["value"] for x in b
                              if x["key"]=="quantity_kg"),"16.9")
        self.assertEqual(next(x["value"] for x in b
                              if x["key"]=="wash_count"),"260")
        self.assertEqual(unit_price("59.99","PLN",a)["amount"],"7.10")
        self.assertEqual(unit_price("109.99","PLN",b)["amount"],"6.51")

    def test_ambiguous_url_slug_cannot_be_interpreted_as_45kg(self):
        facts=title_facts(BASE)
        self.assertFalse(any(x["key"]=="quantity_kg" for x in facts))
        self.assertEqual(next(x["value"] for x in facts
                              if x["key"]=="variant"),"COLOR")

    def test_non_laptop_universal_units(self):
        cases=[
            ("Lotion 3x500ml","quantity_L","1.5"),
            ("Paint 2 x 5 L","quantity_L","10"),
            ("Soap 400 g","quantity_kg","0.4"),
            ("Tablets 24 pieces","count","24"),
        ]
        for title,key,value in cases:
            with self.subTest(title=title):
                facts=title_facts(title)
                self.assertEqual(next(x["value"] for x in facts
                                      if x["key"]==key),value)
        self.assertNotIn("quantity_kg",
                         {x["key"] for x in title_facts("Acer laptop i7 16GB RAM 1TB SSD")})
        appliance=title_facts("Water pump 1200W 230V 8bar")
        self.assertEqual({x["key"]:x["value"] for x in appliance},
                         {"power_w":"1200","voltage_v":"230","pressure_bar":"8"})

    def test_color_and_white_different_product_variants(self):
        source=title_facts("BRYZA 4w1 Color 8.45 kg")
        different=title_facts("Bryza 4w1 Proszek White 8.45kg 130 prań")
        self.assertEqual(next(x["value"] for x in source
                              if x["key"]=="variant"),"COLOR")
        self.assertEqual(next(x["value"] for x in different
                              if x["key"]=="variant"),"WHITE")

    def test_generic_value_ranks_unit_cost_not_pack_total(self):
        p=build_decision_projection(_record())
        result=generic_unit_value(p)
        self.assertEqual(result["status"],"UNIT_PRICE_LEADS_NOT_CHECKOUT")
        self.assertEqual(result["options"][0]["price"],"109.99")
        self.assertEqual(result["options"][0]["unit_comparison_label"],"6.51 PLN/kg")
        self.assertTrue(any(x["price"]=="59.99" for x in result["options"]))
        self.assertNotIn("89.99",{x["price"] for x in result["options"]})
        self.assertEqual(result["different_variant_listings"][0]["price"],"89.99")
        self.assertFalse(result["options"][0]["checkout_verified"])
        self.assertIn("larger bundle may cost more",result["headline"].lower())

    def test_graph_includes_real_title_facts_and_related_listing_connections(self):
        p=build_decision_projection(_record())
        graph=build_offer_knowledge_graph(p)
        self.assertEqual(graph["category"],"UNKNOWN")
        self.assertEqual(graph["stats"]["offers"],6)
        claims=graph["offer_details"]["offer-3"]["title_facts"]
        self.assertEqual(next(f["value"] for f in claims
                              if f["key"]=="quantity_kg"),"16.9")
        self.assertEqual(graph["offer_details"]["offer-3"]["unit_price"]["amount"],"6.51")
        edges=[e for e in graph["edges"]
               if e["relation"]=="ALTERNATIVE_INDEX_LEAD"]
        self.assertEqual(len(edges),5)
        self.assertTrue(all(e["status"]=="SEARCH_RESULT_NOT_VERIFIED_EQUIVALENT"
                            for e in edges))
        fact_ids={n["id"] for n in graph["nodes"] if n["type"]=="title_claim"}
        self.assertTrue(fact_ids)
        self.assertGreater(graph["stats"]["title_claim_links"],0)
        self.assertFalse(graph["provenance"]["shared_parameter_value_proves_identical_model"])
        self.assertEqual(graph["stats"]["verified_checkout_prices"],0)


if __name__=="__main__":
    unittest.main()
