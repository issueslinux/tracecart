"""Validate the 20-product SerpApi/DataForSEO comparison without invented live prices."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / "benchmarks"))
from search_first_provider_benchmark import evaluate, _parsed_rows, _manifest

MANIFEST = ROOT / "benchmarks" / "shopping_20_products.json"
CASE = _manifest(MANIFEST)[0]


SERPAPI = {
    "shopping_results":[
        {"title":"Stanley Air Kit OL195", "source":"Allegro",
         "price":"229,00 zł","extracted_price":229.0,
         "product_link":"https://www.google.com/shopping/product/123"},
        {"title":"Stanley Air Kit OL195", "source":"Narzedzia",
         "price":"367,99 zł","extracted_price":367.99},
        {"title":"Stanley OTHER MODEL 9000", "source":"Other",
         "price":"3,00 zł","extracted_price":3.0},
        {"title":"Stanley Air Kit OL195", "source":"Private shop",
         "price":"5,00 zł","extracted_price":5.0,
         "link":"https://127.0.0.1/private"},
    ],
    "product_results":{
        "title":"Stanley Air Kit OL195",
        "stores":[
            {"name":"Allegro","title":"Stanley Air Kit OL195",
             "link":"https://allegro.pl/oferta/stanley-air-kit-18637535530?utm_source=google",
             "price":"229,00 zł","extracted_price":229},
            {"name":"BadCurrency","title":"Stanley Air Kit OL195",
             "link":"https://bad.example.org/prod/stanley",
             "price":"99.99","extracted_price":99.99},
            {"name":"FakeNaN","title":"Stanley Air Kit OL195",
             "price":"NaN zł","extracted_price":float("nan")},
            {"name":"WrongModel","title":"Stanley Air Kit OL999",
             "link":"https://wrong.example.org/prod/stanley",
             "price":"1,00 zł","extracted_price":1},
        ]
    }
}
DATAFORSEO = {
    "status_code":20000,
    "tasks":[{"status_code":20000,"result":[{"items":[
        {"type":"google_shopping_serp",
         "title":"Stanley Air Kit OL195",
         "seller":"Allegro",
         "price":225.0,"currency":"PLN","url":None},
        {"type":"google_shopping_sponsored_carousel",
         "items":[{"type":"google_shopping_sponsored_carousel_element",
                   "seller":"Narzedzia","title":"Stanley Air Kit OL195",
                   "price":364.99,"currency":"PLN","url":None}]},
        {"type":"related_searches", "title":"Stanley OL195 gratis",
         "price":0.01,"seller":"Fake", "currency":"PLN"},
        {"type":"google_shopping_serp","seller":"Allegro",
         "title":"Stanley Air Kit OL195","price":225.0,
         "currency":"PLN","url":None},
        {"type":"google_shopping_serp","seller":"WrongModel",
         "title":"Stanley Air Kit OL999","price":1.00,
         "currency":"PLN","url":None},
    ]}]}]
}


class SearchFirstBenchmarkTests(unittest.TestCase):
    def test_manifest_contains_20_distinct_real_research_targets(self):
        cases = _manifest(MANIFEST)
        self.assertEqual(len(cases),20)
        self.assertEqual(len({c["id"] for c in cases}),20)
        self.assertEqual(len([c for c in cases if c["barcode"]]),1)

    def test_no_credentials_no_provider_files_means_not_executed_not_no_results(self):
        result = evaluate(MANIFEST, {})
        self.assertEqual(result["case_count"], 20)
        for provider in ("serpapi","dataforseo"):
            status=result["provider_metrics"][provider]
            self.assertEqual(status["responses_supplied"],0)
            self.assertEqual(status["responses_valid"],0)
            self.assertEqual(result["results"][0][provider]["status"],
                             "NOT_EXECUTED_NO_RESPONSE")
        self.assertEqual(result["execution_mode"],
                         "OFFLINE_REPLAY_OF_EXPLICIT_PROVIDER_JSON_ONLY")
        self.assertFalse(result["payment_authorized"])

    def test_serpapi_prices_not_treated_as_verified_marketplace_prices(self):
        rows = _parsed_rows("serpapi", SERPAPI, CASE)
        self.assertEqual(len(rows), 5)
        allegro = [x for x in rows if x["marketplace"] == "allegro"]
        self.assertTrue(all(not x["source_qualified_seller_price"] for x in allegro))
        self.assertEqual(allegro[0]["indexed_price"],"229.00")
        self.assertIsNone(allegro[0]["merchant_url_unverified"])
        self.assertEqual(allegro[1]["merchant_url_unverified"],
                         "https://allegro.pl/oferta/stanley-air-kit-18637535530")
        self.assertEqual([x for x in rows if x["seller"]=="WrongModel"][0][
            "listing_identity"],"MODEL_TOKENS_NOT_ESTABLISHED")
        self.assertTrue(all(x["currency"]=="PLN" for x in rows))

    def test_dataforseo_nested_carousel_and_null_seller_urls(self):
        rows = _parsed_rows("dataforseo", DATAFORSEO, CASE)
        self.assertEqual(len(rows),3)
        self.assertTrue(any(x["seller"]=="Allegro" for x in rows))
        self.assertTrue(all(x["merchant_url_unverified"] is None for x in rows))
        self.assertEqual([x for x in rows if x["seller"]=="Narzedzia"][0][
            "indexed_price"],"364.99")
        self.assertEqual([x for x in rows if x["seller"]=="WrongModel"][0][
            "listing_identity"],"MODEL_TOKENS_NOT_ESTABLISHED")

    def test_two_provider_snapshots_report_only_what_is_supplied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for provider,body in (("serpapi",SERPAPI),("dataforseo",DATAFORSEO)):
                path=root/provider
                path.mkdir()
                (path/"P01.json").write_text(json.dumps(body))
            result=evaluate(MANIFEST, {
                "serpapi":root/"serpapi", "dataforseo":root/"dataforseo",
            })
        self.assertEqual(result["provider_metrics"]["serpapi"]["responses_valid"],1)
        self.assertEqual(result["provider_metrics"]["dataforseo"]["responses_valid"],1)
        self.assertEqual(result["provider_metrics"]["serpapi"][
            "samples_with_indexed_marketplace_price"],1)
        self.assertEqual(result["provider_metrics"]["dataforseo"][
            "samples_with_indexed_marketplace_price"],1)
        self.assertEqual(result["results"][0]["serpapi"][
            "unverified_lowest_same_currency"]["price"],"229.00")
        self.assertEqual(result["results"][0]["dataforseo"][
            "unverified_lowest_same_currency"]["price"],"225.00")
        self.assertEqual(result["results"][1]["serpapi"]["status"],
                         "NOT_EXECUTED_NO_RESPONSE")

    def test_invalid_provider_response_not_falsely_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            (path/"P01.json").write_text(
                '{"status_code":40001,"tasks":[]}')
            result=evaluate(MANIFEST,{"dataforseo":path})
        self.assertEqual(result["provider_metrics"]["dataforseo"][
            "responses_valid"],0)
        self.assertEqual(result["results"][0]["dataforseo"]["status"],
                         "PROVIDER_RESPONSE_INVALID_OR_UNREADABLE")

    def test_require_full_live_results_prevents_fake_provider_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/"report.json"
            proc=subprocess.run([
                sys.executable,
                str(ROOT/"benchmarks"/"search_first_provider_benchmark.py"),
                "--output",str(dest),"--require-all-responses"],
                capture_output=True, text=True)
            self.assertNotEqual(proc.returncode,0)
            self.assertFalse(dest.exists())
            self.assertIn("20 real successful API responses",proc.stderr)

    def test_no_automatic_network_and_no_api_credentials(self):
        src=(ROOT/"benchmarks"/"search_first_provider_benchmark.py").read_text()
        self.assertNotIn("urlopen(",src)
        self.assertNotIn("api_key",src.lower())
        self.assertNotIn("requests.get(",src)


if __name__ == "__main__":
    unittest.main()


class PendingProviderResponsesTests(unittest.TestCase):
    def test_dataforseo_queued_task_not_false_negative_market_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path/"P01.json").write_text(json.dumps({
                "status_code":20000,
                "tasks":[{"status_code":20100, "result":None}],
            }))
            result=evaluate(MANIFEST,{"dataforseo":path})
        self.assertEqual(result["results"][0]["dataforseo"]["status"],
                         "PROVIDER_RESPONSE_PENDING_NOT_MEASURED")
        self.assertEqual(result["provider_metrics"]["dataforseo"]["responses_valid"],0)

    def test_serpapi_processing_not_false_zero_prices(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            (path/"P01.json").write_text(json.dumps({
                "search_metadata":{"status":"Processing"},
                "shopping_results":[],
            }))
            result=evaluate(MANIFEST,{"serpapi":path})
        self.assertEqual(result["results"][0]["serpapi"]["status"],
                         "PROVIDER_RESPONSE_PENDING_NOT_MEASURED")
        self.assertEqual(result["provider_metrics"]["serpapi"]["responses_valid"],0)

    def test_malformed_direct_urls_are_excluded_not_checked(self):
        raw={"shopping_results":[
            {"title":"Stanley Air Kit OL195", "source":"Bad",
             "price":"0,01 zł","extracted_price":0.01,
             "link":"https://evil.example.com:ABC/private"},
            {"title":"Stanley Air Kit OL195", "source":"Allegro",
             "price":"229,00 zł","extracted_price":229,
             "product_link":"https://www.google.com/shopping/product/123"},
        ]}
        rows=_parsed_rows("serpapi",raw,CASE)
        self.assertEqual([r["seller"] for r in rows],["Allegro"])
        self.assertIsNone(rows[0]["merchant_url_unverified"])
