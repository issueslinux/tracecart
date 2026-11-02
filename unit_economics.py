"""Source-qualified, exact price per wash; no guessed usage or retail price.

Only use a uniquely stated number of washes/doses and an actual numeric
seller-listed cart price. No derived comparison from weight alone or
product catalog titles with unknown prices.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

# Strong wash-cycle labels, in several EU languages.
CYCLE_PATTERNS = (
    r"(?<!\w)(\d{1,4})\s*(?:prań|pran|pra[ńn]|prania)(?!\w)",
    # Polish shop-title shorthand, e.g. "75pr" (75 prań).
    r"(?<!\w)(\d{1,4})\s*pr\.?(?!\w)",
    r"(?<!\w)(\d{1,4})\s*(?:washes|wash\s*loads|loads)(?!\w)",
    r"(?<!\w)(\d{1,4})\s*(?:doses|lavages|waschladungen|waschgänge)(?!\w)",
)
MAX_WASHES = 500


def extract_wash_count(title):
    if not isinstance(title, str) or len(title) > 300:
        return {"status": "MISSING_OR_INVALID", "washes": None}
    found = set()
    for expression in CYCLE_PATTERNS:
        for match in re.finditer(expression, title, re.I):
            v = int(match.group(1))
            if 1 <= v <= MAX_WASHES:
                found.add(v)
    if not found:
        return {"status": "NOT_DECLARED", "washes": None}
    if len(found) > 1:
        return {"status": "AMBIGUOUS_DECLARATION", "washes": None,
                "possible_counts": sorted(found)}
    return {"status": "COUNT_FROM_TITLE_UNVERIFIED", "washes": found.pop()}


def unit_cost(item, category):
    """Compute only seller-declared cost, never compare unavailable offers."""
    if category != "laundry_detergent":
        return {"status": "NOT_APPLICABLE", "cost_per_wash": None}
    count = extract_wash_count(item.get("title"))
    base = {
        "status": count["status"],
        "washes_declared_in_title": count.get("washes"),
        "currency": item.get("currency"),
        "seller_listed_price": item.get("price"),
        "cost_per_wash": None,
        "does_not_include": ["delivery", "discount eligibility", "actual dose",
                              "stain-removal performance", "water hardness"],
        "price_evidence": "current selected offer input, NOT confirmed checkout amount",
        "dose_evidence": "product title claim, NOT independently verified",
    }
    if count["status"] != "COUNT_FROM_TITLE_UNVERIFIED":
        return base
    try:
        price = Decimal(str(item.get("price")))
        if (not price.is_finite() or price <= 0 or
                item.get("currency") not in ("PLN", "USD", "EUR")):
            return base
        per = (price / count["washes"]).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP)
    except (ValueError, TypeError, InvalidOperation, ZeroDivisionError):
        return base
    base["status"] = "CALCULATED_FROM_SELLER_CLAIMS"
    base["cost_per_wash"] = str(per)
    return base
