"""Primary HTML product evidence: never confuse minicart, SKU or regular price."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from product_intake import extract_from_html
from visible_offer import parse_primary_offer
from unit_economics import unit_cost
from live_offer_compare import compare_live_offer

URL = "https://shop.example.org/produkt/persil-color-75"


def woo(amount="89.26", ean="4015200031828", stock="in-stock"):
    return ("""<html><head><title>Persil Color 75 prań 4,5 kg</title></head><body>
    <div class="mini-cart"><span class="woocommerce-Price-amount">
    <bdi>0,00 <span>zł</span></bdi></span></div>
    <div class="product type-product">
      <div class="elementor-widget-woocommerce-product-price">
        <p class="price"><span class="woocommerce-Price-amount amount">
        <bdi>""" + amount + """ <span class="woocommerce-Price-currencySymbol">zł</span>
        </bdi></span></p>
      </div>
      <div class="elementor-widget-woocommerce-product-add-to-cart">
        <span class="stock """ + stock + """">Pozostało tylko 1</span>
      </div>
      <table><tr><th>EAN (GTIN)</th><td><p>""" + ean + """</p></td></tr>
      <tr><th>Kod producenta</th><td>99999</td></tr></table>
    </div><section class="related"><p class="price">12,00 zł</p></section>
    </body></html>""")


def rawax():
    return """<html><head><title>Persil Color 4,5kg 75 prań</title></head>
    <body><div class="product-details" itemscope itemtype="http://schema.org/Product">
      <h1 itemprop="name">Persil Color 4,5kg 75 prań</h1>
      <div class="product-details-price" itemprop="offers" itemscope
           itemtype="http://schema.org/Offer">
        <text itemprop="price" content="109.90">109,90</text>
        <text itemprop="priceCurrency" content="PLN">zł</text>
        <meta itemprop="availability" content="http://schema.org/InStock">
      </div>
      <table><tr><th>Kod produktu</th><td>4015200031828</td></tr></table>
    </div></body></html>"""


class VisibleOfferTests(unittest.TestCase):
    def test_woocommerce_primary_widget_and_explicit_table_gtin(self):
        item, meta = extract_from_html(URL, woo().encode())
        self.assertEqual(item["price"], "89.26")
        self.assertEqual(item["currency"], "PLN")
        self.assertEqual(item["barcode"], "4015200031828")
        self.assertEqual(meta["price_evidence_method"], "WOOCOMMERCE_PRIMARY_PRICE")
        self.assertEqual(meta["barcode_evidence_methods"],
                         ["HTML_EXPLICIT_EAN_TABLE_ROW"])
        self.assertEqual(meta["availability_claim"], "https://schema.org/InStock")
        normalized = unit_cost(item, "laundry_detergent")
        self.assertEqual(normalized["washes_declared_in_title"], 75)
        self.assertEqual(normalized["cost_per_wash"], "1.1901")

    def test_microdata_offer_price_stock_but_sku_not_ean(self):
        item, meta = extract_from_html(URL, rawax().encode())
        self.assertEqual(item["price"], "109.90")
        self.assertEqual(item["barcode"], "")
        self.assertEqual(meta["barcode_status"], "NOT_FOUND")
        self.assertEqual(meta["price_evidence_method"], "PRODUCT_OFFER_MICRODATA")
        self.assertEqual(meta["availability_claim"], "http://schema.org/InStock")

    def test_minicart_and_related_product_price_ignored(self):
        item, meta = extract_from_html(URL, b"""<html><title>Persil Color</title>
            <div class="mini-cart"><bdi>0,00 zl</bdi></div>
            <div class="related"><p class="price">12,00 zl</p></div></html>""")
        self.assertIsNone(item["price"])
        self.assertEqual(meta["price_status"], "NOT_FOUND")

    def test_discount_sale_price_not_strikethrough(self):
        html = """<title>Persil Color 75 prań</title>
        <div class="elementor-widget-woocommerce-product-price">
        <p class="price"><del><bdi>150,00 zł</bdi></del>
        <ins><bdi>79,00 zł</bdi></ins></p></div>"""
        item, _ = extract_from_html(URL, html.encode())
        self.assertEqual(item["price"], "79.00")

    def test_conflicting_visible_prices_block_open_graph(self):
        html = """<title>Persil Color</title>
        <meta property="product:price:amount" content="89.00">
        <meta property="product:price:currency" content="PLN">
        <div class="elementor-widget-woocommerce-product-price">
        <p class="price"><bdi>89,00 zł</bdi></p>
        <p class="price"><bdi>95,00 zł</bdi></p></div>"""
        item, meta = extract_from_html(URL, html.encode())
        self.assertIsNone(item["price"])
        self.assertEqual(meta["price_status"], "CONFLICTING_SELLER_PRICE_METADATA")

    def test_ambiguous_multiple_microdata_offers_block_price(self):
        html = rawax().replace("</div></body>", """<div itemprop="offers" itemscope
        itemtype="http://schema.org/Offer">
        <meta itemprop="price" content="70.00">
        <meta itemprop="priceCurrency" content="PLN"></div></div></body>""")
        item, meta = extract_from_html(URL, html.encode())
        self.assertIsNone(item["price"])
        self.assertEqual(meta["price_status"], "CONFLICTING_SELLER_PRICE_METADATA")

    def test_conflicting_gtins_from_table_fail_closed(self):
        html = woo().replace("</table>", """<tr><th>EAN</th>
        <td>8700216908856</td></tr></table>""")
        item, meta = extract_from_html(URL, html.encode())
        self.assertEqual(item["barcode"], "")
        self.assertEqual(meta["barcode_status"], "CONFLICTING_DECLARED_GTINS")

    def test_unscoped_recommendation_ean_is_not_primary_identity(self):
        html = """<html><title>Persil Color</title>
        <table><tr><th>EAN (GTIN)</th><td>4015200031828</td></tr></table>
        <div class="elementor-widget-woocommerce-product-price">
        <p class="price"><bdi>89,26 zł</bdi></p></div></html>"""
        item, meta = extract_from_html(URL, html.encode())
        self.assertEqual(item["price"], "89.26")
        self.assertEqual(item["barcode"], "")
        self.assertEqual(meta["barcode_status"], "NOT_FOUND")

    def test_stock_not_inferred_from_body_words(self):
        html = """<title>Persil Color</title><p>na stanie 100 sztuk</p>"""
        _, meta = extract_from_html(URL, html.encode())
        self.assertEqual(meta["availability_claim"], "")

    def test_out_of_stock_widget_recognized(self):
        _, meta = extract_from_html(URL, woo(stock="out-of-stock").encode())
        self.assertEqual(meta["availability_claim"], "https://schema.org/OutOfStock")

    def test_real_markup_styles_flow_to_evidence_tree_without_false_savings(self):
        selected, src = extract_from_html(URL, woo().encode())
        src.update({"page_sha256": "a"*64, "retrieved_at":
                    "2026-11-02T03:01:05+00:00",
                    "source_url": selected["merchant_url"]})
        second_url = "https://other.example.org/product/persil-color"
        alternative, meta = extract_from_html(second_url, rawax().encode())
        meta.update({"page_sha256": "b"*64, "retrieved_at":
                     "2026-11-02T03:01:06+00:00",
                     "source_url": second_url})
        base = {"source_intake": src, "limitations": [],
                "root": {"details": {"selected_cart_item": selected},
                         "children": [{"kind": "conditional_summary",
                                       "status": "NO_FORCED_WINNER",
                                       "details": {"payment_authorized": False},
                                       "children": []}]}}
        report = compare_live_offer(base, selected, second_url,
                                    extractor=lambda _: (alternative, meta))
        c = report["live_competitor_comparison"]
        self.assertEqual(c["selected_cost_per_wash"]["cost_per_wash"], "1.1901")
        self.assertEqual(c["alternative"]["price"], "109.90")
        self.assertEqual(c["status"], "GTIN_IDENTITY_NOT_ESTABLISHED")
        self.assertTrue(c["both_sellers_claim_stock"])
        self.assertIsNone(c["seller_listed_price_delta_pct_vs_selected"])
        self.assertFalse(c["payment_authorized"])

    def test_two_woo_primary_prices_with_matching_ean_are_conditional(self):
        selected, src = extract_from_html(URL, woo().encode())
        src.update({"page_sha256": "a"*64, "retrieved_at":
                    "2026-11-02T03:01:05+00:00", "source_url": URL})
        second_url = "https://other.example.org/product/persil-color"
        alternative, meta = extract_from_html(second_url,
                                              woo(amount="79.00").encode())
        meta.update({"page_sha256": "b"*64, "retrieved_at":
                     "2026-11-02T03:01:06+00:00",
                     "source_url": second_url})
        base = {"source_intake": src, "limitations": [],
                "root": {"details": {"selected_cart_item": selected},
                         "children": [{"kind": "conditional_summary",
                                       "status": "NO_FORCED_WINNER",
                                       "details": {"payment_authorized": False},
                                       "children": []}]}}
        c = compare_live_offer(base, selected, second_url,
                               extractor=lambda _: (alternative, meta))[
                                   "live_competitor_comparison"]
        self.assertEqual(c["status"], "SAME_GTIN_SELLER_LISTED_PRICE_COMPARISON")
        self.assertEqual(c["delivery_break_even"]["one_pack_listed_price_advantage"], "10.26")
        self.assertIsNone(c["delivery_break_even"]["alternative_delivery_price"])

    def test_microdata_offer_outside_product_rejected(self):
        html = """<title>Persil Color</title><div itemprop="offers"
        itemscope itemtype="http://schema.org/Offer">
        <meta itemprop="price" content="1.00">
        <meta itemprop="priceCurrency" content="PLN"></div>"""
        item, meta = extract_from_html(URL, html.encode())
        self.assertIsNone(item["price"])
        self.assertEqual(meta["price_status"], "NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
