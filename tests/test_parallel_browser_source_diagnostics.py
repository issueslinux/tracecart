"""Prove parallel graphical fallback and source-attempt audit survival."""
import json
import subprocess
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from browser_render import MAX_PARALLEL_RENDERS, rendered_browser_document
from evidence_execution import execute_reference_checks
from generic_source_research import execute_generic_sources

URL="https://example.org/products/a123"
SHELL=b"<html><body><h1>Maker A123 laptop</h1>JS product shell</body></html>"
ROBOTS=b"User-agent: *\nAllow: /\n"


class BrowserSourcePipelineTests(unittest.TestCase):
    def test_three_browser_tasks_overlap_and_five_finish(self):
        self.assertEqual(MAX_PARALLEL_RENDERS,3)
        lock=threading.Lock()
        ready=threading.Event()
        current=[0]
        peak=[0]
        def runner(cmd,**kwargs):
            with lock:
                current[0]+=1
                peak[0]=max(peak[0],current[0])
                if current[0]==3:
                    ready.set()
            ready.wait(.5)
            time.sleep(.05)
            with lock:
                current[0]-=1
            payload={"source_url":URL,
                "browser_request_scope":"SAME_ORIGIN_HTTPS_ONLY_PINNED_PUBLIC_IP",
                "render_method":"ISOLATED_XVFB_CHROMIUM",
                "html":"<html><body>Product technical data: 42 GB</body></html>"}
            return subprocess.CompletedProcess(cmd,0,
                stdout=json.dumps(payload).encode(),stderr=b"")
        with patch("browser_render._public_pinned_ipv4",return_value="93.184.216.34"):
            with ThreadPoolExecutor(max_workers=5) as pool:
                results=list(pool.map(lambda _:rendered_browser_document(
                    URL,SHELL,runner=runner,enabled=True),range(5)))
        self.assertEqual(peak[0],3)
        self.assertTrue(all(b"42 GB" in x for x in results))

    def test_page_rendered_without_matching_data_remains_unverified_but_audited(self):
        offer={"id":"offer-0","title":"Maker A123 laptop","url":URL}
        def fetch(url,*args,**kwargs):
            return ROBOTS if url.endswith("/robots.txt") else SHELL
        with patch("browser_render.rendered_browser_document",return_value=SHELL):
            result=execute_generic_sources(
                offer,"LAPTOP",fetch=fetch,enable_brand_discovery=False)
        self.assertEqual(result["reference_answers"],[])
        self.assertEqual(result["attempted_sources"][0]["browser_status"],
                         "RENDERED_NO_MATCHED_PRODUCT_DATA")
        with patch("generic_source_research.execute_generic_sources",return_value=result):
            final=execute_reference_checks(offer,"SMARTPHONE")
        self.assertEqual(final["status"],"NO_MATCHED_INDEPENDENT_SOURCE")
        self.assertEqual(final["attempted_sources"],result["attempted_sources"])

    def test_graphical_fields_are_declarations_not_independent_tests(self):
        offer={"id":"offer-0","title":"Maker A123 laptop","url":URL}
        page=(b'<html><h1>Maker A123 laptop</h1>'
              b'<table><tr><th>RAM memory</th><td>16 GB</td></tr></table></html>')
        def fetch(url,*args,**kwargs):
            return ROBOTS if url.endswith("/robots.txt") else SHELL
        with patch("browser_render.rendered_browser_document",return_value=page):
            result=execute_generic_sources(
                offer,"LAPTOP",fetch=fetch,enable_brand_discovery=False)
        self.assertGreater(len(result["reference_answers"]),0)
        self.assertEqual(result["attempted_sources"][0]["method"],
                         "ISOLATED_XVFB_CHROMIUM")
        self.assertTrue(all(r["is_independent_lab_test"] is False
                            for r in result["reference_answers"]))


if __name__=="__main__":
    unittest.main()
