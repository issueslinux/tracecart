"""Strict product-scoped visible GTIN claims; no SKU, MPN or URL inference.

Supports schema.org Product itemprop and the Magento product-attributes
label/value widget. Never scans arbitrary page text or recommendation cards.
"""
from html.parser import HTMLParser

GTIN_FIELDS = {"gtin", "gtin8", "gtin12", "gtin13", "gtin14"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr"}


class _VisibleGTIN(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.claims = []
        self.capture = None
        self.attribute = None
        self.field = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = set((a.get("class") or "").split())
        product = ("itemscope" in a and
                   (a.get("itemtype") or "").lower().rstrip("/") in
                   ("https://schema.org/product", "http://schema.org/product"))
        in_product = product or any(s[1] for s in self.stack)
        attr_root = "product-attributes" in classes
        in_attr_root = attr_root or any(s[2] for s in self.stack)
        depth = len(self.stack) + 1
        if (tag == "div" and in_attr_root and
                {"product", "attribute", "custom-attributes"}.issubset(classes)):
            self.attribute = {"depth": depth, "label": "", "value": ""}
        if self.attribute is not None:
            if tag == "strong" and "type" in classes:
                self.field = {"tag": tag, "kind": "label", "text": []}
            elif tag == "div" and "value" in classes:
                self.field = {"tag": tag, "kind": "value", "text": []}
        prop = (a.get("itemprop") or "").lower()
        if in_product and prop in GTIN_FIELDS:
            if a.get("content"):
                self.claims.append((a["content"].strip(), "PRODUCT_MICRODATA_" + prop.upper()))
            elif tag not in VOID:
                self.capture = {"tag": tag, "text": [], "prop": prop}
        if tag not in VOID:
            self.stack.append((tag, in_product, in_attr_root))

    def handle_data(self, data):
        if self.field is not None:
            self.field["text"].append(data)
        if self.capture is not None:
            self.capture["text"].append(data)

    def handle_endtag(self, tag):
        if self.field is not None and tag == self.field["tag"]:
            if self.attribute is not None:
                self.attribute[self.field["kind"]] = " ".join(
                    "".join(self.field["text"]).split())
            self.field = None
        if self.capture is not None and tag == self.capture["tag"]:
            self.claims.append((" ".join("".join(self.capture["text"]).split()),
                                "PRODUCT_MICRODATA_" + self.capture["prop"].upper()))
            self.capture = None
        if (self.attribute is not None and tag == "div" and
                len(self.stack) == self.attribute["depth"]):
            label = self.attribute["label"].strip().casefold().rstrip(":")
            if label in ("ean", "ean-13", "ean13", "gtin", "kod ean"):
                self.claims.append((self.attribute["value"], "MAGENTO_PRODUCT_EAN_ATTRIBUTE"))
            self.attribute = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def visible_gtin_claims(html):
    parser = _VisibleGTIN()
    parser.feed(html)
    return parser.claims
