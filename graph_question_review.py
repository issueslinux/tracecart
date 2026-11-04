"""Bounded graph-delta to local LLM questions. Never produces verified facts."""
from hashlib import sha256
import json
import re

MAX_RUNS=2
MAX_QUESTIONS=3
SOURCE_TYPES={"seller_declaration","source_declaration","reference_observation",
              "source_disagreement"}
ANCHOR_TYPES=SOURCE_TYPES|{"verification_gap"}


def graph_context(projection,graph):
    """Whitelisted source nodes only: no HTML, URLs, credentials or model writes."""
    offers=[{"id":n["id"],"name":str(n.get("label") or "")[:75]}
            for n in graph.get("nodes",[]) if n.get("type")=="offer"][:4]
    facts=[];gaps=[]
    owners={e.get("to"):e.get("from") for e in graph.get("edges",[])
            if str(e.get("from") or "").startswith("offer-")}
    for n in graph.get("nodes",[]):
        kind=n.get("type")
        if kind in SOURCE_TYPES and len(facts)<7:
            facts.append({"id":n["id"],"kind":kind,"offer_id":owners.get(n["id"]),
                          "claim":str(n.get("label") or "")[:80],
                          "value":str(n.get("value") or "")[:35]})
        elif kind=="verification_gap" and len(gaps)<5:
            gaps.append({"id":n["id"],"offer_id":n.get("offer_id"),
                         "question":str(n.get("label") or "")[:110]})
    from purchase_insights import build_purchase_insights
    insights=build_purchase_insights(projection,graph)
    candidates=(insights.get("options") or [])+(insights.get("tradeoffs") or [])
    state={"product":str(projection.get("title") or "")[:90],
           "offers":offers,"source_claims_not_verified":facts,
           "existing_open_gaps":gaps,
           "purchase":{"status":insights.get("status"),
                       "seller_observed_price":insights.get("selected_price"),
                       "coupon_requires_checkout":bool(insights.get("promotion_code")),
                       "peers":[{"offer_id":c.get("offer_id"),
                                 "claimed_price":c.get("price"),
                                 "title":str(c.get("title") or "")[:75],
                                 "tradeoffs":c.get("different_features",[])[:2]}
                                for c in candidates[:2]]}}
    # Fingerprint ALL material source nodes, not only the seven sent to
    # the model. New seller evidence should invalidate an old question.
    revisions=[(n.get("id"),n.get("type"),n.get("value"),
                n.get("status"),n.get("source_sha256"))
               for n in graph.get("nodes",[])
               if n.get("type") in SOURCE_TYPES|{"verification_gap"}][:256]
    digest=sha256(json.dumps([state,revisions],sort_keys=True,
                   ensure_ascii=False,separators=(",",":"),default=str)
                  .encode("utf8")).hexdigest()
    return state,digest


def eligible(state):
    return bool(state["offers"] and state["existing_open_gaps"] and
                state["source_claims_not_verified"])


def ask_local_llm(state,request=None):
    from graph_model_question import ask_graph_question
    return ask_graph_question(state,request=request)


def attach_model_questions(graph,review):
    """Render unverified question nodes, only if their original anchors remain."""
    if review.get("status")!="COMPLETE":return graph
    nodes={n.get("id"):n for n in graph.get("nodes",[])}
    additions=[]
    for row in (review.get("questions") or [])[:MAX_QUESTIONS]:
        oid=row.get("offer_id");anchor=row.get("anchor_id")
        if (nodes.get(oid) or {}).get("type")!="offer":continue
        if (nodes.get(anchor) or {}).get("type") not in ANCHOR_TYPES:continue
        question=str(row.get("question") or "")
        if not 22<=len(question)<=220 or not question.endswith("?"):continue
        key="graph-question:"+sha256(
            (oid+"|"+anchor+"|"+question).encode("utf8")).hexdigest()[:16]
        additions.append((key,oid,anchor,question))
    if not additions:return graph
    graph={**graph,"nodes":list(graph.get("nodes",[])),
           "edges":list(graph.get("edges",[])),
           "stats":dict(graph.get("stats") or {}),
           "offer_details":{k:dict(v) for k,v in
                            (graph.get("offer_details") or {}).items()}}
    for key,oid,anchor,question in additions:
        graph["nodes"].append({
            "id":key,"type":"verification_gap","label":question,
            "priority":"MODEL_PROPOSAL","offer_id":oid,
            "status":"OPEN_UNVERIFIED_MODEL_QUESTION",
            "origin":"LOCAL_LLM_QUESTION_NOT_EVIDENCE"})
        graph["edges"].extend([
            {"id":"edge:"+key,"from":oid,"to":key,
             "relation":"MODEL_PROPOSES_UNVERIFIED_QUESTION"},
            {"id":"edge:anchor:"+key,"from":anchor,"to":key,
             "relation":"QUESTION_REFERENCES_GRAPH_EVIDENCE"}])
        graph["offer_details"].setdefault(oid,{}).setdefault(
            "reactive_questions",[]).append(question)
    graph["stats"]["model_proposed_unverified_questions"]=len(additions)
    return graph
