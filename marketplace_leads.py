"""Preserve potentially cheaper marketplace offers even when direct access fails.

An observed listing price from a browser, index or other observer is a LEAD,
not a verified TraceCart seller-page offer. It never qualifies for the existing
GTIN/stock/price-verified comparison or an automatic purchase decision.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re

from cart_research import validate_cart
from decision_tree import _node
from product_intake import normalized_gtin, normalized_product_url

MAX_LEADS = 4
ORIGINS = frozenset({
    "USER_REPORTED_NOT_FETCHED",
    "PUBLIC_PAGE_REVIEW_NOT_FETCHED_BY_TRACECART",
    "USER_BROWSER_ACTIVE_TAB_NOT_SERVER_VERIFIED",
})
CONDITIONS = frozenset(("NEW_CLAIM", "USED_CLAIM", "OPEN_BOX_CLAIM", "UNKNOWN"))


def _money(value):
    if type(value) is not str:
        raise ValueError("Observed price must be a decimal string")
    if not re.fullmatch(r"(?:0|[1-9][0-9]{0,5})(?:\.[0-9]{1,2})?", value):
        raise ValueError("Observed price must be plain decimal notation")
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ValueError("Invalid observed price")
    if (not amount.is_finite() or amount <= 0 or amount > 100000
            or amount.as_tuple().exponent < -2):
        raise ValueError("Invalid observed price")
    return amount.quantize(Decimal("0.01"))


def add_marketplace_leads(report, selected, observations):
    """Add 1–4 explicitly unverified observations with a full audit trail.

    Original report and its verified-offer counts are not modified.
    Every observation remains separate from direct page extraction, including
    when an Allegro listing was blocked to TraceCart but viewed elsewhere.
    """
    if observations is None or observations == []:
        return report
    if type(observations) is not list or not 1 <= len(observations) <= MAX_LEADS:
        raise ValueError("Expected 1 to 4 marketplace lead observations")
    clean = validate_cart(selected)
    if not isinstance(report, dict) or not report.get("root", {}).get("children"):
        raise ValueError("Research report with decision tree required")
    original_source = report.get("source_intake") or {}
    selected_price_trustworthy = bool(
        original_source.get("source_url") == clean["merchant_url"]
        and original_source.get("page_sha256")
        and original_source.get("price_status") == "SELLER_DECLARED"
        and original_source.get("intake_status") != "URL_ONLY_UNVERIFIED")
    seen = set()
    rows = []
    now = datetime.now(timezone.utc).isoformat()
    for index, entry in enumerate(observations, 1):
        if type(entry) is not dict or (set(entry) -
                {"url", "price", "currency", "origin", "observed_at", "gtin_claim", "condition",
                 "observed_title", "observation_method", "price_evidence_method"}):
            raise ValueError("Unexpected marketplace lead fields")
        url = normalized_product_url(entry.get("url"))
        if url == normalized_product_url(clean["merchant_url"]) or url in seen:
            raise ValueError("Duplicate or original marketplace URL")
        seen.add(url)
        origin = entry.get("origin")
        if origin not in ORIGINS:
            raise ValueError("Explicit observation origin required")
        currency = entry.get("currency")
        if currency not in ("PLN", "EUR", "USD"):
            raise ValueError("Unsupported observed currency")
        price = _money(entry.get("price"))
        condition = entry.get("condition", "UNKNOWN")
        if condition not in CONDITIONS:
            raise ValueError("Invalid condition claim")
        title = entry.get("observed_title")
        capture_method = entry.get("observation_method")
        price_evidence = entry.get("price_evidence_method")
        if origin == "USER_BROWSER_ACTIVE_TAB_NOT_SERVER_VERIFIED":
            if (type(title) is not str or not 3 <= len(title) <= 180
                    or capture_method not in (
                        "ACTIVE_TAB_SINGLE_PRODUCT_JSONLD",
                        "USER_SELECTED_VISIBLE_PRICE")
                    or price_evidence not in (
                        "UNIQUE_PRODUCT_JSONLD", "SELECTED_VISIBLE_TEXT")):
                raise ValueError("Browser observation provenance incomplete")
        elif any(value is not None for value in (title, capture_method, price_evidence)):
            raise ValueError("Source capture metadata must match observation origin")
        observed_at = entry.get("observed_at")
        if observed_at is not None:
            if type(observed_at) is not str or len(observed_at) > 45:
                raise ValueError("Invalid observation time")
            try:
                stamp = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("Invalid observation time")
            if stamp.tzinfo is None or stamp.year < 2020:
                raise ValueError("Timestamp must include timezone")
        gtin = entry.get("gtin_claim")
        if gtin is not None and (type(gtin) is not str or
                                len(gtin) not in (8, 12, 13, 14) or
                                not gtin.isascii() or not gtin.isdigit()):
            raise ValueError("GTIN must be a decimal string or omitted")
        normal_gtin = normalized_gtin(gtin) if gtin else None
        selected_gtin = normalized_gtin(clean["barcode"]) if clean["barcode"] else None
        comparison = "UNKNOWN_CURRENCY_OR_SELECTED_PRICE"
        gap = None
        if selected_price_trustworthy and clean["price"] is not None and currency == clean["currency"]:
            difference = Decimal(clean["price"]) - price
            comparison = ("OBSERVED_LOWER_LISTED_PRICE_NOT_VERIFIED" if difference > 0
                          else "NOT_LOWER_THAN_SELECTED_LISTING")
            gap = str(difference.quantize(Decimal("0.01")))
        # Do not treat an observed cheap listing with a different *valid*
        # GTIN as a same-product price lead. An absent or invalid GTIN remains
        # unresolved; neither establishes identity.
        if normal_gtin and selected_gtin and normal_gtin != selected_gtin:
            comparison = "DIFFERENT_GTIN_OBSERVATION_NOT_COMPARABLE"
            gap = None
        # If the same URL was independently fetched as a current seller page,
        # reconcile it with the observation instead of showing two apparent
        # offers. Contradictory browser/index prices are not lower-price leads.
        direct = [x for x in (
            [report.get("live_competitor_comparison")] +
            list(report.get("live_competitor_comparisons") or []))
            if x and x.get("alternative_requested_url") == url]
        price_crosscheck = "NOT_CROSSCHECKED_NO_DIRECT_SELLER_PRICE"
        if direct:
            checked = direct[0]
            page = checked.get("alternative") or {}
            meta = checked.get("alternative_source") or {}
            if (meta.get("page_sha256") and meta.get("price_status") == "SELLER_DECLARED"
                    and page.get("price") is not None
                    and page.get("currency") == currency):
                try:
                    current = _money(page["price"])
                except ValueError:
                    current = None
                if current is not None:
                    if current == price:
                        price_crosscheck = "AGREES_WITH_DIRECT_SELLER_PRICE"
                        comparison = "OBSERVATION_ALREADY_REPRESENTED_BY_DIRECT_SELLER_PAGE"
                    else:
                        price_crosscheck = "CONFLICTS_WITH_DIRECT_SELLER_PRICE"
                        comparison = "CONFLICTING_OBSERVED_AND_DIRECT_PRICE"
                    gap = None
        row = {
            "id": "market-lead-{}".format(index),
            "url": url,
            "origin": origin,
            "recorded_at": now,
            "observed_at_unverified": observed_at,
            "observed_title_unverified": title,
            "observation_method": capture_method,
            "price_evidence_method": price_evidence,
            "observed_price": str(price),
            "currency": currency,
            "condition_claim": condition,
            "gtin_claim_not_verified": gtin,
            "gtin_checksum_valid": bool(normal_gtin) if gtin else None,
            "same_gtin_claim_not_verified": (
                bool(normal_gtin and selected_gtin == normal_gtin) if gtin and selected_gtin
                else None),
            "comparison_status": comparison,
            "direct_seller_price_crosscheck": price_crosscheck,
            "difference_vs_selected_listed_price": gap,
            "source_page_downloaded_by_tracecart": False,
            "stock_verified": False,
            "independent_product_test": False,
            "payment_authorized": False,
            "research_questions": [
                "Can an authorized source confirm this exact listing's active price and availability?",
                "Does the seller identify the same exact model, condition and included accessories?",
                "Is there independent product testing or a reliable review of this exact variant?",
            ],
        }
        rows.append(row)
    result = deepcopy(report)
    branch = _node(
        "marketplace_leads", "Cheaper-looking marketplace leads requiring verification",
        "UNVERIFIED_OBSERVATIONS", {
            "count": len(rows),
            "potential_lower_price_leads": sum(
                row["comparison_status"] == "OBSERVED_LOWER_LISTED_PRICE_NOT_VERIFIED"
                for row in rows),
            "not_verified_by_tracecart": True,
            "not_included_in_source_qualified_comparisons": True,
            "not_a_checkout_or_purchase_recommendation": True,
        },
        [_node("marketplace_lead", row["url"], row["comparison_status"], row,
               [_node("follow_up", question, "OPEN", {
                   "lead_id": row["id"], "no_independent_evidence_yet": True,
               }, node_id="market-lead-question-{}-{}".format(i, j))
                for j, question in enumerate(row["research_questions"], 1)],
               node_id=row["id"])
         for i, row in enumerate(rows, 1)],
        node_id="cart-marketplace-leads")
    result["root"]["children"].insert(-1, branch)
    result["marketplace_leads"] = {
        "status": "UNVERIFIED_EXTERNAL_PRICE_LEADS",
        "observations": rows,
        "potential_lower_price_leads": branch["details"]["potential_lower_price_leads"],
        "source_qualified_comparisons": 0,
        "payment_authorized": False,
        "limitations": [
            "An observed search/browser price is not fetched or verified by TraceCart.",
            "The marketplace product identity, stock, price, condition and merchant may differ.",
            "Do not exclude a cheaper-looking lead merely because a marketplace returns HTTP 403.",
            "No ranking or checkout saving may be inferred from these observations.",
        ],
    }
    result["generated_at"] = now
    result["limitations"] = list(result.get("limitations", [])) + [
        "Marketplace observations are leads only, not independently verified offers."
    ]
    result.pop("sha256", None)
    result["sha256"] = sha256(json.dumps(
        result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return result
