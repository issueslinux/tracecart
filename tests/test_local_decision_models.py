"""Unit tests for read-only local decision benchmark (no Ollama calls)."""
import json
import unittest
from unittest.mock import patch

from benchmarks.local_decision_models import (
    ACTIONS, amount, cases_from_archive, index_suspect, local_endpoint,
    policy_action, query_model, summary,
)


class DecisionPolicyBenchmarkTests(unittest.TestCase):
    def sample(self):
        return {
            "product":"Archived product","seller_index_quotes_count":3,
            "browser_listed_price":3499.99,"same_seller_index_quote":139.95,
            "conditional_coupon_price":2799.00,"coupon_code_present":True,
            "coupon_applied":False,"checkout_verified":False,
            "exact_variant_verified":False,"exact_variant_conflict":False,
            "source_kind":"saved_browser_observation",
        }

    def test_policy_priorities_never_infer_a_receipt(self):
        value=self.sample()
        self.assertEqual(policy_action(value),"RECHECK_INDEX")
        value["same_seller_index_quote"]=3499.99
        self.assertEqual(policy_action(value),"VERIFY_COUPON")
        value["exact_variant_conflict"]=True
        self.assertEqual(policy_action(value),"VERIFY_VARIANT")
        value["exact_variant_conflict"]=False
        value["coupon_applied"]=True
        value["checkout_verified"]=True
        self.assertEqual(policy_action(value),"VERIFY_SELLER")
        value["exact_variant_verified"]=True
        self.assertEqual(policy_action(value),"ACCEPT_RECEIPT")

    def test_amount_refuses_invalid_or_nonfinite(self):
        for bad in (None,"Not priced",0,-1,True,"NaN","Infinity"):
            self.assertIsNone(amount(bad))
        self.assertEqual(amount("2799.00"),2799)

    def test_quote_requires_actual_same_seller_list_price(self):
        case=self.sample()
        self.assertTrue(index_suspect(case))
        case["same_seller_index_quote"]=3499.99
        self.assertFalse(index_suspect(case))
        case["browser_listed_price"]=None
        self.assertFalse(index_suspect(case))

    def test_only_loopback_endpoints(self):
        self.assertEqual(local_endpoint("http://127.0.0.1:11435"),
                         "http://127.0.0.1:11435")
        for bad in ("https://127.0.0.1:11435","http://example.com",
                    "http://user:pass@127.0.0.1","file:///etc/passwd"):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                local_endpoint(bad)

    def test_synthetic_counterfactuals_separate_from_real_archive(self):
        cases=cases_from_archive([("dell",self.sample()),
                                  ("ryobi",self.sample())])
        self.assertEqual(len(cases),7)
        self.assertEqual(sum(x["kind"]=="archived" for x in cases),2)
        receipt=next(x for x in cases if x["id"]==
                     "dell_checkout_verified_simulated")
        self.assertEqual(receipt["expected"],"ACCEPT_RECEIPT")
        self.assertFalse(self.sample()["checkout_verified"])

    def test_tevs_schema_is_strict_and_probabilities_normalize(self):
        case={"state":self.sample(),"expected":"RECHECK_INDEX"}
        good={"answers":{"action":{"choice":"RECHECK_INDEX",
              "probabilities":{k:(1. if k=="RECHECK_INDEX" else 0.)
                               for k in ACTIONS}}}}
        with patch("benchmarks.local_decision_models.request_json",return_value=good):
            x=query_model("tev1:0.8b",case,"http://127.0.0.1:11435",1)
        self.assertTrue(x["correct_policy"])
        bad=json.loads(json.dumps(good))
        bad["answers"]["action"]["probabilities"].pop("VERIFY_VARIANT")
        with patch("benchmarks.local_decision_models.request_json",return_value=bad):
            with self.assertRaises(ValueError):
                query_model("tev1:0.8b",case,"http://127.0.0.1:11435",1)

    def test_report_denominator_includes_failed_inferences(self):
        rows={"tev1:0.8b":[
            {"choice":"RECHECK_INDEX","correct_policy":True,"seconds":.4},
            {"error_type":"TimeoutError","correct_policy":False}]}
        stats=summary(rows)["tev1:0.8b"]
        self.assertEqual(stats["cases"],2)
        self.assertEqual(stats["valid"],1)
        self.assertEqual(stats["accuracy_on_policy_controls"],.5)
        self.assertEqual(stats["failed_or_timed_out"],1)


if __name__=="__main__":
    unittest.main()
