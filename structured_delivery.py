"""Conservative seller-declared shipping delivery windows from schema.org.

Only numeric handlingTime and transitTime QuantitativeValue day ranges are
accepted. No inferred carrier SLA, stock dispatch, or delivery guarantee.
"""
from decimal import Decimal, InvalidOperation


def _days(value):
    if not isinstance(value, dict):
        return None
    unit = value.get("unitCode") or value.get("unitText")
    if unit not in ("DAY", "d", "day", "days"):
        return None
    try:
        lo = Decimal(str(value["minValue"]))
        hi = Decimal(str(value["maxValue"]))
    except (KeyError, InvalidOperation, ValueError, TypeError):
        return None
    if (not lo.is_finite() or not hi.is_finite() or lo < 0 or
            hi < lo or hi > 365 or lo != int(lo) or hi != int(hi)):
        return None
    return int(lo), int(hi)


def delivery_window_claim(offer):
    unknown = {"status": "UNKNOWN", "min_days": None, "max_days": None,
               "source_field": None, "includes_handling": False}
    if not isinstance(offer, dict):
        return unknown
    details = offer.get("shippingDetails")
    if isinstance(details, dict):
        details = [details]
    if not isinstance(details, list) or len(details) != 1 or not isinstance(details[0], dict):
        return unknown
    detail = details[0]
    timing = detail.get("deliveryTime")
    if not isinstance(timing, dict):
        return unknown
    transit = _days(timing.get("transitTime"))
    handling = _days(timing.get("handlingTime"))
    if transit is None:
        return unknown
    # Transit-only estimates are not a complete delivery window.
    if handling is None:
        return {**unknown, "status": "TRANSIT_ONLY_NOT_END_TO_END",
                "transit_min_days": transit[0], "transit_max_days": transit[1]}
    return {"status": "SELLER_DECLARED_HANDLING_PLUS_TRANSIT_DAYS",
            "min_days": handling[0] + transit[0],
            "max_days": handling[1] + transit[1],
            "source_field": "offers.shippingDetails.deliveryTime",
            "includes_handling": True}
