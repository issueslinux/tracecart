"""Bounded cross-domain source URL discovery, NEVER verified evidence.

Requires a deliberately enabled Brave Web Search subscription and is charged
at most six provider queries per job. Durable job receipts prevent retry fees.
Every returned URL is only a LEAD until a separate robot-checked fetch matches
its own product header; search-result snippets are never source facts.
"""
import os
import re
from urllib.parse import urlencode, urlsplit

from generic_source_research import product_identity
from product_intake import validate_product_url

MAX_QUERIES=6
MAX_RESULTS=8
MAX_LEADS_PER_MODEL=4
API_ROOT="https://api.search.brave.com"

_REJECT_HOSTS={
    "www.google.com","google.com","www.bing.com","bing.com",
    "search.yahoo.com","www.amazon.com","www.amazon.pl",
    "www.allegro.pl","allegro.pl","api.search.brave.com",
    "www.youtube.com","youtube.com",
}

def _identity_key(title):
    identity=product_identity(title)
    return ((identity["brand"],identity["model"]) if identity else None)

def query_plan(offers,limit=MAX_QUERIES):
    """Diverse models, maker documentation + independent review intents."""
    if not isinstance(limit,int) or not 1<=limit<=MAX_QUERIES:
        raise ValueError("Invalid discovery budget")
    candidates=[]
    seen=set()
    for offer in offers:
        identity=_identity_key(offer.get("title",""))
        if identity is None or identity in seen:
            continue
        seen.add(identity)
        candidates.append(identity)
    plans=[]
    for brand,model in candidates:
        for purpose,words in (
                ("SPECIFICATIONS","technical specifications manufacturer"),
                ("REVIEWS","independent review benchmark measured test")):
            if len(plans)>=limit:
                break
            plans.append({
                "identity":{"brand":brand,"model":model},
                "purpose":purpose,
                "query":(brand+" "+model+" "+words)[:160],
            })
        if len(plans)>=limit:
            break
    return plans

def _clean_result(row,identity,purpose):
    if not isinstance(row,dict):
        return None
    url=row.get("url")
    title=row.get("title")
    if not isinstance(url,str) or not isinstance(title,str):
        return None
    try:
        clean=validate_product_url(url)
        parsed=urlsplit(clean)
        if parsed.hostname in _REJECT_HOSTS or parsed.port not in (None,443):
            return None
        if parsed.path in ("","/") or len(parsed.path)>700:
            return None
    except (ValueError,TypeError):
        return None
    wanted={identity["brand"],identity["model"]}
    # The RESULT TITLE, not a snippet or Google tracking URL, must identify
    # the exact brand+model; this is only a candidate, never identity proof.
    tokens=set(re.findall(r"[a-z0-9]+",title.casefold()))
    if not wanted.issubset(tokens):
        return None
    return {
        "url":clean,
        "title":" ".join(title.split())[:180],
        "model_identity":identity,
        "intent":purpose,
        "origin":"PAID_SEARCH_INDEX_LEAD_NOT_EVIDENCE",
        "source_status":"UNVERIFIED_UNFETCHED",
    }

def search_source_urls(offers,request=None,key=None,enabled=None):
    """One bounded provider sweep; caller MUST store the receipt before reuse.

    No other service is used implicitly. Credentials are never returned or
    written into logs/research receipts, and provider failures do not invent
    search results.
    """
    if enabled is None:
        enabled=os.environ.get("TRACECART_SOURCE_SEARCH_ENABLED","0")=="1"
    if not enabled:
        return {"status":"SKIPPED_NOT_ENABLED","queries_used":0,
                "models_considered":0,"leads":[],"query_receipts":[]}
    if key is None:
        key=os.environ.get("BRAVE_API_KEY","")
    if not key:
        return {"status":"SKIPPED_NO_API_KEY","queries_used":0,
                "models_considered":0,"leads":[],"query_receipts":[]}
    queries=query_plan(offers)
    if not queries:
        return {"status":"SKIPPED_NO_UNAMBIGUOUS_MODEL","queries_used":0,
                "models_considered":0,"leads":[],"query_receipts":[]}
    if request is None:
        from cart_research import _get_json
        request=_get_json
    leads=[]
    seen=set()
    receipts=[]
    for spec in queries:
        query_url=API_ROOT+"/res/v1/web/search?"+urlencode({
            "q":spec["query"],"count":MAX_RESULTS,"country":"PL",
            "search_lang":"en",
        })
        try:
            response=request(query_url,"api.search.brave.com",
                {"X-Subscription-Token":key},timeout=12)
            results=(response.get("web") or {}).get("results",[])
            if not isinstance(results,list):
                raise ValueError("Invalid provider results")
            count=0
            for row in results[:MAX_RESULTS]:
                found=_clean_result(row,spec["identity"],spec["purpose"])
                if not found or found["url"] in seen:
                    continue
                key_id=(found["model_identity"]["brand"],
                        found["model_identity"]["model"])
                if sum((x["model_identity"]["brand"],
                        x["model_identity"]["model"])==key_id
                       for x in leads)>=MAX_LEADS_PER_MODEL:
                    break
                seen.add(found["url"])
                leads.append(found)
                count+=1
            state="OK"
        except (ValueError,TypeError,KeyError,OSError):
            count=0
            state="SOURCE_SEARCH_FAILED"
        receipts.append({
            "identity":spec["identity"],"purpose":spec["purpose"],
            "status":state,"lead_urls_added":count,
        })
    return {
        "status":"COMPLETE" if any(x["status"]=="OK" for x in receipts)
                 else "SOURCE_SEARCH_FAILED",
        "queries_used":len(queries),
        "models_considered":len({(q["identity"]["brand"],
                                  q["identity"]["model"]) for q in queries}),
        "leads":leads[:MAX_QUERIES*MAX_LEADS_PER_MODEL],
        "query_receipts":receipts,
    }

def attach_discovery_leads(offers,receipt):
    """Enrich ephemeral offer snapshots; NEVER alter immutable report."""
    index={}
    for row in receipt.get("leads",[])[:MAX_QUERIES*MAX_LEADS_PER_MODEL]:
        identity=row.get("model_identity") or {}
        key=(identity.get("brand"),identity.get("model"))
        if all(isinstance(x,str) and x for x in key):
            index.setdefault(key,[]).append(row)
    for offer in offers:
        key=_identity_key(offer.get("title",""))
        if not key:
            continue
        existing={r.get("url") for r in
                  offer.get("discovered_source_urls",[]) if isinstance(r,dict)}
        for row in index.get(key,[])[:MAX_LEADS_PER_MODEL]:
            if row["url"] in existing:
                continue
            offer.setdefault("discovered_source_urls",[]).append({
                "url":row["url"],"origin":row["origin"]})
            existing.add(row["url"])
    return offers
