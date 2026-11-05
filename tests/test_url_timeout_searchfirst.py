"""Seller robots/product timeout must not kill URL-only Shopping research."""
import os
import socket
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cart_research import CartResearchJobs
from test_live_offer_compare import BASE
from test_bike_search_fallback import BIKE_URL


class UserURLTimeoutTests(unittest.TestCase):
    def test_url_timeout_is_a_partial_source_not_failed_user_job(self):
        with tempfile.TemporaryDirectory() as folder:
            db=str(Path(folder)/"timeout.sqlite")
            jobs=CartResearchJobs(db,runner=lambda item:deepcopy(BASE))
            try:
                with patch("product_intake.extract_product_page",
                           side_effect=TimeoutError("source timed out")),patch.dict(
                           os.environ,{"SERPAPI_API_KEY":""}):
                    jid=jobs.submit_url(BIKE_URL)
                    for _ in range(600):
                        record=jobs.read(jid)
                        if record["state"] not in ("QUEUED","RUNNING"):
                            break
                        time.sleep(0.02)
                self.assertEqual(record["state"],"READY",record["error_type"])
                self.assertEqual(record["report"]["source_intake"]["intake_status"],
                                 "URL_ONLY_UNVERIFIED")
                self.assertEqual(record["report"]["source_intake"]["access_problem"],
                                 "SOURCE_TIMEOUTERROR")
                self.assertEqual(record["item"]["price"],None)
                # Later Search-first nodes can be prepended before source intake.
                intake_nodes = [node for node in record["report"]["root"]["children"]
                                if node.get("kind") == "source_intake"]
                self.assertEqual(len(intake_nodes), 1)
                self.assertFalse(intake_nodes[0]["details"][
                    "price_is_confirmed_checkout_total"])
            finally:
                jobs.close()

    def test_python38_socket_timeout_keeps_real_allegro_url_researchable(self):
        # On hexagony-01 Python 3.8.10 socket.timeout is NOT TimeoutError.
        self.assertTrue(issubclass(socket.timeout, OSError))
        with tempfile.TemporaryDirectory() as folder:
            jobs=CartResearchJobs(str(Path(folder)/"socket.sqlite"),
                                  runner=lambda item:deepcopy(BASE))
            try:
                with patch("product_intake.extract_product_page",
                           side_effect=socket.timeout("HTTPS source timed out")),patch.dict(
                           os.environ,{"SERPAPI_API_KEY":""}):
                    jid=jobs.submit_url(BIKE_URL)
                    for _ in range(600):
                        record=jobs.read(jid)
                        if record["state"] not in ("QUEUED","RUNNING"):
                            break
                        time.sleep(0.02)
                self.assertEqual(record["state"],"READY",record["error_type"])
                self.assertEqual(record["report"]["source_intake"]["intake_status"],
                                 "URL_ONLY_UNVERIFIED")
                self.assertEqual(record["report"]["source_intake"]["access_problem"],
                                 "SOURCE_TIMEOUT")
            finally:
                jobs.close()

    def test_connection_reset_is_url_fallback_too(self):
        with tempfile.TemporaryDirectory() as folder:
            jobs=CartResearchJobs(str(Path(folder)/"reset.sqlite"),
                                  runner=lambda item:deepcopy(BASE))
            try:
                with patch("product_intake.extract_product_page",
                           side_effect=ConnectionResetError("reset")),patch.dict(
                           os.environ,{"SERPAPI_API_KEY":""}):
                    jid=jobs.submit_url(BIKE_URL)
                    for _ in range(600):
                        record=jobs.read(jid)
                        if record["state"] not in ("QUEUED","RUNNING"):
                            break
                        time.sleep(0.02)
                self.assertEqual(record["state"],"READY")
                self.assertEqual(record["report"]["source_intake"]["access_problem"],
                                 "SOURCE_CONNECTIONRESETERROR")
            finally:
                jobs.close()


if __name__=="__main__":
    unittest.main()
