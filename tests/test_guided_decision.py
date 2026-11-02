"""Reconcile old OPF-only counters against real Shopping index observations."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from guided_decision import build_decision_projection
from similar_tier import category_of,read_specs,evaluate_alternative

FIXTURE=Path(__file__).resolve().parents[1]/"examples"/"live_lenovo_ideapad_index_evidence_2026-11-02.json"


class HistoricalResearchUIProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_existing_xkom_laptop_job_separates_catalog_and_index(self):
        self.assertEqual(self.original["report"]["root"]["children"][-1][
            "details"]["catalog_alternatives_found"],0)
        self.assertEqual(self.original["report"]["root"]["children"][-1][
            "details"]["current_competitor_offers_verified"],0)
        actual=build_decision_projection(self.original)
        evidence=actual["evidence"]
        self.assertEqual(actual["state"],"READY")
        self.assertEqual(actual["category"],"LAPTOP")
        self.assertEqual(evidence["catalog_only"],0)
        self.assertEqual(evidence["google_shopping_cards"],12)
        self.assertEqual(evidence["indexed_store_links"],3)
        self.assertEqual(evidence["indexed_listing_records"],15)
        self.assertEqual(evidence["unverified_similar_product_leads"],4)
        self.assertIsNone(evidence["selected_seller_price"])
        self.assertEqual(evidence["input_source_problem"],"SOURCE_TOO_LARGE")
        self.assertEqual(evidence["seller_confirmed_competitor_prices"],0)
        self.assertFalse(actual["payment_authorized"])
        self.assertEqual(len(actual["questions"]),4)
        self.assertIn("x86",str(actual["questions"][2]))
        self.assertTrue(all(c["index_only"] and not c["seller_price_verified"]
                            for c in actual["candidates"]))

    def test_false_124_and_169_index_prices_are_not_verification(self):
        report=build_decision_projection(self.original)
        c=next(x for x in report["candidates"] if x["price"]=="124.95")
        self.assertTrue(c["price_warnings"])
        self.assertFalse(c["quality_verified"])
        self.assertIsNone(report["evidence"]["selected_seller_price"])
        self.assertEqual(report["evidence"]["seller_confirmed_competitor_prices"],0)
        self.assertTrue(all(x["link"] is None or x["link"].startswith("https://")
                            for x in report["candidates"]))

    def test_historical_record_and_sha_are_never_mutated(self):
        before=json.dumps(self.original,sort_keys=True)
        result=build_decision_projection(self.original)
        self.assertEqual(json.dumps(self.original,sort_keys=True),before)
        self.assertEqual(result["saved_report_sha256"],
                         self.original["report"]["sha256"])
        self.assertEqual(result["measurement_provenance"],
                         "Read-only reinterpretation of saved research report")

    def test_laptop_specs_enforce_architecture_as_real_difference(self):
        title=self.original["item"]["title"]
        specs=read_specs(title,category_of(title))
        self.assertEqual(specs["ram_gb"],16)
        self.assertEqual(specs["capacity_gb"],512)
        self.assertEqual(specs["cpu_family"],"Snapdragon ARM")
        self.assertEqual(specs["display_technology"],"OLED")
        intel=evaluate_alternative(title,
            "Laptop Lenovo IdeaPad Slim 3 Intel Core Ultra 5 16GB 512GB OLED")
        self.assertIn("Intel x86",str(intel["different_features"]))
        self.assertTrue(intel["actual_quality_not_measured"])

    def test_progress_projection_is_never_a_ready_decision(self):
        for state in ("QUEUED","RUNNING","FAILED","INTERRUPTED"):
            with self.subTest(state=state):
                item=build_decision_projection({"state":state,"error_type":"timeout"})
                self.assertEqual(item["state"],state)
                self.assertFalse(item["payment_authorized"])
                self.assertNotIn("candidates",item)
        self.assertFalse(build_decision_projection({"state":"READY",
                       "item":{"title":"Unidentified item"},
                       "report":{}})["candidates"])

    def test_different_categories_do_not_create_fake_laptop(self):
        result=build_decision_projection({
           "state":"READY",
           "item":{"title":"Rower elektryczny 250W 15Ah"},
           "report":{"indexed_shopping":{"search_result_groups":[{
                "title":"Etui do laptop Lenovo 15","source":"Shop",
                "indexed_price":"4.99","indexed_currency":"PLN"}]}}})
        self.assertEqual(result["category"],"E_BIKE")
        self.assertEqual(result["evidence"]["google_shopping_cards"],1)
        self.assertEqual(result["candidates"],[])
        self.assertEqual(result["evidence"]["seller_confirmed_competitor_prices"],0)


if __name__=="__main__":
    unittest.main()
