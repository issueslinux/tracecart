#!/usr/bin/env python3
"""20-case bounded live Tavily keyless benchmark; one search per real Allegro offer.

Permission model: no API key, no paid service, no merchant HTTP requests.
Output: per-case response receipts, no credentials, prompt or assistant predictions.
"""
import json
from pathlib import Path
import sys
import time
import requests

ROOT = Path(__file__).resolve().parent
CASES = ROOT / "tavily_allegro_20_cases_20261103.json"
DEST = ROOT / "results" / "tavily_allegro_20_results_20261103.jsonl"
SEARCH_ENDPOINT = "https://api.tavily.com/search"
HEADERS = {
    "Content-Type": "application/json",
    "X-Tavily-Access-Mode": "keyless",
    "X-Client-Source": "tracecart-20-offer-keyless-accuracy-benchmark",
}
MAX_REQUESTS = 20
TIMEOUT_S = 28
MAX_RESULTS = 8


def plan_query(case):
    # Fix the test procedure BEFORE observing results.
    return '"{}" {} {} allegro.pl'.format(
        case["offer_id"], case["brand"], case["model"])


def run():
    corpus = json.loads(CASES.read_text(encoding="utf8"))["cases"]
    assert len(corpus) == MAX_REQUESTS
    assert len({c["offer_id"] for c in corpus}) == MAX_REQUESTS
    DEST.parent.mkdir(parents=True, exist_ok=True)
    already = []
    if DEST.exists():
        already = [json.loads(s) for s in DEST.read_text(encoding="utf8").splitlines() if s]
    if already:
        print("existing_receipts", len(already), "NO_DUPLICATE_REMOTE_REQUESTS", flush=True)
    if any(r.get("http_status") in (401,402,403,429) for r in already):
        print("STOP_PRIOR_ACCESS_ERROR_NO_RETRY", flush=True)
        return
    seen = {r["case_id"] for r in already}
    stopped = False
    session = requests.Session()
    for i, case in enumerate(corpus,1):
        if case["case_id"] in seen:
            continue
        if stopped:
            break
        query = plan_query(case)
        payload = {
            "query": query,
            "include_domains": ["allegro.pl"],
            "search_depth": "basic",
            "max_results": MAX_RESULTS,
            "include_answer": False,
            "include_published_date": True,
        }
        t0 = time.monotonic()
        receipt = {
            "case_id": case["case_id"],
            "offer_id": case["offer_id"],
            "query": query,
            "requested_results_cap": MAX_RESULTS,
            "search_mode": "TAVILY_KEYLESS_BASIC_DOMAIN_FILTER",
            "status": "NETWORK_ERROR",
            "results": [],
        }
        try:
            response = session.post(SEARCH_ENDPOINT, headers=HEADERS,
                                    json=payload, timeout=TIMEOUT_S)
            receipt["http_status"] = response.status_code
            receipt["elapsed_s"] = round(time.monotonic()-t0,2)
            if response.status_code == 200:
                data = response.json()
                receipt["status"] = "OK"
                receipt["response_time_s"] = data.get("response_time")
                receipt["request_id"] = data.get("request_id")
                receipt["results"] = [
                    {k: item.get(k) for k in (
                        "url","title","content","published_date","score")}
                    for item in data.get("results", [])[:MAX_RESULTS]
                    if isinstance(item,dict)
                ]
            else:
                receipt["status"] = "PROVIDER_HTTP_ERROR"
                try:
                    obj = response.json()
                    receipt["error_type"] = str(obj.get("detail",obj.get("error","HTTP")))[:150]
                except ValueError:
                    receipt["error_type"] = "BAD_API_RESPONSE"
                if response.status_code in (401, 402, 403, 429):
                    stopped = True
        except (requests.RequestException, ValueError) as exc:
            receipt["elapsed_s"] = round(time.monotonic()-t0,2)
            receipt["error_type"] = type(exc).__name__
        with DEST.open("a",encoding="utf8") as fp:
            fp.write(json.dumps(receipt,ensure_ascii=False)+"\n")
        print(json.dumps({
            "case":i, "id":case["offer_id"],"status":receipt["status"],
            "http":receipt.get("http_status"),
            "results":len(receipt["results"]),
            "time_s":receipt["elapsed_s"],
        },ensure_ascii=False),flush=True)
        if stopped:
            print("STOPPED_PROVIDER_ACCESS_POLICY", flush=True)
            break
        time.sleep(0.8)
    print("done",str(DEST), flush=True)


if __name__ == "__main__":
    run()
