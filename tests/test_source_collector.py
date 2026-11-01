"""Merchant source-collection tests, including robots, injection, and provenance."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from decision_tree import analyze
import source_collector as s


def page(sku, name, price, availability="InStock", condition="NewCondition"):
    item = {"@context": "https://schema.org", "@type": "Product",
            "name": name, "sku": sku,
            "offers": {"@type": "Offer", "price": price,
                       "priceCurrency": "USD",
                       "availability": "https://schema.org/" + availability,
                       "itemCondition": "https://schema.org/" + condition}}
    html = '<html><script type="application/ld+json">' + json.dumps(item) + '</script></html>'
    return html.encode(), html


ROBOTS_ALLOW = "User-agent: *\nDisallow: /api/\nDisallow: /search\n"
ROBOTS_DENY = "User-agent: *\nDisallow: /product/\n"


class CollectorTests(unittest.TestCase):
    def test_realistic_product_jsonld_to_evidence_tree(self):
        fetches = []

        def fetch(u):
            fetches.append(u)
            return page("1083", "An actual merchant claim", "9.95")

        clock = [100.0]
        sleeps = []

        def sleep(n):
            sleeps.append(n)
            clock[0] += n

        collector = s.ProductCollector(download=fetch, monotonic=lambda: clock[0],
                                       sleep=sleep, robots_text=ROBOTS_ALLOW)
        result = collector.collect(["https://www.adafruit.com/product/1083"])
        self.assertEqual(len(fetches), 1)
        self.assertEqual(result["collection"]["review_sources_collected"], 0)
        self.assertEqual(result["offers"][0]["price"], "9.95")
        quote = result["offers"][0]["questions"][0]["evidence"][0]
        self.assertEqual(quote["publisher"], "adafruit.com")
        self.assertEqual(quote["sha256"],
                         s.sha256(page("1083", "An actual merchant claim", "9.95")[0]).hexdigest())
        self.assertTrue(quote["retrieved_at"].startswith("20"))
        report = analyze({k: result[k] for k in ("goal", "category", "offers")})
        self.assertEqual(report["root"]["children"][-1]["status"], "ABSTAIN")
        first_price = next(n for n in report["root"]["children"][0]["children"]
                           if n["id"] == "question-product_1083-price")
        self.assertEqual(first_price["status"], "SINGLE_SOURCE")
        source = first_price["children"][0]["details"]
        self.assertEqual(source["publisher_domain"], "adafruit.com")
        self.assertTrue(source["retrieved_at"])
        self.assertTrue(source["source_content_sha256"])

    def test_discontinued_stock_is_contradiction(self):
        collector = s.ProductCollector(download=lambda u: page("247", "Legacy board", "29.95", "Discontinued"),
                                       robots_text=ROBOTS_ALLOW)
        out = collector.collect(["https://www.adafruit.com/product/247"])
        report = analyze({k: out[k] for k in ("goal", "category", "offers")})
        status = next(n["status"] for n in report["root"]["children"][0]["children"]
                      if n["id"].endswith("-availability"))
        self.assertEqual(status, "REFUTED")

    def test_robots_disallow_means_no_product_fetch(self):
        fetch = []
        collector = s.ProductCollector(download=lambda u: fetch.append(u) or page("247", "Board", "29.95"),
                                       robots_text=ROBOTS_DENY)
        with self.assertRaisesRegex(ValueError, "No verifiable"):
            collector.collect(["https://www.adafruit.com/product/247"])
        self.assertFalse(fetch)

    def test_bad_urls_do_not_touch_network(self):
        bad = [
            "http://www.adafruit.com/product/247", "https://evil.com/product/247",
            "https://www.adafruit.com.evil.net/product/247",
            "https://www.adafruit.com@127.0.0.1/product/247",
            "https://www.adafruit.com/product/247?redirect=http://evil.com",
            "https://www.adafruit.com/api/anything",
            "file:///etc/passwd",
            "https://127.0.0.1/product/247",
            "https://www.adafruit.com:8443/product/247",
        ]
        for url in bad:
            with self.subTest(url=url), self.assertRaises(ValueError):
                s.ProductCollector(robots_text=ROBOTS_ALLOW).collect([url])

    def test_multiple_pages_respect_delay(self):
        times = [100.]
        delays = []
        c = s.ProductCollector(
            download=lambda u: page(u.rsplit("/", 1)[-1], "New board", "8.00"),
            monotonic=lambda: times[0],
            sleep=lambda t: (delays.append(t), times.__setitem__(0, times[0]+t)),
            robots_text=ROBOTS_ALLOW)
        c.collect(["https://www.adafruit.com/product/247",
                   "https://www.adafruit.com/product/1083"])
        self.assertEqual(len(delays), 1)
        self.assertGreaterEqual(delays[0], 2.)

    def test_bad_schema_never_creates_fictional_product(self):
        c = s.ProductCollector(download=lambda u: (b"<html></html>", "<html></html>"),
                               robots_text=ROBOTS_ALLOW)
        with self.assertRaisesRegex(ValueError, "No verifiable"):
            c.collect(["https://www.adafruit.com/product/247"])

    def test_same_publisher_two_urls_not_independent(self):
        raw = json.loads((Path(__file__).resolve().parents[1] /
                          "examples/sample_research_fixture.json").read_text())
        q = raw["offers"][1]["questions"][0]
        q["evidence"][0]["url"] = "https://www.adafruit.com/product/247"
        q["evidence"][1]["url"] = "https://www.adafruit.com/product/1083"
        result = analyze(raw)
        battery = next(q for q in result["root"]["children"][1]["children"]
                       if q["id"] == "question-offer_b-battery")
        self.assertEqual(battery["status"], "SINGLE_SOURCE")
        evidence = [e["details"] for e in battery["children"] if e["kind"] == "evidence"]
        self.assertTrue(evidence[1]["duplicate_publisher"])
        self.assertNotEqual(evidence[0]["source_url"], evidence[1]["source_url"])

    def test_duplicate_and_excessive_requests_blocked(self):
        c = s.ProductCollector(robots_text=ROBOTS_ALLOW)
        with self.assertRaises(ValueError):
            c.collect(["https://www.adafruit.com/product/247"]*2)
        with self.assertRaises(ValueError):
            c.collect(["https://www.adafruit.com/product/" + str(x) for x in range(100, 106)])

    def test_failed_source_remains_in_full_decision_tree(self):
        def fetch(url):
            if url.endswith("/247"):
                return page("247", "Good product", "29.95")
            return b"<html>bad product</html>", "<html>bad product</html>"
        collector = s.ProductCollector(download=fetch, robots_text=ROBOTS_ALLOW,
                                       sleep=lambda delay: None)
        found = collector.collect(["https://www.adafruit.com/product/247",
                                   "https://www.adafruit.com/product/1083"])
        self.assertEqual(len(found["offers"]), 1)
        self.assertEqual(len(found["collection"]["source_failures"]), 1)
        from source_collector import attach_collection_provenance
        report = s.analyze({k: found[k] for k in ("goal","category","offers")})
        report = attach_collection_provenance(report, found)
        missed = next(x for x in report["root"]["children"] if x["kind"] == "source_failure")
        self.assertIn("/product/1083", missed["title"])
        self.assertEqual(missed["status"], "NOT_RETRIEVED")
        self.assertEqual(report["root"]["children"][-1]["status"], "ABSTAIN")

    def test_metadata_cannot_claim_independent_review(self):
        c = s.ProductCollector(download=lambda u: page("247", "Board", "29.95"),
                               robots_text=ROBOTS_ALLOW)
        item = c.collect(["https://www.adafruit.com/product/247"])
        self.assertEqual(item["collection"]["review_sources_collected"], 0)
        self.assertEqual(item["collection"]["independent_product_tests_collected"], 0)
        for q in item["offers"][0]["questions"]:
            for e in q["evidence"]:
                self.assertEqual(e["source_type"], "listing")
                self.assertEqual(e["publisher"], "adafruit.com")


if __name__ == "__main__":
    unittest.main()
