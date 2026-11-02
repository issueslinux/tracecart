"""Conservative, source-attributed transport evidence for comparison reports.

No network calls, no inferred shipping fees, no invented delivery times.
Inputs are seller/listing claims, never independently verified checkout totals.
"""
from decimal import Decimal
from decision_tree import _dec
from product_intake import validate_product_url

METHODS = {"courier", "parcel_locker", "pickup", "unspecified_delivery"}


def normalize_fulfillment(value, currency, product_price):
    unknown = {"status": "UNKNOWN", "method": None, "shipping_cost": None,
               "eta_min_days": None, "eta_max_days": None, "source_url": None,
               "product_plus_shipping": None, "final_checkout_total_verified": False,
               "payment_fees_known": False}
    if value is None:
        return unknown
    expected = {"method", "cost", "currency", "eta_min_days",
                "eta_max_days", "source_url", "evidence_status"}
    if type(value) is not dict or set(value) != expected:
        raise ValueError("Fulfillment requires method, cost, currency, ETA, source and evidence status")
    method = value["method"]
    if method not in METHODS or value["evidence_status"] != "SELLER_DECLARED":
        raise ValueError("Only source-attributed seller-declared fulfillment is accepted")
    url = validate_product_url(value["source_url"])
    low, high = value["eta_min_days"], value["eta_max_days"]
    if (low is None) != (high is None):
        raise ValueError("ETA range requires both endpoints or neither")
    if low is not None and (type(low) is not int or type(high) is not int or
                            low < 0 or low > high or high > 365):
        raise ValueError("ETA must be a plausible nonnegative day range")
    raw_cost = value["cost"]
    if raw_cost is not None and method == "pickup":
        raise ValueError("Pickup travel costs are not merchant shipping costs")
    if raw_cost is None:
        if value["currency"] is not None:
            raise ValueError("Unknown shipping cost must have unknown currency")
        shipping = None
    else:
        if value["currency"] != currency:
            raise ValueError("Shipping currency must match product currency")
        shipping = _dec(raw_cost)
    subtotal = (str(Decimal(product_price) + Decimal(shipping))
                if shipping is not None else None)
    return {"status": "SELLER_DECLARED_NOT_CHECKOUT_VERIFIED",
            "method": method, "shipping_cost": shipping,
            "eta_min_days": low, "eta_max_days": high,
            "source_url": url, "product_plus_shipping": subtotal,
            "final_checkout_total_verified": False, "payment_fees_known": False,
            "interpretation": ("Pickup requires buyer travel/time costs, which are unknown."
                               if method == "pickup" else
                               "Seller-claimed shipping and ETA; checkout fees, destination "
                               "and eligibility remain unverified.")}
