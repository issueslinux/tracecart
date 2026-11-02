"""Evidence-grade GTIN identity: no SKU/MPN inference, no bad checksums."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from product_intake import extract_from_html, normalized_gtin


def page(product, detail=""):
    return ("<script type='application/ld+json'>" +
            json.dumps(product) + "</script>" + detail).encode()


URL = "https://shop.example.org/product/persil-color-75"
PRODUCT = {"@type": "Product", "name": "Persil Color 75 prań 4,5 kg",
           "offers": {"@type": "Offer", "price": "78.90",
                      "priceCurrency": "PLN"}}


class GtinEvidenceTests(unittest.TestCase):
    def test_checksum_and_equivalent_upc_ean(self):
        self.assertEqual(normalized_gtin("036000291452"),
                         normalized_gtin("0036000291452"))
        self.assertEqual(normalized_gtin("4015200031828"), "04015200031828")
        for bad in ("4015200031829", "1234567890123", "123", "not-an-ean",
                    "4015200031828-2", "", "0000000000001", "0000000000000"):
            with self.subTest(bad=bad):
                self.assertIsNone(normalized_gtin(bad))

    def test_real_persil_ean_in_explicit_product_detail_table(self):
        # Structure like product specification tables, not arbitrary text.
        detail = ("<table><tr><th>EAN (GTIN)</th>"
                  "<td><span>4015200031828</span></td></tr></table>")
        item,meta = extract_from_html(URL,page(PRODUCT,detail))
        self.assertEqual(item["barcode"], "4015200031828")
        self.assertEqual(meta["barcode_status"], "FOUND_CHECKSUM_VALID")
        self.assertIn("HTML_EXPLICIT_EAN_TABLE_ROW",
                      meta["barcode_evidence_methods"])
        self.assertEqual(item["price"], "78.90")

    def test_additional_property_explicit_ean(self):
        p = {**PRODUCT, "additionalProperty": [
            {"@type": "PropertyValue", "name": "EAN", "value": "4015200031828"}]}
        item,meta = extract_from_html(URL,page(p))
        self.assertEqual(item["barcode"], "4015200031828")
        self.assertIn("PRODUCT_ADDITIONAL_PROPERTY",
                      meta["barcode_evidence_methods"])

    def test_generic_product_code_mpn_sku_are_not_gtin(self):
        detail = ("<table><tr><th>Kod produktu</th>"
                  "<td>4015200031828</td></tr></table>")
        p = {**PRODUCT, "sku": "4015200031828", "mpn": "4015200031828"}
        item,meta = extract_from_html(URL,page(p,detail))
        self.assertEqual(item["barcode"], "")
        self.assertEqual(meta["barcode_status"], "NOT_FOUND")

    def test_conflicting_seller_claims_fail_closed(self):
        p = {**PRODUCT, "gtin13": "4015200031828"}
        detail = ("<table><tr><th>EAN</th>"
                  "<td>8700216908856</td></tr></table>")
        item,meta = extract_from_html(URL,page(p,detail))
        self.assertEqual(item["barcode"], "")
        self.assertEqual(meta["barcode_status"], "CONFLICTING_DECLARED_GTINS")

    def test_invalid_claim_overrides_valid_claim(self):
        p = {**PRODUCT, "gtin13": "4015200031828",
             "additionalProperty": {"name": "EAN", "value": "4015200031829"}}
        item,meta = extract_from_html(URL,page(p))
        self.assertEqual(item["barcode"], "")
        self.assertEqual(meta["barcode_status"], "INVALID_DECLARED_GTIN")

    def test_jsonld_and_table_same_gtin_not_conflict(self):
        p = {**PRODUCT, "gtin13": "4015200031828"}
        detail = "<table><tr><th>EAN</th><td>4015200031828</td></tr></table>"
        item,meta = extract_from_html(URL,page(p,detail))
        self.assertEqual(item["barcode"], "4015200031828")
        self.assertEqual(meta["barcode_status"], "FOUND_CHECKSUM_VALID")

    def test_non_explicit_numbers_and_url_ids_not_gtin(self):
        detail = ("<p>SKU 4015200031828 and another recommendation "
                  "8700216908856</p><table><tr><th>Numer oferty</th>"
                  "<td>4015200031828</td></tr></table>")
        item,meta = extract_from_html(URL,page(PRODUCT,detail))
        self.assertEqual(item["barcode"], "")
        self.assertEqual(meta["barcode_status"], "NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
