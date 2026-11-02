import unittest
from html_shipping import html_shipping_claims
from product_intake import extract_from_html

MICRO = '''<div itemscope itemtype="https://schema.org/Product"><span itemprop="name">International Widget</span><div itemprop="offers" itemscope itemtype="https://schema.org/Offer"><div itemprop="shippingDetails" itemscope itemtype="https://schema.org/OfferShippingDetails"><div itemprop="shippingDestination" itemscope itemtype="https://schema.org/DefinedRegion"><meta itemprop="addressCountry" content="DE"></div><div itemprop="shippingRate" itemscope itemtype="https://schema.org/MonetaryAmount"><meta itemprop="value" content="5.50"><meta itemprop="currency" content="EUR"></div></div></div></div>'''

class HTMLShippingTests(unittest.TestCase):
    def test_semantic_microdata(self):
        self.assertEqual(html_shipping_claims(MICRO)['DE']['shipping_cost'], '5.50')
    def test_unscoped_not_used(self):
        self.assertEqual(html_shipping_claims('<meta itemprop="value" content="0">'), {})
    def test_intake(self):
        _, meta = extract_from_html('https://example.org/item', ('<title>International Widget</title>' + MICRO).encode())
        self.assertEqual(meta['structured_shipping_claims_by_country']['DE']['shipping_cost'], '5.50')
    def test_conflict_blocks_country(self):
        jsonld = '<script type="application/ld+json">{"@type":"Product","name":"International Widget","offers":{"@type":"Offer","shippingDetails":{"shippingDestination":{"addressCountry":"DE"},"shippingRate":{"value":"9","currency":"EUR"}}}}</script>'
        _, meta = extract_from_html('https://example.org/item', (MICRO + jsonld).encode())
        self.assertNotIn('DE', meta['structured_shipping_claims_by_country'])
