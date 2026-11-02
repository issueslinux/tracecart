"""Bounded, product-scoped HTML offer evidence when JSON-LD is absent.

Reads ONLY schema.org Offer microdata or a primary WooCommerce price widget.
Never scrapes arbitrary numbers, minicart totals, recommended products, SKU as
GTIN, or generic text about stock. Conflicting claims fail closed.
"""
from html.parser import HTMLParser
import re

_VOID = frozenset(("area", "base", "br", "col", "embed", "hr", "img",
                   "input", "link", "meta", "param", "source", "track", "wbr"))
_PRICE = re.compile(r"^\s*([0-9]{1,6}(?:[.,][0-9]{1,2})?)\s*(zł|PLN|EUR|€|USD|\$)\s*$", re.I)


def _money(text):
    m = _PRICE.fullmatch(" ".join(str(text).replace("\xa0", " ").split()))
    if not m:
        return None
    curr = {"zł": "PLN", "€": "EUR", "$": "USD"}.get(m.group(2).casefold(),
                                                        m.group(2).upper())
    return m.group(1).replace(",", "."), curr


class PrimaryOfferHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.micro = []
        self.blocks = []
        self.current_price = None
        self.current_bdi = None
        self.stock = []

    def _in(self, predicate):
        return any(predicate(classes) for _, classes, _, _ in self.stack)

    def _main_price(self):
        return self._in(lambda c: "elementor-widget-woocommerce-product-price" in c
                        or {"summary", "entry-summary"}.issubset(c))

    def _main_stock(self):
        return self._in(lambda c: "elementor-widget-woocommerce-product-add-to-cart" in c
                        or {"summary", "entry-summary"}.issubset(c))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = set((a.get("class") or "").split())
        active = next((idx for _, _, idx, _ in reversed(self.stack) if idx is not None), None)
        kind = (a.get("itemtype") or "").lower().rstrip("/")
        is_product = ("itemscope" in a and kind in (
            "https://schema.org/product", "http://schema.org/product"))
        is_offer = (a.get("itemprop") == "offers" and "itemscope" in a
                    and kind in ("https://schema.org/offer", "http://schema.org/offer")
                    and any(p for _, _, _, p in self.stack))
        if is_offer:
            active = len(self.micro)
            self.micro.append({"price": [], "currency": [], "availability": []})
        elif active is not None:
            prop = a.get("itemprop")
            if prop in ("price", "priceCurrency", "availability"):
                value = a.get("content")
                if value is not None:
                    key = {"price": "price", "priceCurrency": "currency",
                           "availability": "availability"}[prop]
                    self.micro[active][key].append(value[:100])
        if tag in ("p", "h3") and "price" in classes and self._main_price():
            self.current_price = {"depth": len(self.stack) + 1, "bdi": [],
                                  "text": []}
        if tag == "bdi" and self.current_price is not None:
            context = "regular"
            if any(t == "del" for t, _, _, _ in self.stack):
                context = "del"
            elif any(t == "ins" for t, _, _, _ in self.stack):
                context = "ins"
            self.current_bdi = {"depth": len(self.stack) + 1,
                                "context": context, "text": []}
        if tag in ("span", "p") and "stock" in classes and self._main_stock():
            if "in-stock" in classes:
                self.stock.append("https://schema.org/InStock")
            elif "out-of-stock" in classes:
                self.stock.append("https://schema.org/OutOfStock")
        if tag not in _VOID:
            self.stack.append((tag, classes, active if is_offer else None, is_product))

    def handle_data(self, data):
        if self.current_price is not None:
            self.current_price["text"].append(data)
        if self.current_bdi is not None:
            self.current_bdi["text"].append(data)

    def handle_endtag(self, tag):
        if self.current_bdi is not None and tag == "bdi":
            b = self.current_bdi
            self.current_price["bdi"].append((b["context"], "".join(b["text"])))
            self.current_bdi = None
        if self.current_price is not None and tag in ("p", "h3"):
            b = self.current_price
            self.blocks.append(b)
            self.current_price = None
        # HTML may omit optional closing tags. Never leave a closed Offer in scope.
        for idx in range(len(self.stack) - 1, -1, -1):
            if self.stack[idx][0] == tag:
                del self.stack[idx:]
                break


def _unique(items):
    values = set(items)
    return next(iter(values)) if len(values) == 1 else None


def parse_primary_offer(html):
    """Return price/currency/method/availability without guessed facts.

    All price evidence must be within one actual schema.org Offer or a
    primary WooCommerce product-price widget; unrelated widgets are ignored.
    """
    parser = PrimaryOfferHTML()
    parser.feed(html)
    evidence = []
    conflict = False
    for offer in parser.micro:
        prices, currencies = offer["price"], offer["currency"]
        if len(prices) != 1 or len(currencies) != 1:
            conflict = True
            continue
        evidence.append((prices[0], currencies[0], "PRODUCT_OFFER_MICRODATA"))
    if len(parser.micro) > 1:
        conflict = True
    for block in parser.blocks:
        ins = [_money(v) for kind, v in block["bdi"] if kind == "ins"]
        regular = [_money(v) for kind, v in block["bdi"] if kind == "regular"]
        if ins:
            values = ins
        elif regular:
            values = regular
        else:
            values = [_money("".join(block["text"]))]
        if len(values) != 1 or values[0] is None:
            conflict = True
            continue
        price, currency = values[0]
        evidence.append((price, currency, "WOOCOMMERCE_PRIMARY_PRICE"))
    normalized = set((price, currency) for price, currency, _ in evidence)
    if conflict or len(normalized) > 1:
        price, currency, method = None, None, "CONFLICTING_VISIBLE_OFFER_METADATA"
    elif not evidence:
        price, currency, method = None, None, "NOT_FOUND"
    else:
        price, currency = next(iter(normalized))
        method = "+".join(sorted(set(x[2] for x in evidence)))
    stocks = [x for o in parser.micro for x in o["availability"]] + parser.stock
    availability = _unique(stocks) or ""
    return price, currency, method, availability
