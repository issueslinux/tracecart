"""Explain trade-offs between multiple actual offers without inventing a 'winner'.

The engine reports *relative prices*, explicit like-for-like specifications,
conditional utility and missing seller facts. It never guesses product quality
from price/specification alone, and it never authorizes purchases.
Every offer, question and provenance remains in the full evidence tree.
"""
from decimal import Decimal
from hashlib import sha256
import json
import re

from decision_tree import _dec, _id, _safe_url, _short, analyze, _node
from fulfillment import normalize_fulfillment

MAX_OPTIONS = 12
MAX_METRICS = 24
USED_QUESTIONS = [
    "What is the battery health or measured capacity for this exact unit (if applicable)?",
    "Has this exact unit been repaired, damaged or had parts replaced?",
    "Can the seller provide photos and a working-condition test of the actual unit?",
    "What return rights and warranty terms apply to this used offer?",
    "Is the original purchase proof or serial/model identification available?",
]


def _number(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,8}(?:\.[0-9]{1,4})?", value):
        raise ValueError("Comparable metric must be a nonnegative numeric string")
    return Decimal(value)


def _metric_name(name):
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,35}", name):
        raise ValueError("Metric keys must be short stable identifiers")
    return name


def _format_pct(percent):
    return "{}%".format(percent.quantize(Decimal("0.1")))


def compare(payload):
    """Produce a comparison + a faithful, auditable decision tree.

    Comparisons are possible only between same-currency offers and the same
    explicitly named metric/unit; unknowns remain unknown.
    """
    if type(payload) is not dict or set(payload) != {"goal", "category", "offers"}:
        raise ValueError("Expected goal, category and offers")
    goal = _short(payload["goal"], 300)
    category = _short(payload["category"], 80)
    options = payload["offers"]
    if type(options) is not list or not 2 <= len(options) <= MAX_OPTIONS:
        raise ValueError("Comparison requires 2..12 offers")
    original_ids = set()
    normalized = []
    evidence_offers = []
    currencies = set()
    for option in options:
        allowed = {"id", "title", "price", "currency", "url", "condition", "metrics"}
        if type(option) is not dict or not allowed.issubset(option) or set(option) - allowed - {"fulfillment"}:
            raise ValueError("Unexpected or missing offer fields")
        oid = _id(option["id"])
        if oid in original_ids:
            raise ValueError("Repeated offer identifier")
        original_ids.add(oid)
        title = _short(option["title"], 180)
        currency = option["currency"]
        if currency not in ("PLN", "USD", "EUR"):
            raise ValueError("Only PLN/USD/EUR supported")
        currencies.add(currency)
        price = _dec(option["price"])
        source = _safe_url(option["url"])
        fulfillment = normalize_fulfillment(option.get("fulfillment"), currency, price)
        condition = option["condition"]
        if condition not in ("new", "used", "refurbished", "unknown"):
            raise ValueError("Condition must be new/used/refurbished/unknown")
        metrics = option["metrics"]
        if type(metrics) is not dict or len(metrics) > MAX_METRICS:
            raise ValueError("Expected at most 24 quantitative metrics")
        clean_metrics = {}
        questions = []
        for key, value in metrics.items():
            _metric_name(key)
            if type(value) is not dict or set(value) != {"label", "value", "unit", "benefit", "source_url"}:
                raise ValueError("Metric needs label, value, unit, benefit, source_url")
            label = _short(value["label"], 70)
            number = _number(value["value"])
            unit = _short(value["unit"], 18)
            benefit = value["benefit"]
            if benefit not in ("higher", "lower", "context_dependent"):
                raise ValueError("Unknown interpretation of metric")
            url = _safe_url(value["source_url"])
            clean_metrics[key] = {
                "label": label, "value": str(number), "unit": unit,
                "benefit": benefit, "source_url": url,
                "provenance": "source_declared_not_independently_validated",
            }
            questions.append({
                "id": "metric_" + key,
                "text": "Is the source-declared {} ({}) reliable for this offer?".format(label, unit),
                "importance": 3,
                "evidence": [{
                    "id": "spec_{}_{}".format(oid, key), "stance": "supports",
                    "url": url, "source_type": "listing",
                    "excerpt": "Offer declares {}: {} {}".format(label, str(number), unit),
                    "observation": "Unverified offer specification; not an independent test",
                }],
            })
        # Always attach price provenance, not an imagined verified transaction amount.
        questions.append({
            "id": "listed_price",
            "text": "Is the currently advertised price confirmed including delivery and fees?",
            "importance": 5,
            "evidence": [{
                "id": "price_" + oid, "stance": "supports", "url": source,
                "source_type": "listing",
                "excerpt": "Listing declares {} {} before unverified shipping/fees.".format(price, currency),
                "observation": "Seller's published price, not final total checkout price",
            }],
        })
        normalized.append({
            "id": oid, "title": title, "currency": currency, "price": Decimal(price),
            "condition": condition, "url": source, "metrics": clean_metrics,
            "fulfillment": fulfillment,
        })
        evidence_offers.append({
            "id": oid, "title": title, "price": price, "currency": currency,
            "url": source, "questions": questions,
        })
    if len(currencies) != 1:
        raise ValueError("Never compare prices across currencies without a verified FX rate")
    from decision_tree import _node as mk_node
    report = analyze({"goal": goal, "category": category, "offers": evidence_offers})
    comparison = {
        "type": "conditional_multi_option_comparison",
        "currency": next(iter(currencies)),
        "no_forced_winner": True,
        "prices_are_listing_claims": True,
        "no_automatic_payment": True,
        "options": [],
        "pairwise": [],
    }
    for o in normalized:
        concerns = []
        if o["condition"] in ("used", "refurbished"):
            concerns = list(USED_QUESTIONS)
        elif o["condition"] == "unknown":
            concerns = ["Can the seller confirm whether the product is new, refurbished or used?"]
        record = {
            "offer_id": o["id"], "title": o["title"], "price": str(o["price"]),
            "currency": o["currency"], "condition": o["condition"],
            "fulfillment": o["fulfillment"],
            "advantages": [], "limitations": [],
            "seller_questions": concerns,
            "unknowns": ["Actual total cost including delivery/fees is unverified.",
                         "Independent confirmation of specification claims is missing."],
        }
        if o["fulfillment"]["product_plus_shipping"] is not None:
            record["unknowns"][0] = "Payment fees and final checkout total remain unverified."
        if concerns:
            record["unknowns"].append("Used/refurbished condition and seller assurances are unverified.")
        comparison["options"].append(record)
        # Append seller questions to the full auditable decision tree, not a detached summary.
        tree_offer = next(x for x in report["root"]["children"]
                          if x["kind"] == "offer" and x["details"]["offer_id"] == o["id"])
        tree_offer["children"].append(mk_node(
            "fulfillment", "Delivery and transport evidence", o["fulfillment"]["status"],
            o["fulfillment"], node_id="fulfillment-{}".format(o["id"])))
        for index, question in enumerate(concerns):
            tree_offer["children"].append(mk_node(
                "follow_up", question, "OPEN",
                {"origin": "used_offer_due_diligence",
                 "target": "seller_or_listing_evidence", "offer_id": o["id"]},
                node_id="seller-question-{}-{}".format(o["id"], index)))
    for i, left in enumerate(normalized):
        for right in normalized[i + 1:]:
            if left["price"] == 0:
                increase = None
            else:
                increase = _format_pct((right["price"] - left["price"]) *
                                       Decimal(100) / left["price"])
            if right["price"] == 0:
                saving = None
            else:
                saving = _format_pct((right["price"] - left["price"]) *
                                     Decimal(100) / right["price"])
            metric_diffs = []
            for key in sorted(set(left["metrics"]) | set(right["metrics"])):
                a, b = left["metrics"].get(key), right["metrics"].get(key)
                if not a or not b:
                    metric_diffs.append({
                        "metric": key, "status": "NOT_COMPARABLE_MISSING_DATA",
                        "missing_for": left["id"] if not a else right["id"]})
                    continue
                if (a["unit"] != b["unit"] or a["benefit"] != b["benefit"] or
                        a["label"].casefold() != b["label"].casefold()):
                    metric_diffs.append({"metric": key, "status": "NOT_COMPARABLE_MISMATCH"})
                    continue
                va, vb = Decimal(a["value"]), Decimal(b["value"])
                relation = "equal" if va == vb else "higher" if va > vb else "lower"
                metric_diffs.append({
                    "metric": key, "label": a["label"], "unit": a["unit"],
                    "left_value": a["value"], "right_value": b["value"],
                    "right_vs_left": "equal" if va == vb else "higher" if vb > va else "lower",
                    "left_vs_right": relation,
                    "benefit": a["benefit"], "status": "LISTING_DECLARED_COMPARISON",
                    "conditional_utility": (
                        "The larger value is not automatically more useful; benefit depends "
                        "on workloads and actual demand."
                        if a["benefit"] in ("higher", "context_dependent") else
                        "Lower numeric value is not automatically a better overall purchase."
                    ),
                    "source_urls": [a["source_url"], b["source_url"]],
                })
            left_total = left["fulfillment"]["product_plus_shipping"]
            right_total = right["fulfillment"]["product_plus_shipping"]
            transport_difference = (str(Decimal(right_total) - Decimal(left_total))
                                    if left_total is not None and right_total is not None
                                    else None)
            pair = {
                "right_minus_left_product_plus_shipping": transport_difference,
                "transport_comparison_status": (
                    "CONDITIONAL_SELLER_DECLARED_PRODUCT_PLUS_SHIPPING"
                    if transport_difference is not None else "UNKNOWN_TRANSPORT_COST"),
                "delivery_time_comparison": {
                    "left_eta_days": [left["fulfillment"]["eta_min_days"],
                                      left["fulfillment"]["eta_max_days"]],
                    "right_eta_days": [right["fulfillment"]["eta_min_days"],
                                       right["fulfillment"]["eta_max_days"]],
                    "status": "SELLER_CLAIMS_NOT_DELIVERY_GUARANTEE"},
                "left_offer": left["id"], "right_offer": right["id"],
                "left_price": str(left["price"]), "right_price": str(right["price"]),
                "right_vs_left_pct": increase, "left_cheaper_vs_right_pct": saving,
                "price_difference": str(right["price"] - left["price"]),
                "price_reference": "right relative to LEFT price (right_vs_left_pct); "
                                   "left relative to RIGHT price (left_cheaper_vs_right_pct)",
                "metric_differences": metric_diffs,
                "interpretation": ("These are relative seller-listed prices and specs; "
                    "a higher specification may offer headroom that will not be used. "
                    "No universal winner or overall value score is asserted."),
            }
            comparison["pairwise"].append(pair)
    report["comparison_summary"] = comparison
    # Research incompleteness is not a purchasing verdict. Do not force "ABSTAIN"
    # as the result of comparison, while continuing to block any payment.
    final_decision = report["root"]["children"][-1]
    final_decision["status"] = "NO_FORCED_WINNER"
    final_decision["title"] = "Conditional comparison, not a purchase instruction"
    final_decision["details"]["recommendation"] = (
        "No universal winner. Review prices, specification trade-offs, usage "
        "uncertainty and seller questions before choosing."
    )
    final_decision["details"]["eligible_for_payment"] = False
    report["root"]["children"].insert(-1, mk_node(
        "tradeoffs", "Conditional trade-offs between offers", "INFORMATIONAL",
        {"comparisons": comparison["pairwise"],
         "unknowns_by_offer": {x["offer_id"]: x["unknowns"]
                               for x in comparison["options"]},
         "seller_questions_by_offer": {x["offer_id"]: x["seller_questions"]
                                      for x in comparison["options"]},
         "no_forced_winner": True},
        node_id="comparison-tradeoffs"))
    report["provenance"] = (
        "Direct numerical comparison of supplied listing claims; source pages "
        "were not independently retrieved or verified by this operation.")
    report.pop("sha256", None)
    report["sha256"] = sha256(json.dumps(report, sort_keys=True,
                                        separators=(",", ":")).encode("utf-8")).hexdigest()
    return report
