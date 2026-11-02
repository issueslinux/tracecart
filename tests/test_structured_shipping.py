import unittest
from structured_shipping import shipping_claim
from product_intake import extract_from_html


class StructuredShippingTests(unittest.TestCase):
    def test_explicit_destination_rate(self):
        offer = {"shippingDetails": {"shippingDestination": {"addressCountry": "PL"},
                 "shippingRate": {"value": "17.99", "currency": "PLN"}}}
        claim = shipping_claim(offer)
        self.assertEqual(claim["shipping_cost"], "17.99")
        self.assertEqual(claim["destination_country"], "PL")
        self.assertEqual(claim["status"], "SELLER_DECLARED_DESTINATION_CONDITIONAL")

    def test_missing_destination_not_free(self):
        self.assertIsNone(shipping_claim({"shippingDetails": {
            "shippingRate": {"value": "0", "currency": "PLN"}}})["shipping_cost"])

    def test_multiple_methods_ambiguous(self):
        detail = {"shippingDestination": {"addressCountry": "PL"},
                  "shippingRate": {"value": "20", "currency": "PLN"}}
        self.assertEqual(shipping_claim({"shippingDetails": [detail, detail]})["status"], "UNKNOWN")

    def test_negative_rate_rejected(self):
        detail = {"shippingDestination": {"addressCountry": "PL"},
                  "shippingRate": {"value": "-1", "currency": "PLN"}}
        self.assertIsNone(shipping_claim({"shippingDetails": detail})["shipping_cost"])

    def test_integration_product_metadata(self):
        raw = b'<script type="application/ld+json">{"@type":"Product","name":"Example widget","offers":{"@type":"Offer","price":"25","priceCurrency":"PLN","shippingDetails":{"shippingDestination":{"addressCountry":"PL"},"shippingRate":{"value":"9.99","currency":"PLN"}}}}</script>'
        _, metadata = extract_from_html("https://example.org/product", raw)
        self.assertEqual(metadata["structured_shipping_claim"]["shipping_cost"], "9.99")


if __name__ == "__main__":
    unittest.main()
