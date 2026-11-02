"""Country-qualified, seller-declared product-plus-shipping comparison.

This is NOT a checkout total: payment fees, method eligibility and precise
buyer destination are unverified. Never rank non-equivalent products.
"""
from decimal import Decimal


def conditional_shipping_comparison(selected, alternative, selected_source,
                                    alternative_source, equivalent, country=None):
    result = {"status": "UNKNOWN", "buyer_country": country,
              "selected_product_plus_shipping": None,
              "alternative_product_plus_shipping": None,
              "lower_declared_subtotal": None, "difference": None,
              "final_checkout_total_verified": False,
              "payment_fees_verified": False}
    if not equivalent:
        result["status"] = "PRODUCT_EQUIVALENCE_NOT_ESTABLISHED"
        return result
    if country is None:
        result["status"] = "BUYER_COUNTRY_REQUIRED"
        return result
    if not isinstance(country, str) or len(country) != 2 or not country.isalpha():
        raise ValueError("Buyer country must be ISO 3166-1 alpha-2")
    country = country.upper()
    result["buyer_country"] = country
    claims = [source.get("structured_shipping_claim") or {}
              for source in (selected_source, alternative_source)]
    if any(c.get("status") != "SELLER_DECLARED_DESTINATION_CONDITIONAL" or
           c.get("destination_country") != country for c in claims):
        result["status"] = "SHIPPING_UNKNOWN_OR_DESTINATION_MISMATCH"
        return result
    if any(c.get("currency") != item.get("currency") or
           c.get("shipping_cost") is None or item.get("price") is None
           for c, item in zip(claims, (selected, alternative))):
        result["status"] = "SHIPPING_OR_PRICE_CURRENCY_MISMATCH"
        return result
    if selected["currency"] != alternative["currency"]:
        result["status"] = "DIFFERENT_CURRENCY_NO_FX"
        return result
    totals = [Decimal(item["price"]) + Decimal(claim["shipping_cost"])
              for item, claim in zip((selected, alternative), claims)]
    result.update({"status": "SELLER_DECLARED_SUBTOTALS_NOT_CHECKOUT_VERIFIED",
                   "selected_product_plus_shipping": str(totals[0]),
                   "alternative_product_plus_shipping": str(totals[1]),
                   "lower_declared_subtotal": ("selected" if totals[0] < totals[1]
                                                else "alternative" if totals[1] < totals[0]
                                                else "tie"),
                   "difference": str(abs(totals[0] - totals[1])),
                   "currency": selected["currency"]})
    return result
