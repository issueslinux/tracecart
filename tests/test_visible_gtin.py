"""Product-scoped EAN claims from real-world Magento and microdata shapes."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from product_intake import extract_from_html

URL = "https://store.example.org/stanley-air-kit"
PRODUCT = {"@type": "Product", "name": "Stanley Air Kit 1100 W 8 bar",
           "offers": {"@type": "Offer", "price": "370.84", "priceCurrency": "PLN"}}


def html(body, structured=True):
    ld = ("<script type='application/ld+json'>" + json.dumps(PRODUCT) + "</script>") if structured else ""
    return ("<html><head><title>Stanley Air Kit 1100 W 8 bar</title></head><body>" +
            ld + body + "</body></html>").encode()


class VisibleGtinTests(unittest.TestCase):
    def test_magento_label_value_is_gtin_not_sku(self):
        attrs = ('<div class="product-attributes">'
                 '<div class="product attribute custom-attributes">'
                 '<strong class="type">Indeks handlowy:</strong><div class="value">8215190STN595</div></div>'
                 '<div class="product attribute custom-attributes">'
                 '<strong class="type">EAN:</strong><div class="value">8016738753899</div></div></div>')
        item, meta = extract_from_html(URL, html(attrs))
        self.assertEqual(item["barcode"], "8016738753899")
        self.assertIn("MAGENTO_PRODUCT_EAN_ATTRIBUTE", meta["barcode_evidence_methods"])

    def test_product_microdata_strong_itemprop_gtin13(self):
        body = ('<div itemscope itemtype="https://schema.org/Product">'
                '<p>Kod EAN: <strong itemprop="gtin13">8016738753899</strong></p></div>')
        item, meta = extract_from_html(URL, html(body, structured=False))
        self.assertEqual(item["barcode"], "8016738753899")
        self.assertIn("PRODUCT_MICRODATA_GTIN13", meta["barcode_evidence_methods"])

    def test_unscoped_gtin_and_unrelated_attribute_are_not_identity(self):
        body = ('<div class="related"><strong itemprop="gtin13">8016738753899</strong>'
                '<div class="product attribute custom-attributes">'
                '<strong class="type">EAN:</strong><div class="value">8016738753899</div>'
                '</div></div>')
        item, meta = extract_from_html(URL, html(body))
        self.assertEqual(item["barcode"], "")
        self.assertEqual(meta["barcode_status"], "NOT_FOUND")

    def test_conflicting_claims_fail_closed(self):
        p = {**PRODUCT, "gtin13": "4015200031828"}
        body = ('<script type="application/ld+json">' + json.dumps(p) + '</script>'
                '<div class="product-attributes"><div class="product attribute custom-attributes">'
                '<strong class="type">EAN:</strong><div class="value">8016738753899</div>'
                '</div></div>')
        item, meta = extract_from_html(URL, html(body, structured=False))
        self.assertEqual(item["barcode"], "")
        self.assertEqual(meta["barcode_status"], "CONFLICTING_DECLARED_GTINS")

    def test_invalid_visible_claim_blocks_equivalence(self):
        body = ('<div class="product-attributes"><div class="product attribute custom-attributes">'
                '<strong class="type">EAN:</strong><div class="value">8016738753890</div>'
                '</div></div>')
        item, meta = extract_from_html(URL, html(body))
        self.assertEqual(item["barcode"], "")
        self.assertEqual(meta["barcode_status"], "INVALID_DECLARED_GTIN")


if __name__ == "__main__":
    unittest.main()
