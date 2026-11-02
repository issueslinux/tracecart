"""Boundary between explicitly user-opened browser tabs and seller-page evidence."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_capture import parse_browser_capture
from marketplace_leads import add_marketplace_leads
from test_live_offer_compare import BASE, SELECTED

ALLEGRO = "https://allegro.pl/oferta/kompresor-stanley-air-kit-18637535530"


def captured(**overrides):
    data = {
        "version": 1, "method": "USER_SELECTED_VISIBLE_PRICE",
        "url": ALLEGRO, "title": "Stanley AIR KIT OL195",
        "price": "229.00", "currency": "PLN",
        "gtin_claim": None,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "price_evidence": "SELECTED_VISIBLE_TEXT",
    }
    data.update(overrides)
    return json.dumps(data)


class BrowserCaptureTests(unittest.TestCase):
    def test_active_tab_capture_preserved_as_only_observation(self):
        obs = parse_browser_capture(captured())
        self.assertEqual(obs["origin"], "USER_BROWSER_ACTIVE_TAB_NOT_SERVER_VERIFIED")
        self.assertEqual(obs["price"], "229.00")
        self.assertEqual(obs["observed_title"], "Stanley AIR KIT OL195")
        self.assertEqual(obs["observation_method"], "USER_SELECTED_VISIBLE_PRICE")
        report = add_marketplace_leads(BASE, SELECTED, [obs])
        row = report["marketplace_leads"]["observations"][0]
        self.assertEqual(row["price_evidence_method"], "SELECTED_VISIBLE_TEXT")
        self.assertFalse(row["source_page_downloaded_by_tracecart"])
        self.assertFalse(row["stock_verified"])
        self.assertFalse(report["marketplace_leads"]["payment_authorized"])
        self.assertEqual(report["marketplace_leads"]["source_qualified_comparisons"], 0)

    def test_jsonld_only_capture_schema_and_gtin_are_unverified(self):
        obs = parse_browser_capture(captured(
            method="ACTIVE_TAB_SINGLE_PRODUCT_JSONLD",
            price_evidence="UNIQUE_PRODUCT_JSONLD", gtin_claim="8016738753899",
        ))
        self.assertEqual(obs["gtin_claim"], "8016738753899")
        row = add_marketplace_leads(BASE, SELECTED, [obs])["marketplace_leads"]["observations"][0]
        self.assertTrue(row["gtin_checksum_valid"])
        self.assertEqual(row["origin"], "USER_BROWSER_ACTIVE_TAB_NOT_SERVER_VERIFIED")
        self.assertFalse(row["source_page_downloaded_by_tracecart"])

    def test_invalid_capture_is_refused(self):
        for raw in ("", "foo", "[]" , "x" * 4000):
            with self.subTest(raw=raw[:20]), self.assertRaises(ValueError):
                parse_browser_capture(raw)
        for patch in (
            {"version": 2}, {"method": "SERVER_VERIFIED"},
            {"price_evidence": "CHECKOUT_CONFIRMED"},
            {"currency": "XYZ"}, {"url": "http://127.0.0.1:8765/"},
            {"gtin_claim": "not-a-gtin"}, {"title": "<"},
            {"observed_at": "2020-01-01T00:00:00+00:00"},
            {"observed_at": (datetime.now(timezone.utc)+timedelta(days=5)).isoformat()},
            {"method":"ACTIVE_TAB_SINGLE_PRODUCT_JSONLD"},
            {"price_evidence":"UNIQUE_PRODUCT_JSONLD"},
            {"payment_authorized": True},
        ):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                parse_browser_capture(captured(**patch))

    def test_tracking_parameters_are_stripped(self):
        obs = parse_browser_capture(captured(url=ALLEGRO+"?utm_source=chatgpt"))
        self.assertEqual(obs["url"], ALLEGRO)

    def test_current_price_string_must_be_valid_before_add_to_report(self):
        obs = parse_browser_capture(captured(price="NaN"))
        with self.assertRaises(ValueError):
            add_marketplace_leads(BASE, SELECTED, [obs])


if __name__ == "__main__":
    unittest.main()


class BrowserCaptureIdentityTests(unittest.TestCase):
    def test_different_valid_gtin_is_not_lower_price_claim(self):
        selected_gtin = SELECTED["barcode"]
        # Valid GTIN from a different real product (Stanley, not Persil).
        self.assertNotEqual(selected_gtin, "8016738753899")
        obs = parse_browser_capture(captured(
            method="ACTIVE_TAB_SINGLE_PRODUCT_JSONLD",
            price_evidence="UNIQUE_PRODUCT_JSONLD",
            gtin_claim="8016738753899",
        ))
        report = add_marketplace_leads(BASE, SELECTED, [obs])
        record = report["marketplace_leads"]["observations"][0]
        self.assertEqual(record["comparison_status"],
                         "DIFFERENT_GTIN_OBSERVATION_NOT_COMPARABLE")
        self.assertEqual(record["difference_vs_selected_listed_price"], None)
        self.assertEqual(report["marketplace_leads"]["potential_lower_price_leads"], 0)
