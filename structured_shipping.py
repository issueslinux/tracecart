"""Conservative, language-independent schema.org shipping-rate evidence.

A unique rate/currency for exactly one destination country is required.
Multiple shipping methods or countries are preserved as UNKNOWN rather than
silently choosing the cheapest option. No checkout price is inferred.
"""
from decimal import Decimal, InvalidOperation


def _country(value):
    if isinstance(value, str):
        return value.upper() if len(value) == 2 and value.isascii() and value.isalpha() else None
    if isinstance(value, dict):
        return _country(value.get('addressCountry')) or _country(value.get('name'))
    return None


def _countries(value):
    if isinstance(value, list):
        countries = [_country(item) for item in value]
        return countries if countries and all(countries) and len(set(countries)) == len(countries) else None
    country = _country(value)
    return [country] if country else None


def _rate(detail):
    rate = detail.get('shippingRate')
    if not isinstance(rate, dict) or rate.get('minValue') is not None or rate.get('maxValue') is not None:
        return None
    try:
        amount = Decimal(str(rate.get('value')))
    except (InvalidOperation, TypeError, ValueError):
        return None
    currency = rate.get('currency')
    if (currency not in ('PLN', 'EUR', 'USD') or not amount.is_finite() or
            amount < 0 or amount > 100000 or amount.as_tuple().exponent < -2):
        return None
    return str(amount.quantize(Decimal('0.01'))), currency


def shipping_claim(offer):
    unknown = {'status': 'UNKNOWN', 'shipping_cost': None,
               'currency': None, 'destination_country': None,
               'shipping_method': None, 'source_field': None}
    if not isinstance(offer, dict):
        return unknown
    details = offer.get('shippingDetails')
    if isinstance(details, dict):
        details = [details]
    if not isinstance(details, list) or not details or len(details) > 20:
        return unknown
    entries = []
    for detail in details:
        if not isinstance(detail, dict):
            return unknown
        dest = detail.get('shippingDestination')
        if not isinstance(dest, dict):
            return unknown
        countries = _countries(dest.get('addressCountry'))
        rate = _rate(detail)
        if not countries or rate is None:
            return unknown
        entries.extend((country, rate[0], rate[1]) for country in countries)
    # Existing single-country contract cannot express a destination-dependent
    # rate map. Do not silently pick one of multiple destinations/methods.
    if len(entries) != 1:
        return unknown
    country, amount, currency = entries[0]
    return {'status': 'SELLER_DECLARED_DESTINATION_CONDITIONAL',
            'shipping_cost': amount, 'currency': currency,
            'destination_country': country, 'shipping_method': None,
            'source_field': 'offers.shippingDetails.shippingRate.value'}


def shipping_claims(offer):
    """All unambiguous destination-specific seller rates, without picking a country.

    Conflicting methods for any country invalidate that country's rate.
    Other countries remain independently usable.
    """
    if not isinstance(offer, dict):
        return {}
    details = offer.get('shippingDetails')
    if isinstance(details, dict):
        details = [details]
    if not isinstance(details, list) or not (1 <= len(details) <= 20):
        return {}
    rates, conflicted = {}, set()
    for detail in details:
        if not isinstance(detail, dict):
            return {}
        destination = detail.get('shippingDestination')
        countries = _countries(destination.get('addressCountry')) if isinstance(destination, dict) else None
        rate = _rate(detail)
        if not countries or rate is None:
            return {}
        for country in countries:
            if country in rates:
                conflicted.add(country)
            else:
                rates[country] = {'status': 'SELLER_DECLARED_DESTINATION_CONDITIONAL',
                                  'shipping_cost': rate[0], 'currency': rate[1],
                                  'destination_country': country, 'shipping_method': None,
                                  'source_field': 'offers.shippingDetails.shippingRate.value'}
    return {country: claim for country, claim in rates.items() if country not in conflicted}
