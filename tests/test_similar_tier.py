"""Different brands and models can be alternatives in the same technical tier."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs,urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from similar_tier import (
    category_of,read_specs,evaluate_alternative,enrich_alternatives,
    STATUS_SIMILAR,STATUS_POSSIBLE,STATUS_DIFFERENT,STATUS_OTHER_CATEGORY,
    STATUS_CATEGORY_UNKNOWN,PRICE_BAND_HIGHER)
from search_first import search_serpapi_shopping,attach_shopping_evidence
from app import shopping_search_panel
from test_live_offer_compare import BASE
from test_bike_search_fallback import BIKE_URL
from product_intake import generic_url_identity

BIKE_INDEX=json.loads((Path(__file__).resolve().parents[1]/
  "examples/live_bike_allegro_shopping_fallback_2026-11-02.json").read_text())


class SimilarTierTests(unittest.TestCase):
    def setUp(self):
        self.input_bike,_=generic_url_identity(BIKE_URL,"HTTP_403")
        self.title=self.input_bike["title"]

    def test_bike_specs_from_url_are_not_random(self):
        specs=read_specs(self.title)
        self.assertEqual(category_of(self.title),"E_BIKE")
        self.assertEqual(specs,{"power_w":250.0,"battery_ah":15.0,
            "wheel_in":27.5,"speed_kmh":25.0,"claimed_range_km":100.0,
            "gears":7.0})

    def test_different_brand_same_tier(self):
        assessed=evaluate_alternative(self.title,
           "Orzel C27 Rower Elektryczny 27,5 250W 15Ah 25km/h 100km")
        self.assertEqual(assessed["status"],STATUS_SIMILAR)
        self.assertGreaterEqual(assessed["technical_score"],80)
        self.assertFalse(assessed["same_model_required"])
        self.assertTrue(assessed["actual_quality_not_measured"])
        self.assertTrue(assessed["advertised_range_is_unverified"])

    def test_missing_battery_is_possible_not_exact_rejection(self):
        assessed=evaluate_alternative(self.title,
            "Evercross Rower elektryczny Ek15 27,5 MTB 250W 36V 25 km/h")
        self.assertEqual(assessed["status"],STATUS_POSSIBLE)
        self.assertIn("pojemność akumulatora (Ah)",assessed["unconfirmed_features"])

    def test_500w_and_5ah_are_other_tier(self):
        for description in (
            "Rower Elektryczny MTB 500W 15Ah 27,5 7s 25kmh",
            "Rower Elektryczny MTB 250W 5Ah 27,5 7s 25kmh"):
            self.assertEqual(evaluate_alternative(self.title,description)["status"],
                             STATUS_DIFFERENT)

    def test_regular_bike_accessory_and_scooter_not_equivalent(self):
        for description in (
            "Rower MTB górski 27.5 Shimano bez silnika",
            "Bateria do roweru elektrycznego 15Ah",
            "Hulajnoga elektryczna 250W 15Ah"):
            self.assertEqual(evaluate_alternative(self.title,description)["status"],
                             STATUS_OTHER_CATEGORY)

    def test_ssd_capacity_and_form_factor_are_material(self):
        a="Samsung SSD T7 Shield 1TB dysk zewnętrzny"
        self.assertEqual(evaluate_alternative(
            a,"Kingston SSD 1TB dysk zewnętrzny")["status"],STATUS_SIMILAR)
        for b in ("Kingston SSD 2TB dysk zewnętrzny",
                  "Samsung SSD 1TB NVMe M2"):
            self.assertEqual(evaluate_alternative(a,b)["status"],STATUS_DIFFERENT)

    def test_compressor_different_brand_is_eligible(self):
        self.assertEqual(evaluate_alternative(
            "Stanley Air Kit kompresor 1100W 8bar",
            "Einhell kompresor 1100W 8bar")["status"],STATUS_SIMILAR)

    def test_unknown_product_not_declared_same_quality_from_name(self):
        result=evaluate_alternative("porcelana X","porcelana Y")
        self.assertEqual(result["status"],STATUS_CATEGORY_UNKNOWN)
        self.assertIsNone(result["technical_score"])

    def test_real_12_bike_cards_yield_ranked_similar_alternatives(self):
        result=enrich_alternatives(self.input_bike,[],deepcopy(BIKE_INDEX["cards"]))
        counts=result["status_counts"]
        self.assertEqual(counts[STATUS_SIMILAR],6)
        self.assertEqual(counts[STATUS_POSSIBLE],4)
        self.assertEqual(len(result["ranked_alternatives"]),10)
        self.assertEqual(result["price_reference_provenance"],
                         "ESTIMATE_FROM_SIMILAR_INDEX_LISTINGS")
        self.assertEqual(result["ranked_alternatives"][0]["comparison"]["technical_score"],100)
        orzel=next(x for x in result["ranked_alternatives"]
                   if "Orzel C27" in x["title"])
        self.assertEqual(orzel["comparison"]["status"],STATUS_SIMILAR)
        self.assertEqual(orzel["indexed_price"],"3399.00")
        self.assertTrue(all(not x["selected_model_identity_verified"]
                            and not x["source_verified"]
                            and not x["real_quality_test_available"]
                            for x in result["ranked_alternatives"]))
        self.assertFalse(result["payment_authorized"])

    def test_peer_median_does_not_use_outlier_49pln(self):
        titles=["Rower elektryczny 250W 15Ah 27,5"]*4
        cards=[{"source":"Seller "+str(i),"title":t,
            "indexed_price":str(p),"indexed_currency":"PLN",
            "product_id":str(11111111+i),"index_search_url":"https://www.google.com/search?tbm=shop"}
            for i,(t,p) in enumerate(zip(titles,(2499,2899,3200,49)))]
        data=enrich_alternatives(self.input_bike,[],cards)
        bad=next(r for r in data["ranked_alternatives"] if r["indexed_price"]=="49")
        self.assertEqual(bad["index_price_anomaly"],
                         "SUSPICIOUS_LOW_PRICE_VS_PEER_MEDIAN_NOT_VERIFIED")
        self.assertNotEqual(data["ranked_alternatives"][0]["indexed_price"],"49")
        self.assertGreater(float(data["price_reference"]),2000)

    def test_seller_input_price_has_priority_to_peer_median(self):
        selected={"title":self.title,"price":"2700.00","currency":"PLN"}
        data=enrich_alternatives(selected,[],deepcopy(BIKE_INDEX["cards"]))
        self.assertEqual(data["price_reference"],"2700.00")
        self.assertEqual(data["price_reference_provenance"],
                         "INPUT_SELLER_DECLARED_NOT_CHECKOUT")
        expensive=next(x for x in data["ranked_alternatives"]
                       if x["indexed_price"]=="4507.00")
        self.assertEqual(expensive["comparison"]["price_band"],PRICE_BAND_HIGHER)

    def test_no_source_rows_means_no_suggestions(self):
        result=enrich_alternatives(self.input_bike,[],[])
        self.assertEqual(result["ranked_alternatives"],[])
        self.assertIsNone(result["price_reference"])

    def test_search_provider_pipeline_evidence_and_html(self):
        def fetch(url,host):
            engine=parse_qs(urlsplit(url).query)["engine"][0]
            if engine=="google_shopping":
                return {"search_metadata":{"status":"Success"},
                        "shopping_results":[{
                            "title":x["title"],"source":x["source"],
                            "price":x["indexed_price"]+" zł",
                            "extracted_price":float(x["indexed_price"]),
                            "product_id":str(1111111111111+i)} for i,x in
                            enumerate(BIKE_INDEX["cards"])]}
            return {"error":"Google Product detail unavailable"}
        found=search_serpapi_shopping(self.input_bike,fetch=fetch,api_key="fixture")
        self.assertEqual(found["provider_calls"],2)
        alt=found["functional_alternatives"]
        self.assertEqual(alt["status_counts"][STATUS_SIMILAR],6)
        self.assertFalse(found["payment_authorized"])
        report=attach_shopping_evidence(deepcopy(BASE),self.input_bike,found)
        node=next(n for n in report["root"]["children"]
                  if n["kind"]=="indexed_shopping")
        self.assertEqual(node["details"]["alternative_tier_counts"][STATUS_SIMILAR],6)
        self.assertTrue(all("functional_alternative" in n["details"]
                            for n in node["children"] if n["kind"]=="indexed_search_card"))
        html=shopping_search_panel(report)
        self.assertIn("PODOBNA PÓŁKA",html)
        self.assertIn("3399.00",html)
        self.assertIn("Orzel C27",html)
        self.assertIn("nie niezależna ocena jakości",html)
        self.assertIn("szukaj w Google Shopping",html)


if __name__ == "__main__":
    unittest.main()


class BatteryEnergyAndConditionTests(unittest.TestCase):
    def test_nominal_energy_differs_despite_identical_ah(self):
        a="Rower elektryczny 250W 36V 15Ah 27,5"
        b="Rower elektryczny 250W 48V 15Ah 27,5"
        spec=read_specs(a)
        self.assertEqual(spec["battery_wh"],540)
        comparison=evaluate_alternative(a,b)
        self.assertEqual(comparison["status"],STATUS_POSSIBLE)
        self.assertTrue(any("Wh" in x for x in comparison["different_features"]))
        self.assertEqual(evaluate_alternative(a,a)["status"],STATUS_SIMILAR)

    def test_unknown_voltage_carries_explicit_energy_warning(self):
        a="Rower elektryczny 250W 15Ah 27,5"
        b="Rower elektryczny 250W 15Ah 27,5"
        assessment=evaluate_alternative(a,b)
        self.assertTrue(any("Wh" in x for x in assessment["unconfirmed_features"]))

    def test_used_alternative_is_not_equated_to_new(self):
        a={"title":"Nowy rower elektryczny 250W 15Ah 27,5",
           "price":"2600", "currency":"PLN"}
        c=[{"source":"Allegro","title":"Używany rower elektryczny 250W 15Ah 27,5",
            "indexed_price":"1800","indexed_currency":"PLN",
            "index_search_url":"https://www.google.com/search?tbm=shop"}]
        result=enrich_alternatives(a,[],c)
        self.assertEqual(result["ranked_alternatives"][0]["comparison"]["status"],
                         STATUS_POSSIBLE)
        self.assertIn("Różny deklarowany stan",
                      result["ranked_alternatives"][0]["comparison"]["condition_difference"])

    def test_unknown_condition_never_claimed_new(self):
        a={"title":"Rower elektryczny 250W 15Ah 27,5"}
        c=[{"source":"Allegro","title":"Rower elektryczny 250W 15Ah 27,5",
            "indexed_price":"1800","indexed_currency":"PLN"}]
        result=enrich_alternatives(a,[],c)
        self.assertEqual(result["ranked_alternatives"][0]["comparison"][
            "candidate_condition_from_title"],"NOT_STATED")
