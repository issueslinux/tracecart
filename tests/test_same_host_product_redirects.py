"""Safe same-origin redirect recovery for generic product data."""
import json
import unittest

from generic_source_research import execute_generic_sources
from product_intake import SourceRedirect

OLD="https://shop.example.org/listing/old-dc15250"
NEW="https://shop.example.org/products/dell-dc15250"
ROBOTS=b"User-agent: *\nAllow: /\n"


def product():
    data={"@context":"https://schema.org","@type":"Product",
          "name":"Dell DC15250 laptop","model":"DC15250",
          "additionalProperty":[{"name":"RAM memory","value":"16 GB"},
                                {"name":"Battery capacity","value":"54 Wh"}]}
    return ("<html><h1>Dell DC15250 laptop</h1>"
            '<script type="application/ld+json">'+json.dumps(data)+
            "</script></html>").encode()


class SourceRedirectTests(unittest.TestCase):
    def test_redirect_rechecks_robots_and_records_final_document_url(self):
        calls=[]
        def fetch(u,*a,**kw):
            calls.append(u)
            if u.endswith("/robots.txt"):return ROBOTS
            if u==OLD:raise SourceRedirect(302,"/products/dell-dc15250")
            if u==NEW:return product()
            self.fail("Unexpected URL")
        result=execute_generic_sources(
            {"id":"offer-0","title":"Dell DC15250 laptop","url":OLD},
            "LAPTOP",fetch=fetch,enable_brand_discovery=False)
        self.assertEqual(result["sources_checked"],1)
        self.assertEqual(result["attempted_sources"][0]["resolved_url"],NEW)
        self.assertEqual(result["attempted_sources"][0]["status"],
                         "STRUCTURED_PRODUCT_DECLARATIONS_NOT_INDEPENDENTLY_TESTED")
        self.assertEqual([OLD,NEW],[u for u in calls if not u.endswith("robots.txt")])
        self.assertEqual(sum(x.endswith("/robots.txt") for x in calls),2)
        self.assertTrue(all(x["source_url"]==NEW for x in result["reference_answers"]))
        self.assertTrue(all(not x["verified_for_exact_offer"]
                            for x in result["reference_answers"]))

    def test_cross_origin_redirect_is_never_fetched(self):
        calls=[]
        def fetch(u,*a,**kw):
            calls.append(u)
            if u.endswith("/robots.txt"):return ROBOTS
            if u==OLD:raise SourceRedirect(302,"https://external.example.net/redirected")
            self.fail("Cross-origin fetch should never run")
        r=execute_generic_sources(
            {"id":"offer-0","title":"Dell DC15250 laptop","url":OLD},
            "LAPTOP",fetch=fetch,enable_brand_discovery=False)
        self.assertEqual(r["reference_answers"],[])
        self.assertEqual([u for u in calls if not u.endswith("robots.txt")],[OLD])
        self.assertEqual(r["attempted_sources"][0]["status"],"NOT_RETRIEVED_ValueError")

    def test_loop_does_not_fabricate_a_source(self):
        def fetch(u,*a,**kw):
            if u.endswith("/robots.txt"):return ROBOTS
            if u==OLD:raise SourceRedirect(302,"/products/dell-dc15250")
            raise SourceRedirect(302,OLD)
        r=execute_generic_sources(
            {"id":"offer-0","title":"Dell DC15250 laptop","url":OLD},
            "LAPTOP",fetch=fetch,enable_brand_discovery=False)
        self.assertEqual(r["sources_checked"],0)
        self.assertEqual(r["reference_answers"],[])
        self.assertEqual(r["attempted_sources"][0]["status"],"NOT_RETRIEVED_ValueError")


if __name__=="__main__":
    unittest.main()
