#!/usr/bin/env python3
"""Small, one-shot Tavily keyless evidence benchmark for Allegro products.

Uses official public keyless header; never imports credentials, pays, or
claims that search snippets are current seller-confirmed prices.
"""
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

import requests

BASE = "https://api.tavily.com"
HEADERS = {"Content-Type": "application/json", "X-Tavily-Access-Mode": "keyless",
           "X-Client-Source": "tracecart-allegro-keyless-probe"}
OFFER_ID = "18457369262"
OFFER_URL = (
    "https://allegro.pl/oferta/kompresor-wysokocisnieniowy-18v-"
    "one-ryobi-rpi18-0-18457369262"
)
OFFICIAL_URL = (
    "https://pl.ryobitools.eu/elektronarzedzia/kompresory-i-pompy/"
    "rpi18/rpi18-0/"
)
QUERIES = [
    ("offer_id_exact", '"18457369262" allegro', {"exact_match": True}),
    ("model_allegro", "Ryobi RPI18-0 kompresor Allegro cena",
     {"include_domains": ["allegro.pl"]}),
    ("ean_allegro", '4892210230478 Ryobi Allegro',
     {"include_domains": ["allegro.pl"]}),
    ("model_merchant", "Ryobi RPI18-0 ceny kompresor Polska", {}),
]


def sanitized_result(result, marker):
    txt = " ".join([str(result.get("title","")),str(result.get("content",""))])
    url = str(result.get("url",""))
    path = urlsplit(url).path
    model_hit = bool(re.search(r"(?<![A-Z0-9])RPI18[- ]?0(?![A-Z0-9])",txt.upper()))
    return {
        "url": url,
        "title": str(result.get("title",""))[:300],
        "excerpt": str(result.get("content",""))[:900],
        "published_date": result.get("published_date"),
        "score": result.get("score"),
        "exact_offer_in_url": OFFER_ID in path,
        "exact_offer_in_text": OFFER_ID in txt,
        "model_in_text": model_hit,
        "contains_price_strings": bool(re.search(r"\d+[,.]\d{2}\s*zł",txt)),
        "seller_verified": False,
        "current_price_verified": False,
    }


def call(session, endpoint, label, payload):
    start = time.monotonic()
    try:
        response = session.post(BASE + endpoint, headers=HEADERS, json=payload,
                                timeout=30)
        receipt = {"variant": label, "endpoint": endpoint, "http_status": response.status_code,
                   "elapsed_s": round(time.monotonic()-start,2)}
        try:
            data = response.json()
        except ValueError:
            data = {}
            receipt["error"] = "non-json API response"
        if response.status_code != 200:
            err = data.get("error", data.get("detail", {}))
            receipt["error"] = str(err)[:650]
        else:
            receipt["request_id"] = data.get("request_id")
            receipt["response_time_s"] = data.get("response_time")
            if endpoint == "/search":
                receipt["results"] = [sanitized_result(r,label) for r in data.get("results",[])]
                receipt["result_count"] = len(receipt["results"])
                receipt["exact_offer_url_hits"] = sum(r["exact_offer_in_url"] for r in receipt["results"])
                receipt["model_text_hits"] = sum(r["model_in_text"] for r in receipt["results"])
            else:
                receipt["success_count"] = len(data.get("results",[]))
                receipt["failed_results"] = [
                    {"url":r.get("url"),"error":str(r.get("error",""))[:150]}
                    for r in data.get("failed_results",[])]
                receipt["results"] = []
                for r in data.get("results",[]):
                    raw = str(r.get("raw_content") or "")
                    receipt["results"].append({
                        "url": r.get("url"), "content_bytes":len(raw.encode("utf8")),
                        "offer_id_present":OFFER_ID in raw,
                        "model_present":"RPI18-0" in raw.upper(),
                        "quoted_19790": bool(re.search(r"197[,\.]90", raw)),
                        "snippet":raw[:900]})
        return receipt
    except requests.RequestException as e:
        return {"variant":label,"endpoint":endpoint,"error":type(e).__name__+":"+str(e)[:230],
                "elapsed_s":round(time.monotonic()-start,2)}


def main():
    records = []
    with requests.Session() as session:
        for label,query,extra in QUERIES:
            payload = {"query":query,"search_depth":"basic","max_results":7,
                       "include_answer":False, "include_published_date":True,
                       **extra}
            record=call(session,"/search",label,payload)
            records.append(record)
            print(json.dumps({"variant":label, "http_status":record.get("http_status"),
                  "result_count":record.get("result_count"),"exact_offer_url_hits":record.get("exact_offer_url_hits"),
                  "model_text_hits":record.get("model_text_hits"),"error":record.get("error")},ensure_ascii=False),flush=True)
            if record.get("http_status")==429:
                break
            time.sleep(0.6)
        record=call(session,"/extract","direct_extract_offer_and_official",
                    {"urls":[OFFER_URL,OFFICIAL_URL],"extract_depth":"basic","format":"markdown"})
        records.append(record)
        print(json.dumps({"variant":record["variant"],"http_status":record.get("http_status"),
                          "success_count":record.get("success_count"),
                          "failed_results":record.get("failed_results"),
                          "error":record.get("error")}, ensure_ascii=False),flush=True)
    out=os.environ.get("TRACECART_TAVILY_RECEIPTS",
                       str(Path(__file__).resolve().parent / "results" / "tavily_keyless_allegro_20261103.jsonl"))
    with open(out,"w",encoding="utf8") as fp:
        for r in records:
            fp.write(json.dumps(r,ensure_ascii=False)+"\n")
    print("receipt_path",out,flush=True)


if __name__=="__main__":
    main()
