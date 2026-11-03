"""Offer knowledge graph from saved TraceCart evidence (read-only).

This graph is a navigation aid, not an inference engine. Repeated advertised
numbers share an attribute hub, NOT a verified model identity. Evidence about
another reviewed variant is reference-only; no source-backed answer or checkout
price is created by extracting a listing title or Google Shopping snippet.
"""
from hashlib import sha256
import re

from offer_question_bank import AXES, PROBES, questions_for_offer
from similar_tier import PUBLIC_SPEC_NAMES, read_specs

MAX_OFFERS = 33
MAX_CLAIMS_PER_OFFER = 20
MAX_REFERENCE_ROWS_PER_OFFER = 16


def _key(value):
    """Stable short safe identifier for immutable graph nodes."""
    return sha256(str(value).encode("utf-8", "replace")).hexdigest()[:18]


def _render_spec(key, value):
    if isinstance(value, float) and value.is_integer():
        value=int(value)
    return "{}".format(value)


def _source_id(url, sha):
    return "source:" + _key((url or "") + "|" + (sha or ""))


def _leading_questions(offer, category):
    """Take only per-dimension leading questions; all others remain paginated."""
    if category=="E_BIKE":
        first=questions_for_offer(offer,category,0,24)["questions"]
        return first
    axes=AXES.get(category,AXES["OTHER"])
    return [questions_for_offer(offer,category,d*len(PROBES),1)["questions"][0]
            for d in range(len(axes))]


def build_offer_knowledge_graph(projection):
    """Read-only graph of offers, indexed claims, evidence and unresolved gaps.

    Input is the current persisted decision projection. No model or external
    queries are made. Unknown values never turn into inferred attributes;
    speculative matches are never identity edges.
    """
    offers=(projection.get("offers") or [])[:MAX_OFFERS]
    category=projection.get("category") or "UNKNOWN"
    axes=AXES.get(category,AXES["OTHER"])
    evidence=projection.get("evidence_offers") or {}
    models=projection.get("model_offers") or {}
    vertices={}
    edges={}
    details={}
    spec_name=PUBLIC_SPEC_NAMES

    def add_node(id_, kind, label, **fields):
        if id_ not in vertices:
            vertices[id_]={"id":id_,"type":kind,"label":str(label),**fields}
        return id_

    def add_edge(src,dst,kind,**fields):
        id_="edge:"+_key((src,dst,kind,fields.get("question_id")))
        if id_ not in edges:
            edges[id_]={"id":id_,"from":src,"to":dst,"relation":kind,**fields}

    gate=add_node("decision:abstain","decision_gate",
                  "NO VERIFIED BEST BUY",
                  status="ABSTAIN_PENDING_EXACT_OFFER_AND_PRICE_VERIFICATION",
                  explanation="Exact seller SKU, source tests and current checkout total are not all verified.",
                  payment_authorized=False)
    dim_ids=[]
    for di,description in enumerate(axes):
        dim_ids.append(add_node("dimension:"+str(di),"research_gap",
                                description,priority="P0",
                                status="OPEN_UNTIL_EXACT_MATCHED_SOURCE"))
        add_edge(dim_ids[-1],gate,"RESEARCH_GAP_PREVENTS_VERIFIED_DECISION",
                 status="NEEDS_TRUSTWORTHY_OFFER_SPECIFIC_EVIDENCE")
    unique_measurements=set()
    unique_document_declarations=set()
    linked_references=0
    count_titles=0
    count_prices=0
    exact_verified=0
    gap_edges=0
    discrepancy_count=0
    search=(projection.get("source_search") or {})
    search_lead_ids={}
    for candidate in (search.get("leads") or [])[:24]:
        if not isinstance(candidate,dict):
            continue
        url=candidate.get("url")
        ident=candidate.get("model_identity") or {}
        if (not isinstance(url,str) or
            not isinstance(ident.get("brand"),str) or
            not isinstance(ident.get("model"),str)):
            continue
        lead="lead:"+_key(url)
        add_node(lead,"source_lead",
                 str(candidate.get("title") or "Source URL discovered")[:150],
                 url=url,
                 status="SEARCH_INDEX_LEAD_NOT_FETCHED_OR_VERIFIED",
                 exact_sku_matched=False,
                 identity=ident)
        search_lead_ids.setdefault((ident["brand"],ident["model"]),[]).append(
            (lead,url))
    for offer in offers:
        oid=offer["id"]
        kind=offer.get("kind","UNKNOWN")
        provenance=("URL_TITLE_UNVERIFIED" if kind=="INPUT_PRODUCT" else
                    "SEARCH_INDEX_TITLE_UNVERIFIED")
        add_node(oid,"offer",offer.get("title","Unknown offer"),
                 ordinal=int(oid.split("-")[-1])+1,
                 offer_kind=kind,source=offer.get("source"),
                 url=offer.get("url"),provenance=provenance,
                 question_count=offer.get("question_count",0))
        if search_lead_ids:
            from generic_source_research import product_identity
            identity=product_identity(offer.get("title",""))
            if identity:
                key=(identity["brand"],identity["model"])
                for lead,url in search_lead_ids.get(key,[]):
                    add_edge(oid,lead,"SOURCE_DISCOVERY_LEAD",
                        status="URL_ONLY_UNVERIFIED_NO_PRODUCT_RECEIPT")
        specs=read_specs(offer.get("title",""),category)
        # URL title can be truncated/synthetic. All fields are *claims*.
        listing_claims=[]
        spec_node_ids={}
        for key,value in list(specs.items())[:MAX_CLAIMS_PER_OFFER]:
            raw_value=_render_spec(key,value)
            derived=key=="battery_wh" and (
                "battery_ah" in specs and "battery_voltage_v" in specs)
            claim_status=("ARITHMETIC_FROM_UNVERIFIED_TITLE_VALUES" if derived
                          else "UNVERIFIED_TITLE_LABEL")
            nid=add_node(("derived:"+oid+":"+key) if derived
                          else "spec:"+_key((category,key,raw_value)),
                          "derived_claim" if derived else "title_claim",
                          spec_name.get(key,key)+" · "+raw_value,
                          parameter=key,value=value,unit=None,
                          claim_status=claim_status)
            add_edge(oid,nid,"CALCULATED_FROM_TITLE_CLAIMS" if derived
                     else "TITLE_MENTIONS",
                     status=claim_status,provenance=provenance)
            listing_claims.append({"parameter":key,"label":spec_name.get(key,key),
                                   "value":value,"node_id":nid,
                                   "status":claim_status})
            spec_node_ids[key]=nid
            count_titles+=1
        if "battery_wh" in spec_node_ids:
            for field in ("battery_ah","battery_voltage_v"):
                if field in spec_node_ids:
                    add_edge(spec_node_ids[field],spec_node_ids["battery_wh"],
                             "ARITHMETIC_INPUT",
                             status="V_MULTIPLIED_BY_AH_UNVERIFIED_OPERANDS",
                             formula="Wh = V × Ah")
        quote=offer.get("indexed_price")
        price=None
        if quote is not None:
            # Do not turn an indexed quote into a verified checkout price.
            quote_text=str(quote).strip()
            try:
                numeric=float(quote_text.replace(" ","").replace(",","."))
            except (TypeError,ValueError):
                numeric=0.0
            if 0<numeric<=1000000:
                price={"value":quote_text,"currency":offer.get("currency"),
                       "status":"INDEXED_QUOTE_NOT_CHECKOUT"}
                node=add_node("price:"+oid,"indexed_quote",
                              quote_text+" "+str(offer.get("currency") or ""),
                              value=quote_text,currency=offer.get("currency"),
                              status="INDEXED_QUOTE_NOT_CHECKOUT")
                add_edge(oid,node,"INDEXED_PRICE_CLAIM",
                         status="NOT_VERIFIED_AT_SELLER")
                count_prices+=1
        # One high-impact question for each dimension; the entire backlog
        # is accessible through the existing paginated question endpoint.
        first=_leading_questions(offer,category)
        questions=[]
        for q in first:
            idx=axes.index(q["dimension"])
            add_edge(oid,dim_ids[idx],"EVIDENCE_NEEDED",
                     question_id=q["id"],question=q["question"],
                     priority=q["priority"],status="PLANNED_NOT_INVESTIGATED")
            questions.append({"id":q["id"],"dimension":q["dimension"],
                              "question":q["question"],"status":q["status"],
                              "node_id":dim_ids[idx]})
            gap_edges+=1
        answers=[]
        refs=(evidence.get(oid) or {}).get("reference_answers") or []
        for i,ref in enumerate(refs[:MAX_REFERENCE_ROWS_PER_OFFER]):
            if not isinstance(ref,dict) or not ref.get("source_sha256") or not ref.get("source_url"):
                continue
            verified=ref.get("verified_for_exact_offer") is True
            # A separate independent-review reference cannot prove the
            # offered SKU even when it shares a manufacturer family ID.
            if verified:
                # Source status must explicitly assert identity, otherwise
                # the answer stays a reference-only observation.
                verified=(ref.get("status")=="EXACT_SKU_INDEPENDENTLY_VERIFIED")
            source_url=ref["source_url"]
            digest=ref["source_sha256"]
            source=_source_id(source_url,digest)
            add_node(source,"fetched_source",ref.get("publisher") or "Independent source",
                     url=source_url,sha256=digest,
                     publisher=ref.get("publisher"),retrieved_at=ref.get("retrieved_at"),
                     source_kind=ref.get("source_kind"))
            answer_id="answer:"+oid+":"+str(i)
            independent=ref.get("source_kind")=="INDEPENDENT_TEST"
            node_kind="reference_observation" if independent else "source_declaration"
            answer_status=("EXACT_SKU_INDEPENDENTLY_VERIFIED" if verified else
                "REFERENCE_ONLY_NOT_THIS_OFFER" if independent else
                "DOCUMENT_DECLARATION_EXACT_SKU_UNVERIFIED")
            add_node(answer_id,node_kind,
                     ref.get("value") or ref.get("finding") or "Source finding",
                     question_id=ref.get("question_id"),
                     finding=ref.get("finding"),value=ref.get("value"),
                     reviewed_model=ref.get("reviewed_model"),
                     reviewed_variant=ref.get("reviewed_variant"),
                     variant_match=ref.get("variant_match"),
                     method=ref.get("source_method"),
                     status=answer_status,
                     property_family=ref.get("property_family"),
                     source_kind=ref.get("source_kind"),
                     source_sha256=digest)
            add_edge(oid,answer_id,"HAS_SOURCE_OBSERVATION",
                     status=answer_status)
            add_edge(answer_id,source,"OBSERVED_IN_SOURCE",
                     status="FETCHED_DOCUMENT_WITH_SHA256")
            lead="lead:"+_key(source_url)
            if lead in vertices:
                add_edge(lead,source,"DISCOVERED_PAGE_FETCHED_AND_EXTRACTED",
                    status="DOCUMENT_PRESENT_EXACT_VARIANT_UNVERIFIED")
            if ref.get("dimension") in axes:
                add_edge(answer_id,dim_ids[axes.index(ref["dimension"])],
                         "INFORMS_DIMENSION",
                         status=("EXACT_SKU_INDEPENDENTLY_VERIFIED" if verified
                                 else "REFERENCE_VARIANT_NOT_SKU"))
            answers.append({"id":answer_id,"finding":ref.get("finding"),
                            "value":ref.get("value"),"source_id":source,
                            "source_url":source_url,"source_sha256":digest,
                            "source_kind":ref.get("source_kind"),
                            "property_family":ref.get("property_family"),
                            "status":answer_status,
                            "variant_match":ref.get("variant_match"),
                            "method":ref.get("source_method")})
            identifier=(digest,ref.get("source_property"),str(ref.get("value")))
            if independent:
                unique_measurements.add(identifier)
            else:
                unique_document_declarations.add(identifier)
            linked_references+=1
            if verified:
                exact_verified+=1
        disagreements=(evidence.get(oid) or {}).get(
            "declared_claim_conflicts") or []
        for i,disagreement in enumerate(disagreements[:12]):
            if not isinstance(disagreement,dict):
                continue
            kind=disagreement.get("type")
            if kind not in ("TITLE_VS_PUBLISHED_SPECIFICATION",
                            "PUBLISHED_SOURCES_DISAGREE"):
                continue
            cid="discrepancy:"+oid+":"+_key((kind,i,disagreement.get("parameter"),
                        disagreement.get("source_url"),
                        disagreement.get("source_a_sha256")))
            if kind=="TITLE_VS_PUBLISHED_SPECIFICATION":
                label=(str(disagreement.get("listing_value","?"))+
                    " listed vs "+str(disagreement.get("source_value","?"))+
                    " published")
            else:
                label=(str(disagreement.get("source_a_value","?"))+
                    " vs "+str(disagreement.get("source_b_value","?"))+
                    " in two documents")
            add_node(cid,"source_disagreement",label[:155],
                status=disagreement.get("status"),
                parameter=disagreement.get("parameter"),
                verified_exact_variant=False,
                not_proven_fraud=True,
                requires_variant_or_test_protocol_confirmation=True)
            add_edge(oid,cid,"POTENTIAL_SOURCE_DISCREPANCY",
                status="PUBLISHED_CLAIMS_DIFFER_EXACT_SKU_UNVERIFIED")
            source_refs=(
                [(disagreement.get("source_url"),
                  disagreement.get("source_sha256"))]
                if kind=="TITLE_VS_PUBLISHED_SPECIFICATION" else
                [(disagreement.get("source_a_url"),
                  disagreement.get("source_a_sha256")),
                 (disagreement.get("source_b_url"),
                  disagreement.get("source_b_sha256"))])
            for source_url,digest in source_refs:
                if isinstance(source_url,str) and isinstance(digest,str):
                    sid=_source_id(source_url,digest)
                    if sid in vertices:
                        add_edge(cid,sid,"DISCREPANCY_REQUIRES_SOURCE_REVIEW",
                            status="SOURCE_FETCHED_VARIANT_MATCH_OPEN")
            discrepancy_count+=1
        hints=offer.get("index_model_hints") or []
        for hint in hints[:4]:
            other=hint.get("source_offer")
            if any(x.get("id")==other for x in offers):
                add_edge(oid,other,"SIMILAR_INDEX_MODEL_NAME_LEAD",
                         status="NOT_VERIFIED_SAME_PRODUCT",
                         model_hint=hint.get("model_hint"))
        llm=models.get(oid) or {}
        details[oid]={
            "title":offer.get("title"),"source":offer.get("source"),
            "kind":kind,"url":offer.get("url"),
            "indexed_price":price,"claim_provenance":provenance,
            "claims":listing_claims,"high_impact_questions":questions,
            "planned_question_count":offer.get("question_count",0),
            "model_question_status":llm.get("state","NOT_REQUESTED"),
            "model_questions":[x.get("question") for x in
                               llm.get("questions",[])[:6] if isinstance(x,dict)],
            "source_check_status":(evidence.get(oid) or {}).get("status",
                                 "NOT_STARTED"),
            "reference_observations":answers,
            "declared_claim_conflicts":disagreements[:12],
            "verified_exact_sku_answers":sum(x["status"]==
                        "EXACT_SKU_INDEPENDENTLY_VERIFIED" for x in answers),
            "model_hints":[{"name":h.get("model_hint"),
                            "source_offer":h.get("source_offer"),
                            "identity_status":"INDEX_MODEL_LEAD_NOT_EXACT_SKU"}
                           for h in hints[:4]],
            "missing":(offer.get("research_diagnostics") or {}).get(
                       "missing_evidence",[]),
        }
    return {
        "schema_version":"tracecart.offer-knowledge-graph.v1",
        "category":category,
        "nodes":list(vertices.values()),
        "edges":list(edges.values()),
        "offer_details":details,
        "stats":{
            "offers":len(offers),
            "unique_title_claim_values":sum(n["type"]=="title_claim" for n in
                                             vertices.values()),
            "title_claim_links":count_titles,
            "derived_arithmetic_claims":sum(n["type"]=="derived_claim"
                         for n in vertices.values()),
            "unverified_index_quotes":count_prices,
            "high_priority_unanswered_check_links":gap_edges,
            "total_planned_questions":sum(o.get("question_count",0) for o in offers),
            "independent_reference_measurements":len(unique_measurements),
            "documented_product_declarations":len(unique_document_declarations),
            "unresolved_source_discrepancies":discrepancy_count,
            "source_discovery_leads":len((projection.get("source_search")
                                        or {}).get("leads") or []),
            "reference_offer_links":linked_references,
            "verified_exact_sku_answers":exact_verified,
            "verified_checkout_prices":projection.get("evidence",{}).get(
                "seller_confirmed_competitor_prices",0) or 0,
        },
        "provenance":{
            "built_from":"READ_ONLY_SAVED_REPORT_AND_PERSISTED_SOURCE_RECEIPTS",
            "original_report_sha256":projection.get("saved_report_sha256"),
            "title_claims_are_verified":False,
            "shared_parameter_value_proves_identical_model":False,
            "missing_evidence_means_negative_result":False,
            "reference_review_proves_offer_variant":False,
            "automatic_purchase_authorized":False,
        },
        "decision_status":"ABSTAIN_PENDING_EXACT_OFFER_AND_PRICE_VERIFICATION",
        "limitations":[
            "Title numbers are unverified claims, not tested product specifications.",
            "A matching value or related Shopping title does not establish identical model, battery or frame.",
            "Independent reviews of other variants stay reference-only until exact SKU and tested configuration match.",
            "Seller/OEM/third-party page specifications are source declarations, not independent laboratory tests.",
            "Disagreements between seller and source declarations may indicate different variants, test conditions, or outdated values; they do not prove deception.",
            "A URL discovered through a paid search index is a lead, not a source observation until the page is independently fetched.",
            "No verified seller checkout price is inferred from indexed quotes.",
            "Knowledge gaps are open investigations, not failed performance tests.",
        ],
    }
