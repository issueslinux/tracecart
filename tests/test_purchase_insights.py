"""Compare alternative products by technical tier, not exact model identity."""
import json
import unittest

from purchase_insights import build_purchase_insights
from similar_tier import category_of,read_specs,STATUS_SIMILAR
from model_verdict import insufficient_verdict,generate_final_verdict

BASE="laptop dell dc15250 15 6 i7 1355u 16gb ram 1tb ssd windows 11 home"


def row(i,title,price,url=None):
    return {"id":"offer-"+str(i),"title":title,
            "indexed_price":price,"currency":"PLN","url":url}


def example():
    return {"title":BASE,
      "offers":[
        row(0,BASE,None,"https://www.mediaexpert.pl/product/example"),
        row(1,'Laptop Dell DC 15 15.6" Intel Core i7-1355U 16GB RAM','139.95'),
        row(2,'Laptop Acer 15.6 Intel Core i7-1355U 16GB RAM 1TB SSD Notebook',
            '3499.99',"https://example.org/acer"),
        row(3,'Laptop Dell 15 Core i7-1355U 16GB 1TB SSD 15.6" FHD Dotyk',
            '3399.96'),
        row(4,'Laptop Dell i7-1355U 16GB RAM 512GB SSD Win11',
            '3100.00'),
        row(5,'Laptop Dell i5-1334U 8GB RAM 512GB SSD Win11',
            '2898.95'),
        row(6,'Laptop Lenovo IdeaPad Intel Core i7-1355U 16GB RAM 1TB SSD',
            '3699.99'),
      ],
      "selected_source_intake":{"access_problem":"HTTP_403"}}


def graph():
    return {"stats":{"documented_product_declarations":5,
                     "seller_page_declarations":0,
                     "independent_reference_measurements":0,
                     "unverified_index_quotes":6},
      "nodes":[
        {"id":"offer-0","type":"offer","label":BASE},
        {"id":"doc-1","type":"fetched_source","label":"Retailer page"},
        {"id":"answer:offer-3:0","type":"source_declaration",
         "source_property":"sku","value":"185643","label":"185643"},
        {"id":"answer:offer-3:1","type":"source_declaration",
         "source_property":"Model procesora","value":"i7-1355U","label":"i7-1355U"},
        {"id":"answer:offer-3:2","type":"source_declaration",
         "source_property":"Zainstalowana pojemność pamięci RAM",
         "value":"16 GB","label":"16 GB"},
        {"id":"answer:offer-3:3","type":"source_declaration",
         "source_property":"Pojemność dysku podstawowego",
         "value":"1000 GB","label":"1000 GB"},
        {"id":"answer:offer-3:4","type":"source_declaration",
         "source_property":"Pojemność baterii","value":"54 Wh","label":"54 Wh"},
      ]}


class PurchaseInsightsTests(unittest.TestCase):
    def test_laptop_not_misclassified_as_component_ssd(self):
        self.assertEqual(category_of(BASE),"LAPTOP")
        self.assertEqual(category_of("Samsung SSD 980 Pro NVMe 1TB"),"SSD")
        specs=read_specs(BASE)
        self.assertEqual(specs["ram_gb"],16)
        self.assertEqual(specs["capacity_gb"],1000)
        self.assertEqual(specs["cpu_tier"],"Core i7")
        self.assertEqual(specs["screen_in"],15.6)

    def test_peer_different_brand_is_valid_alternative(self):
        out=build_purchase_insights(example())
        options=out["options"]
        self.assertEqual(out["status"],"COMPARABLE_INDEX_OFFERS_FOUND")
        self.assertTrue(any("Acer" in x["title"] for x in options))
        self.assertTrue(any("Lenovo" in x["title"] for x in options))
        self.assertEqual(options[0]["offer_id"],"offer-3")
        self.assertEqual(options[0]["price"],"3399.96")
        self.assertEqual(options[0]["tier"],"SIMILAR_TITLE_SPEC_TIER")
        self.assertFalse(options[0]["identity_verified"])
        self.assertFalse(options[0]["checkout_verified"])
        self.assertIn("Touchscreen",options[0]["highlights"][0])
        self.assertEqual(options[0]["price_node_id"],"price:offer-3")
        self.assertIsNone(options[0]["source_url"])
        self.assertFalse(out["selected_price_available_in_seller_page"])
        self.assertIn("no confirmed saving can be calculated",out["headline"])

    def test_139_95_not_declared_the_cheapest_new_laptop(self):
        out=build_purchase_insights(example())
        self.assertEqual(len(out["suspicious_price_quotes"]),1)
        self.assertEqual(out["suspicious_price_quotes"][0]["offer_id"],"offer-1")
        self.assertNotIn("139.95",str(out["options"]))
        self.assertGreater(float(out["market_reference"].split()[0]),3000)

    def test_512gb_and_i5_are_not_equivalent_to_i7_1tb(self):
        out=build_purchase_insights(example())
        strong={x["offer_id"] for x in out["options"]}
        self.assertNotIn("offer-4",strong)
        self.assertNotIn("offer-5",strong)
        lower=next(x for x in out["tradeoffs"] if x["offer_id"]=="offer-4")
        self.assertTrue(any("512GB" in t for t in lower["different_features"]))

    def test_fact_cards_are_relevant_specs_not_bare_sku_and_fallback_has_alternatives(self):
        result=insufficient_verdict(graph(),projection=example())
        self.assertEqual(result["status"],"UNAVAILABLE")
        self.assertEqual(result["purchase_insights"]["status"],
                         "COMPARABLE_INDEX_OFFERS_FOUND")
        self.assertTrue(result["observations"])
        self.assertTrue(result["observations"][0]["text"].casefold().startswith("processor"))
        self.assertFalse(any(x["text"]=="185643" for x in result["observations"]))
        self.assertIn("3399.96",result["summary"])
        self.assertFalse(result["payment_authorized"])

    def test_qwen_classification_does_not_invent_sources_or_prices(self):
        def stub(*args,**kwargs):
            request=json.loads(args[2].decode())
            self.assertIn("offer_rows_id_title_price_status",
                          request["messages"][1]["content"])
            return {"message":{"content":json.dumps({"verdict":"COMPARE_WITH_CAUTION"})}}
        result=generate_final_verdict(example(),graph(),request=stub)
        self.assertEqual(result["verdict"],"COMPARE_WITH_CAUTION")
        self.assertEqual(result["purchase_insights"]["options"][0]["price"],"3399.96")
        self.assertTrue(result["observations"][0]["evidence_ids"][0].startswith("answer:"))
        self.assertEqual(result["origin"],"LOCAL_LLM_EVIDENCE_CLASSIFICATION")
        self.assertFalse(result["payment_authorized"])


if __name__=="__main__":
    unittest.main()
