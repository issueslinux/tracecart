"""Compare a second actual merchant page with the already-selected cart item.

No search snippets, fabricated offers, browser cookies, payment calls or
source-restriction bypass. Product identity is only claimed by sellers.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
from urllib.parse import urlsplit

from cart_research import classify_product, validate_cart
from decision_tree import _node
from product_intake import (extract_product_page, normalized_product_url,
                            normalized_gtin, SourceAccessDenied, SourceRedirect,
                            SourceHTTPFailure)
from unit_economics import unit_cost


def compare_live_offer(base_report, selected, candidate_url, extractor=None):
    """Return immutable, source-attributed second-offer report, never a winner."""
    selected = validate_cart(selected)
    candidate_url = normalized_product_url(candidate_url)
    if candidate_url == normalized_product_url(selected["merchant_url"]):
        raise ValueError("Second URL must differ from selected offer")
    extractor = extractor or extract_product_page
    report = deepcopy(base_report)
    source = report.get("source_intake") or {}
    source_url = source.get("source_url")
    base_is_retrieved = (
        source.get("intake_status") != "URL_ONLY_UNVERIFIED"
        and bool(source.get("page_sha256"))
        and source_url == selected["merchant_url"]
        and report.get("root", {}).get("details", {}).get(
            "selected_cart_item", selected) == selected)
    category = classify_product(selected["title"])
    competitor = None
    metadata = None
    error = None
    try:
        competitor, metadata = extractor(candidate_url)
        competitor = validate_cart(competitor)
        if metadata.get("source_url") != competitor["merchant_url"]:
            raise ValueError("Inconsistent competitor source URL")
        if not metadata.get("page_sha256") or not metadata.get("retrieved_at"):
            raise ValueError("Missing competitor source provenance")
        if metadata.get("intake_status") == "URL_ONLY_UNVERIFIED":
            raise ValueError("URL-only identity is not a verified seller page")
    except (SourceAccessDenied, SourceHTTPFailure, SourceRedirect) as exc:
        error = "HTTP_{}".format(exc.status)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        error = type(exc).__name__
    if competitor is None or error:
        competitor = None
        metadata = {"source_url": candidate_url, "page_sha256": None,
                    "retrieved_at": None, "access_status": error or "NO_SOURCE"}
    def merchant_host(url):
        host = urlsplit(url).hostname or ""
        return host[4:] if host.startswith("www.") else host

    same_host = (merchant_host(selected["merchant_url"]) ==
                 merchant_host(candidate_url))
    selected_gtin = normalized_gtin(selected["barcode"])
    alternative_gtin = normalized_gtin(competitor["barcode"]) if competitor else None
    invalid_gtin = bool((selected["barcode"] and not selected_gtin) or
                        (competitor and competitor["barcode"] and
                         not alternative_gtin))
    ean_match = bool(competitor and selected_gtin and alternative_gtin
                     and selected_gtin == alternative_gtin)
    ean_conflict = bool(competitor and selected_gtin and alternative_gtin
                        and not ean_match)
    base_unit = unit_cost(selected, category)
    other_unit = (unit_cost(competitor, category) if competitor else
                  {"status": "NOT_RETRIEVED", "cost_per_wash": None})
    dose_conflict = bool(ean_match and
        base_unit.get("washes_declared_in_title") and
        other_unit.get("washes_declared_in_title") and
        base_unit["washes_declared_in_title"] !=
        other_unit["washes_declared_in_title"])
    valid_seller_price = bool(
        competitor and competitor["price"] is not None and
        metadata.get("price_status") == "SELLER_DECLARED")
    selected_price_sourced = source.get("price_status") == "SELLER_DECLARED"
    independent_store = bool(competitor and not same_host)
    availability = str(metadata.get("availability_claim") or "").casefold()
    unavailable = any(word in availability for word in (
        "outofstock", "discontinued", "soldout"))
    selected_availability = str(source.get("availability_claim") or "").casefold()
    selected_unavailable = any(word in selected_availability for word in (
        "outofstock", "discontinued", "soldout"))
    compared = bool(base_is_retrieved and selected_price_sourced
                    and ean_match and not dose_conflict
                    and not unavailable and not selected_unavailable
                    and independent_store and valid_seller_price
                    and selected["price"] is not None
                    and selected["currency"] == competitor["currency"])
    if error:
        status = "SECOND_PAGE_NOT_RETRIEVED"
    elif not independent_store:
        status = "SAME_STORE_NOT_COMPETITOR"
    elif not base_is_retrieved:
        status = "SELECTED_PAGE_NOT_RETRIEVED"
    elif invalid_gtin:
        status = "INVALID_GTIN_CLAIM"
    elif ean_conflict:
        status = "DIFFERENT_GTIN_NOT_EQUIVALENT"
    elif not ean_match:
        status = "GTIN_IDENTITY_NOT_ESTABLISHED"
    elif dose_conflict:
        status = "CONFLICTING_WASH_COUNT"
    elif selected_unavailable:
        status = "SELECTED_OFFER_NOT_AVAILABLE"
    elif unavailable:
        status = "SECOND_OFFER_NOT_AVAILABLE"
    elif not valid_seller_price or not selected_price_sourced or selected["price"] is None:
        status = "LISTED_PRICE_MISSING"
    elif selected["currency"] != competitor["currency"]:
        status = "DIFFERENT_CURRENCY_NO_FX"
    else:
        status = "SAME_GTIN_SELLER_LISTED_PRICE_COMPARISON"
    delta = None
    if compared:
        original = Decimal(selected["price"])
        if original > 0:
            delta = str(((Decimal(competitor["price"]) - original) / original *
                         Decimal("100")).quantize(Decimal("0.01"),
                                                 rounding=ROUND_HALF_UP))
    comparison = {
        "status": status,
        "selected": selected,
        "selected_source": source,
        "alternative": competitor,
        "alternative_source": metadata,
        "alternative_requested_url": candidate_url,
        "alternative_retrieved": bool(competitor),
        "different_store": independent_store,
        "same_gtin_claimed": ean_match,
        "different_gtin_claimed": ean_conflict,
        "invalid_gtin_claim": invalid_gtin,
        "gtin_checksum_checked": True,
        "wash_count_conflict": dose_conflict,
        "second_offer_availability_claim": metadata.get("availability_claim"),
        "second_offer_not_available": unavailable,
        "selected_offer_not_available": selected_unavailable,
        "selected_cost_per_wash": base_unit,
        "alternative_cost_per_wash": other_unit,
        "seller_listed_price_delta_pct_vs_selected": delta,
        "delta_is_not_delivered_price": True,
        "independent_lab_tests": 0,
        "final_checkout_price_verified": False,
        "payment_authorized": False,
        "limitations": [
            "Retailer pages contain seller claims, not independently verified checkout totals.",
            "GTIN equality is a seller-declared identity match, not proof of equivalent performance.",
            "Delivery, discounts, pack formulation, stock and dosing may change total value.",
            "No price ranking without matching GTIN, source pages, currency and usable prices.",
        ],
    }
    if "root" not in report or not report["root"].get("children"):
        raise ValueError("Original cart report lacks research tree")
    branch = _node("live_competitor", "Second real merchant URL — provenance and equivalence",
                   status, comparison, node_id="cart-live-competitor")
    report["root"]["children"].insert(-1, branch)
    summary = report["root"]["children"][-1]["details"]
    summary["live_second_offer_status"] = status
    summary["current_competitor_offers_verified"] = int(
        independent_store and valid_seller_price and base_is_retrieved
        and ean_match and not dose_conflict and not unavailable
        and not selected_unavailable
        and selected_price_sourced)
    summary["second_retailer_listed_price_observed"] = bool(
        independent_store and valid_seller_price)
    summary["comparison_status"] = status
    summary["result"] = (
        "A second merchant's listed price is available with a seller-declared "
        "matching GTIN. Compare listed prices only; delivery and product claims "
        "remain unverified." if compared else
        "Second-offer evidence is incomplete or identity differs; no cheaper "
        "equivalent product is asserted.")
    report["live_competitor_comparison"] = comparison
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    report["limitations"] = list(report.get("limitations", [])) + [
        "Second-merchant comparison does not authorize a payment or verify checkout totals."]
    report.pop("sha256", None)
    report["sha256"] = sha256(json.dumps(
        report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return report
