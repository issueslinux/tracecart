#!/usr/bin/env python3
"""Offline, reproducible 20-case Tavily offer-ID benchmark evaluation.

All counts require official Allegro result URLs, model/brand identity checked
against title. Neither an HTTP 200 nor a result snippet verifies seller price.
"""
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import re
import statistics
import sys
import unicodedata
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tavily_allegro_index import _identifiable_url, _snippet_price

CORPUS = ROOT / "benchmarks/tavily_allegro_20_cases_20261103.json"
RECEIPTS = ROOT / "benchmarks/results/tavily_allegro_20_results_20261103.jsonl"
SUMMARY = ROOT / "benchmarks/results/tavily_allegro_20_analysis_20261103.json"


def compact(text):
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized.casefold() if ch.isascii() and ch.isalnum())


def same_product_in_title(case, title):
    txt = compact(title)
    return bool(txt and compact(case["brand"]) in txt and compact(case["model"]) in txt)


def explicit_condition(row):
    """Only explicit status in the single result's title / early excerpt."""
    title = str(row.get("title") or "")
    excerpt = str(row.get("content") or "")[:230]
    text = title + " " + excerpt
    if re.search(r"\b(używany|uzywany|used|stan\s*:\s*używany)\b", text, re.I):
        return "USED"
    if re.search(r"\b(powystawowy|outlet\s*demo)\b", text, re.I):
        return "OPEN_BOX"
    if re.search(r"\bstan\s*:\s*nowy\b", text, re.I):
        return "NEW"
    return "UNKNOWN"


def _official_result(row):
    url = row.get("url") or ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return (parts.scheme=="https" and parts.hostname in ("allegro.pl","www.allegro.pl")
            and not parts.username and not parts.password)


def evaluate_case(case, receipt):
    offid = case["offer_id"]
    result = {
        "case_id":case["case_id"],"category":case["category"],
        "expected_brand":case["brand"],"expected_model":case["model"],
        "offer_id":offid,
        "case_source_url":case["url"],
        "case_reference_index_price":case.get("reference_index_price"),
        "separate_index_inactive_notice":bool(case.get("reference_index_page_inactive_notice")),
        "separate_index_note":case.get("reference_index_note"),
        "reference_is_live_seller":False,
        "tavily_status": receipt.get("status") if receipt else "NOT_TESTED",
        "tavily_http_status": receipt.get("http_status") if receipt else None,
        "tavily_elapsed_s": receipt.get("elapsed_s") if receipt else None,
        "total_results":len(receipt.get("results",[])) if receipt else 0,
        "official_results":0,
        "official_brand_model_matches":0,
        "exact_offer_id_in_official_url":False,
        "exact_url_rank":None,
        "exact_url_price_claim":None,
        "exact_url_price_matches_other_index":None,
        "exact_url_condition_claim":"UNKNOWN",
        "explicit_offer_id_in_official_snippet":False,
        "different_allegro_offer_ids":[],
        "product_group_price_claims":[],
        "external_urls_containing_offer_id":0,
        "published_date_present":0,
        "verified_live_seller_price":False,
        "verified_live_stock":False,
    }
    for i,row in enumerate((receipt or {}).get("results",[]),1):
        if not isinstance(row,dict):
            continue
        url = str(row.get("url") or "")
        text = str(row.get("content") or "")
        if not _official_result(row):
            if offid in url:
                result["external_urls_containing_offer_id"]+=1
            continue
        result["official_results"]+=1
        if row.get("published_date"):
            # Date of publication is not necessarily search index crawl date.
            result["published_date_present"]+=1
        title = str(row.get("title") or "")
        is_same=same_product_in_title(case,title)
        if not is_same:
            continue
        result["official_brand_model_matches"]+=1
        parsed=_identifiable_url(url)
        if parsed is None:
            continue
        _, url_id = parsed
        if re.search(r"\bNumer\s+oferty\s*:\s*"+re.escape(offid)+r"\b",text,re.I):
            result["explicit_offer_id_in_official_snippet"]=True
        price = _snippet_price(text)
        if url_id==offid:
            if not result["exact_offer_id_in_official_url"]:
                result["exact_offer_id_in_official_url"]=True
                result["exact_url_rank"]=i
                result["exact_url_price_claim"]=price
                result["exact_url_condition_claim"]=explicit_condition(row)
            elif price and result["exact_url_price_claim"] is None:
                result["exact_url_price_claim"]=price
        elif url_id:
            result["different_allegro_offer_ids"].append(url_id)
        elif price:
            result["product_group_price_claims"].append(price)
    if result["exact_url_price_claim"] and result["case_reference_index_price"]:
        result["exact_url_price_matches_other_index"]=(
            Decimal(result["exact_url_price_claim"]) ==
            Decimal(result["case_reference_index_price"]))
    result["different_allegro_offer_ids"]=sorted(set(result["different_allegro_offer_ids"]))
    result["product_group_price_claims"]=sorted(set(result["product_group_price_claims"]),
                                                key=Decimal)
    if result["exact_offer_id_in_official_url"]:
        result["assessment"]=("EXACT_ID_URL_INDEX_PRICE_CLAIM_UNVERIFIED" if
                              result["exact_url_price_claim"] else
                              "EXACT_ID_URL_NO_PRICE")
    elif result["explicit_offer_id_in_official_snippet"]:
        result["assessment"]="EXACT_ID_ONLY_IN_SNIPPET_NO_PRICE_LINKAGE"
    elif result["product_group_price_claims"]:
        result["assessment"]="PRODUCT_GROUP_PRICE_NOT_EXACT_OFFER"
    elif result["official_brand_model_matches"]:
        result["assessment"]="MODEL_MATCH_ONLY"
    else:
        result["assessment"]="NO_OFFICIAL_MODEL_MATCH"
    return result


def evaluate(corpus,receipts):
    cases = corpus["cases"]
    if len(cases)!=20 or len({x["offer_id"] for x in cases})!=20:
        raise ValueError("Expected 20 distinct real offer IDs in corpus")
    by_id = {x["case_id"]:x for x in receipts}
    if len(by_id) != len(receipts):
        raise ValueError("Duplicate live provider requests for the same case")
    evaluated=[evaluate_case(c,by_id.get(c["case_id"])) for c in cases]
    n=len(cases)
    ok=[r for r in evaluated if r["tavily_status"]=="OK"]
    latency=[r["tavily_elapsed_s"] for r in evaluated
             if r["tavily_elapsed_s"] is not None]
    summaries={
        "total_seeded_real_offer_urls":n,
        "categories":len(set(r["category"] for r in evaluated)),
        "api_requests_made":len(receipts),
        "api_http_200":len(ok),
        "cases_with_any_official_brand_model_match":sum(bool(r["official_brand_model_matches"]) for r in evaluated),
        "exact_offer_id_in_official_result_url":sum(bool(r["exact_offer_id_in_official_url"]) for r in evaluated),
        "exact_id_url_with_index_price_claim":sum(bool(r["exact_offer_id_in_official_url"] and r["exact_url_price_claim"]) for r in evaluated),
        "exact_offer_id_in_official_snippet_without_url":sum(bool(r["explicit_offer_id_in_official_snippet"] and not r["exact_offer_id_in_official_url"]) for r in evaluated),
        "model_group_price_without_exact_offer_id":sum(bool(r["product_group_price_claims"] and not r["exact_offer_id_in_official_url"]) for r in evaluated),
        "cases_with_different_allegro_offer_ids":sum(bool(r["different_allegro_offer_ids"]) for r in evaluated),
        "cases_with_external_id_mention_urls":sum(bool(r["external_urls_containing_offer_id"]) for r in evaluated),
        "indexed_price_agree_with_separate_web_index":sum(r["exact_url_price_matches_other_index"] is True for r in evaluated),
        "indexed_price_disagree_with_separate_web_index":sum(r["exact_url_price_matches_other_index"] is False for r in evaluated),
        "indexed_price_crosscheck_possible":sum(r["exact_url_price_matches_other_index"] is not None for r in evaluated),
        "cases_with_independent_index_inactive_notice":sum(bool(r["separate_index_inactive_notice"]) for r in evaluated),
        "published_date_field_results":sum(r["published_date_present"] for r in evaluated),
        "median_api_latency_s":round(statistics.median(latency),2) if latency else None,
        "status_counts":dict(Counter(r["assessment"] for r in evaluated)),
        "seller_price_verified_count":0,
        "stock_verified_count":0,
        "index_crawl_timestamp_verified_count":0,
        "confidence":"Research-only. One fixed query per case. 20 index-sourced case URLs; no live seller truth; index prices can be stale or reflect different offers."
    }
    return {"benchmark":"TAVILY_KEYLESS_ALLEGRO_20_INDEPENDENT_SEEDS_2026-11-03",
            "method":"ONE_QUERY_PER_CASE_KEYLESS_BASIC_DOMAIN_FILTER",
            "summary":summaries,"cases":evaluated}


def main():
    corpus=json.loads(CORPUS.read_text(encoding="utf8"))
    receipts=[json.loads(x) for x in RECEIPTS.read_text(encoding="utf8").splitlines() if x]
    analysis=evaluate(corpus,receipts)
    SUMMARY.write_text(json.dumps(analysis,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print(json.dumps(analysis["summary"],indent=2,ensure_ascii=False))
    print("CASES")
    for r in analysis["cases"]:
        print("{} {:20} {:16} price={} model_hits={} alt={} external_id={}".format(
            r["case_id"],r["assessment"],r["offer_id"],
            r["exact_url_price_claim"],r["official_brand_model_matches"],
            len(r["different_allegro_offer_ids"]),r["external_urls_containing_offer_id"]))


if __name__=="__main__":
    main()
