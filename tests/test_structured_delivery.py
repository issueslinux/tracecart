import unittest
from structured_delivery import delivery_window_claim
from product_intake import extract_from_html


def days(lo, hi):
    return {"minValue": lo, "maxValue": hi, "unitCode": "DAY"}


def offer(handling=None, transit=None):
    return {"shippingDetails": {"deliveryTime": {"handlingTime": handling,
                                                     "transitTime": transit}}}


class StructuredDeliveryTests(unittest.TestCase):
    def test_combines_handling_and_transit(self):
        r = delivery_window_claim(offer(days(1, 2), days(2, 4)))
        self.assertEqual((r["min_days"], r["max_days"]), (3, 6))
        self.assertEqual(r["status"], "SELLER_DECLARED_HANDLING_PLUS_TRANSIT_DAYS")

    def test_transit_only_not_end_to_end(self):
        r = delivery_window_claim(offer(transit=days(2, 3)))
        self.assertEqual(r["status"], "TRANSIT_ONLY_NOT_END_TO_END")
        self.assertIsNone(r["min_days"])

    def test_invalid_units_rejected(self):
        r = delivery_window_claim(offer(days(1, 2), {"minValue": 1, "maxValue": 3, "unitCode": "HUR"}))
        self.assertEqual(r["status"], "UNKNOWN")

    def test_multiple_methods_ambiguous(self):
        details = offer(days(1, 2), days(2, 3))["shippingDetails"]
        self.assertEqual(delivery_window_claim({"shippingDetails": [details, details]})["status"], "UNKNOWN")

    def test_product_metadata_integration(self):
        raw = b'<script type="application/ld+json">{"@type":"Product","name":"Widget","offers":{"@type":"Offer","price":"10","priceCurrency":"PLN","shippingDetails":{"deliveryTime":{"handlingTime":{"minValue":1,"maxValue":1,"unitCode":"DAY"},"transitTime":{"minValue":2,"maxValue":4,"unitCode":"DAY"}}}}}</script>'
        _, meta = extract_from_html('https://example.org/widget', raw)
        self.assertEqual(meta["structured_delivery_window_claim"]["max_days"], 5)


if __name__ == '__main__':
    unittest.main()
