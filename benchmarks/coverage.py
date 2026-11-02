"""Reproducible offline coverage benchmark; fixtures are synthetic, not live stores.

No network access, robots bypass, or claims about real merchant coverage.
"""
import json
from pathlib import Path
from product_intake import extract_from_html


def evaluate(cases):
    rows = []
    for case in cases:
        raw = case['html'].encode('utf-8')
        try:
            item, meta = extract_from_html(case['url'], raw)
            rows.append({'case': case['id'], 'locale': case['locale'],
                         'product': bool(item.get('title')),
                         'price': item.get('price') is not None,
                         'shipping': bool(meta.get('structured_shipping_claims_by_country')),
                         'delivery': bool(meta.get('structured_delivery_windows_by_country')),
                         'error': None})
        except ValueError as exc:
            rows.append({'case': case['id'], 'locale': case['locale'],
                         'product': False, 'price': False, 'shipping': False,
                         'delivery': False, 'error': type(exc).__name__})
    totals = {field: sum(bool(row[field]) for row in rows)
              for field in ('product', 'price', 'shipping', 'delivery')}
    return {'dataset': 'SYNTHETIC_OFFLINE_FIXTURES_NOT_REAL_STORE_COVERAGE',
            'total': len(rows), 'counts': totals, 'cases': rows}


def main():
    source = Path(__file__).with_name('coverage_cases.json')
    print(json.dumps(evaluate(json.loads(source.read_text(encoding='utf-8'))),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
