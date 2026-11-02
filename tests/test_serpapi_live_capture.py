"""Exact-bound credit consumption and resumption; no mock data disguised as live."""
from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benchmarks.serpapi_live_capture import run
from benchmarks.shopping_search_eval import load_dataset


class SerpApiLiveCaptureTests(unittest.TestCase):
    def setUp(self):
        self.samples=load_dataset(Path(__file__).resolve().parents[1] /
                                  "benchmarks/shopping_20_products.json")
        self.calls=[]
        self.stub=lambda item,api_key: self.fake(item,api_key)

    def fake(self,item,api_key):
        self.assertEqual(api_key,"fake-key")
        self.calls.append(item["id"])
        return {
            "provider_calls":2,"status":"INDEXED_STORES_WITHOUT_SELLER_VERIFICATION",
            "indexed_offers":[{"seller":"test seller", "currency":"PLN"}],
            "search_result_groups":[],
            "marketplace_hosts_seen":[],
            "queried_at":"2026-11-02T18:00:00+00:00",
            "lowest_indexed_observation":None,
        }

    def test_credit_cap_and_checkpoint_resumption(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{
                "SERPAPI_API_KEY":"fake-key"}):
            output=Path(tmp)/"results.json"
            first=run(self.samples,output,limit=4,allow_credits=True,
                      max_calls=4,fetcher=self.stub)
            self.assertEqual(list(first["observations"]),["P01","P02"])
            self.assertEqual(first["total_provider_calls"],4)
            second=run(self.samples,output,limit=4,allow_credits=True,
                       max_calls=8,fetcher=self.stub)
            self.assertEqual(list(second["observations"]),["P01","P02","P03","P04"])
            self.assertEqual(second["total_provider_calls"],8)
            self.assertEqual(self.calls,["P01","P02","P03","P04"])
            self.assertNotIn("fake-key",output.read_text())
            self.assertEqual(output.stat().st_mode & 0o777,0o600)

    def test_no_calls_without_opt_in_or_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/"results.json"
            with patch.dict(os.environ,{"SERPAPI_API_KEY":"fake-key"}):
                with self.assertRaises(ValueError):
                    run(self.samples,out,allow_credits=False,fetcher=self.stub)
            with patch.dict(os.environ,{"SERPAPI_API_KEY":""}):
                with self.assertRaises(ValueError):
                    run(self.samples,out,allow_credits=True,fetcher=self.stub)
            self.assertFalse(out.exists())
            self.assertEqual(self.calls,[])


if __name__=="__main__":
    unittest.main()


class SerpApiFailedRetryTests(unittest.TestCase):
    def test_resuming_failed_sample_retains_total_credit_usage(self):
        samples=load_dataset(Path(__file__).resolve().parents[1] /
                             "benchmarks/shopping_20_products.json")
        seen=[]
        def fetch(item,api_key):
            seen.append(item["id"])
            return {
                "provider_calls":1 if len(seen)==1 else 2,
                "status":("FAILED_ValueError" if len(seen)==1
                          else "INDEXED_STORES_WITHOUT_SELLER_VERIFICATION"),
                "indexed_offers":[],"search_result_groups":[],
                "marketplace_hosts_seen":[],"queried_at":"2026-11-02T00:00:00+00:00",
                "lowest_indexed_observation":None,
            }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{
                "SERPAPI_API_KEY":"fake-key"}):
            dest=Path(tmp)/"checkpoint.json"
            first=run(samples,dest,limit=1,max_calls=5,allow_credits=True,
                      fetcher=fetch)
            self.assertEqual(first["total_provider_calls"],1)
            second=run(samples,dest,limit=1,max_calls=5,allow_credits=True,
                       retry_failed=True,fetcher=fetch)
            self.assertEqual(second["total_provider_calls"],3)
            self.assertEqual(len(seen),2)
            self.assertEqual(second["recovered_failed_attempts"][0]["original_provider_calls"],1)
