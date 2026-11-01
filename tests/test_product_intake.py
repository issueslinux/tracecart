"""URL-first product intake: security, structured extraction and async cart jobs."""
import json
import re
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from product_intake import extract_product_page, extract_from_html, validate_product_url
from cart_research import CartResearchJobs, validate_cart

ROBOT_OK = b"User-agent: *\nAllow: /\n"
PRODUCT_PAGE = json.dumps({
    "@context": "https://schema.org", "@type": "Product",
    "name": "Persil laundry powder 45 washes",
    "gtin13": "8712561344494",
    "brand": {"@type": "Brand", "name": "Persil"},
    "offers": {"@type": "Offer", "price": "34.90", "priceCurrency": "PLN",
               "availability": "https://schema.org/InStock"}
})
HTML = ("<html><title>Other title</title><script type='application/ld+json'>" +
        PRODUCT_PAGE + "</script></html>").encode()


class ProductURLTests(unittest.TestCase):
    def mock_fetch(self, url, size, mimes):
        return ROBOT_OK if url.endswith("/robots.txt") else HTML

    def test_url_is_all_that_is_required_for_actual_extraction(self):
        item, source = extract_product_page(
            "https://www.adafruit.com/product/1083", fetch=self.mock_fetch)
        self.assertEqual(item["title"], "Persil laundry powder 45 washes")
        self.assertEqual(item["price"], "34.90")
        self.assertEqual(item["currency"], "PLN")
        self.assertEqual(item["barcode"], "8712561344494")
        self.assertEqual(source["brand"], "Persil")
        self.assertEqual(source["price_status"], "SELLER_DECLARED")
        self.assertEqual(len(source["page_sha256"]), 64)
        self.assertEqual(source["source_type"], "seller_page_NOT_independent_test")
        self.assertEqual(validate_cart(item)["price"], "34.90")

    def test_missing_price_is_null_not_zero_and_allows_research(self):
        data=json.loads(PRODUCT_PAGE)
        data["offers"].pop("price")
        raw=("<script type='application/ld+json'>" + json.dumps(data) +
             "</script>").encode()
        item,source=extract_from_html("https://www.adafruit.com/product/1083",raw)
        self.assertIsNone(item["price"])
        self.assertIsNone(item["currency"])
        self.assertEqual(source["price_status"], "NOT_FOUND")
        self.assertIsNone(validate_cart(item)["price"])

    def test_denied_robots_prevents_product_fetch(self):
        calls=[]
        def deny(url,size,mimes):
            calls.append(url)
            return b"User-agent: *\nDisallow: /product/\n"
        with self.assertRaisesRegex(ValueError, "robots"):
            extract_product_page("https://www.adafruit.com/product/1083",fetch=deny)
        self.assertEqual(len(calls),1)

    def test_ip_internal_and_credentials_urls_blocked_before_network(self):
        urls=("http://example.org/item", "https://127.0.0.1/item",
              "https://169.254.169.254/latest", "https://localhost/item",
              "https://admin:secret@example.org/item",
              "https://example.org:8443/item", "file:///etc/passwd",
              "https://example.org/item#frag", "https://10.0.0.1/item",
              "https://foo.internal/product")
        for url in urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_product_url(url)

    def test_DNS_private_address_rejected_before_https(self):
        with patch("product_intake.socket.getaddrinfo",return_value=[
            (2,1,6,"",("127.0.0.1",443))]):
            from product_intake import _public_ip
            with self.assertRaisesRegex(ValueError, "public"):
                _public_ip("example.org")

    def test_ambiguous_product_schema_rejected(self):
        raw=("<script type='application/ld+json'>" +
             json.dumps([json.loads(PRODUCT_PAGE),json.loads(PRODUCT_PAGE)]) +
             "</script>").encode()
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            extract_from_html("https://example.org/product",raw)

    def test_og_title_and_price_fallback(self):
        raw=(b'<meta property="og:title" content="Generic Product 123">'
             b'<meta property="product:price:amount" content="19.90">'
             b'<meta property="product:price:currency" content="EUR">')
        item,source=extract_from_html("https://example.org/product/123",raw)
        self.assertEqual(item["title"],"Generic Product 123")
        self.assertEqual(item["price"],"19.90")
        self.assertEqual(source["extraction_method"],"OpenGraph/HTML fallback")

    def test_async_url_extracts_and_retains_full_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            db=Path(directory)/"jobs.db"
            def runner(item):
                return {"root": {"details": {}, "children": [
                    {"kind":"source","title":"test"}, {"kind":"question","title":"test"},
                    {"kind":"summary","title":"ok"}]},
                        "sha256": "old", "selected": item}
            jobs=CartResearchJobs(db,runner=runner)
            try:
                with patch("product_intake.extract_product_page",return_value=(
                        {"title":"Persil laundry powder 45 washes",
                         "price":"34.90","currency":"PLN","barcode":"8712561344494",
                         "merchant_url":"https://www.adafruit.com/product/1083"},
                        {"source_url":"https://www.adafruit.com/product/1083",
                         "retrieved_at":"2026-11-01T00:00:00+00:00",
                         "page_sha256":"a"*64,"price_status":"SELLER_DECLARED",
                         "extraction_method":"Product JSON-LD"})):
                    jid=jobs.submit_url("https://www.adafruit.com/product/1083")
                    for i in range(100):
                        output=jobs.read(jid)
                        if output["state"] in ("READY","FAILED"):break
                        time.sleep(.02)
                self.assertEqual(output["state"],"READY")
                report=output["report"]
                self.assertEqual(output["item"]["price"],"34.90")
                self.assertEqual(report["source_intake"]["source_url"],
                                 "https://www.adafruit.com/product/1083")
                self.assertEqual(report["root"]["children"][2]["kind"],"source_intake")
                self.assertNotEqual(report["sha256"],"old")
            finally:
                jobs.close()


if __name__ == "__main__":
    unittest.main()
