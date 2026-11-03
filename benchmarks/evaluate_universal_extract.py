#!/usr/bin/env python3
"""Offline, deterministic extraction scorecard on synthetic multi-format pages."""
import json
from collections import Counter
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from universal_product_extract import extract_snapshot

CORPUS = Path(__file__).resolve().parent / "fixtures/universal_product_extract_v1.json"
STAMP = "2026-11-03T20:00:00+00:00"


def evaluate(corpus):
    outcomes = []
    for case in corpus["cases"]:
        result = extract_snapshot(
            case["url"], case["body"].encode("utf-8"), case["mime"],
            case["method"], http_status=case.get("http_status", 200),
            acquired_at=STAMP)
        expected = {k: case.get(k) for k in ("title", "price", "currency")}
        actual = {k: result["fields"][k] for k in expected}
        outcomes.append({
            "case_id": case["id"], "expected_status": case["status"],
            "actual_status": result["status"], "expected_fields": expected,
            "actual_fields": actual,
            "pass": result["status"] == case["status"] and expected == actual,
            "seller_verified": result["seller_verified"],
        })
    return {
        "benchmark": "UNIVERSAL_PRODUCT_EXTRACT_V1_OFFLINE",
        "source_type": corpus["provenance"],
        "case_count": len(outcomes),
        "pass_count": sum(x["pass"] for x in outcomes),
        "status_counts": dict(sorted(Counter(x["actual_status"] for x in outcomes).items())),
        "network_requests": 0,
        "seller_price_verifications": 0,
        "conclusion": "Synthetic parser contract only. This is NOT a live-site coverage/accuracy estimate.",
        "cases": outcomes,
    }


def main():
    report = evaluate(json.loads(CORPUS.read_text(encoding="utf-8")))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report["pass_count"] != report["case_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
