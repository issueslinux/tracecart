"""Bounded independent multi-merchant evidence: never pick a winner by listed price.

Each URL is compared to the ORIGINAL selected source, not to another candidate.
Failed pages remain explicit evidence branches. A multi-source report never
assumes a shipping-inclusive winner, even if some listed prices are lower.
"""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from urllib.parse import urlsplit

from live_offer_compare import compare_live_offer
from product_intake import normalized_product_url


MAX_OTHER_MERCHANTS = 4


def _host(url):
    hostname = urlsplit(url).hostname or ""
    return hostname[4:] if hostname.startswith("www.") else hostname


def compare_live_offers(base_report, selected, candidate_urls, extractor=None):
    """Compare 1..4 merchant URLs. Fail validation before any network calls."""
    if type(candidate_urls) is not list or not (1 <= len(candidate_urls) <= MAX_OTHER_MERCHANTS):
        raise ValueError("Provide 1 to 4 alternative product URLs")
    original = normalized_product_url(selected["merchant_url"])
    urls = [normalized_product_url(url) for url in candidate_urls]
    if len(set(urls)) != len(urls) or original in urls:
        raise ValueError("Duplicate URL or selected product URL")
    # One URL per retailer limits requests and avoids counting one merchant
    # repeatedly as independent evidence.
    hosts = [_host(url) for url in urls]
    if len(set(hosts)) != len(hosts):
        raise ValueError("Use one candidate URL per retailer")
    if len(urls) == 1:
        return compare_live_offer(base_report, selected, urls[0], extractor=extractor)

    result = deepcopy(base_report)
    if "root" not in result or not result["root"].get("children"):
        raise ValueError("Original cart report lacks research tree")
    comparisons, branches = [], []
    for index, url in enumerate(urls):
        single = compare_live_offer(base_report, selected, url, extractor=extractor)
        comparison = single["live_competitor_comparison"]
        branch = single["root"]["children"][-2]
        branch["id"] = "cart-live-competitor-{}".format(index + 1)
        branch["title"] = "Independent seller page {}: {}".format(index + 1, url)
        branches.append(branch)
        comparisons.append(comparison)

    result["root"]["children"][-1:-1] = branches
    verified = sum(c["status"] == "SAME_GTIN_SELLER_LISTED_PRICE_COMPARISON"
                   for c in comparisons)
    fetched = sum(c["alternative_retrieved"] for c in comparisons)
    summary = result["root"]["children"][-1]["details"]
    summary.update({
        "live_second_offer_status": "MULTI_RETAILER_RESEARCH",
        "comparison_status": "MULTI_RETAILER_RESEARCH_NO_DELIVERED_WINNER",
        "current_competitor_offers_verified": verified,
        "competing_source_pages_retrieved": fetched,
        "competing_source_pages_requested": len(urls),
        "result": ("Compared {} independent candidate URLs; {} pages retrieved, "
                   "{} passed seller-claim GTIN, variant, stock, price and "
                   "currency gates. No final delivered-price winner: "
                   "shipping, fees and checkout totals are unverified."
                   ).format(len(urls), fetched, verified),
        "payment_authorized": False,
    })
    result["live_competitor_comparisons"] = comparisons
    result["multi_offer_summary"] = {
        "requested": len(urls),
        "pages_retrieved": fetched,
        "source_qualified_comparisons": verified,
        "no_shipping_inclusive_winner": True,
        "price_ranked_as_delivered": False,
        "payment_authorized": False,
        "statuses": [{"url": c["alternative_requested_url"], "status": c["status"]}
                     for c in comparisons],
    }
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    result["limitations"] = list(result.get("limitations", [])) + [
        "Each retailer is independently compared against the original selected source.",
        "Distinct website hostnames are not proof of independent legal ownership.",
        "No delivered-price ranking: destination, shipping and checkout totals are unknown.",
        "No automated purchase or payment capture.",
    ]
    result.pop("sha256", None)
    result["sha256"] = sha256(json.dumps(
        result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return result
