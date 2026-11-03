"""Conservative source-URL key for browser evidence linked to cart research.

Unknown URL query keys may encode color/size/variant; do not drop them and
silently link unrelated offers. Only explicitly known tracking params may
be discarded. This is NOT proof of exact variant.
"""
from urllib.parse import parse_qsl, urlsplit

from product_intake import normalized_product_url, validate_product_url

_TRACKING = frozenset((
    "fbclid", "gclid", "gbraid", "wbraid", "msclkid", "yclid",
    "mc_cid", "mc_eid", "ref", "referrer", "source", "campaign",
))


def browser_cart_link_key(url):
    safe = validate_product_url(url)
    for name, _ in parse_qsl(urlsplit(safe).query, keep_blank_values=True):
        lowered = name.casefold()
        if lowered == "offerid":
            # Current normalized_product_url already retains only numeric
            # offerIds. Non-numeric ones must not become an empty query.
            if name != "offerId":
                return None
            continue
        if lowered.startswith("utm_") or lowered in _TRACKING:
            continue
        return None
    normalized = normalized_product_url(safe)
    if "offerId" in [k for k, _ in parse_qsl(urlsplit(safe).query)]:
        if not urlsplit(normalized).query:
            return None
    return normalized
