#!/usr/bin/env python3
"""Measure model-only fallback after exact-offer search failed; one-shot receipts.

A model page price is never a price for the original exact offerId.
"""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.analyze_tavily_20_offers import CORPUS, RECEIPTS, ROOT, evaluate, evaluate_case

FALLBACK = ROOT / "benchmarks/results/tavily_allegro_20_model_fallback_20261103.jsonl"
OUTPUT = ROOT / "benchmarks/results/tavily_allegro_20_adaptive_analysis_20261103.json"


def assess(corpus, original, fallback):
    initial = evaluate(corpus, original)
    case_map = {case["case_id"]:case for case in corpus["cases"]}
    base = {case["case_id"]:case for case in initial["cases"]}
    misses = {case_id for case_id,case in base.items()
              if not case["exact_offer_id_in_official_url"]}
    attempted = {r["case_id"] for r in fallback}
    if len(attempted) != len(fallback) or not attempted <= misses:
        raise ValueError("Fallback only allowed on distinct original misses")
    results = [evaluate_case(case_map[r["case_id"]],r) for r in fallback]
    ok = [r for r in results if r["tavily_status"]=="OK"]
    rate_limited = [r for r in results if r["tavily_http_status"]==429]
    new_exact = [r for r in results if r["exact_offer_id_in_official_url"]]
    model_hits = [r for r in results if r["official_brand_model_matches"]]
    covered = set()
    for result in initial["cases"]:
        if result["official_brand_model_matches"]:
            covered.add(result["case_id"])
    covered.update(r["case_id"] for r in model_hits)
    model_prices = [{
        "case_id":r["case_id"],
        "model_group_price_claims":r["product_group_price_claims"],
        "explicit_warning":"No exact offer ID in result URL; not a price for the target listing.",
    } for r in results if r["product_group_price_claims"]]
    return {
        "benchmark":"TAVILY_ADAPTIVE_MODEL_ONLY_2026-11-03",
        "summary":{
            "initial_case_count":len(corpus["cases"]),
            "initial_exact_offer_id_url_count":
                initial["summary"]["exact_offer_id_in_official_result_url"],
            "fallback_needed":len(misses),
            "fallback_attempted":len(fallback),
            "fallback_http_200":len(ok),
            "fallback_http_429":len(rate_limited),
            "fallback_not_attempted_due_rate_limit":len(misses-attempted),
            "new_exact_offer_id_url_from_fallback":len(new_exact),
            "combined_exact_offer_id_urls":
                initial["summary"]["exact_offer_id_in_official_result_url"] + len(new_exact),
            "fallback_cases_with_brand_and_model_title_match":len(model_hits),
            "combined_case_coverage_brand_and_model_titles":len(covered),
            "fallback_cases_with_product_group_price_only":len(model_prices),
            "total_live_search_requests_initial_plus_fallback":
                len(original)+len(fallback),
            "seller_price_verified_count":0,
            "index_refresh_time_verified_count":0,
            "decision":"FALLBACK_ONLY_FOR_PRODUCT_DISCOVERY_NEVER_EXACT_OFFER_PRICE",
        },
        "model_level_unverified_price_claims":model_prices,
        "fallback_cases":results,
    }


def main():
    corpus=json.loads(CORPUS.read_text(encoding="utf8"))
    original=[json.loads(x) for x in RECEIPTS.read_text(encoding="utf8").splitlines()]
    fallback=[json.loads(x) for x in FALLBACK.read_text(encoding="utf8").splitlines()]
    out=assess(corpus,original,fallback)
    OUTPUT.write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print(json.dumps(out["summary"],indent=2,ensure_ascii=False))
    print("MODEL_GROUP_PRICES")
    for row in out["model_level_unverified_price_claims"]:
        print(row["case_id"],row["model_group_price_claims"])


if __name__=="__main__":
    main()
