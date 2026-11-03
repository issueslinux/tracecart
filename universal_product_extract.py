"""Network-free, provider-neutral extraction from an already acquired page snapshot.

Acquisition is a separate, permission-checked responsibility. No HTTP calls,
browser execution, checkout decisions or seller verification occur here.
Seller fields are declarations, NOT confirmed checkout prices.
"""
from datetime import datetime, timezone
from hashlib import sha256
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import json
import re

from product_intake import (
    MAX_PAGE_BYTES, _offer_price_evidence, extract_from_html,
    normalized_gtin, validate_product_url,
)

METHODS = frozenset(("STATIC_HTML", "RENDERED_DOM", "AUTHORIZED_JSON",
                     "USER_BROWSER", "INDEX_SNAPSHOT"))
HTML_TYPES = frozenset(("text/html", "application/xhtml+xml"))
JSON_TYPES = frozenset(("application/json", "application/ld+json"))
FIELDS = ("title", "brand", "model", "sku", "gtin", "price", "currency",
          "availability", "condition", "seller")
BLOCKED_HTTP = frozenset((401, 402, 403, 407, 429, 451))
CHALLENGE = ("please enable js and disable any ad blocker",
             "verify you are human", "cf-mitigated", "captcha challenge",
             "access denied - datadome")


def _text(value, maxlen=200):
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())[:maxlen]
    return normalized or None


def _type_is(node, expected):
    raw = node.get("@type", [])
    kinds = [raw] if isinstance(raw, str) else raw
    return isinstance(kinds, list) and any(
        isinstance(item, str) and item.rsplit("/", 1)[-1].casefold() == expected.casefold()
        for item in kinds)


def _pointer(path, key):
    return path + "/" + str(key).replace("~", "~0").replace("/", "~1")


class _HTMLMetadata(HTMLParser):
    """Capture explicit structured metadata without executing remote scripts."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.scripts = []
        self.meta = {}
        self._inside = None
        self._chunks = []
        self._title = False
        self.page_title = []
        self.has_product_microdata = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if ("itemscope" in a and
                (a.get("itemtype") or "").rstrip("/").lower() in
                ("https://schema.org/product", "http://schema.org/product")):
            self.has_product_microdata = True
        if tag == "script":
            self._inside = (a.get("type") or "").lower().split(";", 1)[0].strip()
            self._chunks = []
        if tag == "title":
            self._title = True
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            value = _text(a.get("content"), 300)
            if key and value:
                self.meta.setdefault(key, []).append(value)

    def handle_data(self, data):
        if self._inside in JSON_TYPES and sum(map(len, self._chunks)) < 240000:
            self._chunks.append(data)
        if self._title and len(self.page_title) < 15:
            self.page_title.append(data)

    def handle_endtag(self, tag):
        if tag == "script":
            if self._inside == "application/ld+json" and self._chunks:
                self.scripts.append("".join(self._chunks))
            self._inside = None
            self._chunks = []
        elif tag == "title":
            self._title = False


def _product_nodes(root, base, found, depth=0):
    """Traverse only schema graph entry points, not unrelated recommended items."""
    if depth > 8 or len(found) > 30:
        return
    if isinstance(root, list):
        for i, item in enumerate(root[:40]):
            _product_nodes(item, _pointer(base, i), found, depth+1)
    elif isinstance(root, dict):
        if _type_is(root, "Product"):
            found.append((root, base))
        for key in ("@graph", "mainEntity"):
            if key in root:
                _product_nodes(root[key], _pointer(base, key), found, depth+1)


def _result(url, method, when, digest, status):
    return {
        "status": status, "source_url": url, "acquisition_method": method,
        "acquired_at": when, "snapshot_sha256": digest,
        "fields": {k: None for k in FIELDS}, "evidence": [],
        "conflicts": [], "shipping_claims": [],
        "seller_verified": False, "checkout_verified": False,
        "index_only": method == "INDEX_SNAPSHOT",
    }


def extract_snapshot(source_url, body, content_type="text/html",
                     acquisition_method="STATIC_HTML", http_status=200,
                     acquired_at=None):
    """Analyze an immutable HTML/rendered-DOM/JSON document, never fetch a URL.

    Field evidence contains JSON pointers (for JSON-LD) or explicitly labeled
    HTML extraction sources. Conflicts clear the affected field. Calling code
    must separately verify seller identity, variant, live stock and checkout.
    """
    url = validate_product_url(source_url)
    if acquisition_method not in METHODS:
        raise ValueError("UNKNOWN_ACQUISITION_METHOD")
    if type(http_status) is not int or not 100 <= http_status <= 599:
        raise ValueError("INVALID_HTTP_STATUS")
    if acquired_at is None:
        acquired_at = datetime.now(timezone.utc).isoformat()
    else:
        if not isinstance(acquired_at, str):
            raise ValueError("INVALID_ACQUISITION_TIME")
        try:
            instant = datetime.fromisoformat(acquired_at.replace("Z", "+00:00"))
            if instant.tzinfo is None:
                raise ValueError("naive datetime")
        except ValueError as exc:
            raise ValueError("INVALID_ACQUISITION_TIME") from exc
    if type(body) is not bytes or len(body) > MAX_PAGE_BYTES:
        raise ValueError("SNAPSHOT_MUST_BE_BOUNDED_BYTES")
    digest = sha256(body).hexdigest()
    status = ("ACCESS_DENIED" if http_status in BLOCKED_HTTP else
              "HTTP_ERROR" if http_status != 200 else "CONTENT_EMPTY" if not body
              else "PENDING")
    out = _result(url, acquisition_method, acquired_at, digest, status)
    if status != "PENDING":
        return out
    mime = content_type.partition(";")[0].strip().lower()
    if mime not in HTML_TYPES | JSON_TYPES:
        out["status"] = "UNSUPPORTED_CONTENT_TYPE"
        return out
    text = body.decode("utf-8", errors="replace")
    if any(marker in text[:2500].casefold() for marker in CHALLENGE):
        out["status"] = "ACCESS_CHALLENGE"
        return out

    doc = _HTMLMetadata()
    found = []
    legacy = None
    legacy_meta = {}
    if mime in HTML_TYPES:
        doc.feed(text)
        for i, raw in enumerate(doc.scripts[:35]):
            if len(raw) > 250000:
                continue
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                continue
            _product_nodes(parsed, "/html/jsonld/{}".format(i), found)
        try:
            legacy, legacy_meta = extract_from_html(url, body)
        except ValueError:
            # A generic page can lack a title; JSON-LD can still provide one.
            # Multiple or contradictory product records are rejected below.
            pass
    else:
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            out["status"] = "INVALID_JSON"
            return out
        _product_nodes(parsed, "", found)
        if not found and isinstance(parsed, dict):
            # A provider-owned JSON document may expose exactly one product at
            # this named root; never scan arbitrary recommended-product arrays.
            product = parsed.get("product")
            if isinstance(product, dict) and _text(product.get("name")) and "offers" in product:
                found.append((product, "/product"))

    if len(found) > 1:
        out["status"] = "MULTIPLE_PRODUCTS_AMBIGUOUS"
        return out

    def add(field, value, method, path):
        if value is None or value == "":
            return
        claim = {
            "field": field, "value": value, "method": method,
            "pointer": path, "source_url": url, "acquired_at": acquired_at,
            "snapshot_sha256": digest, "seller_verified": False,
        }
        out["evidence"].append(claim)
        existing = out["fields"][field]
        if existing is None:
            out["fields"][field] = value
        elif existing != value and field not in out["conflicts"]:
            out["conflicts"].append(field)
            out["fields"][field] = None

    # Fields conflicted earlier must never be restored by a later claim.
    def resolve_conflicts():
        for field in out["conflicts"]:
            out["fields"][field] = None

    if found:
        product, base = found[0]
        for field, key in (("title", "name"), ("model", "model"), ("sku", "sku")):
            add(field, _text(product.get(key)), "PRODUCT_JSON_LD", _pointer(base, key))
        brand = product.get("brand")
        if isinstance(brand, dict):
            add("brand", _text(brand.get("name")), "PRODUCT_JSON_LD",
                _pointer(_pointer(base, "brand"), "name"))
        else:
            add("brand", _text(brand), "PRODUCT_JSON_LD", _pointer(base, "brand"))

        for key in ("gtin", "gtin8", "gtin12", "gtin13", "gtin14"):
            if product.get(key) not in (None, ""):
                normalized = normalized_gtin(product[key])
                if normalized is None:
                    if "gtin" not in out["conflicts"]:
                        out["conflicts"].append("gtin")
                else:
                    add("gtin", normalized, "CHECKSUM_VALID_PRODUCT_GTIN",
                        _pointer(base, key))

        offers = product.get("offers", None)
        if isinstance(offers, list):
            if len(offers) != 1:
                out["conflicts"].append("price")
                out["conflicts"].append("currency")
                offers = None
            else:
                offers = offers[0]
                offerbase = _pointer(_pointer(base, "offers"), 0)
        else:
            offerbase = _pointer(base, "offers")
        if isinstance(offers, dict):
            price, currency, price_source, _ = _offer_price_evidence(offers)
            if price_source.startswith("CONFLICTING_") or price_source == "NOT_AN_INDIVIDUAL_OFFER":
                out["conflicts"].extend(["price", "currency"])
            elif price and currency:
                price_pointer = _pointer(offerbase, "price")
                currency_pointer = _pointer(offerbase, "priceCurrency")
                if price_source in ("EXPLICIT_SALE_PRICE_SPECIFICATION",
                                    "UNTYPED_OFFER_PRICE_SPECIFICATION"):
                    specs = offers.get("priceSpecification", [])
                    if isinstance(specs, dict):
                        specs = [specs]
                    if isinstance(specs, list):
                        for i, spec in enumerate(specs[:20]):
                            if not isinstance(spec, dict):
                                continue
                            label = str(spec.get("priceType") or "").rsplit("/", 1)[-1].casefold()
                            allowed = (label == "saleprice" if
                                       price_source == "EXPLICIT_SALE_PRICE_SPECIFICATION"
                                       else not label)
                            try:
                                amount = str(Decimal(str(spec.get("price"))).quantize(
                                    Decimal("0.01")))
                            except (InvalidOperation, ValueError, TypeError):
                                continue
                            if allowed and amount == price and (
                                    spec.get("priceCurrency") or offers.get("priceCurrency")) == currency:
                                price_pointer = _pointer(
                                    _pointer(_pointer(offerbase, "priceSpecification"), i), "price")
                                currency_pointer = _pointer(
                                    _pointer(_pointer(offerbase, "priceSpecification"), i),
                                    "priceCurrency")
                                break
                add("price", price, "PRODUCT_JSON_LD_"+price_source, price_pointer)
                add("currency", currency, "PRODUCT_JSON_LD", currency_pointer)
            for field, key in (("availability", "availability"), ("condition", "itemCondition")):
                value = offers.get(key)
                add(field, _text(value, 150), "PRODUCT_OFFER_JSON_LD", _pointer(offerbase, key))
            seller = offers.get("seller")
            if isinstance(seller, dict):
                add("seller", _text(seller.get("name")), "PRODUCT_OFFER_JSON_LD",
                    _pointer(_pointer(offerbase, "seller"), "name"))
            else:
                add("seller", _text(seller), "PRODUCT_OFFER_JSON_LD", _pointer(offerbase, "seller"))
            shipping = offers.get("shippingDetails")
            if isinstance(shipping, dict):
                shipping = [shipping]
            if isinstance(shipping, list):
                for i, row in enumerate(shipping[:12]):
                    if not isinstance(row, dict):
                        continue
                    rate = row.get("shippingRate")
                    destination = row.get("shippingDestination")
                    if not isinstance(rate, dict) or not isinstance(destination, dict):
                        continue
                    value = rate.get("value")
                    currency = rate.get("currency")
                    country = destination.get("addressCountry")
                    if isinstance(country, dict):
                        country = country.get("name")
                    if (country and currency in ("PLN", "EUR", "USD") and
                            re.fullmatch(r"[0-9]{1,5}(?:\.[0-9]{1,2})?", str(value or ""))):
                        out["shipping_claims"].append({
                            "country": _text(country, 50), "cost": str(value),
                            "currency": currency,
                            "pointer": _pointer(_pointer(offerbase, "shippingDetails"), i),
                            "seller_verified": False,
                        })

    if mime in HTML_TYPES:
        if legacy is not None:
            # The <title> of any arbitrary article is NOT evidence of an
            # actual product. Require a product marker or an explicit offer
            # price on non-JSON-LD HTML pages.
            og_product = any(v.lower() == "product" for v in doc.meta.get("og:type", []))
            if not found and not (doc.has_product_microdata or og_product or
                                  (legacy.get("price") and legacy.get("currency"))):
                out["status"] = "PRODUCT_NOT_IDENTIFIED"
                return out
            # Reuse existing safety checks for identity, barcode and price
            # consistency between JSON-LD, the main DOM and OpenGraph.
            add("title", _text(legacy.get("title")), "EXISTING_HTML_EXTRACTOR", "/html/product-title")
            if not found:
                if (legacy_meta.get("price_status") != "BLOCKED_BY_PAGE_IDENTITY_CONFLICT" and
                        legacy.get("price") and legacy.get("currency")):
                    add("price", legacy["price"], "EXISTING_HTML_EXTRACTOR",
                        "/html/primary-offer-or-product-meta")
                    add("currency", legacy["currency"], "EXISTING_HTML_EXTRACTOR",
                        "/html/primary-offer-or-product-meta")
            if legacy.get("barcode"):
                add("gtin", normalized_gtin(legacy["barcode"]),
                    "EXISTING_HTML_EXTRACTOR", "/html/declared-gtin")
            if legacy_meta.get("brand") and not found:
                add("brand", legacy_meta["brand"], "EXISTING_HTML_EXTRACTOR",
                    "/html/brand")
            if (legacy_meta.get("identity_status") in
                    ("CONFLICTING_PAGE_IDENTITY", "AMBIGUOUS_PAGE_IDENTITY")):
                out["conflicts"].extend(["title", "gtin", "price", "currency"])
            if (legacy_meta.get("price_status", "").startswith("CONFLICTING") or
                    legacy_meta.get("price_status") == "BLOCKED_BY_PAGE_IDENTITY_CONFLICT"):
                out["conflicts"].extend(["price", "currency"])
            elif found and out["fields"]["price"] and not legacy.get("price"):
                # JSON-LD price which the existing HTML safety gate rejected.
                out["conflicts"].extend(["price", "currency"])
            elif found and out["fields"]["price"] and legacy.get("price"):
                if (out["fields"]["price"], out["fields"]["currency"]) != (
                        legacy["price"], legacy["currency"]):
                    out["conflicts"].extend(["price", "currency"])
        elif not found:
            out["status"] = "PRODUCT_NOT_IDENTIFIED"
            return out

    resolve_conflicts()
    # An invalid/conflicting declared product identifier is unsafe to use as
    # a shopping match; keep the raw price evidence for diagnostics only.
    if "gtin" in out["conflicts"] or "title" in out["conflicts"]:
        out["fields"]["price"] = None
        out["fields"]["currency"] = None
        out["fields"]["seller"] = None
    if not out["fields"]["title"]:
        out["status"] = "PRODUCT_NOT_IDENTIFIED" if not out["conflicts"] else "IDENTITY_CONFLICT"
    elif "title" in out["conflicts"] or "gtin" in out["conflicts"]:
        out["status"] = "IDENTITY_CONFLICT"
    elif "price" in out["conflicts"] or "currency" in out["conflicts"]:
        out["status"] = "PRICE_CONFLICT"
    elif acquisition_method == "INDEX_SNAPSHOT":
        out["status"] = "INDEX_ONLY_UNVERIFIED"
    elif out["fields"]["price"] is None:
        out["status"] = "PRODUCT_FOUND_NO_PRICE"
    else:
        out["status"] = "PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED"
    out["conflicts"] = sorted(set(out["conflicts"]))
    return out
