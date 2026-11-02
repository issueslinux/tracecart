"""Seller-page contradictions: refuse to attribute a price to the wrong SKU."""
import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from product_intake import extract_from_html
from live_offer_compare import compare_live_offer

FIRST_URL = "https://shop-one.example.org/product/persil-color"
SECOND_URL = "https://shop-two.example.org/product/persil-color"
EAN = "4015200031828"


def page(title="Persil Color proszek do prania 4,5 kg 75 prań",
         og="Persil Color proszek do prania 4,5 kg 75 prań",
         brand="Persil", price="89.26", visible_price=None,
         stock="https://schema.org/InStock", visible_stock=None):
    p = {"@type": "Product", "name": title, "gtin13": EAN,
         "brand": {"@type": "Brand", "name": brand},
         "offers": {"@type": "Offer", "price": price,
                    "priceCurrency": "PLN", "availability": stock}}
    raw = "<html><head><script type='application/ld+json'>" + json.dumps(p) + "</script>"
    if og:
        raw += '<meta property="og:title" content="' + og + '">'
    raw += "</head><body>"
    if visible_price:
        raw += ('<div class="elementor-widget-woocommerce-product-price">'
                '<p class="price"><bdi>' + visible_price + ' zł</bdi></p></div>')
    if visible_stock:
        raw += ('<div class="elementor-widget-woocommerce-product-add-to-cart">'
                '<span class="stock ' + visible_stock + '">Stock</span></div>')
    return (raw + "</body></html>").encode()


class PageConflictTests(unittest.TestCase):
    def test_jsonld_color_vs_opengraph_white_7kg_blocks_price_and_gtin(self):
        item, meta = extract_from_html(FIRST_URL, page(
            og="Persil proszek do białego 7kg 100 prań"))
        self.assertEqual(meta["identity_status"], "CONFLICTING_PAGE_IDENTITY")
        self.assertEqual({c["attribute"] for c in
                          meta["identity_consistency"]["conflicts"]},
                         {"fabric_use", "net_weight_grams"})
        self.assertIsNone(item["price"])
        self.assertEqual(item["barcode"], "")
        self.assertEqual(meta["price_status"], "BLOCKED_BY_PAGE_IDENTITY_CONFLICT")
        self.assertEqual(meta["barcode_status"], "BLOCKED_BY_PAGE_IDENTITY_CONFLICT")
        self.assertEqual(meta["observed_price_not_attributable"], "89.26")

    def test_jsonld_brand_vs_explicit_title_brand_blocks(self):
        item, meta = extract_from_html(FIRST_URL, page(
            title="Ariel Color proszek do prania 4,5kg", og=None))
        self.assertEqual(meta["identity_status"], "CONFLICTING_PAGE_IDENTITY")
        self.assertIsNone(item["price"])
        self.assertEqual(item["barcode"], "")

    def test_ambiguous_jsonld_color_white_without_og_blocks(self):
        item, meta = extract_from_html(FIRST_URL, page(
            title="Persil Color White proszek do prania 4,5kg", og=None))
        self.assertEqual(meta["identity_status"], "AMBIGUOUS_PAGE_IDENTITY")
        self.assertIsNone(item["price"])

    def test_equivalent_4500g_title_keeps_seller_claims(self):
        item, meta = extract_from_html(FIRST_URL, page(
            og="Persil kolor proszek do prania 4500 g 75 prań"))
        self.assertEqual(meta["identity_status"], "NO_EXPLICIT_PAGE_CONTRADICTION")
        self.assertEqual(item["price"], "89.26")
        self.assertEqual(item["barcode"], EAN)

    def test_missing_opengraph_does_not_fabricate_conflict(self):
        item, meta = extract_from_html(FIRST_URL, page(og=None))
        self.assertEqual(meta["identity_status"], "NO_EXPLICIT_PAGE_CONTRADICTION")
        self.assertEqual(item["price"], "89.26")

    def test_jsonld_price_disagrees_with_visible_primary_price(self):
        item, meta = extract_from_html(FIRST_URL, page(visible_price="99,00"))
        self.assertIsNone(item["price"])
        self.assertEqual(meta["price_status"], "CONFLICTING_SELLER_PRICE_METADATA")
        self.assertEqual(meta["price_evidence_method"],
                         "CONFLICTING_JSONLD_AND_VISIBLE_PRICE")
        self.assertEqual(meta["price_crosscheck"], "CONFLICT")

    def test_jsonld_price_agrees_with_visible_primary_price(self):
        item, meta = extract_from_html(FIRST_URL, page(visible_price="89,26"))
        self.assertEqual(item["price"], "89.26")
        self.assertEqual(meta["price_crosscheck"], "AGREE")

    def test_jsonld_in_stock_but_visible_out_of_stock_unknown(self):
        item, meta = extract_from_html(FIRST_URL, page(visible_stock="out-of-stock"))
        self.assertEqual(meta["availability_crosscheck"], "CONFLICT")
        self.assertEqual(meta["availability_claim"], "")
        self.assertEqual(item["price"], "89.26")

    def test_same_gtin_competitor_with_page_conflict_never_ranks(self):
        selected, selected_meta = extract_from_html(FIRST_URL, page())
        selected_meta.update({"page_sha256": "a"*64, "retrieved_at":
            "2026-11-02T05:00:00+00:00", "source_url": FIRST_URL})
        alternative, other_meta = extract_from_html(SECOND_URL, page(
            og="Persil proszek do białego 7kg", price="69.99"))
        other_meta.update({"page_sha256": "b"*64, "retrieved_at":
            "2026-11-02T05:01:00+00:00", "source_url": SECOND_URL})
        base = {"source_intake": selected_meta, "limitations": [],
                "root": {"details": {"selected_cart_item": selected},
                         "children": [{"kind": "conditional_summary",
                                       "details": {"payment_authorized": False},
                                       "children": []}]}}
        comparison = compare_live_offer(
            base, selected, SECOND_URL,
            extractor=lambda _: (alternative, other_meta))[
                "live_competitor_comparison"]
        self.assertEqual(comparison["status"], "SECOND_PAGE_IDENTITY_CONFLICT")
        self.assertTrue(comparison["alternative_page_identity_blocked"])
        self.assertIsNone(comparison["seller_listed_price_delta_pct_vs_selected"])
        self.assertIsNone(comparison["delivery_break_even"])
        self.assertFalse(comparison["payment_authorized"])


if __name__ == "__main__":
    unittest.main()
