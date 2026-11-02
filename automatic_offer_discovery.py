"""Turn authorized search discovery leads into audited real seller-page checks.

Search hits are NOT prices, product facts or reviews. Every candidate is
validated; fetched pages use product_intake's robots-aware, pinned-public-IP
HTTPS transport. A denied marketplace remains an explicit discovery lead.
"""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from urllib.parse import urlsplit

from cart_research import validate_cart
from decision_tree import _node
from multi_offer_compare import compare_live_offers
from product_intake import normalized_product_url

MAX_SEARCH_HITS = 12
MAX_FETCHED_CANDIDATES = 3
MARKETPLACE_HOSTS = frozenset(("allegro.pl", "www.allegro.pl"))
AGGREGATOR_HOSTS = frozenset(("ceneo.pl", "www.ceneo.pl"))
SOURCE_SCOPES = frozenset(("UNVERIFIED_SEARCH_RESULT_NOT_A_PRICE_OFFER",))


def _candidate_search_records(report, selected, limit):
    """Preserve rejected source hits, then prioritize a marketplace hit.

    Prefer a marketplace *discovery link* when search has returned one. This
    never implies that marketplace prices are verified, or that it is cheapest.
    One product URL per merchant; a search listing/category is not a product.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_FETCHED_CANDIDATES:
        raise ValueError("Limit must be an integer between 1 and 3")
    discovery = report.get("source_discovery") or {}
    hits = discovery.get("web_hits", [])
    if type(hits) is not list or len(hits) > MAX_SEARCH_HITS:
        raise ValueError("Invalid bounded search result list")
    original = normalized_product_url(selected["merchant_url"])
    original_host = urlsplit(original).hostname
    if original_host.startswith("www."):
        original_host = original_host[4:]
    audit = []
    seen_url = set()
    seen_hosts = {original_host}
    for idx, raw in enumerate(hits, 1):
        candidate = {
            "search_result_index": idx,
            "search_title_unverified": "",
            "search_snippet_unverified": "",
            "candidate_url": None,
            "decision": None,
            "source_type": "SEARCH_DISCOVERY_ONLY_NOT_A_SELLER_OFFER",
            "search_price_used": False,
        }
        if type(raw) is not dict:
            candidate["decision"] = "REJECTED_INVALID_RESULT"
            audit.append(candidate)
            continue
        candidate["search_title_unverified"] = str(raw.get("title") or "")[:180]
        candidate["search_snippet_unverified"] = str(raw.get("snippet") or "")[:450]
        if raw.get("source_kind") not in SOURCE_SCOPES:
            candidate["decision"] = "REJECTED_UNTRUSTED_PROVENANCE"
            audit.append(candidate)
            continue
        try:
            url = normalized_product_url(raw.get("url"))
        except (ValueError, TypeError):
            candidate["decision"] = "REJECTED_UNSAFE_URL"
            audit.append(candidate)
            continue
        candidate["candidate_url"] = url
        parsed = urlsplit(url)
        host = parsed.hostname
        merchant_host = host[4:] if host.startswith("www.") else host
        if url == original or merchant_host == original_host:
            candidate["decision"] = "REJECTED_ORIGINAL_SELLER"
        elif url in seen_url:
            candidate["decision"] = "REJECTED_DUPLICATE_URL"
        elif host in AGGREGATOR_HOSTS:
            candidate["decision"] = "DEFERRED_AGGREGATOR_NOT_SELLER"
        elif merchant_host in seen_hosts:
            candidate["decision"] = "REJECTED_DUPLICATE_MERCHANT"
        elif (len(parsed.path.strip("/")) < 7
              or parsed.path.lower().rstrip("/") in (
                  "/search", "/szukaj", "/oferty", "/category", "/kategoria")
              or (merchant_host == "allegro.pl" and not parsed.path.startswith(
                  ("/oferta/", "/produkt/")))):
            candidate["decision"] = "REJECTED_NON_PRODUCT_PATH"
        else:
            candidate["decision"] = "ELIGIBLE_DISCOVERY_LEAD"
            seen_hosts.add(merchant_host)
        seen_url.add(url)
        audit.append(candidate)
    eligible = [x for x in audit if x["decision"] == "ELIGIBLE_DISCOVERY_LEAD"]
    eligible.sort(key=lambda x: (
        0 if urlsplit(x["candidate_url"]).hostname in MARKETPLACE_HOSTS else 1,
        x["search_result_index"]))
    selected_hits = eligible[:limit]
    selected_ids = {row["search_result_index"] for row in selected_hits}
    for row in audit:
        if row["decision"] == "ELIGIBLE_DISCOVERY_LEAD":
            row["decision"] = ("SOURCE_CHECK_REQUESTED" if
                               row["search_result_index"] in selected_ids else
                               "DEFERRED_FETCH_BUDGET")
    return audit, [row["candidate_url"] for row in selected_hits]


def enrich_with_discovered_offers(report, selected, extractor=None, max_checks=3):
    """Bounded live offer checks driven by recorded authorized search results.

    Source discovery is naturally optional: no configured Brave search means no
    hits and zero outbound seller-page requests. A blocked candidate is still
    preserved. The original seller report never mutates.
    """
    selected = validate_cart(selected)
    if type(report) is not dict or not report.get("root", {}).get("children"):
        raise ValueError("Source research report is required")
    audit, candidates = _candidate_search_records(report, selected, max_checks)
    source = report.get("source_intake") or {}
    original_is_fetched = (
        source.get("source_url") == selected["merchant_url"]
        and bool(source.get("page_sha256"))
        and source.get("price_status") == "SELLER_DECLARED"
        and source.get("intake_status") != "URL_ONLY_UNVERIFIED"
    )
    outcome = ("SEARCH_NO_CANDIDATES" if not candidates else
               "SOURCE_CHECKS_COMPLETED" if original_is_fetched else
               "SELECTED_SOURCE_UNVERIFIED_NO_FETCH")
    result = deepcopy(report)
    checks = []
    if candidates and original_is_fetched:
        # Reuse the existing strict comparison gates. They preserve source
        # failures and never infer prices from the search-result snippet.
        result = compare_live_offers(report, selected, candidates,
                                    extractor=extractor)
        if len(candidates) == 1:
            comparisons = [result["live_competitor_comparison"]]
        else:
            comparisons = result["live_competitor_comparisons"]
        for candidate, comp in zip(candidates, comparisons):
            checks.append({
                "url": candidate,
                "status": comp["status"],
                "source_page_retrieved": comp["alternative_retrieved"],
                "source_http_status": (comp.get("alternative_source") or {}).get(
                    "access_status"),
                "qualifies_as_comparable_seller_price": (
                    comp["status"] == "SAME_GTIN_SELLER_LISTED_PRICE_COMPARISON"),
                "source_page_sha256": (comp.get("alternative_source") or {}).get(
                    "page_sha256"),
            })
    elif candidates:
        for row in audit:
            if row["decision"] == "SOURCE_CHECK_REQUESTED":
                row["decision"] = "SKIPPED_SELECTED_SOURCE_UNVERIFIED"
    check_map = {row["url"]: row for row in checks}
    for row in audit:
        if row["decision"] == "SOURCE_CHECK_REQUESTED":
            check = check_map.get(row["candidate_url"])
            if check:
                row["decision"] = (
                    "SOURCE_VERIFIED_COMPARABLE" if check[
                        "qualifies_as_comparable_seller_price"] else
                    "SOURCE_CHECK_INCOMPLETE")
                row["source_check_status"] = check["status"]
                row["source_http_status"] = check["source_http_status"]
    counts = {
        "search_hits_seen": len(audit),
        "candidates_checked": len(checks),
        "seller_pages_retrieved": sum(x["source_page_retrieved"] for x in checks),
        "source_qualified_competing_offers": sum(
            x["qualifies_as_comparable_seller_price"] for x in checks),
        "marketplace_leads_found": sum(
            urlsplit(x["candidate_url"]).hostname in MARKETPLACE_HOSTS
            for x in audit if x["candidate_url"] and x["decision"] in (
                "SOURCE_CHECK_INCOMPLETE", "SOURCE_VERIFIED_COMPARABLE",
                "DEFERRED_FETCH_BUDGET", "SKIPPED_SELECTED_SOURCE_UNVERIFIED")),
    }
    discovery = {
        "status": outcome,
        "method": "EXISTING_AUTHORIZED_SEARCH_RESULTS_THEN_ROBOTS_AWARE_SOURCE_CHECK",
        "counts": counts,
        "search_hit_price_used": False,
        "authorized_search_provider_required": True,
        "source_check_budget": max_checks,
        "candidate_audit": audit,
        "page_checks": checks,
        "limitations": [
            "Search snippets and displayed preview prices are unverified hints, not current seller offers.",
            "No broad-web completeness claim; a search provider may omit cheaper merchants.",
            "Restricted or blocked pages remain visible; HTML access restrictions are never bypassed.",
            "Only matching seller-declared GTIN, variant, price, stock and currency can qualify.",
            "No independent reviews or laboratory tests have yet been collected by this step.",
            "No checkout, delivered-price ranking or payment authorization.",
        ],
        "payment_authorized": False,
    }
    branch = _node(
        "automatic_offer_discovery", "Automatic comparison leads from permitted search",
        outcome, {**counts, "budget": max_checks,
                  "provider": "OPTIONAL_CONFIGURED_SEARCH_ONLY",
                  "all_prices_from_search_ignored": True,
                  "payment_authorized": False},
        [_node("discovery_candidate", row["search_title_unverified"]
               or row["candidate_url"] or "Invalid search result",
               row["decision"], row,
               node_id="cart-discovery-{}".format(row["search_result_index"]))
         for row in audit],
        node_id="cart-automatic-discovery")
    result["root"]["children"].insert(-1, branch)
    result["automatic_offer_discovery"] = discovery
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    result["limitations"] = list(result.get("limitations", [])) + [
        "Search-ranked sites are neither a complete market scan nor verified offers."]
    result.pop("sha256", None)
    result["sha256"] = sha256(json.dumps(
        result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return result
