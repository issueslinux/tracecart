"""RAM snapshots and concurrent source checks are real work, not UI timers."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from cart_research import CartResearchJobs
from live_graph_bus import MemoryLiveGraphCache

ROOT=Path(__file__).resolve().parents[1]
RECORD=json.loads((ROOT/"examples"/"live_lenovo_ideapad_index_evidence_2026-11-02.json").read_text())


class MemoryGraphTests(unittest.TestCase):
    def test_cache_bounded_in_ram_and_invalidated_only_by_actual_signal(self):
        bus=MemoryLiveGraphCache(max_jobs=2)
        calls=[]
        def make(key):
            calls.append(key)
            return {"key":key}
        rev,first=bus.snapshot("jobA",lambda:make("A"))
        self.assertEqual(rev,0)
        self.assertEqual(bus.snapshot("jobA",lambda:make("UNUSED"))[1],first)
        self.assertEqual(calls,["A"])
        bus.snapshot("jobB",lambda:make("B"))
        bus.snapshot("jobC",lambda:make("C"))
        self.assertEqual(bus.stats()["cached_jobs"],2)
        bus.snapshot("jobA",lambda:make("A_again"))
        self.assertIn("A_again",calls)
        rev_before=bus.snapshot("jobA",lambda:make("unused"))[0]
        started=threading.Event()
        observed=[]
        def waiter():
            started.set()
            observed.append(bus.wait_change("jobA",rev_before,timeout=1.2))
        t=threading.Thread(target=waiter)
        t.start()
        self.assertTrue(started.wait(1))
        bus.signal("jobA")
        t.join(2)
        self.assertEqual(observed,[True])
        current,latest=bus.snapshot("jobA",lambda:make("NEW"))
        self.assertEqual(current,rev_before+1)
        self.assertEqual(latest,{"key":"NEW"})

    def test_worker_executes_real_evidence_checks_concurrently(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=str(Path(tmp)/"jobs.sqlite")
            jobs=CartResearchJobs(db,runner=lambda _:RECORD["report"])
            in_flight=0;peak=0
            lock=threading.Lock()
            seen=[]
            def investigator(offer,category,fetch=None):
                nonlocal in_flight,peak
                with lock:
                    in_flight+=1
                    peak=max(peak,in_flight)
                time.sleep(.035)
                with lock:
                    seen.append(offer["id"])
                    in_flight-=1
                return {"status":"NO_MATCHED_INDEPENDENT_SOURCE",
                        "sources_checked":0,"reference_answers":[],
                        "verified_for_exact_offer":0}
            try:
                from evidence_execution import execute_reference_checks
                with patch("evidence_execution.execute_reference_checks",investigator):
                    jobs._execute_source_evidence("T"*24,RECORD)
                self.assertGreaterEqual(peak,8)
                self.assertEqual(len(seen),16)
                with jobs._db() as conn:
                    states=conn.execute("SELECT status,processed,planned FROM cart_evidence_runs").fetchall()
                    per_offer=conn.execute("SELECT status,COUNT(*) FROM cart_offer_evidence GROUP BY status").fetchall()
                self.assertEqual(states,[("COMPLETE",16,16)])
                self.assertEqual(per_offer,[("NO_MATCHED_INDEPENDENT_SOURCE",16)])
                self.assertLessEqual(jobs.live_bus.stats()["cached_jobs"],24)
            finally:
                jobs.close()

    def test_first_offer_source_is_reused_and_graph_grows_after_parallel_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs=CartResearchJobs(str(Path(tmp)/"jobs.sqlite"),
                                  runner=lambda _:RECORD["report"])
            jid="G"*24
            started=threading.Event()
            release=threading.Event()
            seen=[]
            first={
                "status":"GENERAL_DOCUMENT_DECLARATIONS_FETCHED_SKU_UNVERIFIED",
                "sources_checked":1,"verified_for_exact_offer":0,
                "reference_answers":[{
                    "finding":"Manufacturer lists memory variant, exact SKU not proven",
                    "source_kind":"BRAND_SITE_DECLARATIONS_NOT_INDEPENDENT_TESTS",
                    "source_method":"VISIBLE_SPECIFICATION",
                    "source_url":"https://maker.example.org/specs",
                    "source_sha256":"1"*64,"value":"16 GB RAM",
                    "verified_for_exact_offer":False,
                }],
            }
            try:
                with jobs._db() as db:
                    db.execute("""INSERT INTO cart_research_jobs
                        (id,item,state,created,result,error_type)
                        VALUES (?,?,?,?,?,NULL)""",
                        (jid,json.dumps(RECORD["item"]),"READY",
                         "2026-11-03T00:00:00Z",json.dumps(RECORD["report"])))
                    db.execute("""INSERT INTO cart_offer_evidence
                        (job_id,offer_idx,status,result_json) VALUES (?,?,?,?)""",
                        (jid,0,first["status"],json.dumps(first)))
                def slower(offer,category,fetch=None):
                    seen.append(offer["id"])
                    started.set()
                    if not release.wait(4):
                        raise RuntimeError("test worker gate")
                    return {"status":"NO_MATCHED_INDEPENDENT_SOURCE",
                        "sources_checked":0,"reference_answers":[],
                        "verified_for_exact_offer":0}
                with patch("evidence_execution.execute_reference_checks",
                           side_effect=slower):
                    thread=threading.Thread(target=jobs._execute_source_evidence,
                        args=(jid,RECORD))
                    thread.start()
                    self.assertTrue(started.wait(2))
                    revision,snapshot=jobs.live_snapshot(jid)
                    self.assertEqual(snapshot["graph"]["stats"]["offers"],1)
                    self.assertEqual(snapshot["graph"]["stats"]["total_discovered_offers"],16)
                    self.assertTrue(any(x["type"]=="source_declaration"
                                        for x in snapshot["graph"]["nodes"]))
                    self.assertEqual(snapshot["evidence_progress"]["processed"],1)
                    self.assertEqual(len(snapshot["offer_queue"]),16)
                    release.set()
                    thread.join(6)
                    self.assertFalse(thread.is_alive())
                final=jobs.live_snapshot(jid)[1]
                self.assertEqual(final["graph"]["stats"]["offers"],16)
                self.assertEqual(final["evidence_progress"]["status"],"COMPLETE")
                self.assertEqual(final["evidence_progress"]["processed"],16)
                self.assertNotIn("offer-0",seen,
                                 "Never fetch original offer twice")
            finally:
                release.set()
                jobs.close()

    def test_rebuilds_existing_historic_job_without_source_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=str(Path(tmp)/"jobs.sqlite")
            jobs=CartResearchJobs(db,runner=lambda _:RECORD["report"])
            try:
                jid="Q"*24
                with jobs._db() as connection:
                    connection.execute("""INSERT INTO cart_research_jobs
                        (id,item,state,created,result,error_type)
                        VALUES (?,?,?,?,?,NULL)""",
                        (jid,json.dumps(RECORD["item"]),"READY",
                         "2026-11-03T00:00:00Z",json.dumps(RECORD["report"])))
                revision,snapshot=jobs.live_snapshot(jid)
                self.assertEqual(snapshot["graph"]["stats"]["offers"],16)
                self.assertEqual(snapshot["state"],"READY")
                self.assertEqual(snapshot["graph"]["stats"]["verified_exact_sku_answers"],0)
                self.assertFalse(snapshot["payment_authorized"])
                self.assertEqual(jobs.live_snapshot(jid)[0],revision)
            finally:
                jobs.close()


if __name__=="__main__":
    unittest.main()
