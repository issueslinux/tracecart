"""Google Shopping can return >200 KB: do not reject otherwise valid 200s."""
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cart_research import _get_json
from search_first import search_serpapi_shopping


class _FakeBody:
    status=200
    def __init__(self,body):
        self.body=body
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,limit):
        return self.body[:limit]


class _Opener:
    def __init__(self,body): self.body=body
    def open(self,req,timeout):
        return _FakeBody(self.body)


class LargeProviderResponseTests(unittest.TestCase):
    def test_default_source_limit_200kb_remains(self):
        body=json.dumps({"shopping_results":[{"title":"X"*345000}]}).encode()
        with patch("cart_research.build_opener",return_value=_Opener(body)):
            with self.assertRaisesRegex(ValueError,"response too large"):
                _get_json("https://serpapi.com/search.json","serpapi.com")

    def test_fixed_serpapi_source_limit_allows_355kb(self):
        body=json.dumps({"shopping_results":[{"title":"X"*355000}]}).encode()
        with patch("cart_research.build_opener",return_value=_Opener(body)):
            obj=_get_json("https://serpapi.com/search.json","serpapi.com",
                          max_bytes=2_500_000)
        self.assertEqual(len(obj["shopping_results"]),1)

    def test_provider_adapter_passes_bounded_override(self):
        selected={"title":"Raspberry Pi 5 8GB","currency":"PLN","barcode":""}
        payload={"search_metadata":{"status":"Success"},
                 "shopping_results":[{"title":"Raspberry Pi 5 8GB",
                        "price":"500,00 zł","extracted_price":500,
                        "source":"Allegro"}]}
        called=[]
        def fake_get(url, host, timeout, max_bytes):
            called.append(max_bytes)
            self.assertEqual(host,"serpapi.com")
            return payload
        with patch("cart_research._get_json",side_effect=fake_get):
            result=search_serpapi_shopping(selected,api_key="fixture")
        self.assertEqual(called,[2_500_000])
        self.assertEqual(result["status"],"ONLY_GOOGLE_SHOPPING_SEARCH_INDEX_PRICES")


if __name__=="__main__":
    unittest.main()
