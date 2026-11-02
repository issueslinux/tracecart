"""Seller evidence critic must never invent reviews or purchase verdicts."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from offer_research_critic import critique_competing_offers
from live_offer_compare import compare_live_offer
from multi_offer_compare import compare_live_offers
from test_live_offer_compare import BASE, SELECTED, SECOND, META


def comparison(price='72.00', **overrides):
    item = {**SECOND, 'price': price}
    m = {**META}
    if 'availability' in overrides:
        m['availability_claim'] = overrides['availability']
    report = compare_live_offer(BASE, SELECTED, SECOND['merchant_url'],
                                extractor=lambda _: (item, m))
    return report['live_competitor_comparison']


class OfferResearchCriticTests(unittest.TestCase):
    def test_proven_lower_listing_price_is_only_research_lead(self):
        case = comparison()
        review = critique_competing_offers([case])
        self.assertEqual(review['lower_listed_price_leads'], 1)
        row = review['assessments'][0]
        self.assertEqual(row['listed_price_advantage'], '8.00')
        self.assertEqual(row['currency'], 'PLN')
        self.assertEqual(row['finding'], 'LOWER_SELLER_LISTED_PRICE_ONLY')
        self.assertEqual(row['source_page_sha256'], 'b'*64)
        self.assertEqual(row['research_selection'], 'OPEN')
        self.assertEqual(row['independent_product_tests_collected'], 0)
        self.assertFalse(review['payment_authorized'])
        self.assertNotIn('recommendation', str(review).lower().replace('not_purchase_recommendation', ''))

    def test_out_of_stock_and_unknown_gtin_are_blockers_not_savings(self):
        out = comparison(availability='https://schema.org/OutOfStock')
        missing = deepcopy(comparison())
        missing['status'] = 'GTIN_IDENTITY_NOT_ESTABLISHED'
        missing['alternative_requested_url'] = 'https://third.example.net/p/other'
        result = critique_competing_offers([out, missing], research_budget=1)
        self.assertEqual(result['lower_listed_price_leads'], 0)
        self.assertEqual(result['prioritized_questions'][0]['finding'], 'IDENTITY_UNPROVEN')
        self.assertEqual(result['prioritized_questions'][1]['selection'], 'DEFERRED_RESEARCH_BUDGET')
        self.assertEqual(len(result['assessments']), 2)
        self.assertEqual(result['assessments'][0]['listed_price_advantage'], None)

    def test_higher_listed_price_not_mislabeled_savings(self):
        result = critique_competing_offers([comparison(price='88.00')])
        self.assertEqual(result['lower_listed_price_leads'], 0)
        self.assertEqual(result['assessments'][0]['finding'], 'NO_LOWER_SELLER_LISTED_PRICE')

    def test_without_source_provenance_refuse_price_lead(self):
        case = deepcopy(comparison())
        case['alternative_source']['page_sha256'] = None
        with self.assertRaisesRegex(ValueError, 'source evidence'):
            critique_competing_offers([case])

    def test_duplicate_candidates_budget_and_input_validation(self):
        case = comparison()
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            critique_competing_offers([case, case])
        for budget in (-1, 5, True):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                critique_competing_offers([case], research_budget=budget)
        with self.assertRaises(ValueError):
            critique_competing_offers([])

    def test_full_tree_integration_and_immutability(self):
        base = deepcopy(BASE)
        urls = ['https://third.example.net/p/persil',
                'https://fourth.example.net/p/persil']
        def extractor(url):
            return ({**SECOND, 'merchant_url': url, 'price':
                     '72.00' if 'third' in url else '89.00'},
                    {**META, 'source_url': url})
        report = compare_live_offers(base, SELECTED, urls, extractor=extractor)
        review = report['multi_offer_research_critic']
        self.assertEqual(review['lower_listed_price_leads'], 1)
        self.assertEqual(review['candidate_count'], 2)
        self.assertEqual(review['open_question_count'], 2)
        children = report['root']['children']
        self.assertEqual(children[-2]['kind'], 'critic')
        self.assertEqual(len(children[-2]['children']), 2)
        self.assertEqual(children[-1]['kind'], 'conditional_summary')
        self.assertEqual(report['multi_offer_summary']['lower_listed_price_research_leads'], 1)
        self.assertNotIn('multi_offer_research_critic', base)
        self.assertFalse(review['payment_authorized'])
        self.assertNotEqual(report['sha256'], 'old')


if __name__ == '__main__':
    unittest.main()

class ResearchCriticHTMLTests(unittest.TestCase):
    def test_single_merchant_critic_display_escapes_source_urls(self):
        from app import research_critic_panel
        report = compare_live_offer(BASE, SELECTED, SECOND['merchant_url'],
                                    extractor=lambda url: (SECOND, META))
        html = research_critic_panel(report)
        self.assertIn('LOWER_SELLER_LISTED_PRICE_ONLY', html)
        self.assertIn('independent product tests', html)
        self.assertIn('RESEARCH CRITIC', html)
        self.assertIn('noopener noreferrer', html)
        evil = deepcopy(report)
        evil['single_offer_research_critic']['prioritized_questions'][0]['question'] = '<script>oops</script>'
        escaped = research_critic_panel(evil)
        self.assertIn('&lt;script&gt;', escaped)
        self.assertNotIn('<script>', escaped)
