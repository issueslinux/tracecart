"""Conditional comparisons: no fabricated winners, correct relative costs, traceable seller questions."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comparison import compare

SAMPLE = json.loads((Path(__file__).resolve().parents[1] / "examples" /
                     "comparison_three_laptops_FICTIONAL.json").read_text())


def all_nodes(node):
    yield node
    for child in node.get("children", []):
        yield from all_nodes(child)


class ComparisonTests(unittest.TestCase):
    def test_three_way_prices_are_relative_to_correct_baseline(self):
        report = compare(SAMPLE)
        pairs = report["comparison_summary"]["pairwise"]
        self.assertEqual(len(pairs), 3)
        self.assertEqual((pairs[0]["left_offer"], pairs[0]["right_offer"]),
                         ("laptop_a", "laptop_b"))
        self.assertEqual(pairs[0]["right_vs_left_pct"], "10.0%")
        self.assertEqual(pairs[0]["left_cheaper_vs_right_pct"], "9.1%")
        self.assertEqual(pairs[1]["right_vs_left_pct"], "-27.8%")
        self.assertEqual(pairs[2]["right_vs_left_pct"], "-34.3%")
        self.assertEqual(pairs[0]["price_difference"], "90.00")
        self.assertEqual(report["comparison_summary"]["currency"], "PLN")

    def test_more_ram_does_not_prove_better_purchase(self):
        report = compare(SAMPLE)
        metric = next(x for x in report["comparison_summary"]["pairwise"][0]["metric_differences"]
                      if x["metric"] == "ram_gb")
        self.assertEqual(metric["left_value"], "16")
        self.assertEqual(metric["right_value"], "32")
        self.assertEqual(metric["right_vs_left"], "higher")
        self.assertIn("depends on workloads", metric["conditional_utility"])
        self.assertFalse(report["root"]["children"][-1]["details"]["eligible_for_payment"])
        self.assertEqual(report["root"]["children"][-1]["status"], "NO_FORCED_WINNER")
        self.assertTrue(report["comparison_summary"]["no_forced_winner"])

    def test_used_offer_generates_questions_to_seller_not_buyer(self):
        report = compare(SAMPLE)
        used = next(x for x in report["comparison_summary"]["options"]
                    if x["offer_id"] == "laptop_c")
        self.assertEqual(used["condition"], "used")
        self.assertGreaterEqual(len(used["seller_questions"]), 4)
        joined = " ".join(used["seller_questions"])
        self.assertIn("repaired", joined)
        self.assertIn("battery", joined)
        nodes = list(all_nodes(report["root"]))
        followups = [n for n in nodes if n["kind"] == "follow_up"
                     and n["details"].get("origin") == "used_offer_due_diligence"]
        self.assertEqual(len(followups), len(used["seller_questions"]))
        self.assertTrue(all(n["status"] == "OPEN" for n in followups))

    def test_missing_spec_is_explicitly_not_comparable(self):
        report = compare(SAMPLE)
        pair = next(p for p in report["comparison_summary"]["pairwise"]
                    if p["left_offer"] == "laptop_a" and p["right_offer"] == "laptop_c")
        missing = next(x for x in pair["metric_differences"] if x["metric"] == "ssd_gb")
        self.assertEqual(missing["status"], "NOT_COMPARABLE_MISSING_DATA")
        self.assertEqual(missing["missing_for"], "laptop_c")

    def test_conflicting_units_never_mixed(self):
        p = deepcopy(SAMPLE)
        p["offers"][1]["metrics"]["ram_gb"]["unit"] = "MB"
        report = compare(p)
        pair = report["comparison_summary"]["pairwise"][0]
        ram = next(x for x in pair["metric_differences"] if x["metric"] == "ram_gb")
        self.assertEqual(ram["status"], "NOT_COMPARABLE_MISMATCH")

    def test_unknown_condition_creates_one_seller_question(self):
        p = deepcopy(SAMPLE)
        p["offers"][2]["condition"] = "unknown"
        r = compare(p)
        questions = r["comparison_summary"]["options"][2]["seller_questions"]
        self.assertEqual(len(questions), 1)
        self.assertIn("new, refurbished or used", questions[0])

    def test_mixed_currencies_fail_instead_of_guessing_fx(self):
        p = deepcopy(SAMPLE)
        p["offers"][1]["currency"] = "USD"
        with self.assertRaisesRegex(ValueError, "currencies"):
            compare(p)

    def test_prices_and_numeric_specs_are_not_ai_guesses(self):
        for changed_field, val in [("price", "-1"), ("price", "NaN"),
                                   ("price", "1000.123"), ("price", "999e9")]:
            with self.subTest(changed_field=changed_field, val=val):
                p = deepcopy(SAMPLE)
                p["offers"][0][changed_field] = val
                with self.assertRaises(ValueError):
                    compare(p)
        p = deepcopy(SAMPLE)
        p["offers"][0]["metrics"]["ram_gb"]["value"] = "sixteen"
        with self.assertRaises(ValueError):
            compare(p)

    def test_source_evidence_remains_in_full_tree(self):
        r = compare(SAMPLE)
        nodes = list(all_nodes(r["root"]))
        self.assertEqual(len([x for x in nodes if x["kind"] == "offer"]), 3)
        self.assertTrue(any(x["kind"] == "tradeoffs" for x in nodes))
        refs = [n["details"]["source_url"] for n in nodes if n["kind"] == "evidence"]
        self.assertIn("https://example.org/tracecart/laptop-a", refs)
        self.assertIn("https://example.com/tracecart/laptop-b", refs)
        self.assertIn("https://example.net/tracecart/laptop-c", refs)
        self.assertEqual(len(r["sha256"]), 64)
        self.assertIn("not independently retrieved", r["provenance"])

    def test_malicious_host_and_extra_keys_rejected(self):
        p = deepcopy(SAMPLE)
        p["offers"][0]["url"] = "javascript:alert(1)"
        with self.assertRaises(ValueError):
            compare(p)
        p = deepcopy(SAMPLE)
        p["offers"][0]["metrics"]["ram_gb"]["decision"] = "buy immediately"
        with self.assertRaises(ValueError):
            compare(p)

    def test_zero_reference_price_does_not_divide_by_zero(self):
        p = deepcopy(SAMPLE)
        p["offers"][0]["price"] = "0.00"
        r = compare(p)
        self.assertIsNone(r["comparison_summary"]["pairwise"][0]["right_vs_left_pct"])


if __name__ == "__main__":
    unittest.main()
