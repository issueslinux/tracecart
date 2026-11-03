"""All available retailer links get bounded checks without scam false positives."""
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch

from link_safety import (
    assess_links, rdap_registration, root_domain, _host_report,
)


def dns(host):return "93.184.216.34"
def tls(host):return {"valid":True,"tls_version":"TLSv1.3"}
def old_registry(host):
    return {"status":"REGISTRY_DATA_FOUND",
            "registered_at":"2001-08-18","age_days":9000,
            "registration_source":"https://rdap.dns.pl/domain/delkom.pl"}
def new_registry(host):
    return {"status":"REGISTRY_DATA_FOUND",
            "registered_at":"2026-10-30","age_days":4}


class LinkSafetyTests(unittest.TestCase):
    def test_all_actual_urls_and_duplicate_offer_ids_are_covered(self):
        records=[
            {"id":"offer-0","url":"https://www.mediaexpert.pl/item"},
            {"id":"offer-1","url":"https://www.mediaexpert.pl/item"},
            {"id":"offer-2","url":"https://delkom.pl/product"},
            {"id":"offer-3","url":None},
            {"id":"offer-4","url":None},
        ]
        result=assess_links(records,["https://delkom.pl/product",
                      "https://allegro.pl/product"],dns=dns,tls=tls,rdap=old_registry)
        self.assertEqual(result["status"],"COMPLETE")
        self.assertEqual(result["unique_links_checked"],3)
        self.assertEqual(result["index_cards_without_direct_url"],2)
        self.assertEqual(result["hosts_checked"],3)
        self.assertEqual(result["links"][0]["offer_ids"],["offer-0","offer-1"])
        self.assertEqual(result["links"][0]["risk"]["status"],
                         "BASIC_TECHNICAL_CHECKS_PASSED")
        self.assertFalse(result["merchant_legitimacy_verified"])
        self.assertFalse(result["independent_fraud_reputation_checked"])
        self.assertFalse(result["links"][0]["risk"]["legitimacy_verified"])

    def test_unsafe_urls_never_trigger_dns_or_tls(self):
        urls=[
            "http://example.org/sale",
            "https://127.0.0.1/checkout",
            "https://user:pass@example.org/product",
            "https://shop.example.org:4444/item",
            "https://xn--exmple-cua.org@127.0.0.1/data",
        ]
        calls=[]
        def forbidden(*args):
            calls.append(args)
            raise AssertionError("No external network should be contacted")
        result=assess_links(
            [{"id":"offer-"+str(i),"url":u} for i,u in enumerate(urls)],
            dns=forbidden,tls=forbidden,rdap=forbidden)
        self.assertEqual(result["unique_links_checked"],len(urls))
        self.assertEqual(result["hosts_checked"],0)
        self.assertTrue(all(x["risk"]["status"]=="HIGH_RISK_SIGNALS"
                            for x in result["links"]))
        self.assertEqual(calls,[])

    def test_private_dns_rejected_without_tls_connection(self):
        calls=[]
        def forbidden(*args):
            calls.append(args)
            raise AssertionError("TLS not allowed")
        record=assess_links([{"id":"offer-0","url":"https://mall.example.org/item"}],
                            dns=lambda h:"127.0.0.1",tls=forbidden,rdap=forbidden)
        risk=record["links"][0]["risk"]
        self.assertEqual(risk["status"],"HIGH_RISK_SIGNALS")
        self.assertIn("DESTINATION_NOT_PUBLIC",risk["signals"])
        self.assertEqual(calls,[])

    def test_new_domain_is_a_caution_not_a_fraud_verdict(self):
        result=assess_links([{"id":"offer-0","url":"https://brand-new.example.pl/item"}],
                            dns=dns,tls=tls,rdap=new_registry)
        risk=result["links"][0]["risk"]
        self.assertEqual(risk["status"],"REVIEW_REQUIRED")
        self.assertIn("RECENTLY_REGISTERED_DOMAIN_UNDER_90_DAYS",risk["signals"])
        self.assertFalse(risk["legitimacy_verified"])

    def test_missing_dns_or_registry_is_inconclusive_not_a_scam(self):
        record=assess_links([{"id":"offer-0","url":"https://unknown-store.example.org/item"}],
                            dns=lambda h:(_ for _ in ()).throw(OSError("down")),
                            tls=tls,rdap=old_registry)
        risk=record["links"][0]["risk"]
        self.assertEqual(risk["status"],"INCONCLUSIVE")
        self.assertEqual(risk["registration"]["status"],"NOT_CHECKED")

    def test_brand_in_third_party_subdomain_is_review_signal(self):
        record=assess_links([{"id":"offer-0",
             "url":"https://paypal.checkout.strange-example.org/item"}],
             dns=dns,tls=tls,rdap=old_registry)
        signals=record["links"][0]["risk"]["signals"]
        self.assertIn("BRAND_NAME_IN_THIRD_PARTY_SUBDOMAIN",signals)

    def test_nask_registration_uses_only_fixed_official_endpoint(self):
        seen=[]
        def fake_reader(url):
            seen.append(url)
            return json.dumps({
                "ldhName":"delkom.pl",
                "events":[{"eventAction":"registration",
                           "eventDate":"2001-08-18T11:00:00Z"}],
            }).encode()
        d=rdap_registration("www.delkom.pl",reader=fake_reader)
        self.assertEqual(d["status"],"REGISTRY_DATA_FOUND")
        self.assertEqual(d["registered_at"],"2001-08-18")
        self.assertGreater(d["age_days"],7000)
        self.assertEqual(seen,["https://rdap.dns.pl/domain/delkom.pl"])
        self.assertEqual(root_domain("www.delkom.pl"),"delkom.pl")
        self.assertEqual(root_domain("shop.example.co.uk"),"example.co.uk")

    def test_rdap_result_for_other_domain_does_not_count(self):
        wrong=rdap_registration("delkom.pl",reader=lambda u:
            json.dumps({"ldhName":"somebody-else.pl"}).encode())
        self.assertEqual(wrong["status"],"REGISTRY_RESPONSE_INVALID")


if __name__=="__main__":
    unittest.main()
