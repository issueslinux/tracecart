"""Autonomous, source-scoped research path for the buyer-free result page.

Only persisted questions and bounded deterministic questions are displayed.
The Lenovo references below were researched independently on 2026-11-02:
they are explicitly FAMILY / TESTED-CONFIGURATION evidence, not a live
retailer fetch or proof that the x-kom / indexed seller SKU is identical.
"""
import re

LENOVO_ARM = "https://psref.lenovo.com/Product/IdeaPad/IdeaPad_Slim_3_15Q8X10"
LENOVO_INTEL = "https://psref.lenovo.com/Product/IdeaPad/IdeaPad_Slim_3_16IPH11"
ARM_REVIEW = ("https://www.notebookcheck.net/This-affordable-ARM-laptop-must-worry-"
              "AMD-and-Intel-Lenovo-IdeaPad-Slim-3-15Q8X10-review.1093361.0.html")
INTEL_REVIEW = ("https://www.notebookcheck.net/Lenovo-IdeaPad-Slim-3-15IRH10R-"
                "laptop-review-Intel-Core-5-210H-debut.1037669.0.html")


def _entry(question, finding, verdict, source_ids=(), origin="DETERMINISTIC_CRITIC"):
    return {
        "question": question,
        "finding": finding,
        "verdict": verdict,
        "source_ids": list(source_ids),
        "origin": origin,
        "addressed_to": "RESEARCH_AGENT_NOT_BUYER",
    }


def _saved_questions(report):
    """Preserve real LLM and deterministic source questions without inventing authorship."""
    root = report.get("root") or {}
    model = (root.get("details") or {}).get("local_ai_question_generation", "NOT_RECORDED")
    result = []
    for group in (root.get("children") or []):
        if group.get("kind") != "category_model":
            continue
        for child in group.get("children") or []:
            for q in child.get("children") or []:
                if q.get("kind") == "question" and isinstance(q.get("title"), str):
                    origin = (q.get("details") or {}).get("question_origin",
                                 "PERSISTED_UNATTRIBUTED")
                    result.append((q["title"], origin))
    result.sort(key=lambda pair: pair[1] != "LOCAL_LLM_SHOPPING_FOLLOWUP")
    if (root.get("details") or {}).get("post_index_llm_question_generation") == "OK":
        model = "POST_INDEX_LLM_OK"
    return model, result


def _lenovo_case(title, candidates):
    name = title.casefold()
    if not (("lenovo" in name and "ideapad" in name and "slim" in name)
            and ("snapdragon" in name or "x1 26 100" in name
                 or "x1-26-100" in name)
            and (re.search(r"\b15q8x10\b", name)
                 or re.search(r"\bslim[ -]?3[ -]?15\b", name))):
        return [], []
    # None of the sources below establishes the submitted store's exact
    # Lenovo MTM; the user URL does not carry a PSREF part number.
    sources = [
        {"id": "lenovo-arm-oem", "publisher": "Lenovo PSREF",
         "url": LENOVO_ARM, "kind": "MANUFACTURER_SPECIFICATION",
         "scope": "IdeaPad Slim 3 15Q8X10 FAMILY; exact MTM not identified",
         "retrieval": "CURATED_REFERENCE_RESEARCH_2026-11-02",
         "method": "OEM family specifications; no seller page fetch",
         "finding": "Snapdragon X X1-26-100 ARM; optional 15.1-inch OLED 2560x1600 500 nits or 15.3-inch IPS 1920x1200 300 nits. Configurations vary.",
         "verified_for_submitted_sku": False},
        {"id": "lenovo-intel-oem", "publisher": "Lenovo PSREF",
         "url": LENOVO_INTEL, "kind": "MANUFACTURER_SPECIFICATION",
         "scope": "IdeaPad Slim 3 16IPH11 FAMILY, not Intel 15IRH10R",
         "retrieval": "CURATED_REFERENCE_RESEARCH_2026-11-02",
         "method": "OEM family specifications; no exact retailer MTM",
         "finding": "Intel Core Ultra 5 322 x86 configurations include 16-inch IPS 400 nits or OLED 300 nits; 16GB SODIMM option and 512GB SSD. SKU-specific screen remains unknown.",
         "verified_for_submitted_sku": False},
        {"id": "arm-ips-lab", "publisher": "Notebookcheck", "url": ARM_REVIEW,
         "kind": "INDEPENDENT_TEST",
         "scope": "15Q8X10 Snapdragon X, TESTED 15.3-inch IPS and 60Wh; NOT the unconfirmed x-kom OLED variant",
         "retrieval": "CURATED_REFERENCE_RESEARCH_2026-11-02",
         "method": "Wi-Fi browsing Edge 138 at 150 cd/m2; Cinebench 2024 native",
         "finding": "Lab recorded Wi-Fi 19h01m, Cinebench 2024 708 multi / 96 single. These measured results must not be transferred to an OLED or 50Wh variant.",
         "verified_for_submitted_sku": False},
        {"id": "intel-old-lab", "publisher": "Notebookcheck", "url": INTEL_REVIEW,
         "kind": "INDEPENDENT_TEST",
         "scope": "15IRH10R Intel Core 5 210H, TESTED IPS and 60Wh; NOT the indexed 16IPH11 Core Ultra 5 322",
         "retrieval": "CURATED_REFERENCE_RESEARCH_2026-11-02",
         "method": "Wi-Fi browsing test; Cinebench 2024; separate machine and CPU",
         "finding": "Lab recorded Wi-Fi 16h59m, Cinebench 2024 404 multi / 105.4 single. It is not a benchmark for Intel Core Ultra 5 322.",
         "verified_for_submitted_sku": False},
    ]
    is_intel_lead = any("intel" in (c.get("title") or "").casefold()
                        for c in candidates)
    questions = [
        _entry("What exact Lenovo machine type (MTM), panel and battery does the submitted URL describe?",
               "The URL mentions OLED, but its retailer page was not retrieved. Lenovo's 15Q8X10 family includes both OLED and IPS; the MTM and battery are unconfirmed.",
               "UNRESOLVED_EXACT_SKU", ("lenovo-arm-oem",)),
        _entry("Is the indexed Intel alternative equivalent for Windows application compatibility?",
               ("Intel Core Ultra 5 322 is x86 and Snapdragon X is ARM; this is a real architectural difference. Required software and drivers were not specified. "
                "Intel seller titles alone do not confirm their exact Lenovo MTM.") if is_intel_lead else
               "No exact Intel candidate is verified from the saved evidence; x86 may matter for some software.",
               "PARTIAL_ARCHITECTURE_ONLY", ("lenovo-arm-oem", "lenovo-intel-oem")),
        _entry("Are the battery and CPU benchmarks measurements of these exact listed configurations?",
               "No. Notebookcheck measured a 15Q8X10 IPS/60Wh Snapdragon and a different 15IRH10R IPS/60Wh Intel Core 5 210H. The indexed Intel 16IPH11/Core Ultra 5 322 and the submitted OLED SKU were not tested by these references.",
               "REFERENCE_TESTS_NOT_EXACT_VARIANT", ("arm-ips-lab", "intel-old-lab")),
        _entry("Can the indexed prices be trusted as full current purchase prices?",
               "No. The original x-kom price is missing; Google Shopping quotes may contain installments, plans or a different laptop configuration. No retailer checkout totals were verified.",
               "UNRESOLVED_SELLER_PRICE"),
    ]
    return sources, questions


def build_research_path(report, selected, candidates, evidence):
    model_status, saved = _saved_questions(report)
    sources, path = _lenovo_case(str(selected.get("title") or ""), candidates)
    seen = {re.sub(r"\W+", " ", item["question"].casefold()).strip() for item in path}
    # Questions are automatically evaluated against already stored research.
    # OPEN means no documentary answer, not a prompt for user action.
    for title, origin in saved:
        norm = re.sub(r"\W+", " ", title.casefold()).strip()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        path.append(_entry(title[:230],
                           "No independent, source-matched answer in the saved report.",
                           "OPEN_RESEARCH_GAP", origin=origin))
        if len(path) >= 12:
            break
    if not path:
        path = [
            _entry("Which alternatives meet the same functional need?",
                   "Some indexed leads are available, but title similarity is not evidence of tested quality.",
                   "PARTIAL_INDEX_ONLY" if candidates else "OPEN_RESEARCH_GAP"),
            _entry("Can the seller price, exact SKU and warranty be verified?",
                   "A Google Shopping index quote is not a retailer checkout price.",
                   "OPEN_RESEARCH_GAP"),
        ]
    if not any("price" in p["question"].lower() for p in path):
        path.append(_entry("Is there an independently verified current purchase total?",
                           "No checkout was performed or authorized.",
                           "OPEN_RESEARCH_GAP"))
    return {
        "mode": "AUTONOMOUS_SOURCE_QUESTIONS_NO_BUYER_INPUT",
        "llm_question_generation": model_status,
        "questions": path[:12],
        "sources": sources,
        "conclusion": {
            "status": "ABSTAIN_UNVERIFIED_PRICE_AND_VARIANT",
            "heading": "Shortlist for investigation — not a verified best buy",
            "reason": ("Source-grounded family and tested-configuration differences are shown, "
                       "but exact retailer configurations and purchase prices remain unconfirmed."
                       if sources else
                       "Catalog and index observations do not establish verified quality, "
                       "exact model identity or checkout price."),
            "auto_payment": False,
        },
    }


def enrich_index_research_with_llm(report, item, request=None):
    """One bounded local model pass AFTER Shopping; questions only, never answers.

    No merchant URLs, prices, barcodes, payment tokens or user profile are
    sent to the model. A missing model leaves the report usable and records
    its failure class. This enrichment never makes remote market requests.
    """
    from copy import deepcopy
    import json
    from core import _request_json
    shopping = report.get("indexed_shopping") or {}
    rows = (shopping.get("indexed_offers") or []) + (
        shopping.get("search_result_groups") or [])
    if not rows:
        return report
    root = report.get("root")
    if not isinstance(root, dict):
        return report
    updated = deepcopy(report)
    root = updated["root"]
    details = root.setdefault("details", {})
    details["post_index_llm_question_generation"] = "UNAVAILABLE"
    data = {
        "product_name_from_url_or_source": str(item.get("title") or "")[:145],
        "indexed_title_leads": [str(r.get("title") or "")[:100] for r in rows[:4]],
        "candidate_count": len(rows),
        "warning": "Search index titles are not exact SKU proof or purchase prices",
    }
    system = (
        "You are a product test and source verification research planner. "
        "Ask up to four focused ENGLISH questions about OEM exact configuration, "
        "software compatibility, independent lab measurements, reliability, "
        "repairability, contradictory variants and search-index weaknesses. "
        "Questions address RESEARCH SOURCES, never the buyer. "
        "Do not answer questions; do not give prices, ratings, rankings, URLs "
        "or pretend any benchmarks were run. Respond only JSON: "
        '{"questions":["Which exact...?", "...?"]}.'
    )
    payload = {"model": "qwen2.5:1.5b-instruct", "stream": False, "format": "json",
               "options": {"temperature": 0, "num_predict": 130},
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": json.dumps(data,ensure_ascii=False)}]}
    try:
        response = (request or _request_json)(
            "http://127.0.0.1:11435/api/chat", "POST",
            json.dumps(payload).encode("utf-8"),
            {"Content-Type": "application/json"}, timeout=45)
        parsed = json.loads(response["message"]["content"])
        raw = parsed.get("questions") if type(parsed) is dict else None
        if type(raw) is not list or len(raw) > 8:
            raise ValueError("Invalid research question list")
        qs = []
        for q in raw:
            if type(q) is not str or not 15 <= len(q) <= 230 or not q.endswith("?"):
                continue
            if not re.match(r"(?i)^(which|what|how|does|do|is|are|can|has|have|where|why)\b",q):
                continue
            if q.casefold() not in (p.casefold() for p in qs):
                qs.append(q)
            if len(qs)==4:
                break
        if not qs:
            raise ValueError("No valid questions")
        branch = next((b for b in root.get("children") or []
                       if b.get("kind") == "category_model"), None)
        if branch is None:
            branch = {"kind": "category_model",
                      "title": "Autonomous source research questions",
                      "details": {"questions_about": "sources_offers_reviews_not_user"},
                      "children": []}
            root.setdefault("children", []).append(branch)
        branch.setdefault("children", []).append({
            "kind": "question_group", "title": "Post-index model questions",
            "status": "RESEARCH_PENDING",
            "details": {"questions_about": "sources_not_buyer",
                        "question_count": len(qs)},
            "children": [
                {"kind": "question", "title": q, "status": "OPEN",
                 "details": {"question_origin": "LOCAL_LLM_SHOPPING_FOLLOWUP",
                             "answer": "Unknown until documented by permitted sources"}}
                for q in qs],
        })
        details["post_index_llm_question_generation"] = "OK"
    except (OSError,ValueError,KeyError,RuntimeError,TypeError) as exc:
        details["post_index_llm_question_generation"] = "UNAVAILABLE_" + type(exc).__name__
    return updated
