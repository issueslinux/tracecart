"""Cross-category generic source research, source identity, safe failures."""
from hashlib import sha256
import json
import unittest
from unittest.mock import patch

from generic_source_research import (
    product_identity,parse_source_claims,execute_generic_sources,
    candidate_urls,parse_html_document,MAX_CLAIMS)
from evidence_execution import execute_reference_checks
from offer_question_bank import offer_summaries
from guided_decision import build_decision_projection
from offer_knowledge_graph import build_offer_knowledge_graph

ROBOTS=b"User-agent: *\nAllow: /\n"
BLOCK=b"User-agent: *\nDisallow: /\n"

def product_page(name,model,fields):
    data={"@context":"https://schema.org","@type":"Product",
          "name":name,"model":model,"brand":{"@type":"Brand","name":name.split()[0]},
          "additionalProperty":[{"@type":"PropertyValue","name":k,"value":v}
                                for k,v in fields]}
    return ("""<!DOCTYPE html><html><head><script type="application/ld+json">"""+
       json.dumps(data)+"""</script></head><body><h1>"""+name+
       """</h1><p>Product details</p></body></html>""").encode("utf8")

SAMPLES=[
    ("E_BIKE","ALLGOBIKE AM27 electric bike",
     [("Battery Capacity","36 V 15 Ah"),("Motor power","250 W"),
      ("Max range","85 km"),("Brakes","disc")],"am27"),
    ("LAPTOP","Lenovo IdeaPad 16IPH11 laptop",
     [("RAM memory","16 GB"),("Storage capacity","512 GB"),
      ("Display","16 inch IPS"),("Warranty","24 months")],"16iph11"),
    ("SMARTPHONE","Samsung Galaxy S24 phone",
     [("Screen resolution","2340x1080"),("Memory","8 GB"),
      ("Storage","128 GB"),("Battery capacity","4000 mAh")],"s24"),
    ("SSD","Kingston KC3000 SSD",
     [("Storage capacity","2048 GB"),("Read speed","7000 MB/s"),
      ("Warranty","5 years")],"kc3000"),
    ("PRINTER","Brother MFC890 printer",
     [("Print speed","30 ppm"),("Display","color"),("Weight","11 kg")],"mfc890"),
    ("COMPRESSOR","Einhell TEAC27050 compressor",
     [("Power","1800 W"),("Tank capacity","50 L"),
      ("Pressure","8 bar")],"teac27050"),
]

class GeneralSourceTests(unittest.TestCase):
    def test_realistic_product_schema_across_six_categories(self):
        for cat,name,fields,model in SAMPLES:
            with self.subTest(category=cat):
                offer={"id":"offer-0","title":name,"kind":"INPUT_PRODUCT"}
                raw=product_page(name,model,fields)
                result=parse_source_claims(
                    raw,offer,cat,"https://example.org/product/item",
                    "DIRECT_SELLER_LINK")
                self.assertEqual(result["status"],
                    "STRUCTURED_PRODUCT_DECLARATIONS_NOT_INDEPENDENTLY_TESTED")
                self.assertGreaterEqual(len(result["claims"]),2)
                self.assertLessEqual(len(result["claims"]),MAX_CLAIMS)
                self.assertTrue(all(x["source_sha256"]==sha256(raw).hexdigest()
                                    for x in result["claims"]))
                self.assertTrue(all(x["source_kind"]==
                    "SELLER_PRODUCT_PAGE_DECLARATIONS" for x in result["claims"]))
                self.assertTrue(all(not x["verified_for_exact_offer"]
                                    for x in result["claims"]))

    def test_user_selected_ryobi_name_matches_its_own_schema_product(self):
        # User URL displays a marketing name without machine type RPI18-0,
        # but the exact same name and real SKU are present on the page.
        title="Kompresor wysokociśnieniowy 18V ONE+"
        raw=product_page(title,"RPI18-0",[
            ("Napięcie/Moc","18V"),("Kod EAN","4892210230478"),
            ("Pojemność akumulatora [Ah]","-"),
            ("Waga (bez akumulatora)","0.6"),
            ("Wyposażenie standardowe","Igła do piłek sportowych"),
        ])
        parsed=parse_source_claims(raw,{"title":title},"COMPRESSOR",
            "https://maker.example.org/compressors/rpi18-0/",
            "DIRECT_SELLER_LINK")
        self.assertEqual(parsed["identity"],
            "EXACT_SOURCE_PRODUCT_NAME_VARIANT_AT_CHECKOUT_UNVERIFIED")
        self.assertGreaterEqual(len(parsed["claims"]),4)
        self.assertTrue(any(x["source_property"]=="model" and x["value"]=="RPI18-0"
                            for x in parsed["claims"]))
        self.assertTrue(any(x["source_property"]=="Kod EAN"
                            and x["value"]=="4892210230478"
                            for x in parsed["claims"]))
        self.assertTrue(any(x["source_property"]=="Napięcie/Moc"
                            and x["property_family"]=="voltage"
                            for x in parsed["claims"]))
        self.assertFalse(any(x["value"]=="-" for x in parsed["claims"]))
        self.assertTrue(all(not x["verified_for_exact_offer"]
                            for x in parsed["claims"]))
        wrong=product_page("Kompresor wysokociśnieniowy 18V OTHER",
                           "RPI18-0",[("Napięcie/Moc","18V")])
        rejected=parse_source_claims(wrong,{"title":title},"COMPRESSOR",
            "https://maker.example.org/compressors/other/",
            "DIRECT_SELLER_LINK")
        self.assertEqual(rejected["claims"],[])

    def test_html_table_and_definition_list_without_jsonld(self):
        raw=(b"<html><h1>Brand Alpha123 laptop</h1><table>"
             b"<tr><th>RAM memory</th><td>16 GB</td></tr>"
             b"<tr><th>Storage capacity</th><td>1 TB</td></tr>"
             b"</table><dl><dt>Warranty</dt><dd>24 months</dd></dl></html>")
        result=parse_source_claims(raw,{"title":"Brand Alpha123 laptop"},
            "LAPTOP","https://example.org/product/brand","DIRECT_SELLER_LINK")
        self.assertGreaterEqual(len(result["claims"]),2)
        self.assertIn("RAM memory",[x["source_property"] for x in result["claims"]])

    def test_unrelated_schema_and_sidebar_does_not_transfer_claims(self):
        raw=product_page("Brand Other999 laptop","other999",
                         [("RAM memory","128GB"),("Storage","8 TB")])
        offer={"title":"Brand ABC123 laptop"}
        result=parse_source_claims(raw,offer,"LAPTOP",
            "https://example.org/product/other",
            "PUBLISHED_DISCOVERY_HIT")
        self.assertEqual(result["claims"],[])
        self.assertIn(result["status"],(
            "SOURCE_PAGE_IDENTITY_NOT_CONFIRMED",
            "SOURCE_NO_STRUCTURED_PRODUCT_PROPERTIES"))

    def test_script_text_not_a_specification(self):
        raw=b'''<html><h1>Brand A123 Phone</h1>
          <script>document.body.innerHTML="Battery: 99999 Wh";</script>
          <div>No technical details provided.</div></html>'''
        result=parse_source_claims(raw,{"title":"Brand A123 Phone"},
              "SMARTPHONE","https://example.org/a123","DIRECT_SELLER_LINK")
        self.assertEqual(result["claims"],[])

    def test_model_link_found_from_bounded_official_domain_sitemap(self):
        offer={"title":"Laptop Foomaker A123",
               "id":"offer-0"}
        home="https://foomaker.com/"
        doc="https://foomaker.com/products/foomaker-a123"
        sitemap="https://foomaker.com/sitemap.xml"
        page=product_page("Foomaker A123 laptop","a123",[
            ("RAM memory","32 GB"),("Display","OLED")])
        seen=[]
        def loader(url,*args,**kwargs):
            seen.append(url)
            if url.endswith("/robots.txt"):return ROBOTS
            if url==home:
                return b"<html><head><title>Foomaker</title></head><body><h1>Foomaker</h1></body></html>"
            if url==sitemap:
                return (b'<?xml version="1.0" encoding="utf-8"?><urlset>'
                        b'<url><loc>https://foomaker.com/products/foomaker-a123</loc></url>'
                        b'</urlset>')
            if url==doc:return page
            self.fail("unexpected sitemap fetch "+url)
        result=execute_generic_sources(offer,"LAPTOP",fetch=loader)
        self.assertEqual(result["sources_checked"],1)
        self.assertEqual(result["reference_answers"][0]["source_url"],doc)
        self.assertEqual(seen.count(sitemap),1)
        self.assertEqual(seen.count(doc),1)

    def test_numeric_model_tokens_require_context_not_wattage(self):
        self.assertEqual(product_identity("SSD Samsung 990 PRO NVME 2TB"),
                         {"brand":"samsung","model":"990",
                          "identity_status":"TITLE_MODEL_TOKEN_LEAD_NOT_VERIFIED"})
        self.assertEqual(product_identity("Garmin Forerunner 265 smartwatch")
                         ["model"],"265")
        self.assertIsNone(product_identity(
            "Rower elektryczny 250 W 100 KM 15 Ah 27.5 cali"))

    def test_direct_seller_url_crawler_is_robots_checked(self):
        url="https://example.org/products/brand-a123"
        offer={"id":"offer-0","title":"Brand A123 Smartphone","url":url}
        html=product_page("Brand A123 Smartphone","a123",
                          [("Battery","4000mAh"),("Display","OLED")])
        seen=[]
        def fetch(u,*args,**kwargs):
            seen.append(u)
            return ROBOTS if u.endswith("/robots.txt") else html
        result=execute_generic_sources(
            offer,"SMARTPHONE",fetch=fetch,enable_brand_discovery=False)
        self.assertEqual(result["sources_checked"],1)
        self.assertEqual(result["verified_for_exact_offer"],0)
        self.assertTrue(seen[0].endswith("/robots.txt"))
        self.assertEqual(seen[1],url)

    def test_no_source_ever_uses_blocked_page_or_fabricates_price(self):
        offer={"id":"offer-0","title":"Brand A123 Smartphone",
               "url":"https://example.org/products/brand-a123"}
        seen=[]
        def denied(u,*args,**kwargs):
            seen.append(u)
            return BLOCK
        result=execute_generic_sources(offer,"SMARTPHONE",fetch=denied,
                                       enable_brand_discovery=False)
        self.assertEqual(result["reference_answers"],[])
        self.assertEqual(result["verified_for_exact_offer"],0)
        self.assertEqual(len(seen),1)
        self.assertTrue(seen[0].endswith("/robots.txt"))

    def test_generic_exact_brand_model_discovery_from_homepage_link(self):
        home="https://foomaker.com/"
        url="https://foomaker.com/products/foomaker-a123-phone"
        page=product_page("Foomaker A123 Phone","a123",
                          [("Battery","4000 mAh"),("Screen","6.4 inch")])
        calls=[]
        def fetch(u,*args,**kw):
            calls.append(u)
            if u.endswith("/robots.txt"):return ROBOTS
            if u==home:
                return (b'<html><head><title>Foomaker official home</title></head>'
                        b'<body><h1>Foomaker</h1><a href="/products/foomaker-a123-phone">'
                        b'A123</a></body></html>')
            if u==url:return page
            self.fail("Unexpected URL: "+u)
        r=execute_generic_sources({"title":"Smartphone Foomaker A123",
            "id":"offer-0"},"SMARTPHONE",fetch=fetch)
        self.assertEqual(r["sources_checked"],1)
        self.assertTrue(any(x["source_kind"]==
            "BRAND_SITE_DECLARATIONS_NOT_INDEPENDENT_TESTS"
            for x in r["reference_answers"]))
        self.assertEqual([u for u in calls if u==url],[url])

    def test_indexed_search_hits_only_for_exact_brand_model(self):
        record={"item":{"title":"Foomaker A123 Phone","merchant_url":"https://example.org/a123"},
         "report":{"indexed_shopping":{"indexed_offers":[],
                   "search_result_groups":[]},
           "source_discovery":{"web_hits":[
               {"title":"Foomaker A123 smartphone datasheet",
                "url":"https://www.example.org/foo/a123",
                "source_kind":"UNVERIFIED_SEARCH_RESULT_NOT_A_PRICE_OFFER"},
               {"title":"Foomaker A125 smartphone",
                "url":"https://www.example.org/foo/a125",
                "source_kind":"UNVERIFIED_SEARCH_RESULT_NOT_A_PRICE_OFFER"},
               {"title":"Unrelated ABC123 smartphone",
                "url":"https://www.example.org/foo/abc123",
                "source_kind":"UNVERIFIED_SEARCH_RESULT_NOT_A_PRICE_OFFER"},
               {"title":"Foomaker A123 scam data",
                "url":"https://private.example.org/foo/a123",
                "source_kind":"UNTRUSTED_PROVENANCE"},
           ]}}}
        summaries=offer_summaries(record,"SMARTPHONE")
        found=summaries[0]["discovered_source_urls"]
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]["url"],"https://www.example.org/foo/a123")
        urls=[x["url"] for x in candidate_urls(summaries[0])]
        self.assertIn("https://www.example.org/foo/a123",urls)

    def test_graph_counts_general_declarations_not_independent_laboratory_tests(self):
        name="Foomaker A123 Smartphone"
        raw=product_page(name,"a123",[("Battery","4000mAh"),("Screen","OLED")])
        offer={"id":"offer-0","title":name}
        r=execute_generic_sources({**offer,
            "url":"https://example.org/a123"},"SMARTPHONE",
            fetch=lambda u,*a,**k: ROBOTS if u.endswith("/robots.txt") else raw,
            enable_brand_discovery=False)
        record={"state":"READY","item":{"title":name,"merchant_url":
             "https://example.org/a123"},
            "report":{"indexed_shopping":{"indexed_offers":[],
                                         "search_result_groups":[]}},
            "evidence_offers":{"offer-0":r}}
        graph=build_offer_knowledge_graph(build_decision_projection(record))
        self.assertGreater(graph["stats"]["documented_product_declarations"],0)
        self.assertEqual(graph["stats"]["independent_reference_measurements"],0)
        self.assertEqual(graph["stats"]["verified_exact_sku_answers"],0)
        self.assertTrue(any(x["type"]=="source_declaration" for x in graph["nodes"]))
        self.assertTrue(any(x["type"]=="fetched_source" for x in graph["nodes"]))

if __name__=="__main__":
    unittest.main()
