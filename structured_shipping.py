"""Conservative parsing of product-scoped schema.org OfferShippingDetails.

Only an explicit, single shipping rate and destination country is usable.
No inferred free delivery, buyer eligibility, or checkout totals.
"""
from decimal import Decimal, InvalidOperation


def _country(value):
    if isinstance(value, str):
        return value.upper() if len(value) == 2 and value.isalpha() else None
    if isinstance(value, dict):
        return _country(value.get("addressCountry")) or _country(value.get("name"))
    return None


def shipping_claim(offer):
    unknown = {"status": "UNKNOWN", "shipping_cost": None,
               "currency": None, "destination_country": None,
               "shipping_method": None, "source_field": None}
    if not isinstance(offer, dict):
        return unknown
    details = offer.get("shippingDetails")
    if isinstance(details, dict):
        details = [details]
    if not isinstance(details, list) or len(details) != 1 or not isinstance(details[0], dict):
        return unknown
    detail = details[0]
    destinations = detail.get("shippingDestination")
    if not isinstance(destinations, dict):
        return unknown
    country = _country(destinations.get("addressCountry"))
    rate = detail.get("shippingRate")
    if not country or not isinstance(rate, dict):
        return unknown
    if rate.get("minValue") is not None or rate.get("maxValue") is not None:
        return unknown
    currency = rate.get("currency")
    try:
        amount = Decimal(str(rate.get("value")))
    except (InvalidOperation, TypeError, ValueError):
        return unknown
    if (currency not in ("PLN", "EUR", "USD") or not amount.is_finite()
            or amount < 0 or amount > 100000 or amount.as_tuple().exponent < -2):
        return unknown
    return {"status": "SELLER_DECLARED_DESTINATION_CONDITIONAL",
            "shipping_cost": str(amount.quantize(Decimal("0.01"))),
            "currency": currency, "destination_country": country,
            "shipping_method": None, "source_field": "offers.shippingDetails.shippingRate.value"}
