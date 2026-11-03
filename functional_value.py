"""Conditional value leads when a known product category has no comparable title specs.

These are *leads*, not proven equivalent products or live checkout prices.
Uses explicit seller-provided SKU and listing-title function/voltage tokens.
No external network calls, model hallucinations or customer questions.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
import unicodedata
from similar_tier import category_of, read_specs

_STOP = frozenset((
    "kompresor", "laptop", "notebook", "pompa", "pompka", "urzadzenie",
    "produkt", "elektryczny", "akumulatorowy", "akumulatorowa", "akumulatorowe",
    "ryobi", "one", "do", "the", "for", "with", "szt", "zestaw",
    "nowy", "new", "solo", "bez", "cena", "w", "i", "na",
))


def _norm(text):
    value = unicodedata.normalize("NFKD", str(text or "").casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.replace("ł", "l")


def _tokens(title):
    return {t for t in re.findall(r"[a-z0-9]+", _norm(title))
            if len(t) >= 3 and t not in _STOP}


def _model_token(value):
    token = re.sub(r"[^a-z0-9]", "", _norm(value))
    return token if len(token) >= 6 and re.search(r"\d", token) else None


def _models(title):
    # Distinct model designators, not bare voltages or product category words.
    parts = re.findall(r"(?<![a-z0-9])([a-z]{1,5}\d{1,5}[a-z0-9]{0,6}"
                       r"(?:[- ]\d{1,4}[a-z0-9]{0,4})?)(?![a-z0-9])",
                       _norm(title))
    return {_model_token(p) for p in parts} - {None}


def _price(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).replace(" ", "").replace(",", "."))
        return number if number.is_finite() and Decimal("0.01") <= number <= Decimal("1000000") else None
    except (TypeError, ValueError, InvalidOperation):
        return None


def functional_leads(projection, selected_price=None, selected_currency=None):
    """Extract functionally relevant index leads, preserving missing-evidence gates.

    Source SKU is used only to match a title string, not to assert verified
    identity. A second model qualifies only when a distinctive function term
    and a declared operating-system token (e.g. 18V) both match, or two
    distinctive terms match. This prevents mere category/brand matches.
    """
    offers = projection.get("offers") or []
    if not offers:
        return []
    base = str(offers[0].get("title") or projection.get("title") or "")
    category = category_of(base)
    if category in ("UNKNOWN", "ACCESSORY"):
        return []
    source = projection.get("selected_source_intake") or {}
    source_model = _model_token(source.get("sku"))
    base_models = _models(base)
    if source_model:
        base_models.add(source_model)
    base_tokens = _tokens(base)
    base_function = {t for t in base_tokens if not re.fullmatch(r"\d+[a-z]{0,2}", t)
                     and not re.fullmatch(r"\d+v", t)}
    rows = []
    seen = set()
    for offer in offers[1:]:
        if not isinstance(offer, dict):
            continue
        title = str(offer.get("title") or "")
        if category_of(title) != category:
            continue
        currency = str(offer.get("currency") or "").upper()
        price = _price(offer.get("indexed_price"))
        if price is None or currency not in ("PLN", "EUR", "USD"):
            continue
        if selected_currency and currency != selected_currency:
            continue
        tokens = _tokens(title)
        selected_volts = set(re.findall(r"\b\d{1,3}\s*v\b", _norm(base)))
        candidate_volts = set(re.findall(r"\b\d{1,3}\s*v\b", _norm(title)))
        if selected_volts and candidate_volts and not (
                {x.replace(" ", "") for x in selected_volts} &
                {x.replace(" ", "") for x in candidate_volts}):
            continue
        candidate_models = _models(title)
        exact_model = bool(base_models & candidate_models)
        shared_function = base_function & tokens
        matching_voltage = {t for t in (base_tokens & tokens)
                            if re.fullmatch(r"\d{1,3}v", t)}
        # Same source-model code is stronger than category keywords.
        # Otherwise require meaningful function evidence, not brand + voltage.
        functional = (bool(shared_function) and bool(matching_voltage)) or (
            len(shared_function) >= 2)
        if not exact_model and not functional:
            continue
        signature = (title.casefold(), str(price), currency)
        if signature in seen:
            continue
        seen.add(signature)
        matched = (["Same model code as the selected seller's SKU (title claim only)"]
                   if exact_model else [])
        matched += ["Shared advertised function: " + x
                    for x in sorted(shared_function)[:2]]
        matched += ["Advertised operating voltage: " + x.upper()
                    for x in sorted(matching_voltage)[:1]]
        row = {
            "offer_id": offer.get("id"),
            "title": title[:185],
            "price": str(price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "currency": currency,
            "price_source": "SEARCH_INDEX_QUOTE_NOT_CHECKOUT",
            "source_url": offer.get("url"),
            "has_direct_url": bool(offer.get("url")),
            "tier": ("SAME_MODEL_CODE_INDEX_LEAD" if exact_model
                     else "FUNCTIONAL_TITLE_LEAD_NEEDS_SPEC_CHECK"),
            "matched_features": matched,
            "different_features": ([] if exact_model else
                ["Different model or insufficient evidence of identical configuration"]),
            "unconfirmed_features": [
                "Actual performance, fit, included accessories and delivered price not confirmed"
            ],
            "identity_verified": False,
            "checkout_verified": False,
            "value_status": "CANDIDATE_NOT_VERIFIED",
            "vs_index_median": "Conditional lead based on listing title; not a measured functional equivalent.",
        }
        if selected_price is not None:
            difference = selected_price - price
            if difference <= 0:
                continue  # Not a cheaper lead against the observed input price.
            row["relative_to_selected_price"] = str(difference.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP)) + " " + currency
            row["vs_selected_price"] = "below selected seller price by " + row["relative_to_selected_price"]
        rows.append((row, price))
    # A usable retailer URL is more actionable than an unattached search card.
    # Within each access tier prefer the lowest indexed price.
    rows.sort(key=lambda pair: (not pair[0]["has_direct_url"], pair[1],
                                pair[0]["offer_id"] or ""))
    return [row for row, _ in rows[:6]]
