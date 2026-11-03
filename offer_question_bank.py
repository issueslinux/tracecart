"""Fast per-offer research backlog, NOT proof that any question was investigated.

No network calls, no LLM latency, no claims about source results. The backlog is a
structured research decomposition; genuine model-generated source questions live
separately in the persisted report with their true provenance.
"""
import re

# Specific falsifiable aspects. A broad shopping title alone is never an answer.
AXES = {
 "LAPTOP": (
  "exact OEM machine type and SKU", "processor architecture and instruction support",
  "CPU sustained performance", "integrated GPU and graphics drivers",
  "installed RAM type and upgrade path", "SSD type and upgrade path",
  "screen panel identity and gamut", "screen PWM and eye comfort",
  "display resolution and measured brightness", "battery capacity and chemistry",
  "measured battery life under comparable workload", "charging and power limits",
  "Windows on ARM application compatibility", "peripheral and kernel-driver support",
  "thermal behavior and fan acoustics", "keyboard and trackpad ergonomics",
  "ports and external display compatibility", "Wi-Fi Bluetooth and networking",
  "firmware support and security updates", "chassis durability and hinge reliability",
  "component repairability and spare-parts access", "warranty service and returns",
  "actual seller price and installment exclusions", "seller identity and delivery condition",
 ),
 "E_BIKE": (
  "manufacturer frame and variant identity", "motor manufacturer and nominal power",
  "motor peak torque and thermal derating", "battery cell provenance and certification",
  "battery nominal energy in Wh", "battery service and replacement availability",
  "measured range under standardized conditions", "charging safety and service life",
  "drivetrain model and maintenance", "brake hardware and stopping performance",
  "wheel tire and suspension configuration", "frame geometry and rider fit",
  "payload rating and structural robustness", "water resistance and connector sealing",
  "display controller and firmware support", "pedal assistance and speed limits",
  "regulatory road-use compatibility", "service-network geography and warranty",
  "repairability and spare parts", "long-term owner failures", "independent instrumented tests",
  "seller identity and product condition", "current all-in price excluding financing",
  "battery and delivery restrictions",
 ),
 "OTHER": (
  "precise manufacturer and SKU identity", "model version and production revision",
  "core functional capability", "performance measured under real conditions",
  "materials and claimed build quality", "warranty terms and exclusions",
  "repairability and replaceable components", "service and consumables availability",
  "compatibility with intended use", "installation and setup requirements",
  "safety certifications and applicable standards", "durability under accelerated wear",
  "long-term reliability and common failures", "independent benchmark methodology",
  "manufacturer claims versus measured results", "bundle and included accessories",
  "condition new refurbished or used", "seller credibility and return policy",
  "product recall and firmware updates", "total ownership cost and maintenance",
  "accessible documentation and spare parts", "listing variant ambiguity",
  "current purchase price without installments", "shipping and fulfillment restrictions",
 ),
}
# Each dimension has twelve different evidence-investigation tasks; they are
# never labeled "LLM GENERATED" and never marked as measured until evidence.
PROBES = (
 ("oem", "Does the OEM publish an exact-model specification for {aspect} for this listing?"),
 ("sku", "What part number or revision would make the {aspect} claim uniquely identifiable?"),
 ("retailer", "Which {aspect} claim does this particular seller make, and is its source current?"),
 ("lab", "Has an independent laboratory measured {aspect} on this exact configuration?"),
 ("method", "What test protocol and conditions would fairly measure {aspect} here?"),
 ("variant", "Do closely named variants differ in {aspect}, potentially invalidating this offer?"),
 ("conflict", "Are there contradictory primary-source statements about {aspect}?"),
 ("replication", "Can a publisher independent of the OEM corroborate the {aspect} claim?"),
 ("reliability", "What documented defects or failure modes affect {aspect} for this model?"),
 ("currency", "When was the latest admissible evidence about {aspect} published or retrieved?"),
 ("decision", "What evidence is missing before {aspect} may influence a purchase decision?"),
 ("tradeoff", "How could a verified difference in {aspect} affect comparison with the submitted product?"),
)
MAX_OFFERS = 33
PAGE_SIZE = 24


def _safe_title(title):
    return re.sub(r"\s+", " ", str(title or "Unknown listing")).strip()[:190]


def _offer(index, title, source, link, price, currency, kind):
    return {
        "id": "offer-{}".format(index),
        "title": _safe_title(title),
        "source": _safe_title(source or "Unknown source")[:80],
        "url": link if isinstance(link, str) and link.startswith("https://") else None,
        "indexed_price": str(price)[:35] if price is not None else None,
        "currency": currency if currency in ("PLN", "EUR", "USD") else None,
        "kind": kind,
        "question_count": len(AXES["OTHER"]) * len(PROBES),
        "answers_verified": 0,
        "provenance": "INDEX_ONLY" if kind != "INPUT_PRODUCT" else "INPUT_UNVERIFIED_OR_SELLER_CLAIM",
    }


def offer_summaries(record, category=None):
    """One input plus ALL distinct bounded Shopping observations, even if unranked."""
    item = record.get("item") or {}
    report = record.get("report") or {}
    shopping = report.get("indexed_shopping") or {}
    offers = [_offer(0, item.get("title") or item.get("merchant_url") or
                     "Product URL submitted", "Selected product",
                     item.get("merchant_url"), item.get("price"),
                     item.get("currency"), "INPUT_PRODUCT")]
    seen = set()
    for kind, rows in (("INDEXED_SELLER_LINK", shopping.get("indexed_offers") or []),
                       ("INDEXED_SEARCH_CARD", shopping.get("search_result_groups") or [])):
        for row in rows:
            if len(offers) >= MAX_OFFERS:
                break
            title = _safe_title(row.get("title"))
            link = row.get("merchant_url") or row.get("shopping_lookup_url")
            # A seller URL is a stronger identity than a title; allow
            # separate sellers with the same model and distinct prices.
            key = (link or "", str(row.get("seller") or row.get("source") or ""),
                   title.casefold(), str(row.get("current_price_indexed") or
                                         row.get("indexed_price") or ""))
            if key in seen:
                continue
            seen.add(key)
            offers.append(_offer(len(offers), title,
                row.get("seller") or row.get("source"), link,
                row.get("current_price_indexed") if kind == "INDEXED_SELLER_LINK"
                else row.get("indexed_price"),
                row.get("currency") if kind == "INDEXED_SELLER_LINK"
                else row.get("indexed_currency"), kind))
    axes = AXES.get(category, AXES["OTHER"])
    for offer in offers:
        if category == "E_BIKE":
            from ebike_research import (ebike_question_count, ebike_claims,
                                        offer_title_diagnostics)
            offer["question_count"] = ebike_question_count()
            offer["listing_title_claims"] = ebike_claims(offer["title"])
            offer["research_diagnostics"] = offer_title_diagnostics(offer)
        else:
            offer["question_count"] = len(axes) * len(PROBES)
    if category == "E_BIKE" and offers:
        from ebike_research import likely_index_model_hints
        offers[0]["index_model_hints"] = likely_index_model_hints(offers)
    return offers


def questions_for_offer(offer, category, offset=0, limit=PAGE_SIZE):
    """Stable, paginated research *questions*, not hallucinated findings."""
    if category == "E_BIKE":
        from ebike_research import questions_for_ebike
        return questions_for_ebike(offer, offset, limit)
    axes = AXES.get(category, AXES["OTHER"])
    total = len(axes) * len(PROBES)
    if not isinstance(offset, int) or not 0 <= offset <= total:
        raise ValueError("Invalid question offset")
    if not isinstance(limit, int) or not 1 <= limit <= PAGE_SIZE:
        raise ValueError("Invalid question limit")
    questions = []
    for index in range(offset, min(total, offset + limit)):
        aspect, probe = axes[index // len(PROBES)], PROBES[index % len(PROBES)]
        questions.append({
            "id": "{}-{}".format(offer["id"], index+1),
            "question": probe[1].format(aspect=aspect),
            "dimension": aspect,
            "probe": probe[0],
            "priority": "P0" if index % len(PROBES) in (0,2,3,5,6,10) else "P1",
            "origin": "STRUCTURED_RESEARCH_PLAN_NOT_LLM",
            "status": "PLANNED_NOT_INVESTIGATED",
            "finding": None,
            "evidence_ids": [],
            "addressed_to": "RESEARCH_AGENT_NOT_BUYER",
        })
    return {
        "offer_id": offer["id"], "offer_title": offer["title"],
        "total": total, "offset": offset, "limit": limit,
        "questions": questions,
        "next_offset": offset + len(questions) if offset + len(questions) < total else None,
        "verified_answers": 0,
        "important": "These are planned source investigations, not LLM-generated findings or completed research.",
    }


def propose_offer_model_questions(offer, category, request=None):
    """Real LOCAL LLM questions for a specific offer, NEVER alleged findings.

    Called asynchronously after the first customer-visible result. No
    credentials, user info, URLs, prices or payment details go to the model.
    """
    import json
    from core import _request_json
    title = offer.get("title") or ""
    if not title:
        return []
    category_focus = (
        "For an electric bicycle prioritize OEM identity; motor continuous "
        "rating; battery volts, Ah and Wh; range test conditions; brakes, "
        "service and legal pedal-assist cutoff." if category == "E_BIKE" else
        "Prioritize exact variant identification, independent lab tests, "
        "reliability, compatibility, repairability and seller-price ambiguity."
    )
    # A tiny local 1.5B model often emitted truncated JSON when asked for
    # six lengthy questions within 220 tokens. Ask fewer, shorter questions
    # and retry once with an even smaller response, never inventing an answer.
    requester = request or _request_json
    def run_model(question_limit, max_tokens):
        system = (
            "Ask up to {} SHORT, independent, ENGLISH source-research "
            "questions (under 110 chars each) about a product listing. "
            "{} Verify evidence, never guess facts, never address the buyer. "
            "Respond as JSON object only: "
            '{{"questions":["Question one?","Question two?"]}}'
        ).format(question_limit, category_focus)
        payload = {
            "model": "qwen2.5:1.5b-instruct", "stream": False,
            "format": "json",
            "options": {"temperature": 0, "num_predict": max_tokens},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps({
                    "unverified_offer_title": title[:150],
                    "category": category,
                    "listing_type": offer["kind"],
                }, ensure_ascii=False)}],
        }
        response = requester(
            "http://127.0.0.1:11435/api/chat", "POST",
            json.dumps(payload).encode("utf-8"),
            {"Content-Type": "application/json"}, timeout=25)
        raw_text = response["message"]["content"].strip()
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            # Tolerate a JSON object embedded in a markdown fence, but do
            # not guess about syntactically incomplete object contents.
            first = raw_text.find("{")
            if first < 0:
                raise
            parsed, _ = json.JSONDecoder().raw_decode(raw_text[first:])
        raw = parsed.get("questions") if type(parsed) is dict else None
        if type(raw) is not list or len(raw) > 12:
            raise ValueError("Invalid model question list")
        return raw
    try:
        raw = run_model(4, 340)
    except (json.JSONDecodeError, ValueError, KeyError, TypeError):
        raw = run_model(2, 220)
    result = []
    for q in raw:
        if type(q) is not str or not 18 <= len(q) <= 160 or not q.endswith("?"):
            continue
        low=q.casefold()
        # A small local model can propose nonsensical cross-component queries.
        # Do not display unsupported "RAM vs screen" compatibility as research.
        if ("ram" in low and ("display" in low or "screen" in low) and
                "compatib" in low):
            continue
        if low in (x["question"].casefold() for x in result):
            continue
        result.append({
            "question": q, "origin": "LOCAL_LLM_PER_OFFER",
            "status": "OPEN_RESEARCH_GAP", "finding": None,
            "evidence_ids": [], "addressed_to": "RESEARCH_AGENT_NOT_BUYER",
        })
        if len(result) == 4:
            break
    if not result:
        raise ValueError("No valid model questions")
    return result
