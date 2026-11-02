"""Executed evidence must be real HTML, variant-scoped, and never checkout proof."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from evidence_execution import (
    REVIEW_SOURCES, execute_reference_checks, model_family,
    _parse_review, _robot_checked_read,
)
from guided_decision import build_decision_projection
from cart_research import CartResearchJobs

ROOT=Path(__file__).resolve().parents[1]
RECORD=json.loads((ROOT/"examples"/"live_lenovo_ideapad_index_evidence_2026-11-02.json").read_text())
SOURCE=REVIEW_SOURCES["15Q8X10"]
SAMPLE_HTML=(
    '<html><head><title>Lenovo IdeaPad Slim 3 15Q8X10 review</title></head>'
    '<body><h1>Lenovo IdeaPad Slim 3 15Q8X10 review</h1>'
    '<p>The test unit has an IPS display.</p>'
    '<div class="cb_bench_label">Cinebench 2024 CPU Multi Core</div>'
    '<div class="cb_bench_value">708 Points</div>'
    '<table><tr><td class="caption">WiFi Websurfing (Edge 138)</td>'
    '<td class="runtime"><span style="">19h&nbsp;01min</span></td></tr>'
    '</table></body></html>').encode("utf-8")
ROBOTS=b"User-agent: *\nAllow: /\n"


class IndependentSourceExecutionTests(unittest.TestCase):
    def test_review_evidence_extracted_from_fetched_html(self):
        hits=[]
        def fake(url,max_bytes,mimes,timeout):
            hits.append(url)
            return ROBOTS if url.endswith("/robots.txt") else SAMPLE_HTML
        offer={"id":"offer-0",
               "title":"Lenovo IdeaPad Slim 3 15Q8X10 Snapdragon X OLED"}
        result=execute_reference_checks(offer,"LAPTOP",fetch=fake)
        self.assertEqual(result["status"],
                         "INDEPENDENT_REFERENCE_FETCHED_VARIANT_UNVERIFIED")
        self.assertEqual(result["sources_checked"],1)
        self.assertEqual(result["verified_for_exact_offer"],0)
        self.assertEqual(result["variant_match"],
                         "MISMATCH_LISTED_OLED_REVIEWED_IPS")
        self.assertEqual([(x["question_id"],x["value"]) for x in
                          result["reference_answers"]],
                         [("offer-0-28","708 points"),("offer-0-124","19h01m")])
        self.assertTrue(all(x["source_sha256"]==sha256(SAMPLE_HTML).hexdigest()
                            and x["source_url"]==SOURCE["url"]
                            and not x["verified_for_exact_offer"]
                            and x["status"]=="REFERENCE_EVIDENCE_ONLY_EXACT_SKU_UNVERIFIED"
                            for x in result["reference_answers"]))
        self.assertEqual(hits,["https://www.notebookcheck.net/robots.txt",
                               SOURCE["url"]])

    def test_robots_disallow_fails_closed_no_page_requested(self):
        called=[]
        def disallowed(url,*args,**kwargs):
            called.append(url)
            return b"User-agent: *\nDisallow: /\n"
        offer={"id":"offer-0","title":"Lenovo 15Q8X10 OLED"}
        result=execute_reference_checks(offer,"LAPTOP",fetch=disallowed)
        self.assertEqual(result["sources_checked"],0)
        self.assertEqual(result["reference_answers"],[])
        self.assertEqual(called,["https://www.notebookcheck.net/robots.txt"])

    def test_page_model_in_unrelated_sidebar_does_not_suffice(self):
        wrong=(b"<html><head><title>Other laptop review</title></head><body>" +
               b" " * 15000 + SAMPLE_HTML)
        with self.assertRaisesRegex(ValueError,"REVIEW_IDENTITY"):
            _parse_review(wrong,SOURCE)

    def test_broken_markup_or_missing_measurements_cannot_be_answers(self):
        with self.assertRaisesRegex(ValueError,"NO_VERIFIABLE"):
            _parse_review(SAMPLE_HTML.replace(b"708 Points",b"xx Points")
                          .replace(b"19h&nbsp;01min",b"99h 99min"),SOURCE)

    def test_no_foreign_intel_review_transferred_to_16iph11(self):
        for title in ("Lenovo IdeaPad Slim 3 16IPH11 Core Ultra 5 322",
                      "Lenovo IdeaPad Slim 3 15IRH10R Intel Core 5 210H",
                      "Lenovo unknown Laptop", "Lenovo Slim 3 Intel"):
            offer={"id":"offer-4","title":title}
            r=execute_reference_checks(offer,"LAPTOP",
                                       fetch=lambda *a,**k: self.fail("No fetch"))
            self.assertEqual(r["status"],"NO_MATCHED_INDEPENDENT_SOURCE")
            self.assertEqual(r["verified_for_exact_offer"],0)
        self.assertEqual(model_family("Lenovo Slim 3 15Q8X10"),
                         "15Q8X10")

    def test_job_persists_documented_reference_without_changing_original(self):
        hit_urls=[]
        def fake_read(url,max_bytes,mimes,timeout):
            hit_urls.append(url)
            return ROBOTS if url.endswith("/robots.txt") else SAMPLE_HTML
        with tempfile.TemporaryDirectory() as tmp:
            path=str(Path(tmp)/"jobs.sqlite")
            jobs=CartResearchJobs(path,runner=lambda x:deepcopy(RECORD["report"]))
            try:
                jid="Z"*24
                with jobs._db() as db:
                    db.execute("""INSERT INTO cart_research_jobs
                        (id,item,state,created,result,error_type)
                        VALUES (?,?,?,? ,?,NULL)""",
                        (jid,json.dumps(RECORD["item"]),"READY",
                         "2026-11-02T00:00:00Z",json.dumps(RECORD["report"])))
                before=jobs.read(jid)["report"]
                with patch("product_intake._read",side_effect=fake_read):
                    jobs._execute_source_evidence(jid,RECORD)
                after=jobs.read(jid)
                self.assertEqual(after["report"],before)
                self.assertEqual(after["evidence_progress"],
                                 {"status":"COMPLETE","processed":16,"planned":16})
                self.assertEqual(len(after["evidence_offers"]),16)
                self.assertEqual(hit_urls,
                                 ["https://www.notebookcheck.net/robots.txt",
                                  SOURCE["url"]])
                references=[
                    (oid,row) for oid,row in after["evidence_offers"].items()
                    if row["reference_answers"]]
                self.assertGreaterEqual(len(references),2)
                for oid,row in references:
                    self.assertEqual(len(row["reference_answers"]),2)
                    self.assertEqual(row["verified_for_exact_offer"],0)
                    self.assertTrue(row["source_sha256"])
                projected=build_decision_projection(after)
                self.assertFalse(projected["payment_authorized"])
                self.assertEqual(projected["evidence_progress"]["status"],"COMPLETE")
            finally:
                jobs.close()

if __name__=="__main__":
    unittest.main()
