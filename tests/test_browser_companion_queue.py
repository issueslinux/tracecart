"""Consent-gated, local-only browser queue: no merchant network calls."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest

from browser_companion_queue import CompanionQueue, MAX_PENDING, LEASE_SECONDS


URL = "https://store.example.org/item/sku-7"


def sample():
    return {
        "@type": "Product", "name": "Example SKU 7",
        "brand": {"name": "Sample"}, "sku": "SKU-7",
        "offers": {"@type": "Offer", "price": "34.90", "priceCurrency": "PLN",
                   "availability": "https://schema.org/InStock",
                   "seller": {"name": "Sample Merchant"}},
    }


def receipt(job, snapshot=None, error=None, observed=None):
    return {
        "job_id": job["job_id"], "url": job["url"],
        "snapshot": snapshot, "error": error,
        "price_origin": None if error is not None else "DIRECT_OFFER_PRICE",
        "captured_at": observed if observed is not None else
        datetime.now(timezone.utc).isoformat(),
    }


class BrowserCompanionQueueTests(unittest.TestCase):
    def setUp(self):
        self.clock = [100.0]
        self.queue = CompanionQueue(token="a" * 64, clock=lambda: self.clock[0])

    def test_explicit_jobs_and_one_lease_without_automatic_retry(self):
        job_id = self.queue.enqueue(URL)
        self.assertTrue(self.queue.authorized("a" * 64))
        self.assertFalse(self.queue.authorized("bad"))
        self.assertFalse(self.queue.authorized(None))
        with self.assertRaisesRegex(ValueError, "DUPLICATE"):
            self.queue.enqueue(URL)
        job = self.queue.take()
        self.assertEqual(job["job_id"], job_id)
        self.assertIsNone(self.queue.take())
        result = self.queue.report(receipt(job, error="SITE_PERMISSION_REQUIRED"))
        self.assertEqual(result["status"], "SITE_PERMISSION_REQUIRED")
        self.assertIsNone(self.queue.take())
        with self.assertRaisesRegex(ValueError, "JOB_NOT_LEASED"):
            self.queue.report(receipt(job, snapshot=sample()))

    def test_browser_fields_are_unverified_and_have_provenance(self):
        self.queue.enqueue(URL)
        job = self.queue.take()
        result = self.queue.report(receipt(job, snapshot=sample()))
        self.assertEqual(result["status"], "PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED")
        entry = self.queue.listed()[0]
        self.assertEqual(entry["result"]["fields"]["price"], "34.90")
        self.assertEqual(entry["result"]["fields"]["seller"], "Sample Merchant")
        self.assertEqual(entry["result"]["acquisition_method"], "USER_BROWSER")
        self.assertFalse(entry["result"]["seller_verified"])
        self.assertFalse(entry["result"]["checkout_verified"])
        self.assertFalse(entry["result"]["index_only"])
        self.assertEqual(len(entry["result"]["snapshot_sha256"]), 64)
        self.assertEqual(entry["result"]["browser_original_price_origin"],
                         "DIRECT_OFFER_PRICE")
        self.assertTrue(all(v["seller_verified"] is False
                            for v in entry["result"]["evidence"]))

    def test_prohibit_secrets_and_unexpected_schema_keys(self):
        self.queue.enqueue(URL)
        job = self.queue.take()
        for key in ("cookies", "localStorage", "token", "html", "headers"):
            with self.subTest(key=key):
                bad = sample()
                bad[key] = "sensitive"
                with self.assertRaisesRegex(ValueError, "UNEXPECTED_PRODUCT_FIELDS"):
                    self.queue.report(receipt(job, snapshot=bad))
        bad = sample()
        bad["offers"]["checkoutToken"] = "secret"
        with self.assertRaisesRegex(ValueError, "INVALID_OFFER_FIELDS"):
            self.queue.report(receipt(job, snapshot=bad))
        self.assertEqual(self.queue.listed()[0]["status"], "IN_PROGRESS")

    def test_mismatched_source_and_stale_receipt_fail_closed(self):
        self.queue.enqueue(URL)
        job = self.queue.take()
        wrong = receipt(job, snapshot=sample())
        wrong["url"] = "https://unrelated.example.org/item/7"
        with self.assertRaisesRegex(ValueError, "CAPTURE_URL_MISMATCH"):
            self.queue.report(wrong)
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with self.assertRaisesRegex(ValueError, "STALE_CAPTURE"):
            self.queue.report(receipt(job, snapshot=sample(), observed=old))
        self.assertEqual(self.queue.listed()[0]["status"], "IN_PROGRESS")

    def test_dom_microdata_and_woocommerce_provenance_is_unverified(self):
        for origin in ("PRODUCT_OFFER_MICRODATA", "WOOCOMMERCE_PRIMARY_PRICE"):
            with self.subTest(origin=origin):
                queue = CompanionQueue(token="b" * 64)
                queue.enqueue(URL)
                job = queue.take()
                item = receipt(job, snapshot=sample())
                item["price_origin"] = origin
                response = queue.report(item)
                self.assertEqual(response["status"],
                                 "PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED")
                evidence = queue.listed()[0]["result"]
                self.assertFalse(evidence["seller_verified"])
                self.assertFalse(evidence["checkout_verified"])
                self.assertEqual(evidence["browser_original_price_origin"], origin)
                self.assertTrue(any(
                    row["field"] == "price" and
                    row["browser_original_price_origin"] == origin
                    for row in evidence["evidence"]))

    def test_dom_conflicts_and_ambiguity_are_explicit_failures(self):
        for error in ("MULTIPLE_PRODUCTS_AMBIGUOUS",
                      "CONFLICTING_OFFER_EVIDENCE",
                      "CONFLICTING_PRODUCT_IDENTITY"):
            with self.subTest(error=error):
                queue = CompanionQueue(token="b" * 64)
                queue.enqueue(URL)
                job = queue.take()
                failure = receipt(job, error=error)
                self.assertEqual(queue.report(failure)["status"], error)
                self.assertIsNone(queue.listed()[0]["result"])

    def test_expired_lease_never_reissued(self):
        self.queue.enqueue(URL)
        job = self.queue.take()
        self.clock[0] += LEASE_SECONDS + 0.1
        self.assertIsNone(self.queue.take())
        self.assertEqual(self.queue.listed()[0]["status"], "TAB_TIMEOUT")
        with self.assertRaisesRegex(ValueError, "JOB_NOT_LEASED"):
            self.queue.report(receipt(job, snapshot=sample()))

    def test_only_explicit_https_public_looking_urls_and_capacity(self):
        for url in ("http://shop.example.org/p", "https://127.0.0.1/product",
                    "https://foo.local/item", "https://user:pass@foo.org/x",
                    "file:///etc/passwd"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.queue.enqueue(url)
        for i in range(MAX_PENDING):
            self.queue.enqueue("https://store.example.org/item/{}".format(i))
        with self.assertRaisesRegex(ValueError, "COMPANION_QUEUE_FULL"):
            self.queue.enqueue("https://store.example.org/item/overflow")

    def test_atomic_batch_rejects_duplicates_without_partial_enqueue(self):
        self.queue.enqueue_many(["https://store.example.org/item/1",
                                 "https://store.example.org/item/2"])
        self.assertEqual(len(self.queue.listed()), 2)
        with self.assertRaisesRegex(ValueError, "DUPLICATE_BATCH"):
            self.queue.enqueue_many(["https://store.example.org/item/new",
                                     "https://store.example.org/item/new"])
        self.assertEqual(len(self.queue.listed()), 2)
        with self.assertRaisesRegex(ValueError, "DUPLICATE_PENDING"):
            self.queue.enqueue_many(["https://store.example.org/item/new",
                                     "https://store.example.org/item/1"])
        self.assertEqual(len(self.queue.listed()), 2)

    def test_token_persistent_and_not_world_readable(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "secret.token"
            a = CompanionQueue(token_path=path)
            b = CompanionQueue(token_path=path)
            self.assertEqual(a.token, b.token)
            self.assertEqual(len(a.token), 64)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            os.chmod(str(path), 0o644)
            with self.assertRaisesRegex(ValueError, "INSECURE_COMPANION_TOKEN_FILE"):
                CompanionQueue(token_path=path)


if __name__ == "__main__":
    unittest.main()


class BrowserCouponReceiptTests(unittest.TestCase):
    def setUp(self):
        self.queue=CompanionQueue(token="b"*64)
        self.queue.enqueue(URL)
        self.job=self.queue.take()

    def test_browser_coupon_is_conditional_and_never_checkout_verified(self):
        product=sample()
        product["offers"]["price"]="3499.99"
        r=receipt(self.job,snapshot=product)
        r["promotion"]={"price":"2799.00","currency":"PLN",
          "code":"BW1610-0112","valid_until":"2026-12-01",
          "source":"VISIBLE_PRODUCT_PRICE_WITH_CODE"}
        accepted=self.queue.report(r)
        self.assertEqual(accepted["status"],
                         "PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED")
        result=self.queue.get_job(self.job["job_id"])["result"]
        self.assertEqual(result["fields"]["price"],"3499.99")
        self.assertEqual(result["browser_promotion"]["price"],"2799.00")
        self.assertEqual(result["browser_promotion"]["code"],"BW1610-0112")
        self.assertFalse(result["browser_promotion"]["code_applied"])
        self.assertFalse(result["browser_promotion"]["checkout_verified"])

    def test_reject_coupon_equal_or_higher_than_list_price(self):
        for price in ("34.90","99.90"):
            with self.subTest(price=price):
                r=receipt(self.job,snapshot=sample())
                r["promotion"]={"price":price,"currency":"PLN",
                  "code":"SAVE2026","valid_until":None,
                  "source":"VISIBLE_PRODUCT_PRICE_WITH_CODE"}
                with self.assertRaisesRegex(ValueError,"INVALID_COUPON_PRICE_RELATION"):
                    self.queue.report(r)
        self.assertEqual(self.queue.get_job(self.job["job_id"])["status"],"IN_PROGRESS")

    def test_reject_unknown_coupon_or_secret_fields(self):
        r=receipt(self.job,snapshot=sample())
        for bad in ({"price":"29.00","currency":"PLN","code":"SAVE2026",
                     "valid_until":None,"source":"VISIBLE_PRODUCT_PRICE_WITH_CODE",
                     "customer_token":"SECRET"},
                    {"price":"29.00","currency":"USD","code":"SAVE2026",
                     "valid_until":None,"source":"VISIBLE_PRODUCT_PRICE_WITH_CODE"}):
            r["promotion"]=bad
            with self.assertRaisesRegex(ValueError,"INVALID_COUPON_PROJECTION"):
                self.queue.report(r)
