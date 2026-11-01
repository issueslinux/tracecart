"""URL-first product extraction with pinned public HTTPS and robots preflight.

The web page is treated as untrusted seller content. No browser automation,
payment, checkout tokens or private networks are accessed. Redirects and
ambiguous multi-product listings are rejected rather than guessed.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import re
import socket
import ssl
from urllib.parse import urlsplit, urlunsplit, parse_qs, unquote
from urllib.robotparser import RobotFileParser

USER_AGENT = "TraceCartResearchBot/0.5 (+https://github.com/issueslinux/tracecart)"
MAX_URL_LEN = 1200
MAX_PAGE_BYTES = 1200000
MAX_ROBOTS_BYTES = 80000


class SourceAccessDenied(ValueError):
    """Public product page refused automated retrieval (never bypass)."""
    def __init__(self, status):
        self.status = int(status)
        super().__init__("Product page access denied, HTTP {}".format(self.status))


def limited_allegro_identity(url, access_reason):
    """Read ONLY text and IDs the user already provided inside an Allegro URL.

    It cannot verify price, stock, brand, GTIN, offer activity or description.
    Strict host/path/UUID validation avoids inventing identities for arbitrary
    URLs. Marketing parameters are discarded; offerId is a *listing* ID, not GTIN.
    """
    safe = validate_product_url(url)
    p = urlsplit(safe)
    if p.hostname not in ("allegro.pl", "www.allegro.pl"):
        raise ValueError("URL-only recovery supported for Allegro product links")
    m = re.fullmatch(
        r"/produkt/([a-z0-9]+(?:-[a-z0-9]+)*)-"
        r"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-"
        r"[a-f0-9]{4}-[a-f0-9]{12})/?", p.path.lower())
    if not m:
        raise ValueError("URL does not provide a verified Allegro product slug")
    slug, product_id = m.groups()
    query = parse_qs(p.query, keep_blank_values=False)
    offer_id = query.get("offerId", [])
    offer_id = offer_id[0] if len(offer_id) == 1 and re.fullmatch(
        r"[0-9]{5,20}", offer_id[0]) else None
    # The human-readable label is nothing more than the URL's path tokens.
    # Convert "4-5 kg" to "4,5 kg" when followed by an explicit unit;
    # never infer extra labels, marketing claims, EAN or seller price.
    name = " ".join(slug.split("-"))
    name = re.sub(r"\b([0-9]{1,3}) ([0-9]) (kg|l|g|ml)\b",
                  r"\1,\2 \3", name)
    name = name[:180]
    if len(name) < 8:
        raise ValueError("Product URL contains no usable product label")
    product_url = "https://allegro.pl/produkt/{}-{}".format(slug, product_id)
    canonical = (product_url + "?offerId=" + offer_id
                 if offer_id else product_url)
    item = {
        "title": name, "price": None, "currency": None, "barcode": "",
        "merchant_url": canonical,
    }
    metadata = {
        "source_url": canonical,
        "extraction_method": "Allegro URL slug (NOT downloaded page)",
        "intake_status": "URL_ONLY_UNVERIFIED",
        "retrieved_at": None,
        "attempted_at": datetime.now(timezone.utc).isoformat(),
        "page_sha256": None,
        "robots_url": "https://allegro.pl/robots.txt",
        "source_type": "user_supplied_url_NO_PAGE_CONTENT",
        "brand": "",
        "sku": "",
        "allegro_product_id": product_id,
        "allegro_offer_id": offer_id,
        "availability_claim": "",
        "price_status": "NOT_VERIFIED_PAGE_BLOCKED",
        "barcode_status": "NOT_VERIFIED_PAGE_BLOCKED",
        "access_problem": access_reason,
        "limitations": [
            "Product title was parsed from link path, NOT confirmed on Allegro.",
            "Offer ID is not barcode/EAN and may not be active.",
            "No seller price, availability, delivery cost, GTIN or full product description retrieved.",
        ],
    }
    return item, metadata


def validate_product_url(url):
    if type(url) is not str or not 12 < len(url) <= MAX_URL_LEN:
        raise ValueError("Provide a complete HTTPS product URL")
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if (parsed.scheme != "https" or not host or parsed.port not in (None, 443)
            or parsed.username is not None or parsed.password is not None
            or parsed.fragment or host.endswith((".local", ".localhost", ".internal"))
            or not re.fullmatch(r"[a-z0-9.-]{3,253}", host)
            or ".." in host or "." not in host):
        raise ValueError("Only public HTTPS product pages are supported")
    if all(part.isdigit() for part in host.split(".")):
        raise ValueError("IP-address URLs are prohibited")
    return urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))


def _public_ip(host):
    # Pin one address *before* the socket is opened; never re-resolve inside
    # HTTP transport. Stops DNS rebinding between safety check and connection.
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses = set(x[4][0] for x in infos)
    if not addresses or any(not ipaddress.ip_address(x).is_global for x in addresses):
        raise ValueError("Destination must resolve exclusively to public IPs")
    return sorted(addresses)[0]


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, ip, timeout):
        super().__init__(host, port=443, timeout=timeout,
                         context=ssl.create_default_context())
        self.ip = ip

    def connect(self):
        raw = socket.create_connection((self.ip, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def _read(url, max_bytes, expected_mimes, timeout=12):
    parsed = urlsplit(url)
    ip = _public_ip(parsed.hostname)
    con = _PinnedHTTPS(parsed.hostname, ip, timeout)
    try:
        con.request("GET", (parsed.path or "/") +
                    ("?" + parsed.query if parsed.query else ""),
                    headers={"User-Agent": USER_AGENT,
                             "Accept": ", ".join(expected_mimes),
                             "Connection": "close"})
        response = con.getresponse()
        if response.status != 200:
            # Redirects cannot be silently followed to a local or unsafe URL.
            if response.status in (401, 403, 429):
                raise SourceAccessDenied(response.status)
            raise ValueError("Product source unavailable or redirects (HTTP {})".format(
                response.status))
        mime = response.getheader("Content-Type", "").split(";")[0].strip().lower()
        if mime not in expected_mimes:
            raise ValueError("Unsupported product response content type")
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("Page exceeds bounded source size")
        return data
    finally:
        con.close()


class _ProductTags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_script = False
        self.in_title = False
        self.structured = []
        self.title = []
        self.meta = {}

    def handle_starttag(self, tag, attrs):
        a = dict((str(k).lower(), v) for k, v in attrs)
        if tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self.in_script = True
            self.structured.append([])
        elif tag == "title":
            self.in_title = True
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            value = a.get("content") or ""
            if key and value and key not in self.meta and len(value) < 400:
                self.meta[key] = value

    def handle_data(self, text):
        if self.in_script and self.structured:
            self.structured[-1].append(text)
        if self.in_title:
            self.title.append(text)

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False
        if tag == "title":
            self.in_title = False


def _products_from_html(parser):
    candidates = []
    for pieces in parser.structured[:35]:
        raw = "".join(pieces)
        if len(raw) > 250000:
            continue
        try:
            document = json.loads(raw)
        except (ValueError, TypeError):
            continue
        nodes = document if isinstance(document, list) else [document]
        for node in nodes:
            graph = node.get("@graph", [node]) if isinstance(node, dict) else []
            if not isinstance(graph, list):
                continue
            for entry in graph:
                if not isinstance(entry, dict):
                    continue
                types = entry.get("@type", [])
                if isinstance(types, str):
                    types = [types]
                if isinstance(types, list) and ("Product" in types or
                                                "https://schema.org/Product" in types):
                    candidates.append(entry)
    if len(candidates) > 1:
        raise ValueError("Ambiguous page with multiple Product objects")
    return candidates[0] if candidates else {}


def _clean(value, limit=180):
    if not isinstance(value, str):
        return ""
    # Avoid injecting HTML, script or excessive untrusted input into prompts.
    return re.sub(r"\\s+", " ", re.sub(r"<[^>]*>", " ", value)).strip()[:limit]


def _price(value):
    try:
        v = Decimal(str(value))
        if not v.is_finite() or not 0 < v <= 100000 or v.as_tuple().exponent < -2:
            return None
        return str(v.quantize(Decimal("0.01")))
    except (InvalidOperation, TypeError, ValueError):
        return None


def extract_from_html(url, raw):
    parser = _ProductTags()
    parser.feed(raw.decode("utf-8", "replace"))
    product = _products_from_html(parser)
    offers = product.get("offers", {})
    if isinstance(offers, list):
        if len(offers) != 1:
            offers = {}
        else:
            offers = offers[0]
    if not isinstance(offers, dict):
        offers = {}
    title = _clean(product.get("name") or parser.meta.get("og:title") or
                   parser.meta.get("twitter:title") or "".join(parser.title))
    if len(title) < 3:
        raise ValueError("No reliable product name can be extracted from this page")
    price = _price(offers.get("price") or
                   offers.get("lowPrice") or parser.meta.get("product:price:amount"))
    currency = (offers.get("priceCurrency") or
                parser.meta.get("product:price:currency"))
    if currency not in ("PLN", "EUR", "USD"):
        currency = None
        price = None
    if price is None:
        currency = None
    code = (product.get("gtin13") or product.get("gtin") or
            product.get("gtin8") or product.get("gtin14") or
            parser.meta.get("product:gtin13") or "")
    code = str(code)
    if not re.fullmatch(r"[0-9]{8,14}", code):
        code = ""
    brand = product.get("brand", "")
    if isinstance(brand, dict):
        brand = brand.get("name", "")
    availability = _clean(offers.get("availability", ""), 100)
    item = {
        "title": title, "price": price, "currency": currency,
        "barcode": code, "merchant_url": url,
    }
    return item, {
        "source_url": url,
        "extraction_method": "Product JSON-LD" if product else "OpenGraph/HTML fallback",
        "brand": _clean(brand, 100),
        "sku": _clean(product.get("sku"), 100),
        "availability_claim": availability,
        "price_status": "SELLER_DECLARED" if price is not None else "NOT_FOUND",
        "barcode_status": "FOUND" if code else "NOT_FOUND",
    }


def extract_product_page(url, fetch=None):
    safe = validate_product_url(url)
    parsed = urlsplit(safe)
    robots_url = "https://" + parsed.hostname + "/robots.txt"
    getter = fetch or _read
    robots_bytes = getter(robots_url, MAX_ROBOTS_BYTES, ("text/plain", "text/html"))
    rp = RobotFileParser()
    rp.parse(robots_bytes.decode("utf-8", "replace").splitlines())
    if not rp.can_fetch(USER_AGENT, safe):
        raise ValueError("Product source blocked by robots.txt")
    html = getter(safe, MAX_PAGE_BYTES, ("text/html", "application/xhtml+xml"))
    item, metadata = extract_from_html(safe, html)
    metadata["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    metadata["page_sha256"] = sha256(html).hexdigest()
    metadata["robots_url"] = robots_url
    metadata["source_type"] = "seller_page_NOT_independent_test"
    return item, metadata
