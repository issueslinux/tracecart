"""Offline regression checks for 20 real Tavily keyless Allegro offer searches."""
import json
from pathlib import Path
import unittest

from benchmarks.analyze_tavily_20_offers import (
    CORPUS, RECEIPTS, compact, same_product_in_title,
    explicit_condition, evaluate, evaluate_case,
)


class Tavily20CasesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed=json.loads(CORPUS.read_text(encoding="utf8"))
        cls.receipts=[json.loads(x) for x in
                      RECEIPTS.read_text(encoding="utf8").splitlines() if x]
        cls.report=evaluate(cls.seed,cls.receipts)

    def test_independently_seeded_20_unique_offer_urls(self):
        cases=self.seed["cases"]
        self.assertEqual(len(cases),20)
        self.assertEqual(len({r["offer_id"] for r in cases}),20)
        self.assertEqual(len({r["category"] for r in cases}),15)
        for row in cases:
            self.assertTrue(row["url"].startswith("https://allegro.pl/oferta/"))
            self.assertTrue(row["url"].endswith(row["offer_id"]))
            self.assertEqual(row["reference_method"],
                             "public_web_search_index_not_live_seller")

    def test_20_live_keyless_search_receipts_not_20_true_matches(self):
        self.assertEqual(len(self.receipts),20)
        self.assertEqual(len({r["case_id"] for r in self.receipts}),20)
        for row in self.receipts:
            self.assertEqual(row["status"],"OK")
            self.assertEqual(row["http_status"],200)
            self.assertEqual(len(row["results"]),8)
            self.assertEqual(row["search_mode"],"TAVILY_KEYLESS_BASIC_DOMAIN_FILTER")
            self.assertNotIn("Authorization",json.dumps(row))
            self.assertNotIn("TAVILY_API_KEY",json.dumps(row))

    def test_actual_identity_and_price_yields_are_independently_counted(self):
        s=self.report["summary"]
        self.assertEqual(s["api_http_200"],20)
        self.assertEqual(s["cases_with_any_official_brand_model_match"],7)
        self.assertEqual(s["exact_offer_id_in_official_result_url"],5)
        self.assertEqual(s["exact_id_url_with_index_price_claim"],3)
        self.assertEqual(s["exact_offer_id_in_official_snippet_without_url"],1)
        self.assertEqual(s["seller_price_verified_count"],0)
        self.assertEqual(s["index_crawl_timestamp_verified_count"],0)

    def test_ryobi_product_group_not_misassigned_to_specific_offer(self):
        row=next(x for x in self.report["cases"] if x["case_id"]=="RYOBI-001")
        self.assertEqual(row["assessment"],
                         "EXACT_ID_ONLY_IN_SNIPPET_NO_PRICE_LINKAGE")
        self.assertTrue(row["explicit_offer_id_in_official_snippet"])
        self.assertFalse(row["exact_offer_id_in_official_url"])
        self.assertIsNone(row["exact_url_price_claim"])

    def test_specific_exact_url_prices_come_from_retrieved_index(self):
        rows={x["case_id"]:x for x in self.report["cases"]}
        self.assertEqual(rows["BOSCH-005"]["exact_url_price_claim"],"969.00")
        self.assertEqual(rows["PHILIPS-006"]["exact_url_price_claim"],"754.48")
        self.assertEqual(rows["APPLE-009"]["exact_url_price_claim"],"649.90")
        self.assertTrue(rows["APPLE-009"]["exact_url_price_matches_other_index"])
        self.assertFalse(rows["BOSCH-005"]["exact_url_price_matches_other_index"])
        self.assertTrue(rows["PHILIPS-006"]["exact_url_price_matches_other_index"])
        self.assertTrue(rows["PHILIPS-006"]["separate_index_inactive_notice"])
        self.assertEqual(rows["BOSCH-005"]["case_reference_index_price"],"599.00")
        self.assertEqual(rows["APPLE-009"]["exact_url_condition_claim"],"OPEN_BOX")
        for case_id in ("BOSCH-005","PHILIPS-006","APPLE-009"):
            self.assertFalse(rows[case_id]["verified_live_seller_price"])
            self.assertFalse(rows[case_id]["verified_live_stock"])

    def test_unrelated_source_id_is_not_an_allegro_offer(self):
        case=self.seed["cases"][0]
        mirror={"url":"https://spolshy.com.ua/product/18457369262",
                "title":"Ryobi RPI18-0",
                "content":"Ryobi RPI18-0 za 1.00PLN"}
        news={"url":"https://allegro.pl/artykul/ryobi-rpi18-0",
              "title":"Ryobi RPI18-0 review",
              "content":"za 1.00PLN"}
        fake={"url":"https://allegro.pl/oferta/samsung-galaxy-18457369262",
              "title":"Samsung Galaxy S24",
              "content":"za 1.00PLN"}
        receipt={"status":"OK","http_status":200,
                 "results":[mirror,news,fake]}
        row=evaluate_case(case,receipt)
        self.assertFalse(row["exact_offer_id_in_official_url"])
        self.assertEqual(row["external_urls_containing_offer_id"],1)
        self.assertIsNone(row["exact_url_price_claim"])

    def test_unknown_condition_is_not_assumed_new(self):
        self.assertEqual(explicit_condition({"title":"My item", "content":"za 249.00PLN"}),
                         "UNKNOWN")
        self.assertEqual(explicit_condition({"title":"My item Stan: Używany"}),
                         "USED")
        self.assertEqual(explicit_condition({"title":"My item Powystawowy"}),
                         "OPEN_BOX")
        self.assertEqual(explicit_condition({"title":"My item Stan: Nowy"}),
                         "NEW")

    def test_brand_and_whole_model_validation(self):
        case={"brand":"Ryobi","model":"RPI18-0"}
        self.assertFalse(same_product_in_title(case,"Ryobi R18PI-0"))
        self.assertFalse(same_product_in_title(case,"Makita RPI18-0"))
        self.assertTrue(same_product_in_title(case,"Ryobi RPI18-0 kompresor"))
        self.assertTrue(same_product_in_title(
            {"brand":"Philips","model":"NA555/00"},
            "Philips Airfryer NA555/00 dwa kosze"))
        self.assertEqual(compact("De'Longhi ECAM290.51.B"),"delonghiecam29051b")

    def test_duplicate_receipt_or_changed_benchmark_case_count_fails(self):
        with self.assertRaises(ValueError):
            evaluate(self.seed,self.receipts+[self.receipts[0]])
        reduced={"cases":self.seed["cases"][:19]}
        with self.assertRaises(ValueError):
            evaluate(reduced,self.receipts)


if __name__=="__main__":
    unittest.main()
