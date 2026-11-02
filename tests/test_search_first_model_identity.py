"""Regression: a power rating in Shopping must not hide a cheaper Allegro lead."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from search_first import _model_tokens, _variant_assessment, search_serpapi_shopping


class ShoppingModelIdentityRegressionTests(unittest.TestCase):
    def test_1100w_and_8bar_do_not_conflict_with_stanley_model_number(self):
        original = "Stanley Air Kit OL 195 kompresor bezolejowy 8215190STN595"
        alternative = "Kompresor bezolejowy 1100 W Stanley Air Kit 1.5KM 8 bar Sprężarka Zestaw"
        self.assertEqual(_model_tokens(original),{"8215190stn595"})
        self.assertEqual(_model_tokens(alternative),set())
        self.assertEqual(_variant_assessment(original, alternative),
                         "PRODUCT_IDENTITY_NOT_PROVEN_BY_SHOPPING_INDEX")

    def test_two_different_explicit_model_ids_are_conflicting(self):
        self.assertEqual(_variant_assessment(
            "Stanley Air Kit 8215190STN595",
            "Stanley Air Kit 8215190STN9991"),
            "MODEL_TOKEN_CONFLICT_NEEDS_REVIEW")
        self.assertEqual(_variant_assessment(
            "Sony WH 1000XM5 słuchawki",
            "Sony WH 1000XM4 słuchawki"),
            "MODEL_TOKEN_CONFLICT_NEEDS_REVIEW")

    def test_numeric_identifier_is_allowed_but_size_is_not_identity(self):
        self.assertIn("75375",_model_tokens("LEGO Millennium Falcon 75375"))
        self.assertEqual(_model_tokens("1100W 8bar 128GB 1TB 4000mah"),set())

    def test_real_world_stanley_indexed_allegro_260_is_considered_not_blocked(self):
        original = {
            "title":"Stanley Air Kit OL 195 kompresor bezolejowy 8215190STN595",
            "barcode":"8016738753899", "currency":"PLN",
        }
        queries=[]
        def fake(url, host):
            from urllib.parse import parse_qs, urlsplit
            engine=parse_qs(urlsplit(url).query)["engine"][0]
            queries.append(engine)
            if engine=="google_shopping":
                return {"search_metadata":{"status":"Success"},
                    "shopping_results":[{"title":"Stanley Air Kit 8215190STN595",
                       "product_id":"987654321012345","price":"260,00 zł",
                       "extracted_price":260,"source":"Allegro"}]}
            return {"search_metadata":{"status":"Success"}, "product_results":{
                "title":"Stanley Air Kit kompresor bezolejowy",
                "stores":[
                    {"name":"Allegro",
                     "title":"Kompresor bezolejowy 1100 W Stanley Air Kit 1.5KM 8 bar Sprężarka Zestaw",
                     "link":"https://allegro.pl/oferta/stanley-kompresor-air-kit-18637535530",
                     "price":"260,00 zł", "extracted_price":260},
                    {"name":"OBI.pl",
                     "title":"Stanley kompresor bezolejowy bez zbiornika 8 bar",
                     "link":"https://www.obi.pl/p/6615462/stanley-kompresor-bezolejowy-bez-zbiornika-8-bar",
                     "price":"320,52 zł", "extracted_price":320.52},
                    {"name":"Other",
                     "title":"Stanley 8215190STN9991",
                     "link":"https://other.example.org/item/different-model",
                     "price":"99,00 zł", "extracted_price":99}]}}
        result=search_serpapi_shopping(original,fetch=fake,api_key="fixture")
        self.assertEqual(queries,["google_shopping","google_product"])
        self.assertEqual(result["lowest_indexed_observation"]["seller"],"Allegro")
        self.assertEqual(result["lowest_indexed_observation"]["price"],"260.00")
        self.assertEqual(result["indexed_offers"][0]["identity_status"],
                         "MODEL_TOKEN_CONFLICT_NEEDS_REVIEW")
        allegro=next(o for o in result["indexed_offers"] if o["seller"]=="Allegro")
        self.assertEqual(allegro["identity_status"],
                         "PRODUCT_IDENTITY_NOT_PROVEN_BY_SHOPPING_INDEX")
        self.assertEqual(result["source_qualified_seller_offers"],0)


if __name__=="__main__":
    unittest.main()
