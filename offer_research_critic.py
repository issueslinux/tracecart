"""Adversarial, evidence-only research triage for real competing offers.

Operates exclusively on the existing safe seller-page comparisons. It never
fetches sources, creates claims or selects a checkout winner. Questions target
external evidence, not the buyer. Unknown is never treated as negative proof.
"""
from decimal import Decimal


# The research task must address the gate that actually failed. This is not
# a merchant-specific scraper, price recommendation, or buyer questionnaire.
GAPS = {
    'SECOND_PAGE_NOT_RETRIEVED': (
        'SOURCE_UNAVAILABLE', 'Find an independently accessible, permitted primary listing for this exact offer.', 4),
    'SELECTED_PAGE_NOT_RETRIEVED': (
        'BASE_SOURCE_UNVERIFIED', 'Can the originally selected offer be verified from a current primary seller page?', 1),
    'SELECTED_PAGE_IDENTITY_CONFLICT': (
        'BASE_IDENTITY_CONFLICT', 'Which exact model and GTIN does the original seller actually offer?', 1),
    'SECOND_PAGE_IDENTITY_CONFLICT': (
        'CANDIDATE_IDENTITY_CONFLICT', 'Do the candidate page title, product schema and GTIN describe the same SKU?', 1),
    'INVALID_GTIN_CLAIM': (
        'INVALID_PRODUCT_IDENTIFIER', 'Can primary manufacturer documentation confirm the correct valid GTIN?', 2),
    'GTIN_IDENTITY_NOT_ESTABLISHED': (
        'IDENTITY_UNPROVEN', 'Is the same product GTIN explicitly documented by both sellers or its manufacturer?', 2),
    'DIFFERENT_GTIN_NOT_EQUIVALENT': (
        'IDENTITY_DIFFERENT', 'Do reliable product specifications establish whether these differently coded products serve equivalent needs?', 5),
    'CONFLICTING_WASH_COUNT': (
        'PACK_COUNT_CONFLICT', 'Which pack size and dose count apply to the exact current product formulation?', 1),
    'CONFLICTING_VARIANT_CLAIMS': (
        'VARIANT_CONFLICT', 'Which current manufacturer specifications resolve the conflicting product variant claims?', 1),
    'AMBIGUOUS_TITLE_VARIANT': (
        'VARIANT_AMBIGUOUS', 'Which primary SKU information resolves the ambiguous seller title?', 2),
    'SELECTED_OFFER_NOT_AVAILABLE': (
        'BASE_NOT_AVAILABLE', 'Does any current seller offer the exact selected product in stock?', 3),
    'SECOND_OFFER_NOT_AVAILABLE': (
        'CANDIDATE_NOT_AVAILABLE', 'Does the candidate seller currently offer this exact product for purchase?', 3),
    'SELECTED_STOCK_NOT_CONFIRMED': (
        'BASE_STOCK_UNKNOWN', 'Can the selected seller provide current product-level availability evidence?', 3),
    'SECOND_STOCK_NOT_CONFIRMED': (
        'CANDIDATE_STOCK_UNKNOWN', 'Can the candidate seller provide current product-level availability evidence?', 3),
    'LISTED_PRICE_MISSING': (
        'PRICE_UNVERIFIED', 'Can current, SKU-specific seller pricing be independently retrieved and checked?', 3),
    'DIFFERENT_CURRENCY_NO_FX': (
        'CURRENCY_INCOMPATIBLE', 'Is there an authorized, current source for prices in a common currency?', 4),
    'SAME_STORE_NOT_COMPETITOR': (
        'SOURCE_NOT_INDEPENDENT', 'Can a separate retailer publish an independent offer for the same product?', 5),
}


def critique_competing_offers(comparisons, research_budget=3):
    """Prioritize verifiable follow-ups, preserve every rejected/deferred lead.

    An accepted seller-listed comparison is ONLY a pricing lead. Every status
    is retained. No claim of seller reliability, product quality or savings at
    checkout is derived from the difference between listed prices.
    """
    if type(comparisons) is not list or not 1 <= len(comparisons) <= 4:
        raise ValueError('Expected one to four comparison records')
    if type(research_budget) is not int or not 0 <= research_budget <= 4:
        raise ValueError('Research budget must be integer 0..4')
    assessments = []
    seen = set()
    for index, comparison in enumerate(comparisons):
        if not isinstance(comparison, dict):
            raise ValueError('Comparison must be an object')
        url = comparison['alternative_requested_url']
        if url in seen:
            raise ValueError('Duplicate research candidate')
        seen.add(url)
        status = comparison['status']
        source = comparison.get('alternative_source') or {}
        record = {
            'candidate_index': index + 1,
            'url': url,
            'comparison_status': status,
            'source_retrieved_at': source.get('retrieved_at'),
            'source_page_sha256': source.get('page_sha256'),
            'source_scope': 'SELLER_DECLARATION_NOT_INDEPENDENT_PRODUCT_TEST',
            'listed_price_advantage': None,
            'currency': None,
            'independent_product_tests_collected': 0,
            'payment_authorized': False,
        }
        if status == 'SAME_GTIN_SELLER_LISTED_PRICE_COMPARISON':
            original = comparison['selected']
            candidate = comparison['alternative']
            # Fail closed if a future caller bypasses the existing comparison
            # gates. Never promote an unproven arithmetic difference to a lead.
            if (not isinstance(original, dict) or not isinstance(candidate, dict)
                    or not source.get('page_sha256') or not source.get('retrieved_at')
                    or not (comparison.get('selected_source') or {}).get('page_sha256')
                    or original.get('currency') != candidate.get('currency')
                    or original.get('price') is None or candidate.get('price') is None):
                raise ValueError('Qualified price lead lacks source evidence')
            base = Decimal(original['price'])
            other = Decimal(candidate['price'])
            if not base.is_finite() or not other.is_finite() or base < 0 or other < 0:
                raise ValueError('Non-finite or invalid offer price')
            difference = (base - other).quantize(Decimal('0.01'))
            record['currency'] = original['currency']
            if difference > 0:
                record.update({
                    'finding': 'LOWER_SELLER_LISTED_PRICE_ONLY',
                    'listed_price_advantage': str(difference),
                    'research_question': (
                        'Do independent product tests, condition evidence and seller policies support '
                        'considering this lower-listed-price equivalent offer?'),
                    'priority': 0,
                })
            else:
                record.update({
                    'finding': 'NO_LOWER_SELLER_LISTED_PRICE',
                    'research_question': (
                        'Are there independent product tests showing a relevant benefit '
                        'for this comparably identified offer?'),
                    'priority': 5,
                })
        else:
            finding, question, priority = GAPS.get(status, (
                'UNRECOGNIZED_COMPARISON_STATUS',
                'Which primary seller or manufacturer evidence would resolve this comparison?', 4))
            record.update({'finding': finding, 'research_question': question,
                           'priority': priority})
        assessments.append(record)
    ordered = sorted(assessments, key=lambda a: (a['priority'], a['candidate_index']))
    for rank, record in enumerate(ordered):
        record['research_selection'] = ('OPEN' if rank < research_budget
                                        else 'DEFERRED_RESEARCH_BUDGET')
    return {
        'status': 'RESEARCH_GAPS_NOT_PURCHASE_RECOMMENDATION',
        'method': 'DETERMINISTIC_EVIDENCE_CRITIC_NO_AI_SOURCE_FABRICATION',
        'research_budget': research_budget,
        'candidate_count': len(assessments),
        'open_question_count': min(research_budget, len(assessments)),
        'lower_listed_price_leads': sum(
            row['finding'] == 'LOWER_SELLER_LISTED_PRICE_ONLY' for row in assessments),
        'assessments': assessments,
        'prioritized_questions': [
            {'candidate_index': row['candidate_index'], 'url': row['url'],
             'question': row['research_question'],
             'finding': row['finding'], 'selection': row['research_selection']}
            for row in ordered],
        'limitations': [
            'Evidence is retailer-declared, not independent laboratory testing or verified reviews.',
            'Equal seller-declared GTINs do not independently prove product quality or equivalence.',
            'Seller-listed price differences are research leads, not all-in savings or a winner.',
            'No automatic payment or checkout action.',
        ],
        'payment_authorized': False,
    }


def critic_tree_branch(review):
    """Preserve every researched/deferred lead in the exportable evidence tree."""
    from decision_tree import _node
    children = [
        _node('follow_up', entry['research_question'],
              entry['research_selection'], {
                  'candidate_url': entry['url'],
                  'comparison_status': entry['comparison_status'],
                  'research_finding': entry['finding'],
                  'seller_page_sha256': entry['source_page_sha256'],
                  'source_retrieved_at': entry['source_retrieved_at'],
                  'seller_listed_price_advantage': entry['listed_price_advantage'],
                  'currency': entry['currency'],
                  'independent_product_tests_collected': 0,
                  'no_purchase_authorization': True,
              }, node_id='offer-research-question-{}'.format(entry['candidate_index']))
        for entry in review['assessments']
    ]
    return _node(
        'critic', 'Cross-retailer research critic: next evidence to verify',
        'OPEN_RESEARCH_GAPS', {
            'method': review['method'],
            'lower_listed_price_leads': review['lower_listed_price_leads'],
            'open_question_count': review['open_question_count'],
            'source_limitations': review['limitations'],
            'payment_authorized': False,
        }, children, node_id='cart-offer-research-critic')
