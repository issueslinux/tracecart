"""Offline tests for public-HTTPS robots/redirect/browser fallback adapter."""
import json
import unittest

from product_intake import SourceAccessDenied, SourceRedirect
from universal_source_acquisition import acquire_public_product

URL = "https://shop.example.org/product/one"
ROBOTS_URL = "https://shop.example.org/robots.txt"
PRODUCT = {
    "@type": "Product", "name": "Product One",
    "offers": {"@type": "Offer", "price": "39.00", "priceCurrency": "PLN"},
}
HTML = ("<html><script type='application/ld+json'>" +
        json.dumps(PRODUCT) + "</script></html>").encode("utf-8")


class SourceAcquisitionTests(unittest.TestCase):
    def test_robots_pass_and_fields_from_existing_snapshot(self):
        calls = []
        def fetch(url, maximum, mimes):
            calls.append(url)
            return b"User-agent: *\nAllow: /\n" if url == ROBOTS_URL else HTML
        result = acquire_public_product(URL, fetch=fetch)
        self.assertEqual(result["status"], "PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED")
        self.assertEqual(result["fields"]["price"], "39.00")
        self.assertEqual(calls, [ROBOTS_URL, URL])
        self.assertTrue(result["robots_checked"])
        self.assertFalse(result["checkout_verified"])

    def test_robots_denied_never_gets_page(self):
        seen = []
        def fetch(url, maximum, mimes):
            seen.append(url)
            return b"User-agent: *\nDisallow: /product\n"
        result = acquire_public_product(URL, fetch=fetch)
        self.assertEqual(result["status"], "ROBOTS_DENIED")
        self.assertEqual(seen, [ROBOTS_URL])

    def test_robots_unavailable_fails_closed(self):
        def fetch(url, maximum, mimes):
            raise SourceAccessDenied(403)
        self.assertEqual(acquire_public_product(URL, fetch=fetch)["status"],
                         "ROBOTS_UNAVAILABLE")

    def test_status_403_stops_without_render(self):
        calls = []
        def fetch(url, maximum, mimes):
            if url == ROBOTS_URL:
                return b"User-agent: *\nAllow: /\n"
            raise SourceAccessDenied(403)
        def renderer(url, raw):
            calls.append(url)
            return HTML
        result = acquire_public_product(URL, fetch=fetch,
                                        render=renderer, enable_render=True)
        self.assertEqual(result["status"], "ACCESS_DENIED")
        self.assertEqual(result["evidence"], [])
        self.assertEqual(calls, [])

    def test_cross_host_redirect_is_blocked(self):
        calls = []
        def fetch(url, maximum, mimes):
            calls.append(url)
            if url == ROBOTS_URL:
                return b"User-agent: *\nAllow: /\n"
            raise SourceRedirect(302, "https://evil.example.org/product/one")
        result = acquire_public_product(URL, fetch=fetch)
        self.assertEqual(result["status"], "REDIRECT_REJECTED")
        self.assertEqual(calls, [ROBOTS_URL, URL])

    def test_same_host_redirect_rechecks_robots(self):
        final = "https://shop.example.org/product/two"
        calls = []
        def fetch(url, maximum, mimes):
            calls.append(url)
            if url == ROBOTS_URL:
                return b"User-agent: *\nDisallow: /private\nAllow: /\n"
            if url == URL:
                raise SourceRedirect(302, "/product/two")
            return HTML
        result = acquire_public_product(URL, fetch=fetch)
        self.assertEqual(result["status"], "PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED")
        self.assertEqual(result["source_url"], final)
        self.assertEqual(result["original_requested_url"], URL)
        self.assertEqual(calls, [ROBOTS_URL, URL, final])

    def test_opt_in_render_only_after_200(self):
        calls = []
        def fetch(url, maximum, mimes):
            if url == ROBOTS_URL:
                return b"User-agent: *\nAllow: /\n"
            return b"<html><title>Dynamic catalog</title><div id='root'></div></html>"
        def renderer(url, raw):
            calls.append(url)
            return HTML
        no_render = acquire_public_product(URL, fetch=fetch, render=renderer)
        self.assertEqual(no_render["status"], "PRODUCT_NOT_IDENTIFIED")
        self.assertEqual(calls, [])
        rendered = acquire_public_product(URL, fetch=fetch,
                                          render=renderer, enable_render=True)
        self.assertEqual(calls, [URL])
        self.assertEqual(rendered["status"], "PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED")
        self.assertEqual(rendered["acquisition_method"], "RENDERED_DOM")
        self.assertEqual(rendered["fields"]["price"], "39.00")

    def test_js_challenge_http_200_does_not_trigger_render(self):
        calls = []
        def fetch(url, maximum, mimes):
            return (b"User-agent: *\nAllow: /\n" if url == ROBOTS_URL else
                    b"<html><body>Please enable JS and disable any ad blocker</body></html>")
        def renderer(url, raw):
            calls.append(url)
            return HTML
        result = acquire_public_product(URL, fetch=fetch,
                                        render=renderer, enable_render=True)
        self.assertEqual(result["status"], "ACCESS_CHALLENGE")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
