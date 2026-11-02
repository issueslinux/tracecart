"""Evidence-first purchase questions, separated by decision dimension."""
from decimal import Decimal, InvalidOperation

QUESTION_GROUPS = {
    "seller": ("Who is the legal seller and what are their return and complaint terms?", "Are independent seller ratings current and attributable?"),
    "product": ("Do GTIN, model, version and included accessories match?", "What are the warranty and product-condition claims?"),
    "offer": ("Is the listed price current and is stock explicitly declared?", "Are discounts conditional on membership or quantity?"),
    "transport": ("What is delivery cost for the buyer's destination and chosen method?", "What is the earliest and latest promised delivery date?", "Is pickup available and what travel cost does it impose?"),
    "payment": ("Which payment methods are accepted and what fees apply?", "What buyer protections and refund conditions apply?"),
}


def _money(value):
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid monetary amount")
    if not amount.is_finite() or amount < 0:
        raise ValueError("Amounts must be finite and nonnegative")
    return amount


def fulfillment_assessment(price, currency, shipping=None, payment_fee=None,
                           delivery_days_min=None, delivery_days_max=None):
    """Never convert missing shipping/fees to zero or invent transit times."""
    base, freight, fee = (_money(v) for v in (price, shipping, payment_fee))
    for days in (delivery_days_min, delivery_days_max):
        if days is not None and (type(days) is not int or days < 0):
            raise ValueError("Delivery days must be nonnegative integers")
    if (delivery_days_min is not None and delivery_days_max is not None
            and delivery_days_min > delivery_days_max):
        raise ValueError("Invalid delivery range")
    complete = all(v is not None for v in (base, freight, fee))
    return {"currency": currency, "listed_price": str(base) if base is not None else None,
            "shipping_cost": str(freight) if freight is not None else None,
            "payment_fee": str(fee) if fee is not None else None,
            "delivered_total": str(base + freight + fee) if complete else None,
            "total_status": "COMPLETE_DECLARED_INPUTS" if complete else "UNKNOWN_COST_COMPONENTS",
            "delivery_days_min": delivery_days_min, "delivery_days_max": delivery_days_max,
            "delivery_time_status": "DECLARED_RANGE" if delivery_days_min is not None and delivery_days_max is not None else "UNKNOWN_OR_PARTIAL",
            "not_checkout_verified": True}


def purchase_questions():
    return [{"group": group, "questions": list(questions), "answers_verified": False}
            for group, questions in QUESTION_GROUPS.items()]
