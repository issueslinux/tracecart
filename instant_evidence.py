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
