"""Search-first shopping evidence: Google Shopping index, not seller/checkout verification.

SerpApi is only called when explicitly configured. Exactly one Shopping query
and at most one Product-details query per item; product/store identifiers come
from SerpApi's JSON, never constructed as merchant-specific scraping URLs.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import os
import re
import unicodedata
from urllib.parse import urlencode, urlsplit

from product_intake import normalized_product_url

SEARCH_HOST = "serpapi.com"
MAX_STORES = 12
MAX_SHOPPING_ROWS = 12
CURRENCIES = ("PLN", "EUR", "USD")
_PROVIDER = "SERPAPI_GOOGLE_SHOPPING"
MARKETPLACES = frozenset(("allegro.pl", "amazon.pl", "amazon.de", "amazon.com", "ebay.com"))
REFERENCE_TEXT = {
    "PLN": re.compile(r"(?:\bPLN\b|zł)", flags=re.I),
    "EUR": re.compile(r"(?:\bEUR\b|€)", flags=re.I),
    "USD": re.compile(r"\bUSD\b", flags=re.I),
}


def _clean_text(value, limit=160):
    return " ".join(str(value).split())[:limit] if isinstance(value, str) else ""


def _timestamp():
    return datetime.now(timezone.utc).isoformat()


def _currency(price_text):
    if not isinstance(price_text, str):
        return None
    matches = [code for code, pattern in REFERENCE_TEXT.items() if pattern.search(price_text)]
    return matches[0] if len(matches) == 1 else None


def _amount(value):
    """Use only dedicated current extracted_price, not prices in snippets."""
    if isinstance(value, bool) or not isinstance(value, (str, float, int, Decimal)):
        return None
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not price.is_finite() or not 0 < price <= 100000 or price.as_tuple().exponent < -2:
        return None
    return str(price.quantize(Decimal("0.01")))


def _stable_url(value):
    """Only direct, safe public HTTPS product URLs can become clickable stores."""
    try:
        return normalized_product_url(value)
    except (TypeError, ValueError):
        return None


def _model_tokens(value):
    words = re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKC", value).casefold())
    return {w for w in words if len(w) >= 4 and any(c.isdigit() for c in w)}


def _variant_assessment(selected_title, candidate_title):
    """A conflicting model ID is explicit negative evidence, not proof of identity."""
    a = _model_tokens(selected_title)
    b = _model_tokens(candidate_title)
    if a and b and a.isdisjoint(b):
        return "MODEL_TOKEN_CONFLICT_NEEDS_REVIEW"
    return "PRODUCT_IDENTITY_NOT_PROVEN_BY_SHOPPING_INDEX"


def _search_query(item):
    title = _clean_text(item["title"], 140)
    code = item.get("barcode", "")
    if isinstance(code, str) and re.fullmatch(r"\d{8}|\d{12,14}", code):
        return (code + " " + title[:90]).strip()[:180]
    return title[:160]


def _api_json(engine, api_key, fetch, **params):
    # SerpApi's documented API authenticates via api_key query parameter.
    # Never log/persist URLs with keys. No key ever goes to seller hosts.
    url = "https://serpapi.com/search.json?" + urlencode({
        "engine": engine, "gl": "pl", "hl": "pl",
        "api_key": api_key, **params,
    })
    data = fetch(url, SEARCH_HOST)
    if type(data) is not dict:
        raise ValueError("Shopping provider returned invalid JSON")
    if data.get("error"):
        raise ValueError("Shopping provider returned an error")
    status = (data.get("search_metadata") or {}).get("status")
    if status not in (None, "Success"):
        raise ValueError("Shopping provider did not finish successfully")
    return data


def parse_serpapi_google_product(raw, selected, max_stores=MAX_STORES):
    """Parse seller price observations with explicit source and variant boundaries."""
    if type(raw) is not dict or not isinstance(raw.get("product_results"), dict):
        raise ValueError("SerpApi did not return product_results")
    product = raw["product_results"]
    stores = product.get("stores")
    if not isinstance(stores, list):
        return {"product_title": _clean_text(product.get("title")),
                "offers": [], "source_status": "NO_STORES_IN_PRODUCT_GROUP"}
    candidate_title = _clean_text(product.get("title"), 180)
    variant = _variant_assessment(selected["title"], candidate_title)
    entries = []
    seen = set()
    for row in stores[:40]:
        if type(row) is not dict or len(entries) >= max_stores:
            continue
        link = _stable_url(row.get("link"))
        if not link:
            continue
        p = urlsplit(link)
        host = p.hostname[4:] if p.hostname.startswith("www.") else p.hostname
        # A Google/SerpApi redirect is NOT a direct seller-page URL.
        if host in ("google.com", "google.pl", "googleadservices.com",
                    "serpapi.com", "ceneo.pl"):
            continue
        if link in seen:
            continue
        seen.add(link)
        listed_price = _amount(row.get("extracted_price"))
        unit = _currency(row.get("price"))
        if not listed_price or not unit:
            continue
        title = _clean_text(row.get("title") or candidate_title, 180)
        item_variant = _variant_assessment(selected["title"], title)
        if variant.startswith("MODEL_TOKEN_CONFLICT") or item_variant.startswith("MODEL_TOKEN_CONFLICT"):
            identity = "MODEL_TOKEN_CONFLICT_NEEDS_REVIEW"
        else:
            identity = "PRODUCT_IDENTITY_NOT_PROVEN_BY_SHOPPING_INDEX"
        entries.append({
            "seller": _clean_text(row.get("name") or host, 100),
            "merchant_host": host,
            "merchant_url": link,
            "title": title,
            "current_price_indexed": listed_price,
            "currency": unit,
            "previous_price_indexed": _amount(row.get("extracted_original_price")),
            "condition_indexed": _clean_text(row.get("condition"), 80) or "UNKNOWN",
            "identity_status": identity,
            "source_type": "GOOGLE_SHOPPING_INDEX_NOT_DIRECT_SELLER_PAGE",
            "source_page_retrieved": False,
            "price_checked_at_checkout": False,
            "stock_verified": False,
            "selected_gtin_matched_by_seller": False,
            "payment_authorized": False,
        })
    entries.sort(key=lambda entry: (entry["currency"], Decimal(entry["current_price_indexed"]),
                                    entry["merchant_host"]))
    return {
        "product_title": candidate_title,
        "offers": entries,
        "source_status": "INDEXED_STORES_WITHOUT_SELLER_VERIFICATION" if entries
                         else "NO_USABLE_STORE_PRICE",
    }


def _empty(status, stamp, attempted=0):
    return {
        "provider": _PROVIDER,
        "status": status,
        "queried_at": stamp,
        "market": "PL",
        "provider_calls": attempted,
        "indexed_offers": [],
        "lowest_indexed_observation": None,
        "search_result_groups": [],
        "indexed_marketplace_names_seen": [],
        "marketplace_hosts_seen": [],
        "source_qualified_seller_offers": 0,
        "payment_authorized": False,
        "limitations": [
            "Search-indexed prices are not verified seller-page prices, availability or checkout totals.",
            "A Google product group does not independently establish EAN or exact variant.",
            "Results are incomplete, can be delayed, and cannot establish the cheapest offer on the market.",
        ],
    }


def search_serpapi_shopping(selected, fetch=None, api_key=None, max_stores=MAX_STORES):
    """One real index search + at most one seller-group query; no API key = no calls.

    Fails closed on malformed responses. A reachable price index offers valuable
    leads even if Allegro itself rejects direct HTTP access.
    """
    if type(max_stores) is not int or not 1 <= max_stores <= MAX_STORES:
        raise ValueError("max_stores must be 1..12")
    if not isinstance(selected, dict) or not isinstance(selected.get("title"), str):
        raise ValueError("A selected item with a title is required")
    stamp = _timestamp()
    key = api_key if api_key is not None else os.environ.get("SERPAPI_API_KEY", "")
    if not key:
        return _empty("SKIPPED_NO_SERPAPI_API_KEY", stamp)
    if fetch is None:
        from cart_research import _get_json
        fetch = _get_json
    attempts = 0
    output = _empty("NO_SEARCH_RESULTS", stamp)
    try:
        attempts += 1
        response = _api_json("google_shopping", key, fetch, q=_search_query(selected))
        groups = response.get("shopping_results") or []
        if not isinstance(groups, list):
            raise ValueError("Invalid shopping results array")
        # The ranked product groups are candidate hypotheses, not EAN proof.
        for entry in groups[:MAX_SHOPPING_ROWS]:
            if not isinstance(entry, dict):
                continue
            title = _clean_text(entry.get("title"), 180)
            product_id = entry.get("product_id")
            if not title:
                continue
            state = _variant_assessment(selected["title"], title)
            output["search_result_groups"].append({
                "title": title,
                "source": _clean_text(entry.get("source"), 100),
                "source_price_display": _clean_text(entry.get("price"), 70),
                "indexed_price": _amount(entry.get("extracted_price")),
                "indexed_currency": _currency(entry.get("price")),
                "index_product_url": _stable_url(entry.get("product_link")),
                "seller_page_retrieved": False,
                "seller_price_verified": False,
                "identity_status": state,
                "group_has_multiple_sources": bool(entry.get("multiple_sources")),
                "product_id": (str(product_id) if isinstance(product_id, (str, int))
                               and re.fullmatch(r"\d{5,30}", str(product_id)) else None),
                "indexed_only": True,
            })
        output["indexed_marketplace_names_seen"] = sorted({
            row["source"] for row in output["search_result_groups"]
            if any(name in row["source"].casefold() for name in
                   ("allegro", "amazon", "ebay"))
        })
        candidate = next((row for row in output["search_result_groups"]
                          if row["product_id"] and
                          row["identity_status"] != "MODEL_TOKEN_CONFLICT_NEEDS_REVIEW"), None)
        if candidate is None:
            output["status"] = "NO_CANDIDATE_GOOGLE_PRODUCT_GROUP"
        else:
            attempts += 1
            detail = _api_json("google_product", key, fetch, product_id=candidate["product_id"])
            parsed = parse_serpapi_google_product(detail, selected, max_stores)
            output["indexed_offers"] = parsed["offers"]
            output["status"] = parsed["source_status"]
            output["selected_product_group_title"] = parsed["product_title"]
            # When the selected page is blocked, its currency is unknown.
            # The index itself may still show PLN offers for Poland; compute
            # an indexed-only minimum, without comparing to the selected price.
            unit = selected.get("currency")
            if unit is None and any(x["currency"] == "PLN" for x in parsed["offers"]):
                unit = "PLN"
            usable = [offer for offer in parsed["offers"] if
                      offer["currency"] == unit and
                      offer["identity_status"] != "MODEL_TOKEN_CONFLICT_NEEDS_REVIEW"]
            if usable:
                best = min(usable, key=lambda x: Decimal(x["current_price_indexed"]))
                output["lowest_indexed_observation"] = {
                    "price": best["current_price_indexed"],
                    "currency": best["currency"],
                    "seller": best["seller"],
                    "merchant_url": best["merchant_url"],
                    "meaning": "MINIMUM_OF_RETURNED_INDEXED_STORES_NOT_MARKET_WIDE",
                    "product_identity_unverified": True,
                    "checkout_price_unverified": True,
                }
            output["marketplace_hosts_seen"] = sorted({
                entry["merchant_host"] for entry in parsed["offers"]
                if entry["merchant_host"] in MARKETPLACES
            })
        if output["lowest_indexed_observation"] is None:
            group_currency = selected.get("currency")
            if group_currency is None and any(x.get("indexed_currency") == "PLN"
                                              for x in output["search_result_groups"]):
                group_currency = "PLN"
            eligible_groups = [
                row for row in output["search_result_groups"] if
                row.get("indexed_price") is not None and
                row.get("indexed_currency") == group_currency and
                row["identity_status"] != "MODEL_TOKEN_CONFLICT_NEEDS_REVIEW"
            ]
            if eligible_groups:
                best = min(eligible_groups, key=lambda x: Decimal(x["indexed_price"]))
                output["lowest_indexed_observation"] = {
                    "price": best["indexed_price"],
                    "currency": best["indexed_currency"],
                    "seller": best["source"],
                    "merchant_url": None,
                    "index_product_url": best["index_product_url"],
                    "meaning": "MINIMUM_OF_INDEXED_SEARCH_RESULTS_NO_DIRECT_SELLER_LINK",
                    "product_identity_unverified": True,
                    "checkout_price_unverified": True,
                }
                if not output["indexed_offers"]:
                    output["status"] = "ONLY_GOOGLE_SHOPPING_SEARCH_INDEX_PRICES"
    except (OSError, ValueError, TypeError, KeyError) as exc:
        output = _empty("FAILED_" + type(exc).__name__, stamp)
        # Do not disclose provider keys or raw network exception strings.
    output["provider_calls"] = attempts
    return output


def attach_shopping_evidence(report, selected, search_result):
    """Add index evidence to a full report without changing existing seller gates."""
    from copy import deepcopy
    from decision_tree import _node
    if type(report) is not dict or not report.get("root", {}).get("children"):
        raise ValueError("Expected a report with an evidence tree")
    if type(search_result) is not dict or search_result.get("provider") != _PROVIDER:
        raise ValueError("Expected SerpApi shopping evidence")
    output = deepcopy(report)
    data = deepcopy(search_result)
    summary = _node("indexed_shopping", "Indexed shopping stores (NOT seller verified)",
                    data["status"], {
                        "provider": _PROVIDER,
                        "store_offers_indexed": len(data["indexed_offers"]),
                        "provider_calls": data["provider_calls"],
                        "marketplace_hosts_seen": data["marketplace_hosts_seen"],
                        "source_qualified_seller_offers": 0,
                        "payment_authorized": False,
                    },
                    [_node("indexed_store", offer["seller"], offer["identity_status"],
                           offer, node_id="indexed-store-{}".format(i))
                     for i, offer in enumerate(data["indexed_offers"])],
                    node_id="cart-indexed-shopping")
    output["root"]["children"].insert(-1, summary)
    output["indexed_shopping"] = data
    output["limitations"] = list(output.get("limitations", [])) + data["limitations"]
    output["generated_at"] = _timestamp()
    output.pop("sha256", None)
    output["sha256"] = sha256(json.dumps(
        output, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return output
