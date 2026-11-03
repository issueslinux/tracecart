"""Policy-constrained acquisition adapter for universal product extraction.

Reuses TraceCart's DNS-pinned HTTPS transport and robots preflight. It never
bypasses merchant challenges or uses cookies, browser profiles or paid APIs.
"""
from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from product_intake import (
    _read, MAX_PAGE_BYTES, MAX_ROBOTS_BYTES, USER_AGENT,
    SourceAccessDenied, SourceHTTPFailure, SourceRedirect,
    validate_product_url,
)
from universal_product_extract import extract_snapshot

HTML_MIMES = ("text/html", "application/xhtml+xml")


def _failure(url, status, detail):
    now = datetime.now(timezone.utc).isoformat()
    return {
        "status": status, "reason": detail, "source_url": url,
        "acquired_at": now, "acquisition_method": "STATIC_HTML",
        "snapshot_sha256": sha256(b"").hexdigest(),
        "fields": {key: None for key in (
            "title", "brand", "model", "sku", "gtin", "price",
            "currency", "availability", "condition", "seller")},
        "evidence": [], "conflicts": [], "shipping_claims": [],
        "seller_verified": False, "checkout_verified": False,
        "index_only": False, "robots_checked": False,
    }


def acquire_public_product(url, fetch=None, render=None, enable_render=False):
    """Fetch *permitted public* page then extract; no merchant access bypass.

    A supplied fetch/render callable is for dependency-injected tests or a
    separately audited authorized adapter. The default HTTP transport is
    public-DNS-pinned HTTPS only. Browser fallback is opt-in, executed only
    after a successful, robots-approved HTTP 200, never after 403/CAPTCHA.
    """
    safe = validate_product_url(url)
    host = urlsplit(safe).hostname
    robots_url = "https://" + host + "/robots.txt"
    getter = fetch or _read
    try:
        robots = getter(robots_url, MAX_ROBOTS_BYTES, ("text/plain", "text/html"))
        if type(robots) is not bytes or len(robots) > MAX_ROBOTS_BYTES:
            return _failure(safe, "ROBOTS_UNAVAILABLE", "robots.txt invalid")
        rules = RobotFileParser()
        rules.parse(robots.decode("utf-8", "replace").splitlines())
    except (SourceAccessDenied, SourceHTTPFailure, SourceRedirect,
            ValueError, OSError, TimeoutError):
        return _failure(safe, "ROBOTS_UNAVAILABLE", "robots.txt not safely verified")
    if not rules.can_fetch(USER_AGENT, safe):
        rejected = _failure(safe, "ROBOTS_DENIED", "source disallowed by robots.txt")
        rejected["robots_checked"] = True
        return rejected

    current = safe
    seen = {safe}
    for _ in range(3):
        try:
            raw = getter(current, MAX_PAGE_BYTES, HTML_MIMES)
            if type(raw) is not bytes or len(raw) > MAX_PAGE_BYTES:
                raise ValueError("INVALID_SOURCE_BYTES")
            result = extract_snapshot(current, raw, "text/html", "STATIC_HTML")
            result["robots_checked"] = True
            result["original_requested_url"] = safe
            if (enable_render and result["status"] in (
                    "PRODUCT_NOT_IDENTIFIED", "PRODUCT_FOUND_NO_PRICE") and raw):
                try:
                    if render is None:
                        from browser_render import rendered_browser_document
                        rendered = rendered_browser_document(current, raw, enabled=True)
                    else:
                        rendered = render(current, raw)
                    alternate = extract_snapshot(current, rendered, "text/html", "RENDERED_DOM")
                    alternate["robots_checked"] = True
                    alternate["original_requested_url"] = safe
                    alternate["pre_render_status"] = result["status"]
                    # Do not replace a parseable static product with a
                    # less informative browser observation.
                    if alternate["status"] == "PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED":
                        return alternate
                    result["render_fallback_status"] = alternate["status"]
                except (ValueError, OSError, TimeoutError, TypeError):
                    result["render_fallback_status"] = "RENDER_NOT_AVAILABLE"
            return result
        except SourceRedirect as redirect:
            try:
                target = validate_product_url(urljoin(current, redirect.location))
            except (ValueError, TypeError):
                failure = _failure(safe, "REDIRECT_REJECTED", "unsafe redirect target")
                failure["robots_checked"] = True
                return failure
            if urlsplit(target).hostname != host or target in seen or not rules.can_fetch(USER_AGENT, target):
                failure = _failure(safe, "REDIRECT_REJECTED", "cross-host, duplicate or robots-denied redirect")
                failure["robots_checked"] = True
                return failure
            seen.add(target)
            current = target
        except (SourceAccessDenied, SourceHTTPFailure) as err:
            out = extract_snapshot(current, b"", http_status=err.status)
            out["robots_checked"] = True
            out["original_requested_url"] = safe
            return out
        except (ValueError, OSError, TimeoutError):
            out = _failure(safe, "SOURCE_FETCH_FAILED", "source retrieval rejected or failed")
            out["robots_checked"] = True
            return out
    out = _failure(safe, "REDIRECT_LIMIT", "maximum 3 redirect hops")
    out["robots_checked"] = True
    return out
