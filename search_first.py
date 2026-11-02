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
from statistics import median
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


# Prices for household goods and hardware often mention power, pressure,
# storage capacity or package size; none of these is a product model code.
# A different strong model ID is a negative signal, but a missing model ID
# is UNKNOWN, not a contradiction. EAN equivalence is not established here.
_SPEC_SUFFIXES = (
    "w", "kw", "v", "kv", "bar", "kg", "g", "mg", "gb", "tb", "mah",
    "hz", "rpm", "mm", "cm", "ml", "km", "l", "mp", "mpa",
)


def _model_tokens(value):
    if not isinstance(value, str):
        return set()
    tokens = re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKC", value).casefold())
    results = set()
    for word in tokens:
        if len(word) < 5 or not any(c.isdigit() for c in word):
            continue
        if word.isdigit():
            # 1100 W, 8 bar, 128 GB are not standalone model identifiers.
            # Numeric model IDs with 5+ digits can be meaningful (e.g. LEGO).
            results.add(word)
            continue
        # Common units are specs: "1100w", "8bar", "128gb", "4000mah".
        if any(word.endswith(unit) and word[:-len(unit)].isdigit()
               for unit in _SPEC_SUFFIXES):
            continue
        # Keep explicit alpha-numeric model codes (e.g. 1000xm5,
        # 8215190stn595), without assuming they're present in both listings.
        if any(ch.isalpha() for ch in word):
            results.add(word)
    return results


_CAPACITY_RE = re.compile(r"(?<![a-z0-9])(\d+(?:[.,]\d+)?)\s*(tb|gb)\b", flags=re.I)
_BUNDLE_RE = re.compile(r"\b(?:full\s+kit|kit|zestaw|bundle|komplet|pakiet|2x|3x)\b", flags=re.I)


def _capacity_tokens(text):
    if not isinstance(text,str):
        return set()
    return {(amount.replace(",", "."), unit.lower())
            for amount, unit in _CAPACITY_RE.findall(text)}


def _bundle_indicator(title):
    return bool(isinstance(title,str) and _BUNDLE_RE.search(title))


def _variant_assessment(selected_title, candidate_title):
    """Reject provable variant contradictions, leave unsupported claims UNKNOWN."""
    a = _model_tokens(selected_title)
    b = _model_tokens(candidate_title)
    if a and b and a.isdisjoint(b):
        return "MODEL_TOKEN_CONFLICT_NEEDS_REVIEW"
    capacities_a = _capacity_tokens(selected_title)
    capacities_b = _capacity_tokens(candidate_title)
    if capacities_a and capacities_b and capacities_a.isdisjoint(capacities_b):
        return "CAPACITY_VARIANT_CONFLICT_NEEDS_REVIEW"
    # Full kits and bare products cannot silently share a lowest-price claim.
    if _bundle_indicator(selected_title) != _bundle_indicator(candidate_title):
        return "BUNDLE_VARIANT_CONFLICT_NEEDS_REVIEW"
    return "PRODUCT_IDENTITY_NOT_PROVEN_BY_SHOPPING_INDEX"


def _variant_conflict(status):
    return status in (
        "MODEL_TOKEN_CONFLICT_NEEDS_REVIEW",
        "CAPACITY_VARIANT_CONFLICT_NEEDS_REVIEW",
        "BUNDLE_VARIANT_CONFLICT_NEEDS_REVIEW",
    )


def _flag_price_outliers(entries):
    """Mark implausibly low indexed prices; never remove the observed listing.

    Requires at least three same-currency non-conflicting store observations.
    Cheap promotions can be genuine, so this is a triage warning, not proof of
    an incorrect price. A flagged entry is excluded only from the provisional
    minimum, never from the research/evidence list.
    """
    for entry in entries:
        entry["index_price_anomaly"] = "NONE_DETECTED"
    by_currency = {}
    for entry in entries:
        if not _variant_conflict(entry["identity_status"]):
            by_currency.setdefault(entry["currency"],[]).append(entry)
    for group in by_currency.values():
        if len(group) < 3:
            continue
        center = median(Decimal(e["current_price_indexed"]) for e in group)
        if center <= 0:
            continue
        for entry in group:
            if Decimal(entry["current_price_indexed"]) < center * Decimal("0.40"):
                entry["index_price_anomaly"] = "SUSPICIOUS_LOW_PRICE_VS_PEER_MEDIAN_NOT_VERIFIED"
    return entries


def _rankable_indexed_offer(entry):
    return (not _variant_conflict(entry["identity_status"])
            and entry.get("index_price_anomaly") !=
                "SUSPICIOUS_LOW_PRICE_VS_PEER_MEDIAN_NOT_VERIFIED")


def _index_product_url(url):
    safe = _stable_url(url)
    if safe is None:
        return None
    parts = urlsplit(safe)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host in ("google.com","google.pl") and not parts.path.startswith("/shopping/product/"):
        return None
    return safe


def _google_shopping_lookup_url(title, source):
    """Safe public Google Shopping search link, NOT a direct merchant offer.

    Some SerpApi cards do not contain any shop link, and Google's returned
    product_link may be a long search URL with transient internal tokens.
    Construct a short, user-facing search instead of inventing offer URLs.
    """
    terms = " ".join(part for part in (
        _clean_text(title, 120), _clean_text(source, 60)) if part)
    if not terms:
        return None
    return "https://www.google.com/search?" + urlencode({
        "tbm": "shop", "q": terms[:175], "gl": "pl", "hl": "pl",
    })


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
                    "serpapi.com", "ceneo.pl", "e-katalog.pl"):
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
        identity = (variant if _variant_conflict(variant) else item_variant)
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
    _flag_price_outliers(entries)
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
        # Google's full Shopping results may exceed the generic 200 KB
        # catalog-reader limit (observed 355668 bytes on 2026-11-02).
        # Keep fixed-provider HTTPS, no redirects, and a strict 2.5 MB bound.
        fetch = lambda url, host: _get_json(
            url, host, timeout=25, max_bytes=2_500_000)
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
                "index_product_url": _index_product_url(entry.get("product_link")),
                "index_search_url": _google_shopping_lookup_url(title, entry.get("source")),
                "search_card_only_not_direct_offer": True,
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
                          not _variant_conflict(row["identity_status"])), None)
        if candidate is None:
            output["status"] = "NO_CANDIDATE_GOOGLE_PRODUCT_GROUP"
        else:
            attempts += 1
            try:
                detail = _api_json("google_product", key, fetch,
                                   product_id=candidate["product_id"])
                parsed = parse_serpapi_google_product(detail, selected, max_stores)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                # One failed Google Product follow-up must NOT erase the
                # successfully indexed Shopping result cards. This is common
                # on marketplace items whose group/product token is stale.
                # The search cards remain explicitly NOT source-verified.
                parsed = {"offers": [], "source_status": "DETAIL_UNAVAILABLE",
                          "product_title": candidate["title"]}
                output["product_detail_failure_type"] = type(exc).__name__
                output["limitations"].append(
                    "Google Product details request failed; original Google Shopping "
                    "cards are retained without seller-page or checkout verification.")
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
                      _rankable_indexed_offer(offer)]
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
        if (output["lowest_indexed_observation"] is None
                and not output["indexed_offers"]):
            group_currency = selected.get("currency")
            if group_currency is None and any(x.get("indexed_currency") == "PLN"
                                              for x in output["search_result_groups"]):
                group_currency = "PLN"
            eligible_groups = [
                row for row in output["search_result_groups"] if
                row.get("indexed_price") is not None and
                row.get("indexed_currency") == group_currency and
                not _variant_conflict(row["identity_status"])
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
                    output["status"] = (
                        "ONLY_GOOGLE_SHOPPING_CARDS_DETAIL_FAILED"
                        if output.get("product_detail_failure_type")
                        else "ONLY_GOOGLE_SHOPPING_SEARCH_INDEX_PRICES")
        if output.get("product_detail_failure_type") and not output["indexed_offers"]:
            output["status"] = "ONLY_GOOGLE_SHOPPING_CARDS_DETAIL_FAILED"
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
                    ([_node("indexed_store", offer["seller"], offer["identity_status"],
                            offer, node_id="indexed-store-{}".format(i))
                      for i, offer in enumerate(data["indexed_offers"])] +
                     [_node("indexed_search_card", group["source"], group["identity_status"],
                            group, node_id="indexed-shopping-card-{}".format(i))
                      for i, group in enumerate(data["search_result_groups"])]),
                    node_id="cart-indexed-shopping")
    output["root"]["children"].insert(-1, summary)
    output["indexed_shopping"] = data
    output["limitations"] = list(output.get("limitations", [])) + data["limitations"]
    output["generated_at"] = _timestamp()
    output.pop("sha256", None)
    output["sha256"] = sha256(json.dumps(
        output, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return output
