"""Compare seller-declared delivery windows only for the same destination."""

def compare_delivery_windows(first, second, equivalent, country=None):
    result = dict(status='UNKNOWN', buyer_country=country, selected_window_days=None,
                  alternative_window_days=None, faster_declared_maximum=None,
                  arrival_date_verified=False)
    if not equivalent:
        result['status'] = 'PRODUCT_EQUIVALENCE_NOT_ESTABLISHED'
        return result
    if not isinstance(country, str) or len(country) != 2 or not country.isascii() or not country.isalpha():
        result['status'] = 'BUYER_COUNTRY_REQUIRED'
        return result
    country = country.upper()
    result['buyer_country'] = country
    sources = (first, second)
    for source in sources:
        claim = source.get('structured_shipping_claim') or {}
        if claim.get('status') != 'SELLER_DECLARED_DESTINATION_CONDITIONAL' or claim.get('destination_country') != country:
            result['status'] = 'DESTINATION_NOT_ESTABLISHED_FOR_BOTH'
            return result
    windows = [source.get('structured_delivery_window_claim') or {} for source in sources]
    if any(w.get('status') != 'SELLER_DECLARED_HANDLING_PLUS_TRANSIT_DAYS' for w in windows):
        result['status'] = 'COMPLETE_DELIVERY_WINDOWS_UNKNOWN'
        return result
    a, b = windows
    result.update(status='SELLER_DECLARED_WINDOWS_NOT_GUARANTEED',
                  selected_window_days=[a['min_days'], a['max_days']],
                  alternative_window_days=[b['min_days'], b['max_days']],
                  faster_declared_maximum=('selected' if a['max_days'] < b['max_days'] else
                                           'alternative' if b['max_days'] < a['max_days'] else 'tie'))
    return result
