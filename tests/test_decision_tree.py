"""Decision tree and independent critic contract tests."""
from copy import deepcopy
from html import unescape
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import decision_tree as d


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = json.loads((ROOT / "examples" / "sample_research_fixture.json").read_text())


def descendants(node):
    yield node
    for child in node.get("children", []):
        yield from descendants(child)


class ResearchTreeTests(unittest.TestCase):
    def test_every_question_and_critic_is_visible_in_export(self):
        result = d.analyze(SAMPLE)
        nodes = list(descendants(result["root"]))
        self.assertEqual(result["root"]["status"], "INVESTIGATED_WITH_OPEN_QUESTIONS")
        self.assertEqual(len([n for n in nodes if n["kind"] == "offer"]), 2)
        self.assertEqual(len([n for n in nodes if n["kind"] == "decision"]), 1)
        self.assertGreaterEqual(len([n for n in nodes if n["kind"] == "question"]), 14)
        self.assertGreaterEqual(len([n for n in nodes if n["kind"] == "critic"]), 12)
        self.assertEqual(result["root"]["children"][-1]["status"], "ABSTAIN")
        self.assertEqual(result["root"]["children"][-1]["details"]["eligible_for_payment"], False)
        tree = d.to_html_tree(result)
        self.assertIn("battery health", tree)
        self.assertIn("Why do sources disagree", tree)
        self.assertIn("offer_a", json.dumps(result))
        self.assertIn("a1", json.dumps(result))

    def test_support_conflicts_and_open_question(self):
        result = d.analyze(SAMPLE)
        offers = result["root"]["children"][:2]
        a_battery = next(q for q in offers[0]["children"] if q["id"] == "question-offer_a-battery")
        b_battery = next(q for q in offers[1]["children"] if q["id"] == "question-offer_b-battery")
        self.assertEqual(a_battery["status"], "CONFLICTED")
        self.assertEqual(b_battery["status"], "CORROBORATED")
        self.assertFalse(any(c["kind"] == "critic" for c in b_battery["children"]))
        self.assertTrue(any(c["kind"] == "follow_up"
                            for x in descendants(a_battery) for c in x.get("children", [])))

    def test_same_source_does_not_count_as_independent_confirmation(self):
        sample = deepcopy(SAMPLE)
        q = sample["offers"][1]["questions"][0]
        q["evidence"][1]["url"] = q["evidence"][0]["url"]
        r = d.analyze(sample)
        questions = r["root"]["children"][1]["children"]
        battery = next(q for q in questions if q["id"] == "question-offer_b-battery")
        self.assertEqual(battery["status"], "SINGLE_SOURCE")
        self.assertTrue(any(x["details"]["duplicate_url"] for x in battery["children"]
                            if x["kind"] == "evidence"))

    def test_ai_generated_questions_are_not_answers(self):
        sample = deepcopy(SAMPLE)
        sample["generated_questions"] = [
            {"trigger_question_id": "offer_a-battery",
             "text": "Can an independent unit test confirm the battery health?",
             "origin": "model_critic"}
        ]
        r = d.analyze(sample)
        nodes = list(descendants(r["root"]))
        proposed = [n for n in nodes if n["kind"] == "follow_up"
                    and n["details"]["origin"] == "model_critic"]
        self.assertEqual(len(proposed), 1)
        self.assertEqual(proposed[0]["status"], "OPEN")
        self.assertEqual(r["root"]["children"][-1]["status"], "ABSTAIN")

    def test_rejects_fabricated_model_evidence_or_bad_question_id(self):
        for candidate in [
            {"trigger_question_id": "offer_a-battery", "text": "Is this confirmed?",
             "answer": "Yes"},
            {"trigger_question_id": "missing-battery", "text": "Is this confirmed?"},
            {"trigger_question_id": "offer_a-battery", "text": "There are no defects."},
        ]:
            with self.subTest(candidate=candidate):
                sample = deepcopy(SAMPLE)
                sample["generated_questions"] = [candidate]
                with self.assertRaises(ValueError):
                    d.analyze(sample)

    def test_rejects_javascript_urls(self):
        sample = deepcopy(SAMPLE)
        sample["offers"][0]["questions"][0]["evidence"][0]["url"] = "javascript:alert(1)"
        with self.assertRaises(ValueError):
            d.analyze(sample)

    def test_html_escapes_suspicious_input(self):
        sample = deepcopy(SAMPLE)
        sample["offers"][0]["title"] = "<script>alert('bad')</script>"
        sample["offers"][0]["questions"][0]["evidence"][0]["excerpt"] = "<img src=x onerror=alert(1)>"
        html = d.to_html_tree(d.analyze(sample))
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;img", html)

    def test_source_provenance_is_preserved(self):
        r = d.analyze(SAMPLE)
        nodes = list(descendants(r["root"]))
        originals = {e["id"]: e for o in SAMPLE["offers"]
                     for q in o["questions"] for e in q["evidence"]}
        evidence = {n["details"]["source_id"]: n for n in nodes if n["kind"] == "evidence"}
        self.assertEqual(set(evidence), set(originals))
        for key, item in originals.items():
            self.assertEqual(evidence[key]["details"]["excerpt"], item["excerpt"])
            self.assertEqual(evidence[key]["details"]["source_url"], item["url"])

    def test_report_store_survives_reload(self):
        with tempfile.TemporaryDirectory() as root:
            path = str(Path(root) / "research.sqlite")
            db = sqlite3.connect(path)
            rid = d.ReportStore(db).save(d.analyze(SAMPLE))
            db.close()
            db = sqlite3.connect(path)
            saved = d.ReportStore(db).load(rid)
            self.assertEqual(saved["sha256"], d.ReportStore(db).load(rid)["sha256"])
            self.assertEqual(saved["root"]["children"][-1]["status"], "ABSTAIN")
            with self.assertRaises(ValueError):
                d.ReportStore(db).load("../../etc/passwd")
            db.close()

    @patch("core._request_json")
    def test_model_critic_proposes_only_structured_questions(self, model):
        r = d.analyze(SAMPLE)
        model.return_value = {"message": {"content": json.dumps(
            {"questions": [{"trigger_question_id": "offer_a-battery",
                            "text": "Does a measured unit-level battery report exist?"}]}
        )}}
        proposed = d.generate_question_proposals(r, role="critic")
        self.assertEqual(proposed[0]["origin"], "model_critic")
        self.assertEqual(proposed[0]["trigger_question_id"], "offer_a-battery")
        self.assertNotIn("answer", proposed[0])
        self.assertIn("adversarial CRITIC", json.loads(model.call_args[0][2])["messages"][0]["content"])

    @patch("core._request_json")
    def test_critic_cannot_inject_unlinked_fact(self, model):
        r = d.analyze(SAMPLE)
        model.return_value = {"message": {"content": json.dumps(
            {"questions": [{"trigger_question_id": "offer_a-battery",
                            "text": "Is this confirmed?", "source_claim": "all good"}]}
        )}}
        with self.assertRaises(ValueError):
            d.generate_question_proposals(r, role="critic")

    def test_generated_duplicate_and_budget_are_audited_not_hidden(self):
        sample = deepcopy(SAMPLE)
        sample["generated_questions"] = [
            {"trigger_question_id": "offer_a-battery",
             "text": "Is the battery health confirmed for this exact unit?",
             "origin": "model_critic", "selection": "SELECTED"},
            {"trigger_question_id": "offer_a-battery",
             "text": "Does a genuine serial-numbered battery report exist?",
             "origin": "model_critic", "selection": "SELECTED"},
            {"trigger_question_id": "offer_a-price",
             "text": "Are shipping costs supported by independent data?",
             "origin": "model_researcher", "selection": "REJECTED_BUDGET"},
        ]
        r = d.analyze(sample)
        review = next(n for n in r["root"]["children"] if n["kind"] == "question_review")
        statuses = [x["result"] for x in review["details"]["candidates"]]
        self.assertEqual(statuses,
                         ["REJECTED_DUPLICATE", "OPEN_QUESTION_ADDED", "REJECTED_BUDGET"])
        nodes = list(descendants(r["root"]))
        open_generated = [n for n in nodes if n["kind"] == "follow_up"
                          and n["details"]["origin"] in ("model_critic", "model_researcher")]
        self.assertEqual(len(open_generated), 1)

    def test_failed_ai_role_remains_visible_without_trusting_it(self):
        sample = deepcopy(SAMPLE)
        sample["model_failures"] = [
            {"role": "researcher", "error_type": "ValueError"}
        ]
        report = d.analyze(sample)
        self.assertEqual(report["root"]["details"]["model_role_failures"][0]["role"],
                         "researcher")
        self.assertEqual(report["root"]["children"][-1]["status"], "ABSTAIN")

    def test_capped_input_size_and_schema(self):
        sample = deepcopy(SAMPLE)
        sample["offers"] *= 11
        with self.assertRaises(ValueError):
            d.analyze(sample)
        sample = deepcopy(SAMPLE)
        sample["secret"] = "ignored?"
        with self.assertRaises(ValueError):
            d.analyze(sample)


if __name__ == "__main__":
    unittest.main()
