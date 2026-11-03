"""Offline adaptive Tavily model-discovery coverage and throttle assertions."""
import json
import unittest
from benchmarks.analyze_tavily_20_offers import CORPUS, RECEIPTS
from benchmarks.analyze_tavily_20_adaptive import FALLBACK, assess


class Tavily20FallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus=json.loads(CORPUS.read_text(encoding="utf8"))
        cls.original=[json.loads(x) for x in RECEIPTS.read_text(encoding="utf8").splitlines()]
        cls.fallback=[json.loads(x) for x in FALLBACK.read_text(encoding="utf8").splitlines()]
        cls.report=assess(cls.corpus,cls.original,cls.fallback)

    def test_adaptive_strategy_does_not_recategorize_exact_offers(self):
        s=self.report["summary"]
        self.assertEqual(s["initial_case_count"],20)
        self.assertEqual(s["initial_exact_offer_id_url_count"],5)
        self.assertEqual(s["fallback_needed"],15)
        self.assertEqual(s["new_exact_offer_id_url_from_fallback"],0)
        self.assertEqual(s["combined_exact_offer_id_urls"],5)
        self.assertEqual(s["combined_case_coverage_brand_and_model_titles"],15)

    def test_rate_limit_is_recorded_not_zero_result(self):
        s=self.report["summary"]
        self.assertEqual(s["fallback_attempted"],11)
        self.assertEqual(s["fallback_http_200"],10)
        self.assertEqual(s["fallback_http_429"],1)
        self.assertEqual(s["fallback_not_attempted_due_rate_limit"],4)
        self.assertEqual(len(self.fallback),11)
        self.assertEqual(self.fallback[-1]["http_status"],429)
        self.assertNotEqual(self.fallback[-1]["status"],"OK")

    def test_product_group_prices_not_promoted_to_offer_prices(self):
        self.assertEqual(self.report["summary"]["fallback_cases_with_product_group_price_only"],5)
        for r in self.report["model_level_unverified_price_claims"]:
            self.assertEqual(r["explicit_warning"].startswith("No exact offer ID"),True)
        for case in self.report["fallback_cases"]:
            self.assertFalse(case["verified_live_seller_price"])
            self.assertFalse(case["verified_live_stock"])
            self.assertIsNone(case["exact_url_price_claim"])

    def test_fallback_for_new_offer_is_forbidden(self):
        with self.assertRaises(ValueError):
            # This offer had an exact primary URL match, so it is not eligible
            # for any model-only fallback receipt.
            duplicate={**self.fallback[0],"case_id":"BOSCH-005"}
            assess(self.corpus,self.original,self.fallback+[duplicate])


if __name__=="__main__":
    unittest.main()
