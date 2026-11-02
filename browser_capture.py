"""Validate one explicit user-browser capture without treating it as API evidence.

A deliberately small bridge from a normal human-opened product page to the
existing unverified marketplace-lead tier. No unattended visits, network calls,
cookies, access-control bypasses, or payment operations.
"""
from datetime import datetime, timezone
import json
from product_intake import normalized_product_url

MAX_CAPTURE_BYTES = 3800
ALLOWED_METHODS = frozenset(("ACTIVE_TAB_SINGLE_PRODUCT_JSONLD", "USER_SELECTED_VISIBLE_PRICE"))
ALLOWED_CURRENCIES = frozenset(("PLN", "EUR", "USD"))
FIELDS = frozenset(("version", "method", "url", "price", "currency",
                    "observed_at", "title", "gtin_claim", "price_evidence"))


def parse_browser_capture(raw):
    """Return a strict, unverified marketplace observation for existing logic."""
    if type(raw) is not str or not 1 <= len(raw.encode("utf-8")) <= MAX_CAPTURE_BYTES:
        raise ValueError("Capture payload missing or too large")
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        raise ValueError("Capture is not JSON")
    if type(data) is not dict or set(data) != FIELDS or data.get("version") != 1:
        raise ValueError("Unsupported capture schema")
    if data["method"] not in ALLOWED_METHODS:
        raise ValueError("Capture must be explicitly user initiated")
    if data["currency"] not in ALLOWED_CURRENCIES:
        raise ValueError("Unsupported captured currency")
    if type(data["title"]) is not str or not 3 <= len(data["title"]) <= 180:
        raise ValueError("Invalid observed product title")
    if data["price_evidence"] not in ("UNIQUE_PRODUCT_JSONLD", "SELECTED_VISIBLE_TEXT"):
        raise ValueError("Price evidence missing")
    if ((data["method"] == "ACTIVE_TAB_SINGLE_PRODUCT_JSONLD") !=
            (data["price_evidence"] == "UNIQUE_PRODUCT_JSONLD")):
        raise ValueError("Capture source and price evidence disagree")
    stamp = data["observed_at"]
    if type(stamp) is not str or len(stamp) > 45:
        raise ValueError("Invalid capture timestamp")
    try:
        observed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Invalid capture timestamp")
    if observed.tzinfo is None or observed.year < 2020:
        raise ValueError("Capture timestamp must be timezone-aware")
    now = datetime.now(timezone.utc)
    if abs((now - observed.astimezone(timezone.utc)).total_seconds()) > 24 * 3600:
        raise ValueError("Browser capture must be recent (within 24 hours)")
    safe_url = normalized_product_url(data["url"])
    gtin = data["gtin_claim"]
    if gtin is not None and (type(gtin) is not str or len(gtin) not in (8, 12, 13, 14)
                            or not gtin.isascii() or not gtin.isdigit()):
        raise ValueError("Invalid claimed GTIN")
    return {
        "url": safe_url,
        "price": data["price"],
        "currency": data["currency"],
        "origin": "USER_BROWSER_ACTIVE_TAB_NOT_SERVER_VERIFIED",
        "observed_at": stamp,
        "gtin_claim": gtin,
        "condition": "UNKNOWN",
        "observed_title": data["title"],
        "observation_method": data["method"],
        "price_evidence_method": data["price_evidence"],
    }
