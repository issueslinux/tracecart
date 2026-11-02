#!/usr/bin/env python3
"""Opt-in 20-product search-provider benchmark. Never reports fabricated hits.

Run with no credentials for a capability/credential audit; SERPAPI mode costs
search credits; DataForSEO modes explicitly submit paid async tasks or collect
past tasks. A compare report is valid only for actual completed provider data.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from search_first import search_serpapi_shopping
from dataforseo_shopping import queue_dataforseo_products, collect_dataforseo_products


def load_dataset(path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw.get("products") if isinstance(raw, dict) else None
    if not isinstance(items, list) or len(items) != 20:
        raise ValueError("Benchmark requires 20 named product hypotheses")
    ids = [x.get("id") for x in items if isinstance(x, dict)]
    if len(set(ids)) != 20 or any(not isinstance(i, str) or not i for i in ids):
        raise ValueError("Product IDs must be distinct")
    return raw


def report_serpapi(products, n, run_paid=False):
    key = os.environ.get("SERPAPI_API_KEY", "")
    if not key:
        return {"provider": "SERPAPI_GOOGLE_SHOPPING",
                "status": "NOT_EXECUTED_NO_CREDENTIALS",
                "products_executed": 0, "results": [],
                "calls_consumed": 0,
                "note": "No SerpApi key; no live coverage or accuracy metric exists."}
    if not run_paid:
        raise ValueError("SERPAPI queries spend credits; add --allow-paid")
    results = []
    for item in products[:n]:
        capture = search_serpapi_shopping(item, api_key=key)
        results.append({
            "sample_id": item["id"],
            "status": capture["status"],
            "calls_consumed": capture["provider_calls"],
            "marketplace_hosts_seen": capture["marketplace_hosts_seen"],
            "indexed_store_count": len(capture["indexed_offers"]),
            "indexed_offers": capture["indexed_offers"],
            "lowest_indexed_observation": capture["lowest_indexed_observation"],
            "queried_at": capture["queried_at"],
            "accuracy_independently_checked": False,
        })
    return {
        "provider": "SERPAPI_GOOGLE_SHOPPING",
        "status": "COMPLETED_WITH_LIMITED_COVERAGE" if n < 20 else "COMPLETED_20_QUERIES",
        "products_executed": len(results),
        "results": results,
        "calls_consumed": sum(x["calls_consumed"] for x in results),
        "marketplace_product_count": sum(bool(x["marketplace_hosts_seen"]) for x in results),
        "any_priced_product_count": sum(x["indexed_store_count"] > 0 for x in results),
        "price_accuracy_verified_count": 0,
        "note": ("Prices come from Google Shopping's index and have NOT been crosschecked "
                 "with live retailer checkout pages."),
    }


def report_dataforseo_enqueue(products, n, run_paid=False):
    login = os.environ.get("DATAFORSEO_LOGIN", "")
    password = os.environ.get("DATAFORSEO_PASSWORD", "")
    if not login or not password:
        return {"provider": "DATAFORSEO_GOOGLE_SHOPPING_PRODUCTS",
                "status": "NOT_EXECUTED_NO_CREDENTIALS",
                "products_executed": 0, "task_ids": [],
                "note": "No DataForSEO credentials; no live coverage benchmark exists."}
    if not run_paid:
        raise ValueError("DataForSEO tasks incur fees; add --allow-paid")
    return queue_dataforseo_products(products[:n], (login, password), allow_paid=True)


def report_dataforseo_collect(queue_path):
    login = os.environ.get("DATAFORSEO_LOGIN", "")
    password = os.environ.get("DATAFORSEO_PASSWORD", "")
    if not login or not password:
        return {"provider": "DATAFORSEO_GOOGLE_SHOPPING_PRODUCTS",
                "status": "NOT_EXECUTED_NO_CREDENTIALS", "results": []}
    queued = json.loads(Path(queue_path).read_text(encoding="utf-8"))
    return collect_dataforseo_products(queued, (login, password))


def comparison_report(serpapi, dfs):
    a = {x["sample_id"]: x for x in serpapi.get("results", [])}
    b = {x["sample_id"]: x for x in dfs.get("results", [])}
    keys = sorted(set(a) & set(b))
    rows = []
    for key in keys:
        x, y = a[key], b[key]
        is_complete = y.get("status") in ("INDEXED_OFFERS_AVAILABLE", "NO_PRICED_ITEMS")
        if not is_complete:
            rows.append({"id": key, "status": "WAITING_FOR_DATAFORSEO_RESULT"})
            continue
        markets_a = x.get("marketplace_hosts_seen", [])
        markets_b = y.get("marketplace_sellers", [])
        rows.append({
            "id": key,
            "status": "INDEXED_ONLY_COMPARISON_NOT_INDEPENDENT_PRICE_ACCURACY",
            "serpapi_indexed_store_count": x.get("indexed_store_count", 0),
            "dataforseo_indexed_offer_count": len(y.get("offers", [])),
            "serpapi_marketplace_hosts": markets_a,
            "dataforseo_marketplace_sellers": markets_b,
        })
    complete = [x for x in rows if x["status"].startswith("INDEXED_ONLY")]
    return {
        "status": ("COMPARABLE_INDEX_SAMPLES_AVAILABLE" if complete
                   else "NOT_COMPARABLE_NO_OVERLAPPING_COMPLETED_SAMPLES"),
        "products_with_both_provider_results": len(complete),
        "rows": rows,
        "independently_verified_price_accuracy": "NOT_MEASURED",
        "provider_coverage_not_market_completeness": True,
        "source_qualified_checkout_prices": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=str(Path(__file__).with_name(
        "shopping_20_products.json")))
    parser.add_argument("--mode", choices=("preview", "serpapi",
                                          "dataforseo-enqueue", "dataforseo-collect",
                                          "compare"), default="preview")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--queue", help="Existing DataForSEO queued task JSON")
    parser.add_argument("--serpapi-results", help="Existing SerpApi result JSON")
    parser.add_argument("--dataforseo-results", help="Existing collected DFS JSON")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not 1 <= args.limit <= 20:
        parser.error("--limit must be 1..20")
    raw = load_dataset(args.dataset)
    products = raw["products"]
    if args.mode == "preview":
        result = {
            "status": "PROTOCOL_ONLY_NO_PROVIDER_CALLS",
            "dataset_id": raw["dataset_id"],
            "sample_count": len(products),
            "creds_available": {
                "serpapi": bool(os.environ.get("SERPAPI_API_KEY")),
                "dataforseo": bool(os.environ.get("DATAFORSEO_LOGIN") and
                                   os.environ.get("DATAFORSEO_PASSWORD")),
            },
            "products_executed": 0,
            "live_offer_count": None,
            "independently_verified_price_accuracy": "NOT_MEASURED",
            "note": "Preview does not imply that 20 products were actually searched.",
        }
    elif args.mode == "serpapi":
        result = report_serpapi(products, args.limit, args.allow_paid)
    elif args.mode == "dataforseo-enqueue":
        result = report_dataforseo_enqueue(products, args.limit, args.allow_paid)
    elif args.mode == "dataforseo-collect":
        if not args.queue:
            parser.error("--queue required")
        result = report_dataforseo_collect(args.queue)
    else:
        if not args.serpapi_results or not args.dataforseo_results:
            parser.error("--serpapi-results and --dataforseo-results required")
        result = comparison_report(
            json.loads(Path(args.serpapi_results).read_text(encoding="utf-8")),
            json.loads(Path(args.dataforseo_results).read_text(encoding="utf-8")))
    result["captured_at"] = datetime.now(timezone.utc).isoformat()
    result["dataset_id"] = raw["dataset_id"]
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2)
                                 + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": args.output,
                      "products_executed": result.get("products_executed", 0)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
