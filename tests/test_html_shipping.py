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

class ScopeTests(unittest.TestCase):
    def test_wrapper_divs_preserve_semantic_scope(self):
        html = MICRO.replace('<div itemprop="offers"', '<section><div itemprop="offers"').replace('</div></div></div>', '</div></div></section></div>')
        self.assertEqual(html_shipping_claims(html).get('DE', {}).get('shipping_cost'), '5.50')

    def test_multiple_product_offers_fail_closed(self):
        self.assertEqual(html_shipping_claims(MICRO + MICRO), {})

    def test_multiple_offers_fail_closed(self):
        start = MICRO.index('<div itemprop="offers"')
        offer = MICRO[start:-6]
        self.assertEqual(html_shipping_claims(MICRO[:-6] + offer + '</div>'), {})

    def test_unrelated_scope_not_a_shipping_claim(self):
        html = '<div itemscope itemtype="https://schema.org/Product"><meta itemprop="name" content="Widget"><div itemscope itemtype="https://schema.org/Offer" itemprop="offers"><div itemscope itemtype="https://schema.org/OfferShippingDetails" itemprop="shippingDetails"><div itemscope itemtype="https://schema.org/DefinedRegion" itemprop="shippingDestination"><meta itemprop="currency" content="EUR"></div></div></div></div>'
        self.assertEqual(html_shipping_claims(html), {})
