"""Opt-in Shopping configuration and retry from existing cart URL, no paid calls."""
from datetime import datetime,timezone
import json
from pathlib import Path
import secrets
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import app
from cart_research import CartResearchJobs
from browser_companion_queue import CompanionQueue
from tests.test_browser_companion_http import CompanionHTTPTests
from search_first import _empty


class ProviderHTTPTests(unittest.TestCase):
    call=CompanionHTTPTests.call

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.server=app.StreamingHTTPServer(("127.0.0.1",0),app.TraceCartHandler)
        self.server.csrf=secrets.token_urlsafe(24)
        self.db=Path(self.temp.name)/"research.sqlite"
        self.shared_config=patch("shopping_provider_config._shared_config_path",
                                  return_value=Path(self.temp.name)/"not-configured.env")
        self.shared_config.start()
        self.server.cart_jobs=CartResearchJobs(self.db,runner=lambda item:{})
        self.server.companion=CompanionQueue(token="a"*64)
        self.base="http://127.0.0.1:{}".format(self.server.server_port)
        self.worker=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.worker.start()
        self.job="ryobitest_123456789012345"
        item={"title":"Ryobi R18PI-0","merchant_url":
              "https://pl.ryobitools.eu/elektronarzedzia/kompresory-i-pompy/r18pi/r18pi-0/",
              "price":"239.99","currency":"PLN","barcode":"4892210164674"}
        report={"root":{"id":"root","children":[{"id":"base","children":[]},
                  {"id":"last","children":[]}]},
                "indexed_shopping":_empty("SKIPPED_NO_SERPAPI_API_KEY","now"),
                "source_intake":{"intake_status":"PAGE_RETRIEVED"}}
        with self.server.cart_jobs._db() as db:
            db.execute("""INSERT INTO cart_research_jobs
                (id,item,state,created,result) VALUES (?,?,?,?,?)""",
                (self.job,json.dumps(item),"READY",datetime.now(
                 timezone.utc).isoformat(),json.dumps(report)))

    def tearDown(self):
        self.server.shutdown()
        self.worker.join(timeout=4)
        self.server.server_close()
        self.server.cart_jobs.close()
        self.shared_config.stop()
        self.temp.cleanup()

    def test_unconfigured_reports_not_searched_then_explicit_opt_in_refresh(self):
        code,page=self.call("/research/shopping")
        self.assertEqual(code,200)
        self.assertIn("NOT CONFIGURED",page)
        self.assertIn("max",page.lower())
        self.assertEqual(self.call("/cart/status/"+self.job+"/search-index",
                 method="POST",payload={"csrf":self.server.csrf},
                 origin=self.base)[0],400)
        self.assertFalse(self.server.cart_jobs.shopping_provider_status()["configured"])
        key="ab"*32
        code, page=self.call("/research/shopping/configure",method="POST",
            origin=self.base,
            payload={"csrf":self.server.csrf,"operation":"enable","api_key":key})
        self.assertEqual(code,200)
        self.assertIn("ACTIVE",page)
        self.assertNotIn(key,page)
        self.assertTrue(self.server.cart_jobs.shopping_provider_status()["configured"])
        with patch("search_first.search_serpapi_shopping",
                   return_value=_empty("NO_SEARCH_RESULTS","now")) as search:
            code,_=self.call("/cart/status/"+self.job+"/search-index",
                method="POST",origin=self.base,
                payload={"csrf":self.server.csrf})
            self.assertEqual(code,200)
            final={}
            for _ in range(80):
                final=self.server.cart_jobs.shopping_refresh_status(self.job)
                if final["status"] not in ("RUNNING","QUEUED"):
                    break
                time.sleep(.05)
            self.assertEqual(final["status"],"COMPLETE",final)
            self.assertEqual(search.call_count,1)
            self.assertEqual(search.call_args.kwargs["api_key"],key)
        read=self.server.cart_jobs.read(self.job)
        self.assertEqual(read["report"]["indexed_shopping"]["status"],
                         "NO_SEARCH_RESULTS")
        self.assertEqual(len(read["report"]["root"]["children"]),3)
        self.assertEqual(self.server.cart_jobs.shopping_provider_status()
                         ["reserved_calls_today"],2)
        self.assertEqual(self.call("/research/shopping/configure",method="POST",
           origin=self.base,payload={"csrf":self.server.csrf,
           "operation":"disable"})[0],200)
        self.assertFalse(self.server.cart_jobs.shopping_provider_status()["configured"])

    def test_key_write_rejects_cross_origin_and_invalid_inputs(self):
        payload={"csrf":self.server.csrf,"operation":"enable",
                 "api_key":"123456789012345678901234567890"}
        self.assertEqual(self.call("/research/shopping/configure",method="POST",
             origin="https://evil.example.org",payload=payload)[0],400)
        payload["api_key"]="bad"
        self.assertEqual(self.call("/research/shopping/configure",method="POST",
             origin=self.base,payload=payload)[0],400)
        self.assertFalse(self.server.cart_jobs.shopping_provider_status()["configured"])


if __name__=="__main__":
    unittest.main()
