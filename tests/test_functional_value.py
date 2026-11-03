"""Regression: don't discard cheaper compressor leads when source title has no PSI."""
import unittest

from functional_value import functional_leads
from purchase_insights import build_purchase_insights


def fixture():
    title = "Kompresor wysokociśnieniowy 18V ONE+"
    return {
        "title": title, "category": "COMPRESSOR",
        "selected_source_intake": {
            "sku": "R18PI-0",
            "price_status": "SELLER_DECLARED"},
        "selected_item": {"title": title, "price": "239.99", "currency": "PLN"},
        "offers": [
            {"id": "offer-0", "title": title, "indexed_price": "239.99",
             "currency": "PLN"},
            {"id": "offer-1", "title":
             "Kompresor wysokociśnieniowy 18V One+ Ryobi RPI18-0",
             "indexed_price": "197.90", "currency": "PLN",
             "url": "https://allegro.pl/oferta/rpi18"},
            {"id": "offer-2", "title": "Kompresor Ryobi R18PI-0",
             "indexed_price": "131.99", "currency": "PLN", "url": None},
            {"id": "offer-3", "title": "Kompresor Ryobi R18PI-120GJ",
             "indexed_price": "427.33", "currency": "PLN"},
            {"id": "offer-4", "title": "Kompresor wysokociśnieniowy 12V",
             "indexed_price": "90", "currency": "PLN"},
            {"id": "offer-5", "title": "Kompresor ryobi 18V R18AC-0",
             "indexed_price": "100", "currency": "PLN"},
            {"id": "offer-6", "title":
             "Kompresor wysokociśnieniowy 18V One+ Ryobi RPI18-0",
             "indexed_price": "197.90", "currency": "PLN"},
            {"id": "offer-7", "title":
             "Kompresor wysokociśnieniowy 18V Ryobi",
             "indexed_price": "195.00", "currency": "EUR"},
        ],
    }


class FunctionalValueTests(unittest.TestCase):
    def test_realistic_ryobi_has_direct_197_90_and_same_model_index_leads(self):
        result = build_purchase_insights(fixture())
        self.assertEqual(result["status"],
                         "FUNCTIONAL_INDEX_LEADS_NEED_SPEC_VERIFICATION")
        self.assertEqual(result["selected_price"], "239.99 PLN")
        self.assertEqual(result["options"][0]["offer_id"], "offer-1")
        self.assertEqual(result["options"][0]["price"], "197.90")
        self.assertEqual(result["options"][0]["tier"],
                         "FUNCTIONAL_TITLE_LEAD_NEEDS_SPEC_CHECK")
        self.assertEqual(result["options"][1]["offer_id"], "offer-2")
        self.assertEqual(result["options"][1]["tier"],
                         "SAME_MODEL_CODE_INDEX_LEAD")
        self.assertTrue(all(not row["checkout_verified"] and
                            not row["identity_verified"]
                            for row in result["options"]))
        self.assertIn("requiring", result["headline"].lower())

    def test_non_matching_voltages_and_model_revisions_not_promoted(self):
        options = functional_leads(fixture(), selected_currency="PLN")
        ids = {row["offer_id"] for row in options}
        self.assertNotIn("offer-3", ids)
        self.assertNotIn("offer-4", ids)
        self.assertNotIn("offer-5", ids)
        self.assertNotIn("offer-7", ids)
        self.assertEqual(len([r for r in options if r["offer_id"]=="offer-1"]),1)

    def test_no_price_baseline_still_offers_uncertain_candidates(self):
        projection = fixture()
        projection["selected_item"]["price"] = None
        projection["selected_source_intake"]["price_status"] = "UNAVAILABLE"
        output = build_purchase_insights(projection)
        self.assertEqual(output["status"],
                         "FUNCTIONAL_INDEX_LEADS_NEED_SPEC_VERIFICATION")
        self.assertIsNone(output["selected_price"])
        self.assertIn("not independently established", output["headline"])

    def test_wrong_category_and_mass_only_not_compared(self):
        projection = fixture()
        projection["offers"].append({
            "id": "offer-8", "title": "Akumulator Ryobi 18V",
            "indexed_price": "49.99", "currency": "PLN"})
        self.assertNotIn("offer-8",
                         {r["offer_id"] for r in functional_leads(projection)})

    def test_no_plain_category_word_is_sufficient(self):
        projection = fixture()
        projection["selected_source_intake"]["sku"] = None
        projection["offers"] = projection["offers"][:1] + [
            {"id": "offer-x", "title": "Kompresor Ryobi 18V",
             "indexed_price": "50.00", "currency": "PLN"}]
        self.assertEqual(functional_leads(projection), [])


if __name__ == "__main__":
    unittest.main()
