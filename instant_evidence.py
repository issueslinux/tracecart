"""Fast, source-constrained *current* assessment without a model request.

Build from the very same in-RAM graph/projection as the live SVG. The
persisted audit and any prior Qwen classification remain unchanged.
"""
from model_verdict import insufficient_verdict


def current_assessment(projection, graph, evidence_status):
    if not (projection.get("offers") or graph.get("nodes")):
        return None
    result = insufficient_verdict(graph, projection=projection)
    return {
        "status": ("CURRENT" if evidence_status=="COMPLETE" else "PRELIMINARY"),
        "origin": "DETERMINISTIC_CURRENT_EVIDENCE_NOT_LLM",
        "summary": result["summary"],
        "observations": result["observations"],
        "purchase_insights": result["purchase_insights"],
        "priority_checks": priority_actions(projection,graph,result["purchase_insights"]),
        "next_step": result["next_step"],
        "verification": result["verification"],
        "payment_authorized": False,
        "evidence_status": evidence_status,
        "note": ("Recomputed after the most recent recorded source changes. "
                 "Browser declarations, index quotes and coupon codes are "
                 "not verified checkout prices."),
    }


def semantic_review_needed(projection, graph):
    """Conservative *reason to spend inference*, not a trust decision.

    Numeric price anomalies, absent checkout totals and missing documentation
    are handled by transparent rules; Qwen cannot obtain those missing facts.
    Inference is allowed only if there are actual documentary discrepancies,
    or technically different alternatives with sourced specifications.
    """
    if (graph.get("stats") or {}).get("unresolved_source_discrepancies",0):
        return True
    from purchase_insights import build_purchase_insights
    report=build_purchase_insights(projection,graph)
    documented=((graph.get("stats") or {}).get("documented_product_declarations",0)+
                (graph.get("stats") or {}).get("seller_page_declarations",0))
    return bool(documented and
                report.get("status")=="FUNCTIONAL_INDEX_LEADS_NEED_SPEC_VERIFICATION" and
                (report.get("options") or report.get("tradeoffs")))


def priority_actions(projection,graph,insights):
    """Unresolved purchase checks ranked by evidence risk; not facts."""
    actions=[]
    stats=graph.get("stats") or {}
    def add(kind,oid,question,reason):
        if kind not in {x["kind"] for x in actions}:
            actions.append({"kind":kind,"offer_id":oid,"question":question,
                            "reason":reason,"verified":False,
                            "origin":"DETERMINISTIC_EVIDENCE_GAP"})
    if stats.get("unresolved_source_discrepancies"):
        add("DOCUMENT_CONFLICT","offer-0",
            "Which original document confirms the exact conflicting specification?",
            "Published disagreements need independent source checks.")
    anomalies=insights.get("suspicious_price_quotes") or []
    if anomalies:
        first=anomalies[0]
        add("INDEX_PRICE_ANOMALY",first.get("offer_id") or "offer-0",
            "Is the indexed "+str(first.get("indexed_price") or "?")+
            " price a complete item price rather than financing?",
            "Very low index quotes are not verified checkout totals.")
    code=insights.get("promotion_code")
    if code:
        add("CONDITIONAL_COUPON","offer-0",
            "Does coupon "+str(code)[:40]+" apply to the delivered checkout total?",
            "Browser-displayed promotions still need checkout confirmation.")
    comparisons=(insights.get("options") or [])+(insights.get("tradeoffs") or [])
    for option in comparisons[:3]:
        differences=(option.get("different_features") or
                     option.get("unconfirmed_features") or [])
        if differences:
            add("TECHNICAL_DIFFERENCE",option.get("offer_id") or "offer-0",
                "What documented feature differs: "+str(differences[0])[:75]+"?",
                "Search-title technical claims need confirmation.")
            break
    if not stats.get("verified_checkout_prices"):
        add("DELIVERED_TOTAL","offer-0",
            "What is the final delivered checkout price after fees?",
            "No checkout receipt for the exact product has been verified.")
    return actions[:4]
