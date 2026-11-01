"""Store-agnostic URL recovery regression: actual long Amazon and Allegro URLs."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from product_intake import (
    generic_url_identity, normalized_product_url, SourceAccessDenied,
    SourceRedirect, SourceHTTPFailure, extract_product_page,
    extract_from_html, validate_product_url,
)
from cart_research import CartResearchJobs

AMAZON_LONG = (
 "https://www.amazon.pl/Ariel-Proszek-rozpuszczanie-usuwanie-"
 "zapach%C3%B3w/dp/B0FNPZQKMF/ref=sr_1_6?"
 "dib=eyJ2IjoiMSJ9.Up69hkt1c5lvaG_iR8dy-XZLzeWMkPU_zRkFeGWk_GtcowN6696-K6qArl1qssjJx7rWAd-IFd70fyhHLLXSdn4wjTRg4xnTfBIDTI2ojcb6NyhnUD04uxzT-uD5nSFhOuDZs9MDc_e0URQQG0JaWneIIa5dYkU9O_gbwNfN96iI_mQjEwgWN8PDmDkDBfs0og2gjI7Bx86k12mh1c7pWmGYVWGu5WIOdBSLSb6NPsWwlaEZJwEp5qj3qcIUCpOwp6QHreInmdEtoA6OWGKNvE3yKyO8W3V-EZPSz5Utt4A.2_AcvVNb-x4NK76FcVafjyFQsRO0LsUQAP33z_z_OMg"
 "&dib_tag=se&keywords=proszek+do+prania&qid=1793568526&sr=8-6"
)


class GenericRecoveryTests(unittest.TestCase):
    def test_exact_long_amazon_url_is_tracked_neither_logged_nor_stored(self):
        clean = normalized_product_url(AMAZON_LONG)
        self.assertEqual(clean,
            "https://www.amazon.pl/Ariel-Proszek-rozpuszczanie-usuwanie-"
            "zapach%C3%B3w/dp/B0FNPZQKMF")
        item, info = generic_url_identity(AMAZON_LONG, "HTTP_301")
        self.assertEqual(item["merchant_url"], clean)
        self.assertIn("Ariel", item["title"])
        self.assertIn("zapachów", item["title"])
        self.assertEqual(item["price"], None)
        self.assertIsNone(info["page_sha256"])
        self.assertEqual(info["product_url_identifiers"], ["B0FNPZQKMF"])
        self.assertEqual(info["url_title_confidence"], "URL_TITLE_UNVERIFIED")
        self.assertNotIn("dib=",json.dumps(info))

    def test_generic_slug_without_platform_rules(self):
        for url in [
            "https://shop.example.net/ceramic-pendant-blue-flower-45-mm",
            "https://retailer.example.org/catalog/heavy-duty-laundry-powder-5-kg",
            "https://market.example.com/products/organic-hand-soap-large-refill",
        ]:
            with self.subTest(url=url):
                obj, md=generic_url_identity(url,"HTTP_403")
                self.assertIn(" ",obj["title"])
                self.assertEqual(md["intake_status"],"URL_ONLY_UNVERIFIED")
                self.assertIsNone(obj["price"])
                self.assertIsNone(md["retrieved_at"])

    def test_decodes_real_product_html_entities(self):
        raw=(b'<script type="application/ld+json">'
             b'{"@type":"Product","name":"Ariel Color 100 pra&nacute; '
             b'zapach&oacute;w w 30&deg;C",'
             b'"offers":{"price":"76.99","priceCurrency":"PLN"}}'
             b'</script>')
        item,info=extract_from_html(
            "https://www.amazon.pl/Ariel-proszek/dp/B0FNPZQKMF",raw)
        self.assertIn("prań",item["title"])
        self.assertIn("zapachów",item["title"])
        self.assertIn("30°C",item["title"])
        self.assertEqual(item["price"],"76.99")
        self.assertEqual(info["price_status"],"SELLER_DECLARED")

    def test_source_redirect_same_host_and_robots_rechecks_path(self):
        calls=[]
        def getter(url, limit, mimes):
            calls.append(url)
            if url.endswith("/robots.txt"):
                return b"User-agent: *\nDisallow: /private\n"
            if len(calls) == 2:
                raise SourceRedirect(301, "/new-product")
            return (b'<script type="application/ld+json">'
                    b'{"@type":"Product","name":"Sample product name"}'
                    b'</script>')
        item, meta = extract_product_page("https://shop.example.org/old", fetch=getter)
        self.assertEqual(item["title"],"Sample product name")
        self.assertEqual(meta["source_url"],"https://shop.example.org/new-product")
        self.assertEqual(len(calls),3)

    def test_source_redirect_to_other_origin_is_never_followed(self):
        calls=[]
        def getter(url, limit, mimes):
            calls.append(url)
            if url.endswith("/robots.txt"):
                return b"User-agent: *\nAllow: /\n"
            raise SourceRedirect(301,"https://evil.example.org/retrieve")
        with self.assertRaises(SourceRedirect):
            extract_product_page("https://shop.example.org/start",fetch=getter)
        self.assertEqual(len(calls),2)

    def test_source_redirect_to_disallowed_path_is_never_followed(self):
        calls=[]
        def getter(url, limit, mimes):
            calls.append(url)
            if url.endswith("/robots.txt"):
                return b"User-agent: *\nDisallow: /private\n"
            raise SourceRedirect(301,"/private/offer")
        with self.assertRaisesRegex(ValueError,"robots"):
            extract_product_page("https://shop.example.org/start",fetch=getter)
        self.assertEqual(len(calls),2)

    def test_redirect_loop_is_bounded(self):
        def getter(url, limit, mimes):
            if url.endswith("/robots.txt"):
                return b"User-agent: *\nAllow: /\n"
            return (_ for _ in ()).throw(SourceRedirect(301, "/original"))
        with self.assertRaises(SourceRedirect):
            extract_product_page("https://shop.example.org/original",fetch=getter)

    def test_bad_host_security_not_bypassed(self):
        for bad in ["https://localhost/product/blue-dress",
                    "https://127.0.0.1/product/blue-dress",
                    "http://shop.example.org/product/blue-dress",
                    "https://username:password@shop.example.org/item/valid-product"]:
            with self.assertRaises(ValueError):
                generic_url_identity(bad,"HTTP_403")

    def test_any_shop_301_403_and_parser_missing_produce_limited_ready(self):
        from product_intake import SourceHTTPFailure
        for name, error in [
            ("HTTP301",SourceRedirect(301,"/new")),
            ("HTTP403",SourceAccessDenied(403)),
            ("HTTP404",SourceHTTPFailure(404)),
            ("MISSING",ValueError("No reliable product name can be extracted from this page")),
        ]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                def runner(item):
                    self.assertIsNone(item["price"])
                    return {"root":{"details":{},"children":[
                        {"kind":"selected","title":"selected"},
                        {"kind":"questions","title":"questions"},
                        {"kind":"summary","status":"NO_FORCED_WINNER",
                         "details":{"payment_authorized":False}}]},
                        "sha256":"preliminary"}
                jobs=CartResearchJobs(Path(tmp)/"jobs.sqlite",runner=runner)
                try:
                    with patch("product_intake.extract_product_page",side_effect=error):
                        jid=jobs.submit_url(AMAZON_LONG)
                        for _ in range(100):
                            result=jobs.read(jid)
                            if result["state"] in ("READY","FAILED"): break
                            time.sleep(.02)
                    self.assertEqual(result["state"],"READY")
                    self.assertEqual(result["report"]["root"]["children"][2]["status"],
                                     "URL_ONLY_UNVERIFIED")
                    self.assertNotIn("dib=",json.dumps(result))
                finally:
                    jobs.close()

    def test_unreadable_url_no_fake_specific_title(self):
        item, meta=generic_url_identity("https://store.example.org/dp/B0FNPZQKMF","HTTP_403")
        self.assertEqual(meta["url_title_confidence"],"INSUFFICIENT_URL_DESCRIPTION")
        self.assertTrue(item["title"].startswith("Unidentified product"))
        self.assertEqual(item["barcode"],"")


if __name__ == "__main__":
    unittest.main()
