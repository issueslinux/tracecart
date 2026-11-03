"""Read-only decision UI projection from persisted TraceCart research evidence.

The legacy OPF catalog counter is NOT a Google Shopping counter. Project the
latter separately, without changing immutable saved source material. User
answers are local UI choices, NOT independent facts or purchase authorization.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from statistics import median
from urllib.parse import urlsplit
import re

from offer_question_bank import offer_summaries
from autonomous_research import build_research_path
from similar_tier import (
    category_of, read_specs, enrich_alternatives, STATUS_SIMILAR, STATUS_POSSIBLE,
)

MAX_CANDIDATES = 18
MAX_QUESTIONS = 5


def _amount(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number=Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        return None
    if not number.is_finite() or not Decimal("0.01") <= number <= Decimal("1000000"):
        return None
    return number


def _public_link(value):
    if not isinstance(value,str) or len(value) > 1400:
        return None
    try:
        p=urlsplit(value)
        if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None,443):
            return None
        if p.hostname in ("localhost","127.0.0.1") or p.hostname.endswith(".local"):
            return None
    except ValueError:
        return None
    return value


def _question(id_, title, options, detail):
    return {"id":id_, "title":title, "detail":detail,
            "choices":[{"value":key,"label":value,"hint":hint}
                       for key,value,hint in options]}


def questions_for(category):
    """English-only optional buyer questions; the live workflow is autonomous."""
    if category=="LAPTOP":
        return [
            _question("usage","What will you use the laptop for?",[
                ("office","Everyday work","Browser, documents and meetings."),
                ("coding","Programming and apps","Software compatibility matters."),
                ("demanding","Gaming or demanding applications",
                 "Check graphics, performance and compatibility."),
            ],"Your use case changes the relevant trade-offs."),
            _question("priority","What matters most?",[
                ("price","Best value","Look for value; flag suspicious quotes."),
                ("balanced","Balanced choice","Price and comparable specifications."),
                ("screen","Screen and comfort","OLED and IPS are not interchangeable."),
            ],"Your preference is not proof of product quality."),
            _question("compatibility","Do you need x86 app compatibility?",[
                ("x86","Yes","Intel/AMD may avoid unverified ARM compatibility."),
                ("arm","No, ARM can work","Snapdragon models can be considered."),
                ("unknown","Not sure","Do not claim compatibility without testing."),
            ],"Not every Windows x86 tool behaves identically on ARM."),
            _question("verification","Have you checked the seller's checkout terms?",[
                ("yes","Yes, personally","This is your statement, not TraceCart verification."),
                ("no","Not yet","Shopping-index prices can be stale."),
                ("unavailable","The page is blocked","Index prices remain unverified."),
            ],"Verify the exact variant, warranty, shipping and final price."),
        ]
    if category=="E_BIKE":
        return [
            _question("usage","How will you use the e-bike?",[
                ("commute","Daily commuting","Practical range, reliability and service."),
                ("trails","Off-road paths","Brakes, drivetrain and geometry matter."),
                ("leisure","Leisure","Comfort and measured real-world range."),
            ],"An advertised 100 km range is not a measured result."),
            _question("priority","What is most important?",[
                ("price","Price","Look for cheaper comparable products."),
                ("balanced","Specifications and price","Battery, motor and components."),
                ("quality","Service and durability","Warranty and cell quality."),
            ],"Product-index listings rarely contain rigorous component tests."),
            _question("verification","Have you verified the seller's offer?",[
                ("yes","Manually","Your statement is not an independent test."),
                ("no","Not yet","Check the current seller price."),
                ("unavailable","The page is inaccessible","Price remains unverified."),
            ],"Service options and battery origin also matter."),
        ]
    return [
        _question("usage","What is your goal?",[
            ("same","A cheaper similar product","A different brand or model may work."),
            ("quality","Better quality","Independent testing is needed."),
            ("research","Compare alternatives","Show findings and evidence gaps."),
        ],"An identical SKU is not required for functional alternatives."),
        _question("priority","How would you choose?",[
            ("price","Price","Unverified low quotes are not proven bargains."),
            ("balanced","Price and features","Comparable functions, not just model codes."),
            ("quality","Durability and warranty","Needs independent corroboration."),
        ],"Price alone does not establish quality."),
        _question("verification","Have you checked the final terms?",[
            ("yes","At the store","Your statement is not independent verification."),
            ("no","Not yet","A search index is only a lead."),
            ("unavailable","Page inaccessible","More verification is required."),
        ],"TraceCart does not execute payments."),
    ]


def _display_title(title, category, unverified):
    """Readable URL-derived hypothesis, NEVER a verified retailer title."""
    if category != "LAPTOP" or not unverified:
        return title
    text=title.lower()
    if "lenovo" in text and "ideapad" in text and "slim" in text:
        parts=["Laptop Lenovo IdeaPad Slim"]
        m=re.search(r"\bslim[ -]?(\d+)\b",text)
        if m:
            parts[0]+=" "+m.group(1)
        if "snapdragon" in text:
            parts.append("Snapdragon")
        elif "intel" in text:
            parts.append("Intel")
        specs=read_specs(title,"LAPTOP")
        if specs.get("ram_gb"):
            parts.append("{:g} GB RAM".format(specs["ram_gb"]))
        if specs.get("capacity_gb"):
            parts.append("{:g} GB SSD (URL text only)".format(specs["capacity_gb"]))
        if specs.get("display_technology"):
            parts.append(specs["display_technology"])
        return " · ".join(parts)
    return re.sub(r"(?i)\.html?$","",re.sub(r"^\d{4,9}\s+","",title))


def build_decision_projection(record):
    """Produce bounded, explicitly sourced content for interactive navigation.

    Historical jobs are projected on access; the persisted tree and its SHA
    remain unchanged. This prevents silently rewriting an old audit.
    """
    state=record.get("state")
    if state != "READY":
        if state in ("QUEUED", "RUNNING"):
            preview = record.get("preview_report")
            current = {**record, "report": preview} if preview else record
            item = current.get("item") or {}
            title = item.get("title") or item.get("merchant_url") or "Submitted product URL"
            from similar_tier import category_of as classify
            category = classify(title)
            return {
                "state": state, "title": title[:200], "category": category,
                "selected_url": _public_link(item.get("merchant_url")),
                "progress_stage": record.get("progress_stage") or "QUEUED",
                "progress_revision": record.get("progress_revision") or 0,
                "model_progress_stage":record.get("progress_stage") or "QUEUED",
                "offers": offer_summaries(current, category),
                "selected_item":item,
                "browser_claims":record.get("browser_claims") or [],
                "input_price":record.get("input_price"),
                "selected_source_intake":((preview or {}).get(
                    "source_intake") or {}),
                "model_offers":record.get("model_offers") or {},
                "evidence_offers":record.get("evidence_offers") or {},
                "evidence_progress":record.get("evidence_progress") or {
                    "status":"NOT_STARTED","processed":0,"planned":0},
                "source_search":record.get("source_search") or {},
                "final_verdict":record.get("final_verdict") or {"status":"NOT_SCHEDULED"},
                "questions": [],
                "payment_authorized": False,
                "evidence": {"google_shopping_cards": len(
                    ((preview or {}).get("indexed_shopping") or {}).get("search_result_groups") or []),
                    "indexed_store_links": len(
                    ((preview or {}).get("indexed_shopping") or {}).get("indexed_offers") or [])},
            }
        return {"state":state,"error_type":record.get("error_type"),
                "payment_authorized":False}
    report=record.get("report") or {}
    selected=record.get("item") or {}
    title=selected.get("title") or "Produkt ze wskazanego adresu"
    shopping=report.get("indexed_shopping") or {}
    source=report.get("source_intake") or {}
    catalog=(report.get("source_discovery") or {}).get("catalog") or []
    direct=shopping.get("indexed_offers") or []
    cards=shopping.get("search_result_groups") or []
    category=category_of(title)
    # Re-evaluate old historical jobs with the *current* version of
    # similarity rules, without touching original timestamp/source claims.
    tier=enrich_alternatives(selected,deepcopy(direct),deepcopy(cards))
    indexed=[]
    for kind,group in (("INDEXED_STORE_LINK",direct),
                       ("SEARCH_CARD_NO_DIRECT_SELLER_LINK",cards)):
        for entry in group[:20]:
            indexed.append((
                kind,entry,
                entry.get("current_price_indexed") if kind=="INDEXED_STORE_LINK"
                else entry.get("indexed_price"),
                entry.get("currency") if kind=="INDEXED_STORE_LINK"
                else entry.get("indexed_currency"),
            ))
    priced=[(_amount(p), unit) for _,_,p,unit in indexed if unit=="PLN"]
    priced=[p for p,unit in priced if p is not None]
    median_index=median(priced) if len(priced)>=3 else None
    suspicious_raw=0
    if median_index:
        for kind,row,price,unit in indexed:
            amount=_amount(price)
            if (unit=="PLN" and amount is not None and
                    amount < median_index*Decimal("0.40") and
                    category_of(row.get("title"))==category):
                suspicious_raw+=1
    suspicious=0
    candidates=[]
    seen=set()
    for candidate in tier["ranked_alternatives"]:
        title_candidate=candidate.get("title") or ""
        link=_public_link(candidate.get("merchant_url")) or _public_link(
            candidate.get("shopping_lookup_url"))
        comparison=candidate["comparison"]
        amount=_amount(candidate.get("indexed_price"))
        currency=candidate.get("currency")
        reasons=[]
        anomaly=candidate.get("index_price_anomaly")
        if anomaly=="SUSPICIOUS_LOW_PRICE_VS_PEER_MEDIAN_NOT_VERIFIED":
            reasons.append("Very low indexed quote relative to peers")
        if median_index and amount and currency=="PLN" and amount < median_index*Decimal("0.40"):
            reasons.append("Very low indexed quote relative to category median")
        source_name=(candidate.get("source") or "").lower()
        lowered=title_candidate.casefold()
        if ("abonament" in lowered or "abonament" in source_name
                or "miesięcznie" in lowered or "miesiecznie" in lowered):
            reasons.append("May represent installments or a subscription")
        if comparison.get("condition_difference"):
            reasons.append(comparison["condition_difference"])
        if reasons:
            suspicious+=1
        key=(candidate.get("source"),title_candidate.casefold(),candidate.get("indexed_price"))
        if key in seen:
            continue
        seen.add(key)
        specs=read_specs(title_candidate,category)
        cpu=specs.get("cpu_family")
        candidates.append({
            "id":"candidate-{}".format(len(candidates)+1),
            "source":str(candidate.get("source") or "")[:100],
            "title":title_candidate[:200],
            "price":str(amount) if amount is not None else None,
            "currency":currency if currency in ("PLN","EUR","USD") else None,
            "link":link,
            "link_kind":("seller URL (not retrieved)" if
                         candidate.get("merchant_url") else
                         "Google Shopping search (no direct seller link)"),
            "source_kind":candidate.get("source_kind"),
            "tier":comparison["status"],
            "technical_fit":comparison.get("technical_score"),
            "matched_specs":comparison.get("matched_features",[])[:6],
            "missing_specs":comparison.get("unconfirmed_features",[])[:5],
            "different_specs":comparison.get("different_features",[])[:5],
            "specs":specs,
            "cpu_architecture":("ARM" if cpu and "ARM" in cpu else
                                "x86" if cpu and "x86" in cpu else "UNKNOWN"),
            "quality_verified":False,
            "seller_price_verified":False,
            "price_warnings":reasons,
            "index_only":True,
        })
    evidence={
        "catalog_only":len(catalog),
        "google_shopping_cards":len(cards),
        "indexed_store_links":len(direct),
        "indexed_listing_records":len(direct)+len(cards),
        "unverified_similar_product_leads":len(candidates),
        "index_prices_flagged_in_alternatives":sum(bool(x["price_warnings"]) for x in candidates),
        "unusually_low_raw_index_quotes":suspicious_raw,
        "seller_confirmed_competitor_prices":shopping.get("source_qualified_seller_offers",0),
        "selected_seller_price":selected.get("price"),
        "selected_currency":selected.get("currency"),
        "input_source_status":source.get("intake_status") or "UNKNOWN",
        "input_source_problem":source.get("access_problem"),
        "shopping_status":shopping.get("status") or "NOT_RESEARCHED",
        "shopping_api_calls":shopping.get("provider_calls") or 0,
        "independent_product_tests":0,
    }
    if evidence["seller_confirmed_competitor_prices"] != 0:
        # The legacy Search-First field must never be promoted into a
        # checkout-verification claim. This projection is intentionally strict.
        evidence["seller_confirmed_competitor_prices"]=0
    reasons=[]
    if selected.get("price") is None:
        reasons.append("Selected retailer price could not be retrieved.")
    if source.get("intake_status") == "URL_ONLY_UNVERIFIED":
        reasons.append("Selected product description is inferred from URL, not fetched seller HTML.")
    if direct or cards:
        reasons.append("Google Shopping quotes are indexed observations, not verified checkout prices.")
    if not direct and not cards:
        reasons.append("No comparable indexed offers could be retrieved.")
    if suspicious or suspicious_raw:
        reasons.append(
            "{} indexed quotes are much lower than others; "
            "they may be index errors, installments or other variants. They are not "
            "verified purchase prices.".format(suspicious_raw))
    payload={
        "state":"READY",
        "title":str(title)[:200],
        "display_title":_display_title(
            title, category, source.get("intake_status")=="URL_ONLY_UNVERIFIED"),
        "selected_url":_public_link(selected.get("merchant_url")),
        "category":category,
        "selected_specs":read_specs(title,category),
        "source_provenance":"URL-derived, unverified title" if source.get("intake_status")=="URL_ONLY_UNVERIFIED"
                            else "Retailer page claims",
        "evidence":evidence,
        "offers":offer_summaries(record,category),
        "selected_item":selected,
        "browser_claims":record.get("browser_claims") or [],
        "input_price":record.get("input_price"),
        "selected_source_intake":source,
        "source_search":record.get("source_search") or {},
        "final_verdict":record.get("final_verdict") or {"status":"NOT_SCHEDULED"},
        "model_offers":record.get("model_offers") or {},
        "model_progress_stage":record.get("progress_stage") or "NOT_SCHEDULED",
        "evidence_offers":record.get("evidence_offers") or {},
        "evidence_progress":record.get("evidence_progress") or {
            "status":"NOT_STARTED","processed":0,"planned":0},
        "questions":[],  # Deprecated buyer questionnaire; no clicks required.
        "research":build_research_path(report, selected, candidates[:MAX_CANDIDATES], evidence),
        "candidates":candidates[:MAX_CANDIDATES],
        "research_questions":[
            "Is the price current, non-subscription, and for this exact variant?",
            "Are specifications and software compatibility confirmed by the manufacturer?"
            if category=="LAPTOP" else
            "Are the key specifications documented beyond the indexed title?",
            "Are returns, warranty and merchant reputation independently documented?",
        ],
        "warnings":reasons,
        "decision_boundary":"NO_AUTOMATIC_PAYMENT_OR_VERIFIED_CHEAPEST_CLAIM",
        "measurement_provenance":"Read-only reinterpretation of saved research report",
        "saved_report_sha256":report.get("sha256"),
        "payment_authorized":False,
    }
    return payload
