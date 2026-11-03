"""Opt-in Tavily indexed Allegro leads. Never treats index snippets as seller evidence.

Deliberately separate from Search First's qualified Google Shopping and
marketplace_leads (which currently have different provenance contracts).
No network unless enabled=True; a fixed Tavily API host, three-query cap,
no paid subscription required (Tavily keyless has its own rate limits).
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import parse_qs, urlsplit

TAVILY_SEARCH = "https://api.tavily.com/search"
MAX_QUERIES = 3
MAX_RESULTS = 7
PRICE_MARKER = re.compile(r"\bza\s+([0-9]{1,6}[,.][0-9]{2})\s*(?:PLN|zł)\b", re.I)


def _search_plan(brand, model, offer_id=None, ean=None):
    if not isinstance(brand, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9\-]{1,34}", brand):
        raise ValueError("Expected an explicit brand name")
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-]{2,34}", model):
        raise ValueError("Expected an exact model identifier (e.g. RPI18-0)")
    if offer_id is not None and (not isinstance(offer_id, str)
                                 or not re.fullmatch(r"[0-9]{8,20}", offer_id)):
        raise ValueError("Invalid Allegro offer ID")
    if ean is not None and (not isinstance(ean, str)
                            or not re.fullmatch(r"[0-9]{8}|[0-9]{12,14}", ean)):
        raise ValueError("Invalid EAN candidate")
    rows = []
    if offer_id:
        rows.append({"purpose": "EXACT_OFFER_ID", "query": '"{}" allegro'.format(offer_id),
                     "exact_match": True})
    rows.append({"purpose": "EXACT_MODEL", "query": "{} {} Allegro cena".format(brand, model),
                 "include_domains": ["allegro.pl"]})
    if ean:
        rows.append({"purpose": "EAN_CANDIDATE", "query": "{} {} Allegro".format(ean, brand),
                     "include_domains": ["allegro.pl"]})
    return rows[:MAX_QUERIES]


def _match_model(title, model):
    escaped = re.escape(model).replace(r"\-", r"[-\s]?")
    return bool(re.search(r"(?<![A-Za-z0-9])" + escaped + r"(?![A-Za-z0-9])",
                          title, re.I))


def _identifiable_url(url):
    """Only Allegro's actual offer/product URLs, never third-party mirror URLs."""
    if not isinstance(url, str) or len(url) > 1500:
        return None
    try:
        p = urlsplit(url)
        if (p.scheme != "https" or p.hostname not in ("allegro.pl", "www.allegro.pl")
                or p.username or p.password or p.port not in (None,443)):
            return None
        segments = p.path.strip("/").split("/")
        if len(segments) < 2:
            return None
        category = segments[0]
        if category not in ("produkt","oferta"):
            return None
        offer_id = None
        if category == "oferta":
            m = re.search(r"-(\d{8,20})$", segments[1])
            if m:
                offer_id = m.group(1)
        elif category == "produkt":
            ids = parse_qs(p.query).get("offerId", [])
            if len(ids) == 1 and re.fullmatch(r"\d{8,20}", ids[0]):
                offer_id = ids[0]
        return category, offer_id
    except (ValueError,TypeError):
        return None


def _snippet_price(snippet):
    """Accept only a leading product card's 'za N.NNPLN' claim, not arbitrary numbers."""
    if not isinstance(snippet, str) or len(snippet) < 12:
        return None
    first = snippet[:230]
    m = PRICE_MARKER.search(first)
    if not m:
        return None
    try:
        n = Decimal(m.group(1).replace(",", "."))
    except InvalidOperation:
        return None
    if n <= 0 or n > 100000:
        return None
    return str(n.quantize(Decimal("0.01")))


def normalize_index_result(row, brand, model, target_offer_id=None):
    if not isinstance(row, dict):
        return None
    url = row.get("url")
    parsed = _identifiable_url(url)
    if parsed is None:
        return None
    title = row.get("title")
    if (not isinstance(title, str) or not _match_model(title,model)
            or not re.search(r"(?<![A-Za-z0-9])" + re.escape(brand) +
                             r"(?![A-Za-z0-9])", title, re.I)):
        return None
    snippet = row.get("content") or ""
    if not isinstance(snippet,str):
        snippet = ""
    category, offer_id = parsed
    price = _snippet_price(snippet) if category=="produkt" or offer_id else None
    condition = ("USED_CLAIM" if re.search(r"\bstan\s*:\s*używan", snippet, re.I)
                 else "NEW_CLAIM" if re.search(r"\bstan\s*:\s*nowy", snippet, re.I)
                 else "UNKNOWN")
    if target_offer_id and offer_id == target_offer_id:
        relation = "EXACT_OFFER_ID_IN_URL_NOT_LIVE_VERIFIED"
    elif target_offer_id and offer_id and offer_id != target_offer_id:
        relation = "DIFFERENT_OFFER_ID_NOT_COMPARABLE_AS_SAME_OFFER"
    elif not offer_id:
        relation = "PRODUCT_PAGE_WITHOUT_SINGLE_OFFER_ID"
    else:
        relation = "OFFER_ID_NOT_CROSSCHECKED"
    return {
        "url": url,
        "indexed_title": title[:180],
        "model_in_index_title": True,
        "offer_id_from_url": offer_id,
        "offer_relation": relation,
        "indexed_price_claim": price,
        "currency": "PLN" if price else None,
        "indexed_condition_claim": condition,
        "source_type": "TAVILY_SEARCH_INDEX_NOT_DIRECT_SELLER_PAGE",
        "indexed_last_updated_at": row.get("published_date") or None,
        "seller_verified": False,
        "source_page_retrieved": False,
        "stock_verified": False,
        "price_verified_by_seller": False,
        "payment_authorized": False,
    }


def _provider(payload, key=None):
    import requests
    headers = {"Content-Type":"application/json","X-Client-Source":"tracecart-index-lead"}
    if key:
        headers["Authorization"] = "Bearer "+key
    else:
        headers["X-Tavily-Access-Mode"] = "keyless"
    response = requests.post(TAVILY_SEARCH, json=payload, headers=headers,timeout=25)
    response.raise_for_status()
    return response.json()


def search_tavily_allegro(brand, model, offer_id=None, ean=None, enabled=False,
                         provider=None, api_key=None):
    """Discover possible index leads. Inactive by default to prevent API abuse.

    The returned fields can inform a research interface; they must NOT enter
    verified seller or checkout-price comparisons.
    """
    plan = _search_plan(brand, model, offer_id, ean)
    if not enabled:
        return {"status":"SKIPPED_NOT_ENABLED","queries_used":0,"leads":[],
                "source_qualified_seller_offers":0,"payment_authorized":False}
    provider = provider or _provider
    key = api_key  # Do not implicitly use a potentially billable environment key.
    receipts = []
    leads = []
    by_url = {}
    for row in plan:
        payload = {"query":row["query"],"search_depth":"basic",
                   "max_results":MAX_RESULTS,"include_answer":False,
                   "include_published_date":True}
        if "include_domains" in row:
            payload["include_domains"] = row["include_domains"]
        if row.get("exact_match"):
            payload["exact_match"] = True
        try:
            raw = provider(payload,key)
            if not isinstance(raw, dict) or not isinstance(raw.get("results"),list):
                raise ValueError("Invalid Tavily search results")
            hits = 0
            for item in raw["results"][:MAX_RESULTS]:
                lead = normalize_index_result(item,brand,model,offer_id)
                if lead is None:
                    continue
                existing = by_url.get(lead["url"])
                if existing is not None:
                    # The same indexed product URL can appear without a price
                    # in the ID search, and with an indexed price in model search.
                    # Never transfer that price to a *specific* offerId.
                    current = existing["indexed_price_claim"]
                    new_price = lead["indexed_price_claim"]
                    if new_price is not None and current is None and not existing.get("price_claim_conflict"):
                        existing["indexed_price_claim"] = new_price
                        existing["currency"] = "PLN"
                    elif current is not None and new_price is not None and current != new_price:
                        existing["price_claim_conflict"] = True
                        existing["indexed_price_claim"] = None
                        existing["currency"] = None
                    continue
                leads.append(lead)
                by_url[lead["url"]] = lead
                hits += 1
            receipts.append({"purpose":row["purpose"],"status":"OK","leads_added":hits})
        except Exception as e:
            # Do not emit credentials or URLs in exception bodies.
            receipts.append({"purpose":row["purpose"],"status":"SEARCH_FAILED",
                             "error_type":type(e).__name__})
            # No busy retry when rate-limited or blocked. Preserve partial data.
            break
    return {"status":"INDEX_LEADS_FOUND" if leads else
            "NO_INDEX_LEADS" if receipts and all(r["status"]=="OK" for r in receipts)
            else "SOURCE_FAILED",
            "queried_at":datetime.now(timezone.utc).isoformat(),
            "queries_used":len(receipts),
            "leads":leads,
            "query_receipts":receipts,
            "source_qualified_seller_offers":0,
            "payment_authorized":False,
            "limitations":[
                "Index price is an unverified historical product/offer claim.",
                "A product group URL without an offerId cannot verify the target offer.",
                "An indexed timestamp is not a seller's live price or availability.",
            ]}
