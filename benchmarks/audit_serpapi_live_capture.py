"""Offline quality audit of stored, normalized, genuine SerpApi observations.

NO new SerpApi requests, no credentials. Conservative comparisons of
unverified indexed prices and explicit anomalies with full provenance.
"""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benchmarks.shopping_search_eval import load_dataset
from search_first import (_variant_assessment, _variant_conflict,
                          _flag_price_outliers, _rankable_indexed_offer)

AGGREGATORS = {"ceneo.pl", "e-katalog.pl"}
MAX_SAMPLES = 20
MAX_OFFERS = 20


def audit(capture, manifest):
    if (type(capture) is not dict or
            capture.get("dataset_id") != manifest["dataset_id"] or
            type(capture.get("observations")) is not dict):
        raise ValueError("Dataset/report mismatch")
    cases = []
    aggregate = Counter()
    for item in manifest["products"]:
        entry = capture["observations"].get(item["id"])
        if not isinstance(entry,dict):
            cases.append({"id":item["id"],"status":"NOT_EXECUTED",
                          "price_index_accuracy":"NOT_VERIFIED"})
            continue
        observed = deepcopy(entry["indexed_offers"])
        if len(observed)>MAX_OFFERS:
            raise ValueError("Bounded normalized offers required")
        aggregate["executed"]+=1
        aggregate["provider_calls"]+=entry["provider_calls"]
        if entry["status"].startswith("FAILED_"):
            aggregate["provider_errors"]+=1
        direct_allegro = any(o.get("merchant_host")=="allegro.pl" for o in observed)
        if direct_allegro:
            aggregate["with_allegro_direct_index_link"]+=1
        if observed:
            aggregate["with_priced_store_rows"]+=1
        if any("allegro" in str(name).lower()
               for name in entry.get("indexed_marketplace_names_seen",[])):
            aggregate["with_allegro_search_cards"]+=1
        aggregate["source_indexed_price_records"]+=len(observed)
        audit_rows=[]
        for row in observed:
            row["identity_status"] = _variant_assessment(item["title"],row["title"])
            if row["merchant_host"] in AGGREGATORS:
                row["identity_status"]="AGGREGATOR_INDEX_NOT_DIRECT_MERCHANT"
            audit_rows.append(row)
        # Exclude aggregators from constructing median peer pricing.
        price_rows=[r for r in audit_rows if
                    r["identity_status"]!="AGGREGATOR_INDEX_NOT_DIRECT_MERCHANT"]
        _flag_price_outliers(price_rows)
        verified_candidates=[r for r in price_rows if
            r["currency"]=="PLN" and _rankable_indexed_offer(r)]
        flagged=[{"seller":r["seller"],"price":r["current_price_indexed"],
                  "currency":r["currency"],"reason":r["index_price_anomaly"]}
                 for r in price_rows if
                 r["index_price_anomaly"]!="NONE_DETECTED"]
        blocked=[{"seller":r["seller"],"price":r["current_price_indexed"],
                  "reason":r["identity_status"]}
                 for r in audit_rows if _variant_conflict(r["identity_status"])
                 or r["identity_status"]=="AGGREGATOR_INDEX_NOT_DIRECT_MERCHANT"]
        aggregate["flagged_extreme_low_index_prices"]+=len(flagged)
        aggregate["source_or_variant_rejected"]+=len(blocked)
        valid_lowest=min(verified_candidates,
                        key=lambda r: Decimal(r["current_price_indexed"])) if verified_candidates else None
        cases.append({
            "id":item["id"],"title":item["title"],
            "provider_status":entry["status"],
            "queried_at":entry["queried_at"],
            "provider_calls":entry["provider_calls"],
            "indexed_priced_store_rows":len(observed),
            "index_allegro_link_seen":direct_allegro,
            "index_allegro_search_card_seen":any(
                "allegro" in str(v).lower()
                for v in entry.get("indexed_marketplace_names_seen",[])),
            "price_anomalies":flagged,
            "not_comparable_listings":blocked,
            "lowest_remaining_index_candidate":(
                {"seller":valid_lowest["seller"],
                 "price":valid_lowest["current_price_indexed"],
                 "currency":valid_lowest["currency"],
                 "merchant_url":valid_lowest["merchant_url"],
                 "condition":"INDEX_ONLY_NOT_GTIN_OR_CHECKOUT_VERIFIED"}
                if valid_lowest else None),
            "price_index_accuracy":"NOT_VERIFIED",
        })
    result={
        "dataset_id":manifest["dataset_id"],
        "origin":"ACTUAL_SERPAPI_GOOGLE_SHOPPING_API_NORMALIZED_SNAPSHOTS",
        "audit_created_at":datetime.now(timezone.utc).isoformat(),
        "sample_method":"PURPOSIVE_20_NOT_RANDOM_OR_COMPLETE_MARKET",
        "case_count":len(cases),
        "counts":dict(aggregate),
        "provider_calls_attempted_including_failed_retries":capture.get(
            "total_provider_calls",aggregate["provider_calls"]),
        "failed_retry_attempts":capture.get("recovered_failed_attempts",[]),
        "cases":cases,
        "no_direct_allegro_html_fetch":True,
        "price_accuracy_independently_confirmed_for_all":False,
        "marketplace_coverage_not_guaranteed":True,
        "source_page_verified_prices":0,
        "payment_authorized":False,
        "limitations":[
            "Google Shopping indexed prices may be stale or poisoned; SerpApi status page reported incidents on 2026-11-02.",
            "Model-token/capacity/bundle filters cannot prove exact SKU or GTIN match.",
            "Extreme low prices are flagged, not claimed false or removed from recorded evidence.",
            "Lowest remaining indexed candidate is not the globally cheapest purchase.",
            "Source access checks must be documented separately, not counted as API price accuracy."
        ]
    }
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",required=True)
    parser.add_argument("--dataset",default=str(Path(__file__).with_name(
        "shopping_20_products.json")))
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    raw=json.loads(Path(args.input).read_text(encoding="utf-8"))
    manifest=load_dataset(args.dataset)
    report=audit(raw,manifest)
    Path(args.output).write_text(json.dumps(
        report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("QUALITY_AUDIT",report["counts"])


if __name__=="__main__":
    main()
