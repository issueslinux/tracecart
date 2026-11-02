"""Explicit opt-in live coverage probe. No unattended crawling or bypasses."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from product_intake import extract_product_page, validate_product_url


def probe(urls, extractor=extract_product_page):
    rows = []
    for url in urls:
        safe = validate_product_url(url)
        row = {'url': safe, 'status': 'UNKNOWN', 'product': False,
               'price': False, 'shipping': False, 'delivery': False}
        try:
            item, meta = extractor(safe)
            row.update(status='FETCHED', product=bool(item.get('title')),
                       price=item.get('price') is not None,
                       shipping=bool(meta.get('structured_shipping_claims_by_country')),
                       delivery=bool(meta.get('structured_delivery_windows_by_country')),
                       page_sha256=meta.get('page_sha256'),
                       retrieved_at=meta.get('retrieved_at'))
        except Exception as exc:
            # No arbitrary exception text: it may contain remote content.
            row['status'] = 'UNAVAILABLE_' + type(exc).__name__
        if row['status'] == 'FETCHED':
            row['shipping_diagnosis'] = ('EXTRACTED' if row['shipping'] else
                'UNDETERMINED_ABSENT_OR_UNRECOGNIZED')
            row['delivery_diagnosis'] = ('EXTRACTED' if row['delivery'] else
                'UNDETERMINED_ABSENT_OR_UNRECOGNIZED')
        else:
            row['shipping_diagnosis'] = 'NOT_ASSESSED_PAGE_UNAVAILABLE'
            row['delivery_diagnosis'] = 'NOT_ASSESSED_PAGE_UNAVAILABLE'
        rows.append(row)
    return {'dataset': 'LIVE_URLS_ROBOTS_RESPECTED',
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'total': len(rows),
            'fetched': sum(r['status'] == 'FETCHED' for r in rows),
            'counts': {k: sum(r[k] for r in rows) for k in ('product','price','shipping','delivery')},
            'diagnostics': {field: {status: sum(r[field] == status for r in rows)
                for status in sorted({r[field] for r in rows})}
                for field in ('shipping_diagnosis', 'delivery_diagnosis')},
            'cases': rows}


def main():
    parser = argparse.ArgumentParser(description='Opt-in live product coverage measurement')
    parser.add_argument('--urls', required=True, help='JSON array of public HTTPS product URLs')
    parser.add_argument('--output', required=True, help='Output JSON report path')
    parser.add_argument('--max-urls', type=int, default=10)
    args = parser.parse_args()
    urls = json.loads(Path(args.urls).read_text(encoding='utf-8'))
    if (not isinstance(urls, list) or not 1 <= len(urls) <= min(args.max_urls, 20)
            or any(not isinstance(url, str) for url in urls)):
        parser.error('Expected 1-20 product URLs within the explicit limit')
    report = probe(urls)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'total': report['total'], 'fetched': report['fetched'], 'counts': report['counts']}))


if __name__ == '__main__':
    main()
