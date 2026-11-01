"""Cart-triggered, non-blocking evidence research. NO commerce or payment actions.

Research products in Open Products Facts and attempt Open Prices price evidence.
A Brave web search is optionally used for offer URL discovery when the
operator has configured BRAVE_API_KEY; snippets are NOT verified store offers.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
import re
import secrets
import sqlite3
import threading
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from decision_tree import _node, to_html_tree

USER_AGENT = "TraceCart/0.4 (https://github.com/issueslinux/tracecart)"
OPF_ROOT = "https://world.openproductsfacts.org"
OPEN_PRICES_ROOT = "https://prices.openfoodfacts.org"
BRAVE_ROOT = "https://api.search.brave.com"
MAX_CANDIDATES = 8
MAX_SEARCH_HITS = 6


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


class _NoExternalRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a confidential search key to another host.
        raise ValueError("Unexpected API redirect")


def _get_json(url, host, headers=None, timeout=15):
    if urlsplit(url).scheme != "https" or urlsplit(url).hostname != host:
        raise ValueError("Unsupported API host")
    # Fixed host and fixed paths: no user-controlled outbound URL.
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    request_headers.update(headers or {})
    req = Request(url, headers=request_headers)
    with build_opener(_NoExternalRedirect()).open(req, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError("Source API returned non-200")
        buf = response.read(200001)
        if len(buf) > 200000:
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


def research_cart(item, fetch=_get_json, max_candidates=MAX_CANDIDATES):
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
        search_q = " ".join(item["title"].split()[:12]) + " kup online cena porównanie"
        brave_url = BRAVE_ROOT + "/res/v1/web/search?" + urlencode({
            "q": search_q[:240], "country": "PL", "search_lang": "pl", "count": 6,
        })
        try:
            hits = fetch(brave_url, "api.search.brave.com",
                         {"X-Subscription-Token": key})
            results = hits.get("web", {}).get("results", [])
            for hit in results[:MAX_SEARCH_HITS]:
                if type(hit) is not dict:
                    continue
                target = hit.get("url", "")
                parsed = urlsplit(target) if isinstance(target, str) else None
                if parsed and parsed.scheme == "https" and parsed.hostname and not parsed.username:
                    sources["web_hits"].append({
                        "title": str(hit.get("title", ""))[:180],
                        "url": target, "snippet": str(hit.get("description", ""))[:450],
                        "source_kind": "UNVERIFIED_SEARCH_RESULT_NOT_A_PRICE_OFFER",
                    })
            attempts.append({"source": "Brave Web Search", "status": "OK",
                             "candidate_urls": len(sources["web_hits"]),
                             "verified_retail_prices": 0})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            attempts.append({"source": "Brave Web Search", "status": "FAILED",
                             "error_type": type(exc).__name__})
    else:
        attempts.append({"source": "Brave Web Search", "status": "SKIPPED_NO_API_KEY",
                         "note": "Cross-store search requires configured search API; no fake offers."})
    qs = _derive_questions(item, sources["catalog"], sources, category)
    # A failed local model does NOT erase the deterministic decision tree.
    ai_questions, ai_status = [], "SKIPPED"
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
    root["children"].append(_node("category_model",
        "Adaptive questions for " + category, "RESEARCH_QUESTIONS",
        {"question_count": len(qs), "questions_about": "sources_offers_reviews_not_user"},
        [_node("question", q, "OPEN",
               {"answer": "Not established by retrieved sources; needs product evidence"},
               node_id="cart-q-{}".format(i)) for i, q in enumerate(qs)],
        node_id="cart-questions"))
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
            "comparison_status": "UNPRICED_ALTERNATIVES",
            "result": ("Other catalog products found; retailer offers and price "
                       "differences remain unverified. Show questions and alternatives "
                       "before checkout, without blocking it."),
            "payment_authorized": False,
        }, node_id="cart-summary"))
    report = {
        "schema_version": 1, "generated_at": now,
        "root": root, "source_discovery": sources,
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
        self.runner = runner
        self.pool = ThreadPoolExecutor(max_workers=worker_limit)
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS cart_research_jobs (
                id TEXT PRIMARY KEY, item TEXT NOT NULL, state TEXT NOT NULL,
                created TEXT NOT NULL, result TEXT, error_type TEXT)""")
            db.execute("UPDATE cart_research_jobs SET state='INTERRUPTED' "
                       "WHERE state IN ('QUEUED','RUNNING')")
        self.lock = threading.Lock()

    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=8)
        db.execute("PRAGMA busy_timeout=8000")
        return db

    def submit(self, item):
        clean = validate_cart(item)
        job_id = secrets.token_urlsafe(18)
        with self._db() as db:
            db.execute("INSERT INTO cart_research_jobs(id,item,state,created) VALUES (?,?,?,?)",
                       (job_id, json.dumps(clean), "QUEUED",
                        datetime.now(timezone.utc).isoformat()))
        self.pool.submit(self._work, job_id, clean)
        return job_id

    def submit_url(self, product_url):
        from product_intake import validate_product_url
        url = validate_product_url(product_url)
        job_id = secrets.token_urlsafe(18)
        with self._db() as db:
            db.execute("INSERT INTO cart_research_jobs(id,item,state,created) VALUES (?,?,?,?)",
                       (job_id, json.dumps({"merchant_url": url,
                                             "intake": "URL_EXTRACTION_PENDING"}),
                        "QUEUED", datetime.now(timezone.utc).isoformat()))
        self.pool.submit(self._work_url, job_id, url)
        return job_id

    def _work_url(self, job_id, url):
        from product_intake import extract_product_page
        with self._db() as db:
            db.execute("UPDATE cart_research_jobs SET state='RUNNING' WHERE id=?", (job_id,))
        try:
            item, source = extract_product_page(url)
            clean = validate_cart(item)
            with self._db() as db:
                db.execute("UPDATE cart_research_jobs SET item=? WHERE id=?",
                           (json.dumps(clean), job_id))
            report = self.runner(clean)
            report["source_intake"] = source
            report["root"]["details"]["source_intake"] = {
                "url": url, "price_status": source["price_status"],
                "extraction_method": source["extraction_method"]}
            report["root"]["children"].insert(2, _node(
                "source_intake", "Actual selected product web page",
                "SELLER_DECLARATION",
                {"extracted_product": clean, "page_metadata": source,
                 "price_is_confirmed_checkout_total": False},
                node_id="cart-source-intake"))
            report.pop("sha256", None)
            report["sha256"] = sha256(json.dumps(
                report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            state, result, error = "READY", json.dumps(report, ensure_ascii=False), None
        except Exception as exc:
            state, result, error = "FAILED", None, type(exc).__name__
        with self._db() as db:
            db.execute("UPDATE cart_research_jobs SET state=?,result=?,error_type=? WHERE id=?",
                       (state, result, error, job_id))

    def _work(self, job_id, item):
        with self._db() as db:
            db.execute("UPDATE cart_research_jobs SET state='RUNNING' WHERE id=?", (job_id,))
        try:
            report = self.runner(item)
            state = "READY"
            result = json.dumps(report, ensure_ascii=False)
            error = None
        except Exception as exc:
            # Never store credential-bearing network error strings.
            state, result, error = "FAILED", None, type(exc).__name__
        with self._db() as db:
            db.execute("UPDATE cart_research_jobs SET state=?,result=?,error_type=? WHERE id=?",
                       (state, result, error, job_id))

    def read(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{18,40}", job_id):
            raise ValueError("Invalid job id")
        with self._db() as db:
            row = db.execute("SELECT item,state,created,result,error_type FROM cart_research_jobs WHERE id=?",
                             (job_id,)).fetchone()
        if not row:
            raise ValueError("Unknown cart research job")
        return {"item": json.loads(row[0]), "state": row[1],
                "created": row[2],
                "report": json.loads(row[3]) if row[3] else None,
                "error_type": row[4]}

    def close(self):
        self.pool.shutdown(wait=True)
