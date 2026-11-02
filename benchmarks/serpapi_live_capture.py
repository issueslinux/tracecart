"""Explicit budgeted SerpApi Google Shopping research with incremental checkpoints.

Intended for an operator with an independently configured SerpApi account.
No source scraping or background crawler. API keys are never stored.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from time import sleep

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benchmarks.shopping_search_eval import load_dataset
from search_first import search_serpapi_shopping

MAX_PRODUCTS = 20
MAX_PROVIDER_CALLS = 44
STOP_FAILURES = 2


def run(samples, output, limit=20, allow_credits=False, max_calls=44,
        fetcher=search_serpapi_shopping, retry_failed=False):
    if not allow_credits:
        raise ValueError("Explicit --allow-credits required before billable queries")
    if type(limit) is not int or not 1 <= limit <= MAX_PRODUCTS:
        raise ValueError("Product limit must be 1..20")
    if type(max_calls) is not int or not 2 <= max_calls <= MAX_PROVIDER_CALLS:
        raise ValueError("Request cap must be 2..40")
    key = os.environ.get("SERPAPI_API_KEY","")
    if not key:
        raise ValueError("SERPAPI_API_KEY is not set")
    if output.exists():
        result = json.loads(output.read_text(encoding="utf-8"))
        if result.get("dataset_id") != samples["dataset_id"]:
            raise ValueError("Checkpoint dataset id mismatch")
        if not isinstance(result.get("observations"),dict):
            raise ValueError("Unexpected checkpoint format")
    else:
        result = {
            "dataset_id":samples["dataset_id"],
            "provider":"SERPAPI_GOOGLE_SHOPPING",
            "method":"EXPLICIT_RESEARCH_NO_CHECKOUT_VERIFICATION",
            "started_at":datetime.now(timezone.utc).isoformat(),
            "observations":{},
            "total_provider_calls":0,
        }
    consumed=result.get("total_provider_calls",
                        sum(entry.get("provider_calls",0)
                            for entry in result["observations"].values()))
    if consumed > max_calls:
        raise ValueError("Previous samples exceed requested call limit")
    consecutive_errors = 0
    for item in samples["products"][:limit]:
        previous=result["observations"].get(item["id"])
        if previous and not (retry_failed and
                             previous["status"].startswith("FAILED_")):
            continue
        if consumed + 2 > max_calls:
            print("STOP_CAP_NEXT_TWO_CALLS", consumed, flush=True)
            break
        response = fetcher(item, api_key=key)
        used=response["provider_calls"]
        consumed+=used
        if used > 2:
            raise ValueError("Provider exceeded per-product call bound")
        # Do not preserve user API credentials in any serialized results.
        record = {
            "id":item["id"],
            "title":item["title"],
            "queried_at":response["queried_at"],
            "status":response["status"],
            "provider_calls":used,
            "index_offer_count":len(response["indexed_offers"]),
            "indexed_offers":response["indexed_offers"],
            "search_result_groups":response["search_result_groups"],
            "marketplace_hosts_seen":response["marketplace_hosts_seen"],
            "indexed_marketplace_names_seen":response.get(
                "indexed_marketplace_names_seen",[]),
            "lowest_indexed_observation":response["lowest_indexed_observation"],
            "source_qualified_seller_offers":0,
            "price_accuracy_independently_checked":False,
        }
        if previous:
            result.setdefault("recovered_failed_attempts", []).append({
                "id":item["id"], "original_failure_status":previous["status"],
                "original_provider_calls":previous["provider_calls"]})
        result["observations"][item["id"]]=record
        result["total_provider_calls"]=consumed
        result["updated_at"]=datetime.now(timezone.utc).isoformat()
        result["completed_cases"]=len(result["observations"])
        content=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
        if key in content:
            raise ValueError("Unexpected API key in provider response; will not persist")
        # Preserve only sensitive-free research metadata; restrict local file.
        output.write_text(content,encoding="utf-8")
        os.chmod(str(output),0o600)
        print("CASE",item["id"],"STATUS",record["status"],
              "CALLS",used,"OFFERS",record["index_offer_count"],
              "MARKETS",",".join(record["marketplace_hosts_seen"]),
              "TOTAL_CALLS",consumed,flush=True)
        if response["status"].startswith("FAILED_"):
            consecutive_errors+=1
            if consecutive_errors>=STOP_FAILURES:
                print("STOP_REPEATED_API_FAILURES",flush=True)
                break
        else:
            consecutive_errors=0
        sleep(0.35)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset",default=str(
        Path(__file__).with_name("shopping_20_products.json")))
    parser.add_argument("--output",required=True)
    parser.add_argument("--limit",type=int,default=20)
    parser.add_argument("--max-calls",type=int,default=44)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--allow-credits",action="store_true")
    args=parser.parse_args()
    os.umask(0o077)
    output=Path(args.output)
    samples=load_dataset(args.dataset)
    if output.exists() and (output.stat().st_mode & 0o077):
        raise ValueError("Existing output file is not private (mode 600 required)")
    result=run(samples,output,args.limit,args.allow_credits,args.max_calls,
               retry_failed=args.retry_failed)
    print("FINISHED_SNAPSHOT",len(result["observations"]),"/20",
          "CALLS",result["total_provider_calls"],flush=True)


if __name__=="__main__":
    main()
