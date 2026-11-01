"""Robots-aware, merchant-specific collector of verifiable LIVE product claims.

Strictly allowlisted Adafruit product pages only. No broad crawler, no search
engine scraping, no login, no API keys. Merchant statements remain single-source
claims, never independent proof of quality or seller reliability.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from html.parser import HTMLParser
import ipaddress
import json
import re
import socket
import time
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.robotparser import RobotFileParser

from decision_tree import analyze

USER_AGENT = "TraceCartResearchBot/0.2 (+https://github.com/issueslinux/tracecart)"
ALLOWED_HOSTS = frozenset(("www.adafruit.com",))
MAX_OFFERS = 5
MAX_HTML_BYTES = 300000
MIN_INTERVAL_SECONDS = 2.0
_TIMEOUT = 12


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirect to an unverified host is blocked")


def _safe_product_url(url):
    if not isinstance(url, str) or len(url) > 300:
        raise ValueError("Short product URL required")
    p = urlsplit(url)
    if (p.scheme != "https" or p.hostname not in ALLOWED_HOSTS
            or p.username or p.password or p.port not in (None, 443)
            or p.query or p.fragment or not re.fullmatch(r"/product/[1-9][0-9]{0,7}/?", p.path)):
        raise ValueError("Only HTTPS product pages on supported merchants may be fetched")
    # Canonical URL removes an unnecessary trailing slash and normalizes the host.
    return "https://www.adafruit.com" + p.path.rstrip("/")


def _public_addresses(host):
    # Defense in depth against DNS rebinding; allowlisted host is still required.
    answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not answers:
        raise ValueError("No public addresses for merchant")
    for address in answers:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("Non-public remote IP prohibited")


def _download(url, max_bytes=MAX_HTML_BYTES):
    _public_addresses(urlsplit(url).hostname)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    with build_opener(_NoRedirect()).open(
            Request(url, headers=headers), timeout=_TIMEOUT) as response:
        if response.status != 200:
            raise ValueError("Merchant returned unexpected HTTP status")
        mime = response.headers.get_content_type()
        if mime not in ("text/html", "application/xhtml+xml"):
            raise ValueError("Unexpected response MIME type")
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ValueError("Merchant response exceeds allowed size")
        charset = response.headers.get_content_charset() or "utf-8"
        if charset.lower() not in ("utf-8", "iso-8859-1", "windows-1252"):
            raise ValueError("Unsupported encoding")
        return body, body.decode(charset, errors="replace")


class _LdJsonParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inside = False
        self.fragments = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            attr = dict((k.lower(), v) for k, v in attrs)
            if (attr.get("type") or "").lower() == "application/ld+json":
                self.inside = True

    def handle_data(self, data):
        if self.inside:
            self.fragments.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "script":
            self.inside = False


def _jsonld_product(html):
    parser = _LdJsonParser()
    parser.feed(html)
    products = []
    for snippet in parser.fragments:
        if len(snippet) > 150000:
            continue
        try:
            data = json.loads(snippet)
        except (ValueError, TypeError):
            continue
        flattened = data if isinstance(data, list) else [data]
        for obj in flattened:
            if not isinstance(obj, dict):
                continue
            flattened2 = obj.get("@graph", [obj])
            if not isinstance(flattened2, list):
                continue
            for item in flattened2:
                if not isinstance(item, dict):
                    continue
                kinds = item.get("@type", [])
                kinds = [kinds] if isinstance(kinds, str) else kinds
                if isinstance(kinds, list) and "Product" in kinds:
                    products.append(item)
    if len(products) != 1:
        raise ValueError("Expected exactly one structured Product per page")
    return products[0]


def _price(raw):
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError):
        raise ValueError("Invalid merchant price")
    if not value.is_finite() or value < 0 or value > 100000:
        raise ValueError("Merchant price out of range")
    if value.as_tuple().exponent < -4:
        raise ValueError("Merchant price too precise")
    return str(value.quantize(Decimal("0.01")))


def _snippet(s, maxlen=400):
    if not isinstance(s, str):
        raise ValueError("Merchant description is not plain text")
    return re.sub(r"\s+", " ", s).strip()[:maxlen]


def _fact_evidence(sku, url, retrieved_at, digest, kind, excerpt, stance="supports"):
    return {
        "id": "merchant_{}_{}".format(sku, kind),
        "stance": stance, "url": url, "source_type": "listing",
        "excerpt": excerpt,
        "observation": "Merchant JSON-LD field (unverified, NOT independent research)",
        "retrieved_at": retrieved_at,
        "publisher": "adafruit.com",
        "sha256": digest, "extraction_method": "merchant_product_jsonld",
    }


class ProductCollector:
    def __init__(self, download=None, monotonic=None, sleep=None, robots_text=None):
        self.download = download or _download
        self.monotonic = monotonic or time.monotonic
        self.sleep = sleep or time.sleep
        self.robots_text = robots_text
        self.last_fetch = None

    def _pause(self):
        if self.last_fetch is not None:
            delay = MIN_INTERVAL_SECONDS - (self.monotonic() - self.last_fetch)
            if delay > 0:
                self.sleep(delay)
        self.last_fetch = self.monotonic()

    def _robots(self):
        robots_url = "https://www.adafruit.com/robots.txt"
        if self.robots_text is None:
            _public_addresses("www.adafruit.com")
            with build_opener(_NoRedirect()).open(
                    Request(robots_url, headers={"User-Agent": USER_AGENT}),
                    timeout=_TIMEOUT) as response:
                if response.status != 200:
                    raise ValueError("Cannot verify robots.txt")
                body = response.read(50000)
                if len(body) >= 50000:
                    raise ValueError("robots.txt exceeds size cap")
                content = body.decode("utf-8", errors="replace")
        else:
            content = self.robots_text
        rules = RobotFileParser()
        rules.parse(content.splitlines())
        return rules

    def collect(self, urls, category="electronics", goal="Compare real product listing claims"):
        if not isinstance(urls, list) or not 1 <= len(urls) <= MAX_OFFERS:
            raise ValueError("Provide between one and five product URLs")
        targets = [_safe_product_url(u) for u in urls]
        if len(set(targets)) != len(targets):
            raise ValueError("Duplicate product URLs")
        robots = self._robots()
        offers = []
        failures = []
        for index, url in enumerate(targets):
            product_id = urlsplit(url).path.split("/")[-1]
            if not robots.can_fetch(USER_AGENT, url):
                failures.append({"source_url": url, "reason": "ROBOTS_DISALLOW"})
                continue
            self._pause()
            try:
                raw, page = self.download(url)
                product = _jsonld_product(page)
                metadata = product.get("offers")
                if isinstance(metadata, list):
                    if len(metadata) != 1:
                        raise ValueError("Ambiguous merchant offers")
                    metadata = metadata[0]
                if not isinstance(metadata, dict):
                    raise ValueError("No merchant Offer JSON-LD")
                price = _price(metadata.get("price"))
                if metadata.get("priceCurrency") != "USD":
                    raise ValueError("This prototype supports only USD")
                title = _snippet(product.get("name"), 180)
                if not title:
                    raise ValueError("Merchant product title missing")
                retrieved_at = datetime.now(timezone.utc).isoformat()
                digest = sha256(raw).hexdigest()
                base = "merchant_" + product_id
                availability = (metadata.get("availability") or "").split("/")[-1]
                condition = (metadata.get("itemCondition") or "").split("/")[-1]
                facts = [
                    {"id": "price",
                     "text": "Is the advertised total price independently verifiable?",
                     "importance": 5, "evidence": [
                         _fact_evidence(product_id, url, retrieved_at, digest,
                                        "price", "Merchant JSON-LD offers.price={} USD (excludes shipping/tax).".format(price))]},
                ]
                if availability in ("InStock", "OutOfStock", "Discontinued", "PreOrder", "LimitedAvailability"):
                    available = availability in ("InStock", "LimitedAvailability")
                    facts.append({
                        "id": "availability",
                        "text": "Does the merchant claim this product is presently in stock?",
                        "importance": 5,
                        "evidence": [_fact_evidence(
                            product_id, url, retrieved_at, digest, "availability",
                            "Merchant JSON-LD offers.availability={}.".format(availability),
                            "supports" if available else "contradicts")],
                    })
                if condition:
                    facts.append({
                        "id": "declared_condition",
                        "text": "Does the merchant explicitly declare a product condition?",
                        "importance": 4, "evidence": [
                            _fact_evidence(product_id, url, retrieved_at, digest,
                                           "condition", "Merchant JSON-LD itemCondition={}; "
                                           "does NOT independently verify physical condition.".format(condition))],
                    })
                offers.append({
                    "id": "product_" + product_id, "title": title, "price": price,
                    "currency": "USD", "url": url, "questions": facts,
                })
            except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
                failures.append({"source_url": url, "reason": type(exc).__name__,
                                 "detail": _snippet(str(exc), 160)})
        if not offers:
            raise ValueError("No verifiable merchant Product JSON-LD could be retrieved; "
                             + json.dumps(failures, ensure_ascii=False)[:1100])
        return {
            "goal": goal, "category": category, "offers": offers,
            "collection": {
                "collector": "merchant_jsonld_adafruit_v1",
                "fetched_pages": len(offers), "requested_pages": len(targets),
                "source_failures": failures,
                "evidence_type": "merchant_assertions_only",
                "review_sources_collected": 0,
                "independent_product_tests_collected": 0,
                "retrieval_policy": "robots-checked, explicit HTTPS allowlist, 2 seconds between products",
            },
        }


def attach_collection_provenance(report, collected):
    report["source_collection"] = collected["collection"]
    report["provenance"] = ("Live merchant JSON-LD extracted from permitted product pages; "
                            "single-publisher claims, not independently verified")
    for i, failure in enumerate(collected["collection"]["source_failures"]):
        report["root"]["children"].insert(-1, {
            "id": "failed-source-" + str(i), "kind": "source_failure",
            "title": "Source not collected: " + failure["source_url"],
            "status": "NOT_RETRIEVED", "details": failure, "children": [],
        })
    report.pop("sha256", None)
    report["sha256"] = sha256(json.dumps(
        report, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return report


def collect_and_analyze(urls, category="electronics",
                        goal="Compare real product listing claims"):
    collected = ProductCollector().collect(urls, category, goal)
    report = analyze({key: collected[key] for key in ("goal", "category", "offers")})
    return attach_collection_provenance(report, collected), collected
