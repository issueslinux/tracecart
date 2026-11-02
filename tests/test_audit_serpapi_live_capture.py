"""No hidden lower-price winner when observed Shopping data is poisoned."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benchmarks.audit_serpapi_live_capture import audit
from benchmarks.shopping_search_eval import load_dataset


class SerpApiLiveAuditTests(unittest.TestCase):
    def test_quality_audit_filters_extreme_low_price_and_generic_aggregator(self):
        manifest=load_dataset(Path(__file__).resolve().parents[1] /
                              "benchmarks/shopping_20_products.json")
        entries={
            "id":"P03","title":"Apple iPhone 16 128GB",
            "queried_at":"2026-11-02T18:00:00Z",
            "status":"INDEXED_STORES_WITHOUT_SELLER_VERIFICATION",
            "provider_calls":2,"indexed_marketplace_names_seen":["Allegro"],
            "indexed_offers":[
                {"seller":name,"title":"Apple iPhone 16 128GB",
                 "current_price_indexed":str(price),"currency":"PLN",
                 "merchant_host":name.lower()+".pl",
                 "merchant_url":"https://"+name.lower()+".pl/a"}
                for name,price in (("MediaExpert",349.90),
                    ("Euro",399.90),("AbFoto",3469),("Allegro",3737),("XKom",3999))],
        }
        result=audit({"dataset_id":manifest["dataset_id"],
                      "observations":{"P03":entries}},manifest)
        self.assertEqual(result["counts"]["flagged_extreme_low_index_prices"],2)
        case=next(c for c in result["cases"] if c["id"]=="P03")
        self.assertEqual(case["lowest_remaining_index_candidate"]["price"],"3469")
        self.assertFalse(result["price_accuracy_independently_confirmed_for_all"])
        self.assertEqual(result["provider_calls_attempted_including_failed_retries"],2)

    def test_wrong_capacity_not_accepted_as_cheapest(self):
        manifest=load_dataset(Path(__file__).resolve().parents[1]/
                              "benchmarks/shopping_20_products.json")
        cases={"dataset_id":manifest["dataset_id"],
               "observations":{"P17":{
                   "status":"INDEXED_STORES_WITHOUT_SELLER_VERIFICATION",
                   "provider_calls":2,"queried_at":"2026-11-02T18:00:00Z",
                   "indexed_offers":[
                       {"seller":"Wrong","title":"Samsung T7 Shield 2TB",
                        "current_price_indexed":"25.00","currency":"PLN",
                        "merchant_host":"wrong.pl",
                        "merchant_url":"https://wrong.pl/prod"},
                       {"seller":"Correct","title":"Samsung T7 Shield 1TB",
                        "current_price_indexed":"550.00","currency":"PLN",
                        "merchant_host":"correct.pl",
                        "merchant_url":"https://correct.pl/prod"}]}}}
        result=audit(cases,manifest)
        case=next(c for c in result["cases"] if c["id"]=="P17")
        self.assertEqual(case["lowest_remaining_index_candidate"]["price"],"550.00")
        self.assertEqual(case["not_comparable_listings"][0]["reason"],
                         "CAPACITY_VARIANT_CONFLICT_NEEDS_REVIEW")


if __name__=="__main__":
    unittest.main()
