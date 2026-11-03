#!/usr/bin/env python3
"""Bounded read-only diagnostic of Scrapling's HTTP-only modes on Allegro.

No CAPTCHA solving, authenticated session, new IP/proxy provider or purchase.
One request per explicit variant, no automatic retries on HTTP failures.
Do not store response cookies or bot tokens.
"""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
import sys
import time
from urllib.parse import urlsplit

from scrapling.fetchers import Fetcher, FetcherSession

TARGET = (
    "https://allegro.pl/produkt/kompresor-wysokocisnieniowy-18v-one-"
    "ryobi-rpi18-0-9898857e-3ffe-4ace-93db-2b55ba32bcc9"
    "?offerId=18457369262"
)
REFERENCE = (
    "https://www.mediaexpert.pl/dom-i-ogrod/wyposazenie-warsztatu/"
    "kompresory-samochodowe/kompresor-samochodowy-ryobi-rpi18-0"
)
ROBOTS = "https://allegro.pl/robots.txt"


class MetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self._title = False
        self.structured = []
        self._jsonld = False
        self._buf = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self._title = True
        if tag == "script" and "ld+json" in attrs.get("type", "").lower():
            self._jsonld = True
            self._buf = ""

    def handle_data(self, data):
        if self._title:
            self.title += data[:200]
        if self._jsonld:
            self._buf += data[:100000]

    def handle_endtag(self, tag):
        if tag == "title":
            self._title = False
        if tag == "script" and self._jsonld:
            try:
                self.structured.append(json.loads(self._buf))
            except (ValueError, TypeError):
                pass
            self._jsonld = False


def read_receipt(response, label, seconds):
    body = response.html_content or ""
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    else:
        body = str(body)
    meta = MetaParser()
    meta.feed(body[:3000000])
    headers = response.headers or {}
    # Distinguish genuine product data from CAPTCHA / interstitial HTML.
    block_marker = any(word in body[:3000].lower() for word in (
        "captcha-delivery.com", "datadome", "you have been blocked"))
    has_product = ("application/ld+json" in body.lower() and
                   ("rpi18-0" in body.lower() or "r18pi-0" in body.lower()))
    return {
        "variant": label,
        "status": response.status,
        "elapsed_s": round(seconds, 2),
        "bytes": len(body.encode("utf-8")),
        "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()[:20],
        "title": meta.title.strip()[:100],
        "jsonld_count": len(meta.structured),
        "contains_product_reference": has_product,
        "datadome_cookie_present": "datadome=" in str(headers.get("set-cookie","")).lower(),
        "datadome_cid_header": bool(headers.get("x-datadome-cid")),
        "dd_block_header": headers.get("x-dd-b"),
        "block_marker": block_marker,
        "decision": (
            "PRODUCT_CONTENT" if response.status == 200 and has_product
            else "ACCESS_DENIED" if response.status in (401,403,429) or block_marker
            else "NO_PRODUCT" if response.status == 200 else "OTHER")
    }


def one(label, url, **kwargs):
    start = time.monotonic()
    try:
        resp = Fetcher.get(url, timeout=11, retries=1, **kwargs)
        return read_receipt(resp, label, time.monotonic() - start)
    except Exception as e:
        return {"variant": label, "decision": "ERROR", "elapsed_s": round(time.monotonic()-start, 2),
                "error": type(e).__name__ + ": " + str(e)[:200]}


def retained_session():
    start = time.monotonic()
    try:
        with FetcherSession(impersonate="chrome142", timeout=11, retries=1,
                            stealthy_headers=True) as session:
            warm = session.get(ROBOTS)
            # Same session reuses cookies and transport; browser-backed CAPTCHA cookies
            # cannot be minted by the HTTP client.
            direct = session.get(TARGET)
            out = read_receipt(direct, "chrome142_session_after_robots", time.monotonic()-start)
            out["prior_robots_http_status"] = warm.status
            return out
    except Exception as e:
        return {"variant": "chrome142_session_after_robots", "decision": "ERROR",
                "elapsed_s": round(time.monotonic()-start,2),
                "error": type(e).__name__ + ": " + str(e)[:200]}


def run():
    print(json.dumps({"purpose": "Scrapling HTTP only", "host": "allegro.pl",
                      "target_path": urlsplit(TARGET).path, "method": "GET",
                      "no_paid_proxy": True, "no_captcha_solving": True}), flush=True)
    variants = [
        ("reference_mediaexpert_chrome", REFERENCE, dict(impersonate="chrome142")),
        ("allegro_chrome142", TARGET, dict(impersonate="chrome142")),
        ("allegro_chrome131", TARGET, dict(impersonate="chrome131")),
        ("allegro_firefox133", TARGET, dict(impersonate="firefox133")),
        ("allegro_chrome_android", TARGET, dict(impersonate="chrome131_android")),
    ]
    for label, url, kwargs in variants:
        print(json.dumps(one(label, url, **kwargs), ensure_ascii=False), flush=True)
        time.sleep(1.2)
    print(json.dumps(retained_session(), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    run()
