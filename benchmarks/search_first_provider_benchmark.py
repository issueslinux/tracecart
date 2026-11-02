"""OFFLINE comparison of raw SerpApi/DataForSEO Google Shopping responses.

No network access, credentials, browser automation, payment or estimates.
Input file for each product/provider must contain an actual captured JSON API
response; missing files are NOT_RUN, never zero-coverage failures.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json
import re
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from product_intake import normalized_product_url
PROVIDERS = ("serpapi", "dataforseo")
PL_CURRENCY = ("PLN", "EUR", "USD")
MAX_CASES = 20
MAX_JSON_BYTES = 2_500_000
ALLOWED_ITEM_TYPES = {
    "google_shopping_serp", "google_shopping_paid",
    "google_shopping_carousel_element",
    "google_shopping_sponsored_carousel_element",
}
MARKETS = {"allegro", "amazon", "ebay", "ceneo"}


class ProviderNotReady(ValueError):
    """Response is pending, not a completed provider search with no matches."""


def _compact(text):
    return "".join(re.findall(r"[a-z0-9]+", str(text).casefold().replace("ł", "l")))


def _safe_price(value):
    if type(value) not in (int, float, str):
        return None
    try:
        dec = Decimal(str(value))
    except (ValueError, InvalidOperation):
        return None
    if not dec.is_finite() or not Decimal("0.01") <= dec <= Decimal("100000"):
        return None
    if dec.as_tuple().exponent < -2:
        return None
    return str(dec.quantize(Decimal("0.01")))


def _currency_from_display(price_text):
    if not isinstance(price_text, str):
        return None
    matched = []
    for currency, tokens in (("PLN", ("zł", "PLN")),
                             ("EUR", ("€", "EUR")),
                             ("USD", ("USD",))):
        if any(token.casefold() in price_text.casefold() for token in tokens):
            matched.append(currency)
    return matched[0] if len(matched) == 1 else None


def _safe_url(url):
    if not isinstance(url, str) or len(url) > 1400:
        return None
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower()
        port = p.port
    except ValueError:
        return None
    if (p.scheme != "https" or p.username or p.password or
            port not in (None, 443) or not host or "." not in host
            or host in ("localhost", "127.0.0.1")
            or host.endswith((".local", ".internal"))):
        return None
    if all(bit.isdigit() for bit in host.split(".")):
        return None
    # Google Shopping links are source URLs, NOT direct merchant offer links.
    if host.startswith(("www.google.", "google.")) or host == "google.com":
        return None
    try:
        return normalized_product_url(url)
    except (TypeError, ValueError):
        return None


def _marketplace(seller, url):
    host = (urlsplit(url).hostname or "").lower() if url else ""
    name = str(seller).casefold()
    for marker in MARKETS:
        if (marker in name or host == marker + ".pl" or
                host.startswith(marker + ".") or
                ("." + marker + ".") in host):
            return marker
    return None


def _variant(case, title):
    if not isinstance(title, str) or not title.strip():
        return "NO_LISTING_TITLE"
    compact = _compact(title)
    tokens = case["model_tokens"]
    if all(_compact(token) in compact for token in tokens):
        return "MODEL_TOKENS_PRESENT_GTIN_STILL_UNVERIFIED"
    return "MODEL_TOKENS_NOT_ESTABLISHED"


def _dataforseo_candidates(raw):
    if not isinstance(raw, dict) or raw.get("status_code") != 20000:
        raise ValueError("DataForSEO provider request was not successful")
    rows = []
    finished = False
    pending = False
    for task in (raw.get("tasks") or [])[:3]:
        if not isinstance(task, dict):
            continue
        if task.get("status_code") != 20000:
            if task.get("status_code") in (20100, 20101, 20102):
                pending = True
            continue
        if task.get("result") is None:
            pending = True
            continue
        finished = True
        for result in (task.get("result") or [])[:2]:
            if not isinstance(result, dict):
                continue
            def walk(nodes, depth=0):
                if depth > 2 or not isinstance(nodes, list):
                    return
                for item in nodes[:100]:
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") in ALLOWED_ITEM_TYPES:
                        rows.append({
                            "title":item.get("title"),
                            "seller":item.get("seller"),
                            "price":item.get("price"),
                            "currency":item.get("currency"),
                            "url":item.get("url"),
                            "tier":"GOOGLE_SHOPPING_SERP_INDEX",
                        })
                    walk(item.get("items"), depth+1)
            walk(result.get("items"))
    if pending and not finished:
        raise ProviderNotReady("DataForSEO task was not completed")
    if not finished:
        raise ValueError("DataForSEO did not return completed task results")
    return rows


def _serpapi_candidates(raw):
    if not isinstance(raw, dict):
        raise ValueError("SerpApi response must be JSON object")
    if "error" in raw:
        raise ValueError("SerpApi returned an error")
    status = (raw.get("search_metadata") or {}).get("status")
    if status in ("Processing", "Queued"):
        raise ProviderNotReady("SerpApi response was not completed")
    if status not in (None, "Success"):
        raise ValueError("SerpApi response was not successful")
    result = raw.get("shopping_results")
    detail = raw.get("product_results")
    if result is None and detail is None:
        raise ValueError("No SerpApi Shopping or Product result found")
    rows = []
    if isinstance(result, list):
        for item in result[:120]:
            if not isinstance(item, dict):
                continue
            rows.append({
                "title":item.get("title"), "seller":item.get("source"),
                "price":item.get("extracted_price"),
                "currency":_currency_from_display(item.get("price")),
                "url":item.get("link"),  # NOT Google product_link
                "tier":"GOOGLE_SHOPPING_SEARCH_INDEX",
            })
    if isinstance(detail, dict) and isinstance(detail.get("stores"), list):
        for item in detail["stores"][:70]:
            if not isinstance(item, dict):
                continue
            rows.append({
                "title":item.get("title") or detail.get("title"),
                "seller":item.get("name"), "price":item.get("extracted_price"),
                "currency":_currency_from_display(item.get("price")),
                "url":item.get("link"),
                "tier":"GOOGLE_PRODUCT_STORE_INDEX",
            })
    return rows


def _parsed_rows(provider, data, case):
    raw = (_serpapi_candidates(data) if provider == "serpapi"
           else _dataforseo_candidates(data))
    results = []
    seen = set()
    for entry in raw:
        price = _safe_price(entry["price"])
        currency = entry["currency"]
        seller = entry["seller"] if isinstance(entry["seller"], str) else ""
        title = entry["title"] if isinstance(entry["title"], str) else ""
        if not seller.strip() or not price or currency not in PL_CURRENCY:
            continue
        url = _safe_url(entry["url"])
        # A provider may omit merchant URL entirely, but an explicitly
        # supplied unsafe/non-public link is NOT an acceptable offer lead.
        if entry["url"] and url is None:
            continue
        key = (seller.casefold(), price, currency, _compact(title), url)
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "seller":seller.strip()[:100],
            "title":title[:180],
            "indexed_price":price,
            "currency":currency,
            "merchant_url_unverified":url,
            "listing_identity":_variant(case, title),
            "marketplace":_marketplace(seller, url),
            "evidence_tier":entry["tier"],
            "source_qualified_seller_price":False,
        })
    return results


def _manifest(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("products")
    if (not isinstance(cases, list) or len(cases) != MAX_CASES or
            not isinstance(data.get("dataset_id"), str)):
        raise ValueError("Expected exactly 20 Poland shopping research cases")
    seen = set()
    for item in cases:
        if (not isinstance(item, dict) or
                not re.fullmatch(r"[A-Za-z0-9_]{3,45}", str(item.get("id", ""))) or
                not isinstance(item.get("title"), str) or
                not 6 <= len(item["title"]) <= 180 or
                not isinstance(item.get("model_tokens"), list) or
                not 1 <= len(item["model_tokens"]) <= 3 or
                any(not isinstance(t, str) or not 2 <= len(t) <= 22
                    for t in item["model_tokens"]) or item["id"] in seen):
            raise ValueError("Invalid case identity/variant token")
        seen.add(item["id"])
    return cases


def evaluate(manifest_path, input_dirs):
    """Response comparison, not a simulated or automatic API search."""
    cases = _manifest(Path(manifest_path))
    rows = []
    for case in cases:
        result = {"id":case["id"], "title":case["title"], "segment":case["category"]}
        for provider in PROVIDERS:
            base = input_dirs.get(provider)
            row = {"status":"NOT_EXECUTED_NO_RESPONSE", "observed_offers":0,
                   "model_token_candidates":0, "marketplace_price_observations":0,
                   "marketplaces":[], "unverified_lowest_same_currency":None,
                   "direct_merchant_links_seen":0,
                   "sample_observations":[]}
            if base is not None:
                fname = Path(base) / (case["id"] + ".json")
                if fname.is_file():
                    try:
                        if fname.stat().st_size > MAX_JSON_BYTES:
                            raise ValueError("Provider sample exceeds size bound")
                        body = json.loads(fname.read_text(encoding="utf-8"))
                        candidates = _parsed_rows(provider, body, case)
                        hits = [o for o in candidates
                                if o["listing_identity"] ==
                                "MODEL_TOKENS_PRESENT_GTIN_STILL_UNVERIFIED"
                                and o["currency"] == "PLN"]
                        markets = [o for o in hits if o["marketplace"]]
                        row["status"] = ("INDEXED_PRODUCT_CANDIDATES" if hits
                                         else "RESPONSE_WITHOUT_MATCHED_MODEL_AND_PLN")
                        row["observed_offers"] = len(candidates)
                        row["model_token_candidates"] = len(hits)
                        row["marketplace_price_observations"] = len(markets)
                        row["marketplaces"] = sorted({o["marketplace"] for o in markets})
                        row["direct_merchant_links_seen"] = sum(
                            bool(o["merchant_url_unverified"]) for o in hits)
                        if hits:
                            best = min(hits, key=lambda x: Decimal(x["indexed_price"]))
                            row["unverified_lowest_same_currency"] = {
                                "price":best["indexed_price"], "currency":"PLN",
                                "seller":best["seller"], "source_type":best["evidence_tier"]}
                        row["sample_observations"] = candidates[:25]
                    except ProviderNotReady:
                        row["status"] = "PROVIDER_RESPONSE_PENDING_NOT_MEASURED"
                    except (OSError, ValueError, TypeError, KeyError,
                            json.JSONDecodeError):
                        row["status"] = "PROVIDER_RESPONSE_INVALID_OR_UNREADABLE"
            result[provider] = row
        rows.append(result)
    aggregate = {}
    for provider in PROVIDERS:
        completed = [r[provider] for r in rows
                     if r[provider]["status"] not in (
                         "NOT_EXECUTED_NO_RESPONSE",)]
        valid = [r for r in completed if r["status"] not in (
            "PROVIDER_RESPONSE_INVALID_OR_UNREADABLE",
            "PROVIDER_RESPONSE_PENDING_NOT_MEASURED")]
        aggregate[provider] = {
            "samples_target":len(cases),
            "responses_supplied":len(completed),
            "responses_valid":len(valid),
            "samples_with_model_token_and_PLN_price":sum(
                r["model_token_candidates"] > 0 for r in valid),
            "samples_with_indexed_marketplace_price":sum(
                r["marketplace_price_observations"] > 0 for r in valid),
            "observed_priced_listings":sum(r["observed_offers"] for r in valid),
            "unverified_merchant_links":sum(r["direct_merchant_links_seen"] for r in valid),
            "representative_market_coverage":False,
        }
    return {
        "dataset":"SHOPPING_API_20_PRODUCT_SOURCE_BENCHMARK",
        "report_generated_at":datetime.now(timezone.utc).isoformat(),
        "execution_mode":"OFFLINE_REPLAY_OF_EXPLICIT_PROVIDER_JSON_ONLY",
        "sample_scope":"PURPOSIVE_NOT_RANDOM_NOT_MARKET_REPRESENTATIVE",
        "case_count":len(rows),
        "provider_metrics":aggregate,
        "results":rows,
        "limitations":[
            "No API response file means NOT EXECUTED, never zero coverage.",
            "Provider response timestamps and freshness must be independently checked; the report generation timestamp is NOT the price-observation time.",
            "Google Shopping indexed listings and prices are not fresh checkout-verified offers.",
            "Exact product variant/EAN cannot be confirmed solely by matching model words.",
            "No direct marketplace site access or bypass is attempted.",
            "No request was sent to SerpApi, DataForSEO, Allegro or any seller by this benchmark.",
        ],
        "payment_authorized":False,
    }


def main():
    cli=argparse.ArgumentParser(description="Offline replay benchmark: SerpApi vs DataForSEO")
    cli.add_argument("--samples", default=str(ROOT/"shopping_20_products.json"))
    cli.add_argument("--serpapi-dir")
    cli.add_argument("--dataforseo-dir")
    cli.add_argument("--output", required=True)
    cli.add_argument("--require-all-responses", action="store_true")
    args=cli.parse_args()
    data=evaluate(args.samples, {"serpapi":args.serpapi_dir,
                                 "dataforseo":args.dataforseo_dir})
    if args.require_all_responses and any(
            stat["responses_valid"] != MAX_CASES
            for stat in data["provider_metrics"].values()):
        cli.error("20 real successful API responses for BOTH providers are required")
    Path(args.output).write_text(
        json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(data["provider_metrics"], ensure_ascii=False))


if __name__ == "__main__":
    main()
