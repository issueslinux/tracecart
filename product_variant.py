"""Fail-closed product-variant crosscheck independent of seller-declared GTIN.

A matching barcode is necessary but insufficient: marketplaces can attach
wrong variants or even another product to an otherwise valid GTIN. Only
explicit, unambiguous seller-title claims are compared. Missing fields
stay unknown, never guessed from EAN or marketing claims.
"""
import re
from decimal import Decimal, InvalidOperation

_TOKEN = {
    "brand": {
        "persil": r"\bpersil\b",
        "ariel": r"\bariel\b",
    },
    "fabric_use": {
        "colors": r"\b(?:colou?r|kolor(?:u|y|ów|ow|owych|owe|owy|owa|em)?|bunt|farbig)\b",
        "whites": r"\b(?:white|whites|bia(?:ł|l)(?:e|ego|ych|y|a|ą)?|weiss|weiß)\b",
    },
    "form": {
        "powder": r"\b(?:proszek|proszku|powder|pulver|waschpulver)\b",
        "liquid": r"\b(?:płyn|plyn|żel|zel|liquid|gel|flüssig|fluessig)\b",
        "capsules": r"\b(?:kapsułki|kapsulki|capsules|caps|pods)\b",
    },
}
_WEIGHT = re.compile(r"(?<![\w\d])([0-9]{1,5}(?:[.,][0-9]{1,3})?)\s*(kg|g)(?!\w)", re.I)


def _title_signals(title):
    text = str(title or "").casefold()[:250]
    signals = {}
    ambiguous = []
    for kind, values in _TOKEN.items():
        found = sorted(name for name, pattern in values.items()
                       if re.search(pattern, text, flags=re.I))
        signals[kind] = found[0] if len(found) == 1 else None
        if len(found) > 1:
            ambiguous.append(kind)
    weights = set()
    for match in _WEIGHT.finditer(text):
        try:
            value = Decimal(match.group(1).replace(",", "."))
            grams = value * (1000 if match.group(2).casefold() == "kg" else 1)
            if Decimal("1") <= grams <= Decimal("100000"):
                weights.add(grams)
        except InvalidOperation:
            pass
    signals["net_weight_grams"] = (format(next(iter(weights)).normalize(), "f")
                                    if len(weights) == 1 else None)
    if len(weights) > 1:
        ambiguous.append("net_weight_grams")
    return signals, sorted(ambiguous)


def check_variant_consistency(selected_title, alternative_title, category):
    """Detect concrete contradictions, not semantic similarity or quality.

    UNKNOWN means no explicit contradiction was found, not equivalence.
    For non-detergent categories, the specialized gate is not applied.
    """
    if category != "laundry_detergent":
        return {"status": "NOT_APPLICABLE", "conflicts": [],
                "selected_signals": {}, "alternative_signals": {}}
    left, left_ambiguous = _title_signals(selected_title)
    right, right_ambiguous = _title_signals(alternative_title)
    conflicts = []
    for key in ("brand", "fabric_use", "form", "net_weight_grams"):
        if left[key] is not None and right[key] is not None and left[key] != right[key]:
            conflicts.append({
                "attribute": key, "selected_claim": left[key],
                "alternative_claim": right[key],
                "reason": "EXPLICIT_SELLER_TITLE_CONTRADICTION",
            })
    if left_ambiguous or right_ambiguous:
        status = "AMBIGUOUS_TITLE_VARIANT"
    elif conflicts:
        status = "CONFLICTING_VARIANT_CLAIMS"
    else:
        status = "NO_EXPLICIT_TITLE_CONTRADICTION"
    return {
        "status": status, "conflicts": conflicts,
        "selected_signals": left, "alternative_signals": right,
        "selected_ambiguous_fields": left_ambiguous,
        "alternative_ambiguous_fields": right_ambiguous,
        "equivalence_proven": False,
        "evidence_scope": "seller titles only; a matching GTIN remains seller-declared",
    }
