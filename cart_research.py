"""Cart-triggered, non-blocking evidence research. NO commerce or payment actions.

Research products in Open Products Facts and attempt Open Prices price evidence.
A Brave web search is optionally used for offer URL discovery when the
operator has configured BRAVE_API_KEY; snippets are NOT verified store offers.
"""
from concurrent.futures import ThreadPoolExecutor, Future, wait, FIRST_COMPLETED
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
import re
import secrets
import socket
import sqlite3
import threading
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from decision_tree import _node, to_html_tree
from live_graph_bus import MemoryLiveGraphCache
from unit_economics import unit_cost

USER_AGENT = "TraceCart/0.4 (https://github.com/issueslinux/tracecart)"
OPF_ROOT = "https://world.openproductsfacts.org"
OPEN_PRICES_ROOT = "https://prices.openfoodfacts.org"
BRAVE_ROOT = "https://api.search.brave.com"
MAX_CANDIDATES = 8
MAX_SEARCH_HITS = 12


def _short(x, limit):
    if not isinstance(x, str) or not x.strip() or len(x) > limit:
        raise ValueError("Text is required, maximum {} characters".format(limit))
    return x.strip()


def validate_cart(obj):
    if type(obj) is not dict or set(obj) != {
            "title", "price", "currency", "barcode", "merchant_url"}:
        raise ValueError("Cart item must have title, price, currency, barcode, merchant_url")
    title = _short(obj["title"], 180)
    currency = obj["currency"]
    if obj["price"] is None and currency is None:
        price = None  # Source omission is not a free/zero-priced product.
    else:
        if currency not in ("PLN", "EUR", "USD"):
            raise ValueError("Unsupported cart currency")
        try:
            price = Decimal(obj["price"])
        except (TypeError, ValueError, ArithmeticError):
            raise ValueError("Invalid cart price")
        if not price.is_finite() or price < 0 or price > 100000 or price.as_tuple().exponent < -2:
            raise ValueError("Invalid cart price")
    barcode = obj["barcode"]
    if type(barcode) is not str or (barcode and not re.fullmatch(r"[0-9]{8,14}", barcode)):
        raise ValueError("Barcode must be empty or 8–14 decimal digits")
    merchant_url = obj["merchant_url"]
    if not isinstance(merchant_url, str):
        raise ValueError("Invalid retailer URL")
    p = urlsplit(merchant_url)
    if len(merchant_url) > 500 or p.scheme != "https" or not p.hostname or p.username or p.password:
        raise ValueError("Retailer URL must be a safe HTTPS web page")
    return {"title": title,
            "price": str(price.quantize(Decimal("0.01"))) if price is not None else None,
            "currency": currency, "barcode": barcode, "merchant_url": merchant_url}


def classify_product(title):
    t = title.casefold()
    detergent = ("proszek do prania", "poudre", "washing powder",
                 "waschpulver", "laundry powder", "detergent", "persil", "ariel")
    electronics = ("laptop", "notebook", "thinkpad", "computer", "komputer")
    if any(w in t for w in detergent):
        return "laundry_detergent"
    if any(w in t for w in electronics):
        return "laptop"
    return "general"


CORE_QUESTIONS = (
    "Is the final delivered price verified against comparable alternatives?",
    "Are the compared items genuinely equivalent in package and intended use?",
    "What do credible independent tests and reviews say about effectiveness?",
    "Which important product claims lack primary evidence?",
)
CATEGORY_QUESTIONS = {
    "laundry_detergent": (
        "What is the actual cost per wash at the stated dose, not per package?",
        "How does stain removal differ at 20°C, 30°C and 40°C?",
        "Does hard water change the required dose and relative cost?",
        "Are powder, liquid and capsules being compared on equivalent wash counts?",
        "Are the claimed enzymes and ingredients documented for this formula?",
        "Are fragrances or other potential irritants disclosed?",
        "Does the product suit colours, whites and delicate fabrics?",
        "Are reviews about the current formulation rather than an older recipe?",
    ),
    "laptop": (
        "Which use-cases benefit from higher RAM/CPU specifications?",
        "What is actual battery health and repair history for used units?",
        "What do sustained performance and reliability tests report?",
        "How do repairability, warranty and return rights differ?",
    ),
    "general": (
        "Which specifications materially affect the intended use?",
        "What do independent reliability data and warranty terms show?",
        "Which claims and conditions should be verified with the seller?",
    ),
}


# Evidence questions are for sources and sellers, not a buyer questionnaire.
# They are grouped for audit and prioritization; unanswered is not a negative verdict.
PURCHASE_GROUP_QUESTIONS = {
    "product": ("Does the exact model/EAN and included accessory set match across offers?",),
    "offer": ("Is this offer currently available, and do promotions require eligibility?",),
    "seller": ("Who is the legal seller and what independent evidence supports reliability?",
               "What warranty, return and complaint terms does this seller publish?"),
    "delivery": ("What is the source-declared shipping cost to the buyer's destination?",
                 "What delivery window, carrier and parcel size restrictions are documented?",
                 "For pickup, what travel distance, expense and time would be required?"),
    "payment": ("Which payment methods and mandatory processing fees are documented?",
                "Are buyer protections and refund routes documented for the payment method?"),
    "total_cost": ("Can product, shipping, mandatory fees and eligible discounts be reconciled?",
                   "Is the checkout total confirmed for the selected destination and quantity?"),
}


def group_purchase_questions(questions):
    grouped = {name: [] for name in PURCHASE_GROUP_QUESTIONS}
    for question in questions:
        q = question.casefold()
        if any(word in q for word in ("delivered price", "cost per wash", "prices can", "cheaper")):
            group = "total_cost"
        elif any(word in q for word in ("retailer", "offer", "stock", "promotion", "available")):
            group = "offer"
        elif any(word in q for word in ("seller", "warranty", "return")):
            group = "seller"
        else:
            group = "product"
        grouped[group].append(question)
    for group, prompts in PURCHASE_GROUP_QUESTIONS.items():
        for question in prompts:
            if question not in grouped[group]:
                grouped[group].append(question)
    return grouped


class _NoExternalRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a confidential search key to another host.
        raise ValueError("Unexpected API redirect")


def _get_json(url, host, headers=None, timeout=15, max_bytes=200000):
    # Larger documents are permitted only when explicitly requested by the
    # bounded shopping-provider adapter. Legacy sources retain 200 KB cap.
    if type(max_bytes) is not int or not 1 <= max_bytes <= 2_500_000:
        raise ValueError("Invalid bounded JSON response limit")
    if urlsplit(url).scheme != "https" or urlsplit(url).hostname != host:
        raise ValueError("Unsupported API host")
    # Fixed host and fixed paths: no user-controlled outbound URL.
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    request_headers.update(headers or {})
    req = Request(url, headers=request_headers)
    with build_opener(_NoExternalRedirect()).open(req, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError("Source API returned non-200")
        buf = response.read(max_bytes + 1)
        if len(buf) > max_bytes:
            raise ValueError("Source response too large")
        return json.loads(buf.decode("utf-8"))


def _safe_code(code):
    return isinstance(code, str) and bool(re.fullmatch(r"[0-9]{8,14}", code))


def _select_search_query(item, category):
    # Search is about the actual cart item, not unrelated random merchandise.
    name = item["title"]
    brand = next((b for b in ("Persil", "Ariel", "Tide", "Denkmit", "Woolite")
                  if b.casefold() in name.casefold()), None)
    if category == "laundry_detergent":
        return brand or "washing powder"
    return " ".join(name.split()[:4])


def _same_form(title, selected_title):
    """Filter obviously incomparable formats; unknown stays unknown."""
    a = selected_title.casefold()
    b = title.casefold()
    marker = ("powder", "poudre", "proszek", "pulver")
    capsules = ("capsule", "caps", "pods", "dosettes", "kapsuł")
    liquid = ("liquid", "liquide", "gel", "płyn", "lessive liquide")
    if any(w in a for w in marker):
        # A powder's comparison set needs explicit powder form evidence;
        # incomplete product names must NOT be treated as equivalent.
        return any(w in b for w in marker) and not any(
            w in b for w in capsules + liquid + (" liq ", " liq"))
    return True


def _derive_questions(item, candidates, sources, category):
    q = list(CORE_QUESTIONS + CATEGORY_QUESTIONS[category])
    if not candidates:
        q.append("Which alternative products can be documented from other sources?")
    if any(not c.get("quantity") for c in candidates):
        q.append("Can the missing package size and wash count be verified?")
    if category == "laundry_detergent":
        if not any(re.search(r"\b\d+\s*(?:wash(?:es)?|lavages|doses|prań)\b",
                             c.get("quantity", "") + " " + c["name"], flags=re.I)
                   for c in candidates):
            q.append("Can the manufacturer confirm doses per pack for a fair cost-per-wash comparison?")
    if not sources.get("verified_prices"):
        q.append("Which current retailer prices can be VERIFIED rather than guessed from snippets?")
    return list(dict.fromkeys(q))


def generate_local_ai_questions(item, category, catalog, request=None):
    """A local AI proposes *unanswered* product/source questions, never findings.

    Safe failure leaves the deterministic model in place. Cart price, barcode,
    merchant URL and customer information are never passed to the model.
    """
    from core import _request_json
    request = request or _request_json
    system = (
        "You are an evidence research planner, not a salesperson. "
        "Suggest at most four NEW high-impact questions to ask internet product "
        "listings, independent tests, reviews or product documentation. "
        "Do NOT ask the buyer. Do NOT return answers, price, merchant endorsements, "
        "final recommendations, or fabricated citations. "
        'Respond only as JSON {"questions":["Question?", "..."]}.'
    )
    payload = {
        "model": "qwen2.5:1.5b-instruct", "stream": False, "format": "json",
        "options": {"temperature": 0, "num_predict": 160},
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": json.dumps({
                         "product": item["title"], "category": category,
                         "catalog_product_names": [x["name"][:90] for x in catalog[:5]],
                         "research_goal": "compare alternatives before checkout",
                     }, ensure_ascii=False)}],
    }
    response = request("http://127.0.0.1:11435/api/chat", "POST",
                       json.dumps(payload).encode("utf-8"),
                       {"Content-Type": "application/json"}, timeout=18)
    data = json.loads(response["message"]["content"])
    if type(data) is not dict or set(data) != {"questions"}:
        raise ValueError("AI question-only response required")
    questions = data["questions"]
    if type(questions) is not list or len(questions) > 12:
        raise ValueError("AI question budget exceeded")
    result = []
    for question in questions:
        if (type(question) is not str or
                not 12 <= len(question) <= 230 or not question.endswith("?")):
            continue
        if question.casefold() not in [v.casefold() for v in result]:
            result.append(question)
        if len(result) >= 4:
            break
    return result


def research_cart(item, fetch=_get_json, max_candidates=MAX_CANDIDATES,
                  use_local_questions=True):
    """One bounded live research run; never invent price/offer data."""
    item = validate_cart(item)
    category = classify_product(item["title"])
    query = _select_search_query(item, category)
    attempts = []
    sources = {"catalog": [], "prices": [], "web_hits": [],
               "verified_prices": [], "attempts": attempts}
    # Catalog identity is not a retailer offer and has no validated sale price.
    opf_url = (OPF_ROOT + "/cgi/search.pl?" + urlencode({
        "search_terms": query, "search_simple": 1, "action": "process",
        "json": 1, "page_size": 18,
        "fields": "code,product_name,brands,quantity,product_quantity",
    }))
    try:
        data = fetch(opf_url, "world.openproductsfacts.org")
        raw = data.get("products", [])
        if type(raw) is not list:
            raise ValueError("Invalid OPF product list")
        seen = set()
        for x in raw:
            if type(x) is not dict or not _safe_code(x.get("code")):
                continue
            name = x.get("product_name", "")
            if not isinstance(name, str) or len(name) < 3 or len(name) > 180:
                continue
            if not _same_form(name, item["title"]):
                continue
            code = x["code"]
            if code in seen or code == item["barcode"]:
                continue
            seen.add(code)
            sources["catalog"].append({
                "code": code, "name": name, "brand": str(x.get("brands", ""))[:100],
                "quantity": str(x.get("quantity", ""))[:100],
                "url": OPF_ROOT + "/product/" + code,
                "source_kind": "product_catalog_NOT_a_retail_offer",
            })
            if len(sources["catalog"]) >= max_candidates:
                break
        attempts.append({"source": "Open Products Facts", "status": "OK",
                         "product_candidates": len(sources["catalog"]),
                         "raw_results_inspected": len(raw),
                         "filter": "strict powder vs capsule/liquid matching" if
                         category == "laundry_detergent" else "product identity",
                         "url": opf_url})
        # A second limited query finds cross-brand alternatives rather than
        # endlessly researching variants from the cart item's own brand.
        if category == "laundry_detergent" and len(sources["catalog"]) < max_candidates:
            cross_url = (OPF_ROOT + "/cgi/search.pl?" + urlencode({
                "search_terms": "Lessive Poudre", "search_simple": 1,
                "action": "process", "json": 1, "page_size": 12,
                "fields": "code,product_name,brands,quantity,product_quantity",
            }))
            try:
                cross_data = fetch(cross_url, "world.openproductsfacts.org")
                other = cross_data.get("products", [])
                if type(other) is not list:
                    raise ValueError("Invalid cross-brand list")
                for x in other:
                    if type(x) is not dict or not _safe_code(x.get("code")):
                        continue
                    name = x.get("product_name", "")
                    if (not isinstance(name, str) or not 3 <= len(name) <= 180
                            or not _same_form(name, item["title"])):
                        continue
                    code = x["code"]
                    if code in seen or code == item["barcode"]:
                        continue
                    seen.add(code)
                    sources["catalog"].append({
                        "code": code, "name": name,
                        "brand": str(x.get("brands", ""))[:100],
                        "quantity": str(x.get("quantity", ""))[:100],
                        "url": OPF_ROOT + "/product/" + code,
                        "source_kind": "product_catalog_NOT_a_retail_offer",
                    })
                    if len(sources["catalog"]) >= max_candidates:
                        break
                attempts.append({
                    "source": "Open Products Facts cross-brand", "status": "OK",
                    "raw_results_inspected": len(other),
                    "product_candidates_total": len(sources["catalog"]),
                    "url": cross_url,
                })
            except (OSError, ValueError, TypeError, KeyError) as exc:
                attempts.append({"source": "Open Products Facts cross-brand",
                                 "status": "FAILED",
                                 "error_type": type(exc).__name__})
    except (OSError, ValueError, KeyError, TypeError) as exc:
        attempts.append({"source": "Open Products Facts", "status": "FAILED",
                         "error_type": type(exc).__name__})
    # The selected EAN is the best possible price query. An empty result is recorded.
    if item["barcode"]:
        price_url = OPEN_PRICES_ROOT + "/api/v1/prices?" + urlencode({
            "product_code": item["barcode"], "size": 5})
        try:
            prices = fetch(price_url, "prices.openfoodfacts.org")
            entries = prices.get("items", [])
            if type(entries) is not list:
                raise ValueError("Invalid Open Prices data")
            for x in entries[:5]:
                if type(x) is not dict or str(x.get("product_code", "")) != item["barcode"]:
                    continue
                value, curr = x.get("price"), x.get("currency")
                if curr not in ("PLN", "USD", "EUR"):
                    continue
                try:
                    amount = Decimal(str(value))
                except (ArithmeticError, ValueError):
                    continue
                if not amount.is_finite() or amount <= 0 or amount > 100000:
                    continue
                sources["prices"].append({
                    "value": str(amount), "currency": curr,
                    "date": str(x.get("date", ""))[:30],
                    "source_url": price_url, "type": "historical_crowdsourced_price",
                    "not_current_retail_offer": True,
                })
            attempts.append({"source": "Open Prices", "status": "OK",
                             "historical_prices": len(sources["prices"]),
                             "current_offers_verified": 0, "url": price_url})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            attempts.append({"source": "Open Prices", "status": "FAILED",
                             "error_type": type(exc).__name__})
    else:
        attempts.append({"source": "Open Prices", "status": "SKIPPED_NO_EAN"})
    key = os.environ.get("BRAVE_API_KEY", "")
    if key:
        # A general search alone often misses a major marketplace offer.
        # Request two small, distinct searches, one including a marketplace.
        # This is provider-backed discovery, NOT a price-data source.
        identity = item["barcode"] if _safe_code(item["barcode"]) else ""
        name = " ".join(item["title"].split()[:9])
        queries = [
            ("GENERAL_RETAILERS", (identity + " " + name + " cena sklep").strip()),
            ("ALLEGRO_MARKETPLACE", ("site:allegro.pl " + identity + " " +
                                    " ".join(item["title"].split()[:5])).strip()),
        ]
        discovered = set()
        for scope, search_q in queries:
            brave_url = BRAVE_ROOT + "/res/v1/web/search?" + urlencode({
                "q": search_q[:240], "country": "PL", "search_lang": "pl",
                "count": 6,
            })
            try:
                hits = fetch(brave_url, "api.search.brave.com",
                             {"X-Subscription-Token": key})
                results = hits.get("web", {}).get("results", [])
                if type(results) is not list:
                    raise ValueError("Invalid search results")
                inspected = 0
                for hit in results[:6]:
                    if type(hit) is not dict:
                        continue
                    target = hit.get("url", "")
                    parsed = urlsplit(target) if isinstance(target, str) else None
                    if (parsed and parsed.scheme == "https" and parsed.hostname
                            and not parsed.username and not parsed.password
                            and not parsed.fragment and target not in discovered
                            and len(sources["web_hits"]) < MAX_SEARCH_HITS):
                        discovered.add(target)
                        inspected += 1
                        sources["web_hits"].append({
                            "title": str(hit.get("title", ""))[:180],
                            "url": target,
                            "snippet": str(hit.get("description", ""))[:450],
                            "search_scope": scope,
                            "source_kind": "UNVERIFIED_SEARCH_RESULT_NOT_A_PRICE_OFFER",
                        })
                attempts.append({
                    "source": "Brave Web Search " + scope, "status": "OK",
                    "candidate_urls_added": inspected,
                    "verified_retail_prices": 0,
                })
            except (OSError, ValueError, KeyError, TypeError) as exc:
                attempts.append({
                    "source": "Brave Web Search " + scope, "status": "FAILED",
                    "error_type": type(exc).__name__,
                })
    else:
        attempts.append({"source": "Brave Web Search", "status": "SKIPPED_NO_API_KEY",
                         "note": "Cross-store search requires configured search API; no fake offers."})
    qs = _derive_questions(item, sources["catalog"], sources, category)
    # A failed local model does NOT erase the deterministic decision tree.
    ai_questions, ai_status = [], "SKIPPED"
    if not use_local_questions:
        ai_status = "DEFERRED_TO_SINGLE_BATCHED_MODEL_WORKER"
    else:
        try:
            ai_questions = generate_local_ai_questions(item, category, sources["catalog"])
            ai_status = "OK"
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            ai_status = "UNAVAILABLE_" + type(exc).__name__
    unique_lower = {x.casefold() for x in qs}
    for proposal in ai_questions:
        if proposal.casefold() not in unique_lower:
            qs.append(proposal)
            unique_lower.add(proposal.casefold())
    now = datetime.now(timezone.utc).isoformat()
    root = _node("cart_research", "Before checkout: " + item["title"],
                 "PARTIAL_COMPARISON", {
        "selected_cart_item": item, "category": category,
        "research_scope": "Automatic research after cart item, no buyer questionnaire",
        "local_ai_question_generation": ai_status,
        "not_a_checkout_action": True, "price_claim": "cart input, not independently verified",
    }, node_id="cart-root")
    selected = _node("selected_product", "Item in cart: " + item["title"],
                     "CART_CLAIM", {"price": item["price"],
                                    "currency": item["currency"],
                                    "barcode": item["barcode"],
                                    "merchant_url": item["merchant_url"]},
                     node_id="cart-selected")
    root["children"].append(selected)
    economics = unit_cost(item, category)
    grouped_questions = group_purchase_questions(qs)
    root["children"].append(_node("category_model",
        "Purchase-stage evidence questions for " + category, "RESEARCH_QUESTIONS",
        {"question_count": sum(map(len, grouped_questions.values())),
         "question_groups": {name: len(items) for name, items in grouped_questions.items()},
         "questions_about": "sources_offers_reviews_not_user"},
        [_node("question_group", name.replace("_", " ").title(), "OPEN",
               {"group": name, "question_count": len(items)},
               [_node("question", q, "OPEN",
                      {"answer": "Unknown until documented by a permitted source",
                       "group": name,
                       "question_origin": ("LOCAL_LLM" if q in ai_questions else "RULE_BASED")},
                      node_id="cart-q-{}-{}".format(name, i))
                for i, q in enumerate(items)],
               node_id="cart-group-{}".format(name))
         for name, items in grouped_questions.items()],
        node_id="cart-questions"))
    root["children"].append(_node(
        "unit_economics", "Cost per wash from selected seller's claims",
        economics["status"], economics, node_id="unit-cost-from-source"))
    catalog_branch = _node("catalog_discovery", "Other product identities (NOT store offers)",
                           "CATALOG_ONLY", {"count": len(sources["catalog"]),
                                            "verified_retail_offers": 0},
                           node_id="cart-catalog")
    for i, product in enumerate(sources["catalog"]):
        catalog_branch["children"].append(_node(
            "candidate_product", product["name"], "UNPRICED_CATALOG_IDENTITY",
            product, node_id="catalog-{}".format(i)))
    root["children"].append(catalog_branch)
    if sources["prices"]:
        root["children"].append(_node(
            "historical_prices", "Historical crowd-sourced prices (NOT current store offers)",
            "HISTORICAL_ONLY", {"count": len(sources["prices"])},
            [_node("historical_price", "Historic recorded price", "NOT_CURRENT",
                   value, node_id="cart-price-{}".format(i))
             for i, value in enumerate(sources["prices"])],
            node_id="cart-historical-prices"))
    if sources["web_hits"]:
        root["children"].append(_node(
            "web_search", "Search-engine store URL candidates (NOT verified offers)",
            "UNVERIFIED", {"count": len(sources["web_hits"])},
            [_node("search_result", v["title"], "UNVERIFIED",
                   v, node_id="cart-web-hit-{}".format(i))
             for i, v in enumerate(sources["web_hits"])],
            node_id="cart-search-hits"))
    critic = _node("critic", "Counterarguments and incomplete evidence",
                   "OPEN", {
        "core_challenges": [
            "The catalog identifies products, not offers available in a particular store.",
            "No current verified competitor shop prices; do not claim A is cheaper.",
            "Shipping, destination, delivery time and payment fees are not established by catalog records.",
            "Unverified product label and manufacturer claims cannot establish washing performance.",
            "Do not compare powder, liquids and capsules without normalized doses."
            if category == "laundry_detergent" else
            "Equivalent product identity, compatibility and actual needs remain uncertain.",
        ],
        "independent_reviews_collected": 0,
        "independent_tests_collected": 0,
    }, node_id="cart-critic")
    root["children"].append(critic)
    root["children"].append(_node(
        "research_attempts", "What was searched and what failed",
        "AUDIT", {"attempts": attempts}, node_id="cart-attempts"))
    root["children"].append(_node(
        "conditional_summary", "Useful pre-checkout information — no forced winner",
        "NO_FORCED_WINNER", {
            "catalog_alternatives_found": len(sources["catalog"]),
            "current_competitor_offers_verified": 0,
            "cart_price": item["price"], "currency": item["currency"],
            "unit_economics": economics,
            "transport_and_payment_fees_verified": False,
            "comparison_status": "UNPRICED_ALTERNATIVES",
            "result": ("Other catalog products found; retailer offers and price "
                       "differences remain unverified. Show questions and alternatives "
                       "before checkout, without blocking it."),
            "payment_authorized": False,
        }, node_id="cart-summary"))
    report = {
        "schema_version": 1, "generated_at": now,
        "root": root, "source_discovery": sources,
        "unit_economics": economics,
        "all_questions_preserved": True,
        "provenance": "External OPF and Open Prices APIs; optional Brave search; "
                      "cart price is user-supplied and NOT validated against checkout.",
        "limitations": ["Catalog records are not buyable store offers.",
                        "Search snippets do not prove stock or price.",
                        "No independent testing collected.",
                        "No automatic purchase, payment capture or buyer authorization."],
    }
    report["sha256"] = sha256(json.dumps(
        report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return report


class CartResearchJobs:
    """Durable bounded async jobs; SQLite accessed only through per-call connections."""

    def __init__(self, db_path, runner=research_cart, worker_limit=2):
        self.db_path = str(db_path)
        self.live_bus = MemoryLiveGraphCache(max_jobs=24)
        self.runner = runner
        self.pool = ThreadPoolExecutor(max_workers=worker_limit)
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS cart_research_jobs (
                id TEXT PRIMARY KEY, item TEXT NOT NULL, state TEXT NOT NULL,
                created TEXT NOT NULL, result TEXT, error_type TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS cart_research_progress (
                job_id TEXT PRIMARY KEY, stage TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0, preview TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS cart_offer_model_questions (
                job_id TEXT NOT NULL, offer_idx INTEGER NOT NULL,
                status TEXT NOT NULL, questions_json TEXT,
                PRIMARY KEY(job_id,offer_idx))""")
            db.execute("""CREATE TABLE IF NOT EXISTS cart_offer_evidence (
                job_id TEXT NOT NULL, offer_idx INTEGER NOT NULL,
                status TEXT NOT NULL, result_json TEXT NOT NULL,
                PRIMARY KEY(job_id,offer_idx))""")
            db.execute("""CREATE TABLE IF NOT EXISTS cart_evidence_runs (
                job_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                processed INTEGER NOT NULL DEFAULT 0,
                planned INTEGER NOT NULL DEFAULT 0)""")
            db.execute("""CREATE TABLE IF NOT EXISTS cart_source_search (
                job_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                receipt_json TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS cart_final_verdict (
                job_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                result_json TEXT, error_type TEXT)""")
            # Never leave a durable LLM verdict marked RUNNING after a
            # process restart. Do not silently rerun model inference.
            db.execute("""UPDATE cart_final_verdict
                SET status='INTERRUPTED',
                    error_type='SERVER_RESTART'
                WHERE status IN ('QUEUED','RUNNING')""")
            # A model task that was RUNNING in another process is stale;
            # it cannot remain an eternal WRITING row after a restart.
            db.execute("""UPDATE cart_offer_model_questions
                SET status='INTERRUPTED_RESTART'
                WHERE status IN ('RUNNING','BATCH_RUNNING','QUEUED')""")
            db.execute("UPDATE cart_evidence_runs SET status='INTERRUPTED' "
                       "WHERE status='RUNNING'")
            db.execute("UPDATE cart_research_jobs SET state='INTERRUPTED' "
                       "WHERE state IN ('QUEUED','RUNNING')")
        self.evidence_pool = ThreadPoolExecutor(max_workers=1)
        self.evidence_stop = threading.Event()
        self.model_pool = ThreadPoolExecutor(max_workers=1)
        self.model_stop = threading.Event()
        self.lock = threading.Lock()

    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=8)
        db.execute("PRAGMA busy_timeout=8000")
        return db

    def _progress(self, job_id, stage, report=None):
        """Cheap committed snapshot; visible while a slow provider/LLM runs."""
        snapshot = json.dumps(report, ensure_ascii=False) if report else None
        with self._db() as db:
            db.execute("""INSERT INTO cart_research_progress(job_id,stage,revision,preview)
                VALUES (?,?,1,?)
                ON CONFLICT(job_id) DO UPDATE SET stage=excluded.stage,
                revision=revision+1,
                preview=COALESCE(excluded.preview,cart_research_progress.preview)""",
                       (job_id, stage, snapshot))
        self.live_bus.signal(job_id)

    def live_snapshot(self, job_id):
        """Bounded in-RAM projection for SSE subscribers; SQLite is durable."""
        def build():
            from guided_decision import build_decision_projection
            from offer_knowledge_graph import build_offer_knowledge_graph
            record=self.read(job_id)
            projection=build_decision_projection(record)
            graph=build_offer_knowledge_graph(projection)
            return {
                "state":record["state"],
                "offer_queue":[{"id":o["id"],"title":o.get("title"),
                     "kind":o.get("kind"),"url":o.get("url")}
                    for o in projection.get("offers",[])],
                "progress_stage":record.get("progress_stage"),
                "progress_revision":record.get("progress_revision",0),
                "graph":graph,
                "evidence_progress":record.get("evidence_progress",{}),
                "model_offers":record.get("model_offers",{}),
                "evidence_offers":record.get("evidence_offers",{}),
                "source_search":record.get("source_search",{}),
                "final_verdict":record.get("final_verdict",{"status":"NOT_SCHEDULED"}),
                "payment_authorized":False,
            }
        return self.live_bus.snapshot(job_id,build)

    def _check_input_source(self, job_id, item):
        """Fetch and persist the actual submitted product before alternatives.

        Starts as soon as the original page identity is extracted, in
        parallel with catalog/Shopping discovery and before a single Qwen
        request. The full worker later reuses this source result.
        """
        from offer_question_bank import offer_summaries
        from evidence_execution import execute_reference_checks
        from similar_tier import category_of
        category=category_of(item.get("title") or "")
        offer=offer_summaries({"item":item,"report":{}},category)[0]
        with self._db() as db:
            db.execute("""INSERT OR REPLACE INTO cart_offer_evidence
                (job_id,offer_idx,status,result_json) VALUES (?,?,?,?)""",
                (job_id,0,"RUNNING",json.dumps({"status":"RUNNING",
                    "reference_answers":[],"verified_for_exact_offer":0})))
        self.live_bus.signal(job_id)
        try:
            result=execute_reference_checks(offer,category)
        except (OSError,ValueError,TypeError,KeyError,RuntimeError) as exc:
            result={"status":"SOURCE_NOT_VERIFIED_"+type(exc).__name__,
                    "reference_answers":[],"sources_checked":0,
                    "verified_for_exact_offer":0}
        with self._db() as db:
            db.execute("""UPDATE cart_offer_evidence SET status=?,result_json=?
                WHERE job_id=? AND offer_idx=0""",
                (result["status"],json.dumps(result,ensure_ascii=False),
                 job_id))
        self.live_bus.signal(job_id)

    def _execute_source_evidence(self, job_id, record):
        """Bounded real source retrieval; never mutates the original audit.

        Deduplicate HTML documents across indexed variants, and progress
        independently from slow local LLM questions and existing READY jobs.
        """
        from offer_question_bank import offer_summaries
        from evidence_execution import execute_reference_checks
        from product_intake import _read
        from similar_tier import category_of
        item=record.get("item") or {}
        category=category_of(item.get("title") or item.get("merchant_url") or "")
        offers=offer_summaries(record,category)
        from source_search import search_source_urls,attach_discovery_leads
        with self._db() as db:
            prior=db.execute("""SELECT status,receipt_json FROM
                cart_source_search WHERE job_id=?""",(job_id,)).fetchone()
            if not prior:
                db.execute("""INSERT INTO cart_source_search
                    (job_id,status,receipt_json) VALUES (?,?,NULL)""",
                    (job_id,"RUNNING"))
        if prior and prior[1]:
            discovery=json.loads(prior[1])
        elif prior:
            # Another worker's incomplete reservation may be interrupted:
            # never risk retrying a possibly billed search automatically.
            discovery={"status":"INTERRUPTED_UNKNOWN_PROVIDER_CHARGE",
                       "queries_used":0,"leads":[],"query_receipts":[]}
        else:
            self.live_bus.signal(job_id)
            try:
                discovery=search_source_urls(offers)
            except (ValueError,TypeError,KeyError,OSError):
                discovery={"status":"FAILED_NO_SOURCE_LEADS",
                           "queries_used":0,"leads":[],"query_receipts":[]}
            with self._db() as db:
                db.execute("""UPDATE cart_source_search
                    SET status=?,receipt_json=? WHERE job_id=?""",
                    (discovery["status"],
                     json.dumps(discovery,ensure_ascii=False),job_id))
            self.live_bus.signal(job_id)
        attach_discovery_leads(offers,discovery)
        # Index-only cards without direct URLs often repeat the SAME model.
        # Investigate one representative manufacturer domain per identity,
        # not 12 redundant brand-home probes and redirections per job.
        from generic_source_research import candidate_urls,product_identity
        seen_no_link_models=set()
        for offer in offers:
            if candidate_urls(offer):
                continue
            identity=product_identity(offer.get("title") or "")
            key=(identity["brand"],identity["model"]) if identity else None
            if key is None or key in seen_no_link_models:
                offer["_skip_brand_discovery"]=True
            else:
                seen_no_link_models.add(key)
        cache={}
        cache_lock=threading.Lock()
        def cached_fetch(url,max_bytes,mimes,timeout=10):
            # One concurrent fetch for the same URL; waiters reuse its
            # successful result OR failure. Prevents repeated robots/review
            # requests when many indexed listings share a model family.
            with cache_lock:
                future=cache.get(url)
                owner=future is None
                if owner:
                    future=Future()
                    cache[url]=future
            if owner:
                try:
                    future.set_result(_read(url,max_bytes,mimes,timeout=timeout))
                except Exception as exc:
                    future.set_exception(exc)
            return future.result()

        count=len(offers)
        with self._db() as db:
            initial=db.execute("""SELECT status FROM cart_offer_evidence
                WHERE job_id=? AND offer_idx=0""",(job_id,)).fetchone()
            primary_done=bool(initial and initial[0] not in
                ("RUNNING","QUEUED","NOT_STARTED"))
            db.execute("""INSERT OR REPLACE INTO cart_evidence_runs
                (job_id,status,processed,planned) VALUES (?,?,?,?)""",
                (job_id,"RUNNING",int(primary_done),count))
            # Keep the real input-document result instead of replacing it
            # with a fake QUEUED state and re-downloading the same source.
            for index in range(count):
                if index==0 and primary_done:
                    continue
                db.execute("""INSERT OR REPLACE INTO cart_offer_evidence
                    (job_id,offer_idx,status,result_json) VALUES (?,?,?,?)""",
                    (job_id,index,"QUEUED",json.dumps({
                        "status":"QUEUED","reference_answers":[],
                        "verified_for_exact_offer":0})))
        self.live_bus.signal(job_id)

        def check(index,offer):
            if self.evidence_stop.is_set():
                return index,{"status":"INTERRUPTED","reference_answers":[],
                              "verified_for_exact_offer":0}
            try:
                result=execute_reference_checks(offer,category,fetch=cached_fetch)
            except (ValueError,TypeError,KeyError,OSError) as exc:
                result={"status":"SOURCE_NOT_VERIFIED_"+type(exc).__name__,
                        "sources_checked":0,"reference_answers":[],
                        "verified_for_exact_offer":0}
            return index,result

        completed=int(primary_done)
        pending_indices=list(range(1,count)) if primary_done else list(range(count))
        # Parallel SOURCE I/O, not 16 simultaneous GPU inference requests.
        # Per-URL Future de-duplicates remote reads, preserving robots checks.
        # All SQLite status changes are made by the coordinator so 16 worker
        # threads do not block on the single-writer SQLite lock.
        with ThreadPoolExecutor(max_workers=min(16,max(1,count))) as executor:
            running={}
            next_index=0
            slots=min(16,len(pending_indices))
            running_row=json.dumps({"status":"RUNNING",
                "reference_answers":[],"verified_for_exact_offer":0})
            # Batch initial status writes, so SQLite never serializes
            # worker *startups* and blocks the intended I/O concurrency.
            with self._db() as db:
                for index in pending_indices[:slots]:
                    db.execute("""UPDATE cart_offer_evidence SET status=?,
                        result_json=? WHERE job_id=? AND offer_idx=?""",
                        ("RUNNING",running_row,job_id,index))
            self.live_bus.signal(job_id)
            def dispatch(initial=False):
                nonlocal next_index
                i=pending_indices[next_index]
                next_index+=1
                if not initial:
                    with self._db() as db:
                        db.execute("""UPDATE cart_offer_evidence SET status=?,
                            result_json=? WHERE job_id=? AND offer_idx=?""",
                            ("RUNNING",running_row,job_id,i))
                    self.live_bus.signal(job_id)
                future=executor.submit(check,i,offers[i])
                running[future]=i
            for _ in range(slots):
                dispatch(initial=True)
            while running:
                done,_=wait(list(running),return_when=FIRST_COMPLETED)
                for future in done:
                    running.pop(future)
                    index,result=future.result()
                    completed+=1
                    with self._db() as db:
                        db.execute("""UPDATE cart_offer_evidence
                            SET status=?,result_json=? WHERE job_id=? AND offer_idx=?""",
                            (result["status"],json.dumps(result,ensure_ascii=False),
                             job_id,index))
                        db.execute("""UPDATE cart_evidence_runs SET processed=?
                            WHERE job_id=?""",(completed,job_id))
                    self.live_bus.signal(job_id)
                    if next_index<len(pending_indices):
                        dispatch()
        with self._db() as db:
            db.execute("""UPDATE cart_evidence_runs SET status=? WHERE job_id=?""",
                       ("INTERRUPTED" if self.evidence_stop.is_set()
                        else "COMPLETE",job_id))
        self.live_bus.signal(job_id)
        # The last stage must be a substantive local-model synthesis,
        # not the earlier question-planning batch. One model_pool worker
        # serializes all inference; HTTP/source extraction runs separately.
        if self.runner is research_cart and not self.evidence_stop.is_set():
            with self._db() as db:
                verdict=db.execute("""SELECT status FROM cart_final_verdict
                    WHERE job_id=?""",(job_id,)).fetchone()
            if verdict and verdict[0]=="QUEUED":
                self._progress(job_id,"FINAL_VERDICT_QUEUED")
                self.model_pool.submit(self._generate_final_verdict,job_id)

    def _generate_offer_questions(self, job_id, record):
        """At most ONE GPU inference call, overlapping all source I/O.

        Since local Qwen has one actual inference slot, N simultaneous GPU
        requests would queue internally. Batch <=4 distinct models, skip
        duplicate title variants and mark the rest with an explicit terminal
        budget status. Source workers continue in parallel.
        """
        from offer_question_bank import (offer_summaries,
                                         propose_offer_question_batch)
        from generic_source_research import product_identity
        from similar_tier import category_of
        category=category_of((record.get("item") or {}).get("title") or "")
        offers=offer_summaries(record,category)
        selected=[]
        duplicate_of={}
        seen={}
        for offer in offers:
            ident=product_identity(offer.get("title",""))
            key=((ident["brand"],ident["model"]) if ident else
                 ("unidentified"," ".join(
                     offer.get("title","").casefold().split())[:85]))
            if key in seen:
                duplicate_of[offer["id"]]=seen[key]
                continue
            if len(selected)>=4:
                continue
            selected.append(offer)
            seen[key]=offer["id"]
        selected_idx={int(o["id"].split("-")[-1]) for o in selected}
        # One SQLite transaction for all state transitions, and an SSE update
        # as soon as the single actual inference request starts.
        with self._db() as db:
            for index,offer in enumerate(offers):
                status=("BATCH_RUNNING" if index in selected_idx else
                    "SKIPPED_DUPLICATE_MODEL" if offer["id"] in duplicate_of else
                    "SKIPPED_MODEL_BUDGET")
                db.execute("""INSERT OR REPLACE INTO cart_offer_model_questions
                    (job_id,offer_idx,status,questions_json) VALUES (?,?,?,?)""",
                    (job_id,index,status,json.dumps([])))
        self.live_bus.signal(job_id)
        if selected:
            try:
                outputs,_,_=propose_offer_question_batch(
                    selected,category,max_models=4)
                failed=False
            except (OSError,ValueError,TypeError,KeyError,RuntimeError) as exc:
                outputs={}
                failure="UNAVAILABLE_"+type(exc).__name__
                failed=True
            with self._db() as db:
                for offer in selected:
                    index=int(offer["id"].split("-")[-1])
                    questions=outputs.get(offer["id"],[])
                    status=(failure if failed else
                            "OK" if questions else "EMPTY")
                    db.execute("""UPDATE cart_offer_model_questions
                        SET status=?,questions_json=?
                        WHERE job_id=? AND offer_idx=?""",
                        (status,json.dumps(questions,ensure_ascii=False),
                         job_id,index))
            self.live_bus.signal(job_id)
        # When evidence retrieval completed first, retain the "verdict
        # queued" status; this question batch is not the end of analysis.
        with self._db() as db:
            evidence=db.execute("""SELECT status FROM cart_evidence_runs
                WHERE job_id=?""",(job_id,)).fetchone()
            verdict=db.execute("""SELECT status FROM cart_final_verdict
                WHERE job_id=?""",(job_id,)).fetchone()
        if (evidence and evidence[0]=="COMPLETE" and
            verdict and verdict[0]=="QUEUED"):
            self._progress(job_id,"FINAL_VERDICT_QUEUED")
        else:
            self._progress(job_id,"PER_OFFER_MODEL_COMPLETE")

    def _generate_final_verdict(self, job_id):
        """Synthesize completed evidence once; persist an honest fallback."""
        from model_verdict import generate_final_verdict, insufficient_verdict
        with self._db() as db:
            evidence=db.execute("""SELECT status FROM cart_evidence_runs
                WHERE job_id=?""",(job_id,)).fetchone()
            row=db.execute("""SELECT status FROM cart_final_verdict
                WHERE job_id=?""",(job_id,)).fetchone()
            if not row or row[0]!="QUEUED" or not evidence or evidence[0]!="COMPLETE":
                return
            db.execute("""UPDATE cart_final_verdict SET status='RUNNING'
                WHERE job_id=?""",(job_id,))
        self._progress(job_id,"FINAL_VERDICT_RUNNING")
        # Graph/projection are computed from the same persisted evidence
        # as the user sees. A model must never rewrite a source receipt.
        graph={}
        projection={}
        try:
            from guided_decision import build_decision_projection
            from offer_knowledge_graph import build_offer_knowledge_graph
            record=self.read(job_id)
            projection=build_decision_projection(record)
            graph=build_offer_knowledge_graph(projection)
            result=generate_final_verdict(projection,graph)
            status="COMPLETE"
            error=None
        except (ValueError,KeyError,TypeError,OSError,RuntimeError,
                TimeoutError) as exc:
            status="UNAVAILABLE"
            error=type(exc).__name__
            result=insufficient_verdict(graph,error,projection)
        with self._db() as db:
            db.execute("""UPDATE cart_final_verdict
                SET status=?,result_json=?,error_type=? WHERE job_id=?""",
                (status,json.dumps(result,ensure_ascii=False),error,job_id))
        self._progress(job_id,"FINAL_VERDICT_"+status)

    def submit(self, item):
        clean = validate_cart(item)
        job_id = secrets.token_urlsafe(18)
        with self._db() as db:
            db.execute("INSERT INTO cart_research_jobs(id,item,state,created) VALUES (?,?,?,?)",
                       (job_id, json.dumps(clean), "QUEUED",
                        datetime.now(timezone.utc).isoformat()))
        self._progress(job_id, "QUEUED")
        self.pool.submit(self._work, job_id, clean)
        return job_id

    def submit_url(self, product_url):
        from product_intake import normalized_product_url
        url = normalized_product_url(product_url)
        job_id = secrets.token_urlsafe(18)
        with self._db() as db:
            db.execute("INSERT INTO cart_research_jobs(id,item,state,created) VALUES (?,?,?,?)",
                       (job_id, json.dumps({"merchant_url": url,
                                             "intake": "URL_EXTRACTION_PENDING"}),
                        "QUEUED", datetime.now(timezone.utc).isoformat()))
        self._progress(job_id, "QUEUED")
        self.pool.submit(self._work_url, job_id, url)
        return job_id

    def _work_url(self, job_id, url):
        self._progress(job_id, "SOURCE_FETCH")
        from product_intake import (
            extract_product_page, generic_url_identity,
            SourceAccessDenied, SourceRedirect, SourceHTTPFailure)
        with self._db() as db:
            db.execute("UPDATE cart_research_jobs SET state='RUNNING' WHERE id=?", (job_id,))
        try:
            try:
                item, source = extract_product_page(url)
            except (SourceAccessDenied, SourceRedirect, SourceHTTPFailure) as exc:
                item, source = generic_url_identity(
                    url, "HTTP_" + str(exc.status))
            except (TimeoutError, socket.timeout, ConnectionError) as exc:
                # Python 3.8 socket.timeout is a separate OSError subclass,
                # not a built-in TimeoutError. HTTPS source timeouts and
                # resets are connectivity failures,
                # not evidence that the item cannot be researched. Continue
                # with the URL-only (unverified) product identity and Search-First.
                # Do not catch arbitrary ValueError / unsafe private DNS errors.
                item, source = generic_url_identity(
                    url, "SOURCE_" + type(exc).__name__.upper())
            except ValueError as exc:
                # Product-page access/metadata failure is recoverable using
                # only the customer-provided URL, regardless of retailer.
                # Invalid/dangerous URL, unsafe DNS and SSRF errors still fail.
                known = {
                    "Product source blocked by robots.txt": "ROBOTS_DISALLOW",
                    "No reliable product name can be extracted from this page": "METADATA_MISSING",
                    "Ambiguous page with multiple Product objects": "METADATA_AMBIGUOUS",
                    "Unsupported product response content type": "UNSUPPORTED_PAGE_TYPE",
                    "Page exceeds bounded source size": "SOURCE_TOO_LARGE",
                }
                reason = known.get(str(exc))
                if reason is None:
                    raise
                item, source = generic_url_identity(url, reason)
            clean = validate_cart(item)
            with self._db() as db:
                db.execute("UPDATE cart_research_jobs SET item=? WHERE id=?",
                           (json.dumps(clean), job_id))
            self._progress(job_id, "CATALOG_AND_BASE_RESEARCH")
            if self.runner is research_cart:
                # Input source takes precedence on the evidence I/O lane.
                self.evidence_pool.submit(self._check_input_source,job_id,clean)
            report = (self.runner(clean,use_local_questions=False)
                      if self.runner is research_cart else self.runner(clean))
            report["source_intake"] = source
            report["root"]["details"]["source_intake"] = {
                "url": clean["merchant_url"], "price_status": source["price_status"],
                "extraction_method": source["extraction_method"],
                "intake_status": source.get("intake_status", "PAGE_RETRIEVED")}
            limited = source.get("intake_status") == "URL_ONLY_UNVERIFIED"
            report["root"]["children"].insert(2, _node(
                "source_intake", ("Product identity inferred ONLY from user URL"
                                  if limited else "Actual selected product web page"),
                "URL_ONLY_UNVERIFIED" if limited else "SELLER_DECLARATION",
                {"extracted_product": clean, "page_metadata": source,
                 "price_is_confirmed_checkout_total": False},
                node_id="cart-source-intake"))
            self._progress(job_id, "BASE_RESEARCH_AVAILABLE", report)
            # Search-first: a contracted shopping-index provider can return
            # merchant prices even if the selected marketplace URL is HTTP 403.
            # No provider key -> no paid queries or invented offers. Indexed
            # prices are separate from directly verified seller declarations.
            if os.environ.get("SERPAPI_API_KEY"):
                from search_first import search_serpapi_shopping, attach_shopping_evidence
                indexed = search_serpapi_shopping(clean)
                report = attach_shopping_evidence(report, clean, indexed)
            # Automatic offer discovery can run only on public URLs already
            # returned by an authorized search provider. Keep the background
            # cart task bounded and do not invent search results if no key.
            self._progress(job_id, "SHOPPING_EVIDENCE_AVAILABLE", report)
            if report.get("source_discovery", {}).get("web_hits"):
                from automatic_offer_discovery import enrich_with_discovered_offers
                report = enrich_with_discovered_offers(report, clean, max_checks=3)
            else:
                report.pop("sha256", None)
                report["sha256"] = sha256(json.dumps(
                    report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            # Per-offer Qwen work runs later as ONE batched background
            # request. Do not hold user READY or source checks hostage
            # to a second sequential LLM in this request path.
            report["root"]["details"]["post_index_llm_question_generation"] = (
                "DEFERRED_TO_SINGLE_BATCHED_MODEL_WORKER")
            report.pop("sha256",None)
            report["sha256"]=sha256(json.dumps(
                report,sort_keys=True,separators=(",",":")).encode()).hexdigest()
            self._progress(job_id, "RESEARCH_COMPLETE", report)
            state, result, error = "READY", json.dumps(report, ensure_ascii=False), None
        except Exception as exc:
            state, result, error = "FAILED", None, type(exc).__name__
        with self._db() as db:
            db.execute("UPDATE cart_research_jobs SET state=?,result=?,error_type=? WHERE id=?",
                       (state, result, error, job_id))
        self.live_bus.signal(job_id)
        if state == "READY" and self.runner is research_cart:
            # Insert the verdict receipt before any evidence can finish so
            # SSE cannot mistake an unfinished analysis for a terminal run.
            with self._db() as db:
                db.execute("""INSERT INTO cart_final_verdict
                    (job_id,status,result_json,error_type)
                    VALUES (?,'QUEUED',NULL,NULL)""",(job_id,))
            # Source checks are the only prerequisite for the final Qwen
            # verdict. The previous representative-question model batch used
            # the SAME inference slot first, timed out, and delayed actual
            # synthesis. Rule-based evidence gaps remain fully available.
            self._progress(job_id,"SOURCE_CHECKS_QUEUED")
            self.evidence_pool.submit(self._execute_source_evidence,job_id,
                                      {"item":clean,"report":report})

    def _work(self, job_id, item):
        self._progress(job_id, "CATALOG_AND_BASE_RESEARCH")
        with self._db() as db:
            db.execute("UPDATE cart_research_jobs SET state='RUNNING' WHERE id=?", (job_id,))
        try:
            report = self.runner(item)
            self._progress(job_id, "BASE_RESEARCH_AVAILABLE", report)
            if (os.environ.get("SERPAPI_API_KEY")
                    and isinstance(report.get("root"), dict)
                    and report["root"].get("children")):
                from search_first import search_serpapi_shopping, attach_shopping_evidence
                indexed = search_serpapi_shopping(item)
                report = attach_shopping_evidence(report, item, indexed)
            self._progress(job_id, "RESEARCH_COMPLETE", report)
            state = "READY"
            result = json.dumps(report, ensure_ascii=False)
            error = None
        except Exception as exc:
            # Never store credential-bearing network error strings.
            state, result, error = "FAILED", None, type(exc).__name__
        with self._db() as db:
            db.execute("UPDATE cart_research_jobs SET state=?,result=?,error_type=? WHERE id=?",
                       (state, result, error, job_id))
        self.live_bus.signal(job_id)

    def read(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{18,40}", job_id):
            raise ValueError("Invalid job id")
        with self._db() as db:
            row = db.execute("SELECT item,state,created,result,error_type FROM cart_research_jobs WHERE id=?",
                             (job_id,)).fetchone()
        if not row:
            raise ValueError("Unknown cart research job")
        with self._db() as db:
            progress = db.execute(
                "SELECT stage,revision,preview FROM cart_research_progress WHERE job_id=?",
                (job_id,)).fetchone()
            model_rows = db.execute(
                "SELECT offer_idx,status,questions_json FROM cart_offer_model_questions WHERE job_id=?",
                (job_id,)).fetchall()
            evidence_rows=db.execute(
                "SELECT offer_idx,result_json FROM cart_offer_evidence WHERE job_id=?",
                (job_id,)).fetchall()
            evidence_run=db.execute(
                "SELECT status,processed,planned FROM cart_evidence_runs WHERE job_id=?",
                (job_id,)).fetchone()
            discovery_row=db.execute("""SELECT status,receipt_json FROM
                cart_source_search WHERE job_id=?""",(job_id,)).fetchone()
            verdict_row=db.execute("""SELECT status,result_json,error_type FROM
                cart_final_verdict WHERE job_id=?""",(job_id,)).fetchone()
        model_offers = {
            "offer-{}".format(i): {"state": status,
                "questions": json.loads(data) if data else []}
            for i,status,data in model_rows
        }
        evidence_offers={"offer-{}".format(i):json.loads(raw)
                         for i,raw in evidence_rows}
        evidence_progress={
            "status":evidence_run[0],"processed":evidence_run[1],
            "planned":evidence_run[2]
        } if evidence_run else {"status":"NOT_STARTED","processed":0,"planned":0}
        source_search=(json.loads(discovery_row[1]) if discovery_row and
                       discovery_row[1] else {
                       "status":discovery_row[0] if discovery_row
                                else "NOT_STARTED",
                       "queries_used":0,"leads":[],"query_receipts":[]})
        final_verdict=(
            {**(json.loads(verdict_row[1]) if verdict_row[1] else {}),
             "status":verdict_row[0],
             "error_type":verdict_row[2]} if verdict_row else
            {"status":"NOT_SCHEDULED"})
        return {"source_search":source_search,
                "final_verdict":final_verdict,
                "item": json.loads(row[0]), "state": row[1],
                "created": row[2],
                "report": json.loads(row[3]) if row[3] else None,
                "error_type": row[4],
                "model_offers": model_offers,
                "evidence_offers":evidence_offers,
                "evidence_progress":evidence_progress,
                "progress_stage": progress[0] if progress else row[1],
                "progress_revision": progress[1] if progress else 0,
                "preview_report": json.loads(progress[2]) if progress and
                                  progress[2] and row[1] in ("QUEUED","RUNNING") else None}

    def close(self):
        self.model_stop.set()
        self.evidence_stop.set()
        self.pool.shutdown(wait=True)
        self.model_pool.shutdown(wait=True)
        self.evidence_pool.shutdown(wait=True)
