#!/usr/bin/env python3
"""CLI: extract from local snapshot OR explicitly fetch a public HTTPS product.

Offline: python3 scripts_extract_snapshot.py --url https://shop.example.org/p/1
         --input /tmp/product.html --content-type text/html
Network: python3 scripts_extract_snapshot.py --url https://shop.example.org/p/1
         --fetch
The network form enforces robots.txt, public pinned HTTPS and redirect bounds.
"""
import argparse
import json
from pathlib import Path
import sys

from universal_product_extract import MAX_PAGE_BYTES, METHODS, extract_snapshot
from universal_source_acquisition import acquire_public_product


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Original HTTPS source URL")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="Previously saved local snapshot")
    source.add_argument("--fetch", action="store_true", help="Explicit, policy-checked network fetch")
    parser.add_argument("--content-type", default="text/html")
    parser.add_argument("--method", choices=sorted(METHODS), default="STATIC_HTML")
    parser.add_argument("--http-status", type=int, default=200)
    parser.add_argument("--enable-render", action="store_true",
                        help="Opt-in isolated Chromium fallback after approved HTTP 200")
    args = parser.parse_args(argv)
    if args.enable_render and not args.fetch:
        parser.error("--enable-render requires --fetch")
    if args.fetch:
        if args.method != "STATIC_HTML" or args.content_type != "text/html" or args.http_status != 200:
            parser.error("--fetch sets its own method/content type/HTTP status")
        result = acquire_public_product(args.url, enable_render=args.enable_render)
    else:
        if not args.input.is_file() or args.input.stat().st_size > MAX_PAGE_BYTES:
            parser.error("Input snapshot missing or too large")
        try:
            result = extract_snapshot(args.url, args.input.read_bytes(),
                                      content_type=args.content_type,
                                      acquisition_method=args.method,
                                      http_status=args.http_status)
        except ValueError as exc:
            parser.error(str(exc))
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
