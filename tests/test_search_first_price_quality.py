"""Live-index anomalies must not silently outrank real shopping candidates."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from search_first import (_flag_price_outliers, _rankable_indexed_offer,
                          _variant_assessment, parse_serpapi_google_product,
                          search_serpapi_shopping, _index_product_url)

def row(seller, title, price):
    return {
        "name":seller, "title":title, "link":"https://"+seller.lower().replace(" ","-")+
        ".example.com/product/test", "price":str(price)+" zł", "extracted_price":price
    }


class SearchPriceQualityTests(unittest.TestCase):
    def setUp(self):
        self.iphone={"title":"Apple iPhone 16 128GB","currency":"PLN","barcode":""}
        self.garmin={"title":"Garmin Forerunner 265","currency":"PLN","barcode":""}

    def test_unrealistic_iphone_low_price_is_retained_but_no_longer_minimum(self):
        raw={"product_results":{"title":"Apple iPhone 16 128GB","stores":[
            row("mediaexpert","Apple iPhone 16 128GB",349.90),
            row("euro","Apple iPhone 16 128GB",399.90),
            row("abfoto","Apple iPhone 16 128GB",3469.00),
            row("allegro","Apple iPhone 16 128GB",3737.67),
            row("xkom","Apple iPhone 16 128GB",3999.00),
        ]}}
        entries=parse_serpapi_google_product(raw,self.iphone)["offers"]
        self.assertEqual(len(entries),5)
        flagged=[x for x in entries if x["index_price_anomaly"] != "NONE_DETECTED"]
        self.assertEqual(len(flagged),2)
        self.assertEqual({x["current_price_indexed"] for x in flagged},
                         {"349.90","399.90"})
        self.assertEqual(min(x["current_price_indexed"] for x in entries
                          if _rankable_indexed_offer(x)), "3469.00")

    def test_garmin_low_48_pln_stays_flagged_without_falsely_declared_savings(self):
        prices=(48.79,1455.00,1455.00,1455.00,1535.00)
        entries=_flag_price_outliers([
            {"seller":"s"+str(i),"current_price_indexed":str(price),
             "currency":"PLN",
             "identity_status":"PRODUCT_IDENTITY_NOT_PROVEN_BY_SHOPPING_INDEX"}
            for i,price in enumerate(prices)])
        self.assertEqual(entries[0]["index_price_anomaly"],
                         "SUSPICIOUS_LOW_PRICE_VS_PEER_MEDIAN_NOT_VERIFIED")
        self.assertFalse(_rankable_indexed_offer(entries[0]))
        self.assertTrue(_rankable_indexed_offer(entries[1]))

    def test_capacity_and_bare_vs_kit_variants_remain_distinct(self):
        self.assertEqual(_variant_assessment("Samsung T7 Shield 1TB",
                                             "Samsung T7 Shield 2 TB"),
                         "CAPACITY_VARIANT_CONFLICT_NEEDS_REVIEW")
        self.assertEqual(_variant_assessment("Raspberry Pi 5 8GB",
                                             "Raspberry Pi 5 8GB Full Kit"),
                         "BUNDLE_VARIANT_CONFLICT_NEEDS_REVIEW")
        self.assertEqual(_variant_assessment("Stanley Air Kit OL195",
                                             "Stanley Air Kit 1100 W 8 bar"),
                         "PRODUCT_IDENTITY_NOT_PROVEN_BY_SHOPPING_INDEX")

    def test_google_search_page_is_not_product_link(self):
        self.assertIsNone(_index_product_url("https://www.google.com/search"))
        self.assertEqual(_index_product_url("https://www.google.com/shopping/product/123"),
                         "https://www.google.com/shopping/product/123")


class ShoppingPanelQualityTests(unittest.TestCase):
    def test_outlier_warning_visible_in_html_but_not_purchase_approval(self):
        from app import shopping_search_panel
        from search_first import attach_shopping_evidence, _empty
        from test_live_offer_compare import BASE
        import copy
        record=_empty("INDEXED_STORES_WITHOUT_SELLER_VERIFICATION",
                      "2026-11-02T18:40:00+00:00")
        record["indexed_offers"]=[{
            "seller":"Unknown indexed seller",
            "merchant_url":"https://example.org/product/iphone16",
            "title":"iPhone 16 128GB",
            "current_price_indexed":"349.90",
            "currency":"PLN",
            "identity_status":"PRODUCT_IDENTITY_NOT_PROVEN_BY_SHOPPING_INDEX",
            "index_price_anomaly":"SUSPICIOUS_LOW_PRICE_VS_PEER_MEDIAN_NOT_VERIFIED",
        }]
        report=attach_shopping_evidence(copy.deepcopy(BASE),
                                        {"title":"Apple iPhone 16 128GB"},record)
        html=shopping_search_panel(report)
        self.assertIn("SUSPICIOUS_LOW_PRICE_VS_PEER_MEDIAN_NOT_VERIFIED",html)
        self.assertIn("SEARCH INDEX ONLY",html)
        self.assertFalse(report["indexed_shopping"]["payment_authorized"])
