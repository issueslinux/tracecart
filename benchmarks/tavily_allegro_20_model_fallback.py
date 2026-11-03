#!/usr/bin/env python3
"""Deterministic additional 15 keyless Tavily queries where exact ID lookup failed.

This is ADAPTIVE fallback analysis for *the same* 20-case corpus, not a new
independent 15-item test. No retries, no authenticated API, no merchant HTTP.
"""
import json
from pathlib import Path
import sys
import time
import requests
from analyze_tavily_20_offers import CORPUS, RECEIPTS, evaluate

ROOT=Path(__file__).resolve().parent
DEST=ROOT/"results/tavily_allegro_20_model_fallback_20261103.jsonl"
URL="https://api.tavily.com/search"
HEADERS={"Content-Type":"application/json","X-Tavily-Access-Mode":"keyless",
         "X-Client-Source":"tracecart-20case-adaptive-fallback-eval"}
MAX_FALLBACK=15


def main():
    corpus=json.loads(CORPUS.read_text(encoding="utf8"))
    prior=[json.loads(x) for x in RECEIPTS.read_text(encoding="utf8").splitlines()]
    report=evaluate(corpus,prior)
    missed={x["case_id"] for x in report["cases"]
            if not x["exact_offer_id_in_official_url"]}
    cases=[c for c in corpus["cases"] if c["case_id"] in missed]
    assert len(cases)==MAX_FALLBACK, (len(cases),"Unexpected primary search performance")
    already=[json.loads(x) for x in DEST.read_text(encoding="utf8").splitlines()] if DEST.exists() else []
    completed={r["case_id"] for r in already}
    if completed:
        print("existing_no_retries",len(completed),flush=True)
    if any(r.get("http_status") in (401,402,403,429) for r in already):
        print("STOP_PRIOR_ACCESS_ERROR_NO_RETRY",flush=True)
        return
    with requests.Session() as client:
        for i,c in enumerate(cases,1):
            if c["case_id"] in completed:
                continue
            query="{} {} Allegro cena".format(c["brand"],c["model"])
            payload={"query":query,"search_depth":"basic","max_results":8,
                     "include_domains":["allegro.pl"],"include_answer":False,
                     "include_published_date":True}
            row={"case_id":c["case_id"],"offer_id":c["offer_id"],"query":query,
                 "search_mode":"MODEL_ONLY_FALLBACK_KEYLESS_BASIC",
                 "status":"NETWORK_ERROR","results":[]}
            start=time.monotonic()
            try:
                r=client.post(URL,json=payload,headers=HEADERS,timeout=28)
                row["http_status"]=r.status_code
                row["elapsed_s"]=round(time.monotonic()-start,2)
                if r.status_code==200:
                    data=r.json()
                    row["status"]="OK"
                    row["response_time_s"]=data.get("response_time")
                    row["results"]=[{k:x.get(k) for k in ("url","title","content",
                                                          "published_date","score")}
                                    for x in data.get("results",[])[:8] if isinstance(x,dict)]
                else:
                    row["status"]="PROVIDER_HTTP_ERROR"
                    row["error_type"]="HTTP_{}".format(r.status_code)
            except requests.RequestException as e:
                row["elapsed_s"]=round(time.monotonic()-start,2)
                row["error_type"]=type(e).__name__
            with DEST.open("a",encoding="utf8") as f:
                f.write(json.dumps(row,ensure_ascii=False)+"\n")
            print(json.dumps({"case":i,"id":c["offer_id"],
                              "http":row.get("http_status"),
                              "results":len(row["results"]),
                              "seconds":row["elapsed_s"]}),flush=True)
            if row.get("http_status") in (401,402,403,429):
                print("STOP_ACCESS_ERROR",flush=True)
                break
            time.sleep(.8)
    print("done",DEST,flush=True)


if __name__=="__main__":
    main()
