"""Explicit paid DataForSEO Google Shopping research, asynchronous task contract.

These are product-index observations, not seller-page EAN verification or
checkout prices. Tasks must be explicitly queued; normal requests are not
charged by default. Task ids are later collected without re-posting.
"""
import base64
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import re
import urllib.request
from urllib.parse import urlsplit
from uuid import UUID

API_HOST = "api.dataforseo.com"
POST_PATH = "/v3/merchant/google/products/task_post"
GET_PREFIX = "/v3/merchant/google/products/task_get/advanced/"
MAX_BATCH = 20
MAX_JSON = 2500000


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("DataForSEO response redirect rejected")


def _api(url, method, credentials, body=None):
    if (urlsplit(url).hostname != API_HOST or urlsplit(url).scheme != "https"
            or urlsplit(url).port not in (None, 443)
            or not (urlsplit(url).path == POST_PATH
                    or urlsplit(url).path.startswith(GET_PREFIX))):
        raise ValueError("Unsupported provider endpoint")
    login, password = credentials
    if not (isinstance(login, str) and isinstance(password, str) and login and password):
        raise ValueError("DataForSEO credentials are missing")
    token = base64.b64encode((login + ":" + password).encode()).decode()
    payload = (json.dumps(body).encode("utf-8") if body is not None else None)
    request = urllib.request.Request(url, data=payload, method=method, headers={
        "Authorization": "Basic " + token,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "TraceCart/0.4 (+https://github.com/issueslinux/tracecart)",
    })
    with urllib.request.build_opener(_NoRedirect()).open(request, timeout=25) as response:
        if response.status != 200:
            raise ValueError("Shopping provider status not 200")
        raw = response.read(MAX_JSON + 1)
        if len(raw) > MAX_JSON:
            raise ValueError("Shopping response exceeds size bound")
        return json.loads(raw.decode("utf-8"))


def _valid_tasks(data):
    if type(data) is not dict or data.get("status_code") != 20000:
        raise ValueError("DataForSEO request failed")
    tasks = data.get("tasks")
    if type(tasks) is not list:
        raise ValueError("Invalid DataForSEO task response")
    return tasks


def queue_dataforseo_products(items, credentials, requester=None, allow_paid=False):
    """One task per selected product; intentionally no automatic background job."""
    if not allow_paid:
        raise ValueError("A paid request requires explicit allow_paid=True")
    if type(items) is not list or not 1 <= len(items) <= MAX_BATCH:
        raise ValueError("Expected 1–20 selected product names")
    request = requester or _api
    specs = []
    for idx, item in enumerate(items):
        if type(item) is not dict or not isinstance(item.get("title"), str):
            raise ValueError("Each product must have a title")
        name = " ".join(item["title"].split())
        if not 5 <= len(name) <= 170:
            raise ValueError("Invalid product title")
        code = item.get("barcode", "")
        if code and (not isinstance(code, str) or not re.fullmatch(r"\d{8}|\d{12,14}", code)):
            raise ValueError("Invalid optional product EAN")
        term = (code + " " + name).strip()[:200] if code else name[:200]
        specs.append({
            "location_name": "Poland",
            "language_code": "pl",
            "keyword": term,
            "priority": 1,
            "tag": "tracecart-sample-{:02d}".format(idx+1),
        })
    # Do not log endpoint body with credentials or user's raw query.
    response = request("https://" + API_HOST + POST_PATH, "POST", credentials, specs)
    tasks = _valid_tasks(response)
    if len(tasks) != len(items):
        raise ValueError("Provider task-count mismatch")
    output = []
    for i, row in enumerate(tasks):
        if type(row) is not dict:
            raise ValueError("Malformed provider task")
        tid = row.get("id")
        if not isinstance(tid, str) or not _valid_uuid(tid):
            raise ValueError("Missing valid task ID")
        output.append({
            "sample_id": items[i].get("id"),
            "task_id": tid,
            "state": "QUEUED_PROVIDER_ASYNC",
            "provider_status_code": row.get("status_code"),
        })
    return {
        "provider": "DATAFORSEO_GOOGLE_SHOPPING_PRODUCTS",
        "status": "QUEUED_PROVIDER_ASYNC_NOT_PRICE_RESULTS",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sample_count": len(items),
        "task_ids": output,
        "estimated_cost_not_quoted": True,
        "payment_authorized": False,
        "note": "Task creation may incur DataForSEO charges. Collect results separately; standard queue is asynchronous.",
    }


def _valid_uuid(value):
    try:
        UUID(value)
        return True
    except (TypeError, ValueError):
        return False


def parse_dataforseo_products_result(payload, max_offers=20):
    """Parse current indexed prices with explicit currency and merchant name.

    The Products endpoint often returns url=null. Never fabricate a direct
    merchant URL from a Google Shopping item or shop_ad_aclk.
    """
    tasks = _valid_tasks(payload)
    offers = []
    state = "PENDING_OR_NO_RESULT"
    for task in tasks[:2]:
        if not isinstance(task, dict):
            continue
        if task.get("status_code") not in (20000,):
            if task.get("status_code") in (20100, 20101):
                continue
            raise ValueError("Provider task not successful")
        results = task.get("result")
        if not isinstance(results, list):
            continue
        state = "NO_PRICED_ITEMS"
        for result in results[:2]:
            if not isinstance(result, dict):
                continue
            items = result.get("items") or []
            if not isinstance(items, list):
                continue
            for raw in items[:80]:
                if not isinstance(raw, dict) or len(offers) >= max_offers:
                    continue
                if raw.get("type") not in ("google_shopping_serp",
                                          "google_shopping_carousel_element",
                                          "google_shopping_sponsored_carousel_element"):
                    continue
                seller = raw.get("seller")
                title = raw.get("title")
                price = raw.get("price")
                curr = raw.get("currency")
                if not isinstance(seller, str) or not seller.strip():
                    continue
                if not isinstance(title, str) or not title.strip() or curr not in ("PLN", "EUR", "USD"):
                    continue
                try:
                    number = Decimal(str(price))
                except (InvalidOperation, ValueError, TypeError):
                    continue
                if not number.is_finite() or not 0 < number <= 100000 or number.as_tuple().exponent < -2:
                    continue
                # Direct merchant URL is deprecated/null in this endpoint.
                link = raw.get("url")
                safe = None
                if isinstance(link, str):
                    try:
                        from product_intake import normalized_product_url
                        safe = normalized_product_url(link)
                    except (ValueError, TypeError):
                        pass
                offers.append({
                    "seller": seller.strip()[:100],
                    "title": title.strip()[:180],
                    "indexed_price": str(number.quantize(Decimal("0.01"))),
                    "currency": curr,
                    "merchant_url": safe,
                    "identity_status": "PRODUCT_IDENTITY_NOT_PROVEN_BY_SHOPPING_INDEX",
                    "source_type": "GOOGLE_SHOPPING_INDEX_NOT_DIRECT_SELLER_PAGE",
                    "source_page_retrieved": False,
                    "stock_verified": False,
                    "payment_authorized": False,
                })
                state = "INDEXED_OFFERS_AVAILABLE"
    return {"status": state, "offers": offers,
            "marketplace_sellers": sorted({r["seller"] for r in offers if
                  "allegro" in r["seller"].casefold() or "amazon" in r["seller"].casefold()}),
            "source_qualified_seller_offers": 0, "payment_authorized": False}


def collect_dataforseo_products(queued, credentials, requester=None):
    """Check each id once without blocking/requeueing a paid async task."""
    if type(queued) is not dict or queued.get("provider") != "DATAFORSEO_GOOGLE_SHOPPING_PRODUCTS":
        raise ValueError("Expected DataForSEO queued task manifest")
    task_rows = queued.get("task_ids")
    if type(task_rows) is not list or not 1 <= len(task_rows) <= MAX_BATCH:
        raise ValueError("Invalid pending tasks")
    request = requester or _api
    data = []
    for row in task_rows:
        tid = row.get("task_id") if type(row) is dict else None
        if not _valid_uuid(tid):
            raise ValueError("Invalid DataForSEO task ID")
        try:
            raw = request("https://" + API_HOST + GET_PREFIX + tid,
                          "GET", credentials)
            parsed = parse_dataforseo_products_result(raw)
            data.append({"sample_id": row.get("sample_id"), "task_id": tid, **parsed})
        except (OSError, ValueError, TypeError, KeyError) as exc:
            data.append({
                "sample_id": row.get("sample_id"), "task_id": tid,
                "status": "FAILED_" + type(exc).__name__, "offers": [],
                "source_qualified_seller_offers": 0,
                "payment_authorized": False,
            })
    return {
        "provider": "DATAFORSEO_GOOGLE_SHOPPING_PRODUCTS",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "results": data,
        "completed_count": sum(x["status"] in
                               ("INDEXED_OFFERS_AVAILABLE", "NO_PRICED_ITEMS")
                               for x in data),
        "payment_authorized": False,
    }
