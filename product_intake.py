"""URL-first product extraction with pinned public HTTPS and robots preflight.

The web page is treated as untrusted seller content. No browser automation,
payment, checkout tokens or private networks are accessed. Redirects and
ambiguous multi-product listings are rejected rather than guessed.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from html.parser import HTMLParser
from html import unescape
import http.client
import ipaddress
import json
import re
import socket
import ssl
from urllib.parse import urlsplit, urlunsplit, parse_qs, unquote, urljoin, parse_qsl, urlencode
from urllib.robotparser import RobotFileParser
from visible_offer import parse_primary_offer
from structured_shipping import shipping_claim, shipping_claims
from structured_delivery import delivery_window_claim, delivery_windows_by_country
from product_variant import check_page_identity_consistency
from visible_gtin import visible_gtin_claims

USER_AGENT = "TraceCartResearchBot/0.5 (+https://github.com/issueslinux/tracecart)"
MAX_URL_LEN = 1200
MAX_PAGE_BYTES = 1200000
MAX_ROBOTS_BYTES = 80000


class SourceAccessDenied(ValueError):
    """Public product page refused automated retrieval (never bypass)."""
    def __init__(self, status):
        self.status = int(status)
        super().__init__("Product page access denied, HTTP {}".format(self.status))


class SourceRedirect(ValueError):
    """An HTTP redirect that requires origin+robots checks before following."""
    def __init__(self, status, location):
        self.status = int(status)
        self.location = str(location or "")[:1600]
        super().__init__("Product source redirects, HTTP {}".format(status))


class SourceHTTPFailure(ValueError):
    """Non-successful remote page response (not a URL validation failure)."""
    def __init__(self, status):
        self.status = int(status)
        super().__init__("Product source unavailable, HTTP {}".format(status))


def normalized_product_url(url):
    """Generic removal of tracking parameters and path referral suffixes.

    Identifying offerId is retained for any seller, but search keywords,
    marketing/referrer and potentially sensitive query values are discarded.
    """
    safe = validate_product_url(url)
    p = urlsplit(safe)
    segments = p.path.split("/")
    segments = [x for x in segments if x]
    for i, segment in enumerate(segments):
        if segment.lower().startswith(("ref=", "ref_", "ref-")):
            segments = segments[:i]
            break
    path = "/" + "/".join(segments) if segments else "/"
    query_pairs = []
    for key, value in parse_qsl(p.query, keep_blank_values=False):
        if key == "offerId" and re.fullmatch(r"[0-9]{5,20}", value):
            query_pairs.append((key, value))
    return urlunsplit(("https", p.hostname, path,
                       urlencode(query_pairs), ""))


def generic_url_identity(url, access_reason):
    """Store-agnostic, *UNVERIFIED* identity from the URL the buyer supplied.

    Never use blocked page contents, manufacture a price, or substitute search
    snippets as proof. Works for readable slugs on ANY publicly addressed
    HTTPS domain, not merely a known marketplace.
    """
    safe = normalized_product_url(url)
    p = urlsplit(safe)
    segments = [unquote(v) for v in p.path.split("/") if v]
    # Identify common generic URL markers; NOT vendor-specific APIs.
    marker = ("dp", "gp", "product", "produkt", "products", "item",
              "items", "p", "offer", "oferta")
    ids = []
    for i, seg in enumerate(segments[:-1]):
        if seg.casefold() in marker and re.fullmatch(r"[A-Za-z0-9_-]{6,40}", segments[i+1]):
            ids.append(segments[i+1])
    for seg in segments:
        match = re.search(r"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$", seg, flags=re.I)
        if match:
            ids.append(match.group(1))
    options = []
    for segment in segments:
        seg = re.sub(r"-[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", "", segment, flags=re.I)
        if seg.casefold() in marker or seg.startswith(("ref=", "ref_")):
            continue
        if re.fullmatch(r"[A-Z0-9]{10}", seg) or re.fullmatch(
                r"[a-f0-9-]{32,36}", seg, flags=re.I):
            continue
        label = re.sub(r"[_+\-]+", " ", seg)
        label = re.sub(r"[^\w\s,.%°]", " ", label, flags=re.UNICODE)
        label = " ".join(label.split())
        if len(label) >= 8 and len(re.findall(r"[A-Za-zÀ-ž]{3,}", label)) >= 2:
            options.append((len(label.split()), len(label), label))
    options.sort(reverse=True)
    title = options[0][2][:180] if options else None
    if title:
        title = re.sub(r"\b([0-9]{1,3}) ([0-9]) (kg|l|g|ml)\b",
                       r"\1,\2 \3", title, flags=re.I)
    # Unreadable URLs still yield an auditable partial result, but should NOT
    # generate claims about what product this is or assume a brand/category.
    if title is None:
        title = "Unidentified product from " + p.hostname
        confidence = "INSUFFICIENT_URL_DESCRIPTION"
    else:
        confidence = "URL_TITLE_UNVERIFIED"
    query = parse_qs(p.query, keep_blank_values=False)
    offer_id = (query.get("offerId") or [None])[0]
    item = {"title": title, "price": None, "currency": None,
            "barcode": "", "merchant_url": safe}
    metadata = {
        "source_url": safe,
        "extraction_method": "Generic URL path (NOT downloaded page)",
        "intake_status": "URL_ONLY_UNVERIFIED",
        "url_title_confidence": confidence,
        "retrieved_at": None,
        "attempted_at": datetime.now(timezone.utc).isoformat(),
        "page_sha256": None,
        "robots_url": "https://" + p.hostname + "/robots.txt",
        "source_type": "user_supplied_url_NO_PAGE_CONTENT",
        "brand": "", "sku": "",
        "product_url_identifiers": ids[:3],
        "allegro_offer_id": offer_id if p.hostname.endswith("allegro.pl") else None,
        "availability_claim": "",
        "price_status": "NOT_VERIFIED_PAGE_BLOCKED",
        "barcode_status": "NOT_VERIFIED_PAGE_BLOCKED",
        "access_problem": access_reason,
        "limitations": [
            "Product identity is inferred only from the user's URL path.",
            "URL words are NOT confirmed as the actual seller's product title.",
            "No seller price, stock, delivery cost, GTIN or full description retrieved.",
        ],
    }
    return item, metadata


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
            if response.status in (301, 302, 303, 307, 308):
                raise SourceRedirect(response.status,
                                     response.getheader("Location", ""))
            raise SourceHTTPFailure(response.status)
        mime = response.getheader("Content-Type", "").split(";")[0].strip().lower()
        if mime not in expected_mimes:
            raise ValueError("Unsupported product response content type")
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("Page exceeds bounded source size")
        return data
    finally:
        con.close()


def normalized_gtin(value):
    """Return canonical GTIN-14 only for a valid GS1 check digit.

    Zero-padding makes a UPC-A (12 digits) and its EAN-13 representation
    comparable without changing the seller's original declared identifier.
    SKU, MPN and vendor product codes are NOT treated as GTINs.
    """
    code = str(value) if value is not None else ""
    if not re.fullmatch(r"[0-9]{8}|[0-9]{12,14}", code) or len(set(code)) == 1:
        return None
    digits = [int(d) for d in code]
    total = digits[-1]
    for i, digit in enumerate(reversed(digits[:-1])):
        total += digit * (3 if i % 2 == 0 else 1)
    return code.zfill(14) if total % 10 == 0 else None


def _barcode_evidence(product, parser, html=""):
    """Read only explicitly labelled product GTINs, never SKU/MPN/URLs.

    If seller fields disagree or any explicitly claimed GTIN is malformed,
    fail closed: no identifier is eligible for an equivalence assertion.
    """
    claims = []
    for field in ("gtin13", "gtin14", "gtin12", "gtin8", "gtin"):
        value = product.get(field)
        if value not in (None, ""):
            claims.append((str(value), "PRODUCT_JSON_LD_" + field.upper()))
    additional = product.get("additionalProperty", [])
    if isinstance(additional, dict):
        additional = [additional]
    if isinstance(additional, list):
        for entry in additional[:60]:
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("name") or entry.get("propertyID") or "")
            if _is_gtin_label(label) and entry.get("value") not in (None, ""):
                claims.append((str(entry["value"]), "PRODUCT_ADDITIONAL_PROPERTY"))
    for field in ("product:gtin13", "product:gtin14", "product:gtin12",
                  "product:gtin8", "product:gtin"):
        if parser.meta.get(field):
            claims.append((str(parser.meta[field]), "PRODUCT_META_" + field.upper()))
    # Without Product JSON-LD, only accept EAN rows within the primary
    # Product microdata or WooCommerce single-product root. Related-product
    # tables must never establish the selected product's GTIN.
    rows = (parser.specification_rows if product else
            parser.primary_specification_rows)
    for label, value in rows[:150]:
        if _is_gtin_label(label):
            claims.append((value, "HTML_EXPLICIT_EAN_TABLE_ROW"))
    claims.extend(visible_gtin_claims(html))
    if not claims:
        return "", "NOT_FOUND", []
    normalized = [normalized_gtin(code) for code, _ in claims]
    sources = sorted(set(source for _, source in claims))
    if any(code is None for code in normalized):
        return "", "INVALID_DECLARED_GTIN", sources
    if len(set(normalized)) != 1:
        return "", "CONFLICTING_DECLARED_GTINS", sources
    return claims[0][0], "FOUND_CHECKSUM_VALID", sources


def _is_gtin_label(value):
    label = " ".join(str(value).strip().casefold().split())
    return bool(re.fullmatch(
        r"(?:ean(?:[- ]?(?:8|13))?|gtin(?:[- ]?(?:8|12|13|14))?|"
        r"ean\s*\(gtin\)|kod\s*ean)", label))


class _ProductTags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_script = False
        self.in_title = False
        self.structured = []
        self.title = []
        self.meta = {}
        self.specification_rows = []
        self.primary_specification_rows = []
        self._scope_stack = []
        self._row = None
        self._cell_type = None
        self._cell_data = []

    def handle_starttag(self, tag, attrs):
        a = dict((str(k).lower(), v) for k, v in attrs)
        classes = set((a.get("class") or "").split())
        itemtype = (a.get("itemtype") or "").lower().rstrip("/")
        primary = ("itemscope" in a and itemtype in
                   ("http://schema.org/product", "https://schema.org/product"))
        primary = primary or ("product" in classes and "type-product" in classes)
        in_primary = primary or any(flag for _, flag in self._scope_stack)
        if tag == "tr" and len(self.specification_rows) < 150:
            self._row = {"primary": in_primary}
        elif tag in ("th", "td") and self._row is not None:
            self._cell_type = tag
            self._cell_data = []
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
        if tag not in ("area", "base", "br", "col", "embed", "hr", "img",
                       "input", "link", "meta", "param", "source", "track", "wbr"):
            self._scope_stack.append((tag, primary))

    def handle_data(self, text):
        if self.in_script and self.structured:
            self.structured[-1].append(text)
        if self.in_title:
            self.title.append(text)
        if self._cell_type is not None and sum(map(len, self._cell_data)) < 160:
            self._cell_data.append(text)

    def handle_endtag(self, tag):
        if tag == self._cell_type and self._row is not None:
            self._row[tag] = " ".join("".join(self._cell_data).split())[:160]
            self._cell_type = None
            self._cell_data = []
        elif tag == "tr" and self._row is not None:
            if self._row.get("th") and self._row.get("td"):
                pair = (self._row["th"], self._row["td"])
                self.specification_rows.append(pair)
                if self._row.get("primary"):
                    self.primary_specification_rows.append(pair)
            self._row = None
        if tag == "script":
            self.in_script = False
        if tag == "title":
            self.in_title = False
        for idx in range(len(self._scope_stack) - 1, -1, -1):
            if self._scope_stack[idx][0] == tag:
                del self._scope_stack[idx:]
                break


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
    # Decode entities from actual seller titles; strip markup and collapse
    # whitespace before passing descriptive text to the research planner.
    return " ".join(re.sub(r"<[^>]*>", " ", unescape(value)).split())[:limit]


def _price(value):
    try:
        v = Decimal(str(value))
        if not v.is_finite() or not 0 < v <= 100000 or v.as_tuple().exponent < -2:
            return None
        return str(v.quantize(Decimal("0.01")))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _offer_price_evidence(offer):
    """Select a current Offer price, never a crossed-out reference/list price.

    A merchant can publish multiple UnitPriceSpecifications (e.g. ListPrice
    153.99 and SalePrice 78.90). Only a unique explicit SalePrice, a
    consistent direct Offer.price, or a unique untyped specification can
    establish a current seller-listed price. Conflicts fail closed.
    """
    if not isinstance(offer, dict):
        return None, None, "NOT_FOUND", None
    kind = str(offer.get("@type", "Offer")).rsplit("/", 1)[-1]
    if kind not in ("Offer", ""):
        return None, None, "NOT_AN_INDIVIDUAL_OFFER", None
    currency = offer.get("priceCurrency")
    direct = _price(offer.get("price"))
    specs = offer.get("priceSpecification", [])
    if isinstance(specs, dict):
        specs = [specs]
    if not isinstance(specs, list):
        specs = []
    sale, untyped, reference = set(), set(), set()
    for spec in specs[:20]:
        if not isinstance(spec, dict):
            continue
        value = _price(spec.get("price"))
        curr = spec.get("priceCurrency") or currency
        if value is None or curr not in ("PLN", "EUR", "USD"):
            continue
        label = str(spec.get("priceType") or "").rsplit("/", 1)[-1].casefold()
        entry = (value, curr)
        if label == "saleprice":
            sale.add(entry)
        elif label in ("listprice", "strikethroughprice", "regularprice"):
            reference.add(entry)
        elif not label:
            untyped.add(entry)
    list_price = next(iter(reference))[0] if len(reference) == 1 else None
    if len(sale) > 1 or len(untyped) > 1:
        return None, None, "CONFLICTING_SPECIFICATIONS", list_price
    if direct is not None and currency in ("PLN", "EUR", "USD"):
        if sale and (direct, currency) not in sale:
            return None, None, "CONFLICTING_DIRECT_AND_SALE_PRICE", list_price
        return direct, currency, "DIRECT_OFFER_PRICE", list_price
    if len(sale) == 1:
        value, curr = next(iter(sale))
        return value, curr, "EXPLICIT_SALE_PRICE_SPECIFICATION", list_price
    if len(untyped) == 1:
        value, curr = next(iter(untyped))
        return value, curr, "UNTYPED_OFFER_PRICE_SPECIFICATION", list_price
    return None, None, "NOT_FOUND", list_price


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
    price, currency, price_method, list_price = _offer_price_evidence(offers)
    # A primary product widget or explicit schema.org Offer microdata can
    # provide the price when JSON-LD is absent. Never use minicart totals,
    # unrelated products, crossed-out regular prices or unlabeled numbers.
    visible_price, visible_currency, visible_method, visible_stock = (
        parse_primary_offer(raw.decode("utf-8", "replace")))
    price_crosscheck = "NOT_BOTH_AVAILABLE"
    # Product JSON-LD and the primary product widget are independent seller
    # declarations. A disagreement must not silently prefer either price.
    if price_method.startswith("CONFLICTING_"):
        price = currency = None
    elif price is not None and visible_method.startswith("CONFLICTING_"):
        price = currency = None
        price_method = "CONFLICTING_JSONLD_AND_VISIBLE_PRICE"
        price_crosscheck = "CONFLICT"
    elif price is not None and visible_price is not None:
        visible_normalized = _price(visible_price)
        if visible_normalized != price or visible_currency != currency:
            price = currency = None
            price_method = "CONFLICTING_JSONLD_AND_VISIBLE_PRICE"
            price_crosscheck = "CONFLICT"
        else:
            price_crosscheck = "AGREE"
    elif price is None:
        if visible_method.startswith("CONFLICTING_"):
            price_method = visible_method
        elif visible_price is not None:
            normalized = _price(visible_price)
            if normalized is not None and visible_currency in ("PLN", "EUR", "USD"):
                price, currency = normalized, visible_currency
                price_method = visible_method
        else:
            # OpenGraph is a product-level claim but may be stale. Never
            # substitute it when the primary visible price is contradictory.
            og_currency = parser.meta.get("product:price:currency")
            og_price = _price(parser.meta.get("product:price:amount"))
            if og_price is not None and og_currency in ("PLN", "EUR", "USD"):
                price, currency = og_price, og_currency
                price_method = "PRODUCT_OPENGRAPH_PRICE"
    if price is None:
        currency = None
    code, code_status, code_sources = _barcode_evidence(product, parser, raw.decode("utf-8", "replace"))
    brand = product.get("brand", "")
    if isinstance(brand, dict):
        brand = brand.get("name", "")
    page_identity = check_page_identity_consistency(
        _clean(product.get("name"), 250),
        _clean(parser.meta.get("og:title"), 250),
        _clean(brand, 100))
    identity_blocked = page_identity["status"] in (
        "CONFLICTING_PAGE_IDENTITY", "AMBIGUOUS_PAGE_IDENTITY")
    # Contradictory seller identities make both price and barcode unusable
    # for ranking. Preserve observed price in metadata, but do not present it
    # as an attributable current offer for the selected SKU.
    observed_price = price
    if identity_blocked:
        price = currency = None
        code = ""
        code_status = "BLOCKED_BY_PAGE_IDENTITY_CONFLICT"
    structured_stock = _clean(offers.get("availability", ""), 100)
    visible_stock = _clean(visible_stock, 100)
    def stock_kind(value):
        suffix = str(value).strip().rstrip("/").rsplit("/", 1)[-1].casefold()
        if suffix in ("instock", "limitedavailability"):
            return "IN_STOCK"
        if suffix in ("outofstock", "soldout", "discontinued"):
            return "UNAVAILABLE"
        if suffix in ("preorder", "presale", "backorder"):
            return "DELAYED"
        return None
    stock_conflict = bool(stock_kind(structured_stock) and
                          stock_kind(visible_stock) and
                          stock_kind(structured_stock) != stock_kind(visible_stock))
    availability = "" if stock_conflict or identity_blocked else (
        structured_stock or visible_stock)
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
        "availability_crosscheck": ("CONFLICT" if stock_conflict else
                                    "NOT_CONTRADICTED"),
        "identity_status": page_identity["status"],
        "identity_consistency": page_identity,
        "observed_price_not_attributable": observed_price if identity_blocked else None,
        "price_status": ("BLOCKED_BY_PAGE_IDENTITY_CONFLICT" if identity_blocked
                         else "SELLER_DECLARED" if price is not None else
                         "CONFLICTING_SELLER_PRICE_METADATA" if
                         price_method.startswith("CONFLICTING_") else "NOT_FOUND"),
        "price_evidence_method": price_method,
        "price_crosscheck": price_crosscheck,
        "reference_list_price": list_price,
        "structured_shipping_claim": shipping_claim(offers) if not identity_blocked else shipping_claim({}),
        "structured_shipping_claims_by_country": shipping_claims(offers) if not identity_blocked else {},
        "structured_delivery_window_claim": delivery_window_claim(offers) if not identity_blocked else delivery_window_claim({}),
        "structured_delivery_windows_by_country": delivery_windows_by_country(offers) if not identity_blocked else {},
        "barcode_status": code_status,
        "barcode_evidence_methods": code_sources,
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
    current = safe
    seen = {safe}
    for _ in range(3):
        try:
            html = getter(current, MAX_PAGE_BYTES,
                          ("text/html", "application/xhtml+xml"))
            break
        except SourceRedirect as redirect:
            target = validate_product_url(urljoin(current, redirect.location))
            # Redirects are only followed for SAME HOST. Any new path must
            # remain permitted under the same robots policy; never forward
            # user credentials or tokens.
            if urlsplit(target).hostname != parsed.hostname:
                raise SourceRedirect(redirect.status, "CROSS_ORIGIN_BLOCKED")
            if target in seen:
                raise SourceRedirect(redirect.status, "REDIRECT_LOOP")
            if not rp.can_fetch(USER_AGENT, target):
                raise ValueError("Product source blocked by robots.txt")
            seen.add(target)
            current = target
    else:
        raise SourceRedirect(302, "REDIRECT_LIMIT")
    item, metadata = extract_from_html(current, html)
    metadata["source_url"] = current
    metadata["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    metadata["page_sha256"] = sha256(html).hexdigest()
    metadata["robots_url"] = robots_url
    metadata["source_type"] = "seller_page_NOT_independent_test"
    return item, metadata
