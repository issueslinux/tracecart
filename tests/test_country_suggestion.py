import unittest
from country_suggestion import suggested_country


class CountrySuggestionTests(unittest.TestCase):
    def test_region_from_browser_preferences(self):
        self.assertEqual(suggested_country('pl-PL,pl;q=0.9,en-US;q=0.7'), 'PL')

    def test_no_country_from_language_only(self):
        self.assertIsNone(suggested_country('pl,en;q=0.8'))

    def test_no_country_from_malformed_region(self):
        self.assertIsNone(suggested_country('en-US-foo'))

    def test_first_explicit_region_wins(self):
        self.assertEqual(suggested_country('fr;q=1,en-GB;q=0.8,en-US;q=0.6'), 'GB')


if __name__ == '__main__':
    unittest.main()
