"""Isolated evidence-only benchmark. No payment, account, proxies or CAPTCHA resolution."""
import argparse
import asyncio
import hashlib
from html.parser import HTMLParser
import json
import os
import sys
import time
import urllib.request

TARGETS = {
    "ryobi_r18pi": "https://pl.ryobitools.eu/elektronarzedzia/kompresory-i-pompy/r18pi/r18pi-0/",
    "ryobi_rpi18": "https://pl.ryobitools.eu/elektronarzedzia/kompresory-i-pompy/rpi18/rpi18-0/",
    "allegro_rpi18": "https://allegro.pl/produkt/kompresor-wysokocisnieniowy-18v-one-ryobi-rpi18-0-9898857e-3ffe-4ace-93db-2b55ba32bcc9?offerId=18457369262",
    "mediaexpert_rpi18": "https://www.mediaexpert.pl/dom-i-ogrod/wyposazenie-warsztatu/kompresory-samochodowe/kompresor-samochodowy-ryobi-rpi18-0",
    "js_control": "https://quotes.toscrape.com/js/",
}
CHROME = os.getenv("TRACECART_BENCH_CHROME", "/usr/bin/chromium")
CDP = os.getenv("TRACECART_BENCH_CDP", "http://127.0.0.1:9337")
PRICE_SIDECAR = os.getenv("TRACECART_BENCH_PRICE_SIDECAR", "http://127.0.0.1:5119/scrape")

class StructuredHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.mode = None
        self.buffer = ""
        self.title = ""
        self.ldjson = []
        self.meta_prices = []
        self.quote_divs = 0
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "div" and "quote" in d.get("class", "").split():
            self.quote_divs += 1
        if tag == "script" and "ld+json" in d.get("type", "").lower():
            self.mode = "jsonld"
            self.buffer = ""
        elif tag == "title":
            self.mode = "title"
            self.buffer = ""
        elif tag == "meta":
            k = (d.get("property") or d.get("name") or d.get("itemprop") or "").lower()
            if k in ("product:price:amount", "price", "og:price:amount", "product:price:currency"):
                self.meta_prices.append({"key": k, "value": (d.get("content") or "")[:60]})
    def handle_data(self, data):
        if self.mode:
            self.buffer += data[:200000]
    def handle_endtag(self, tag):
        if self.mode == "title" and tag == "title":
            self.title = self.buffer[:200].strip()
            self.mode = None
        elif self.mode == "jsonld" and tag == "script":
            try:
                self.ldjson.append(json.loads(self.buffer))
            except (TypeError, ValueError):
                pass
            self.mode = None

def products_from_ld(entries):
    out = []
    def visit(obj):
        if isinstance(obj, list):
            for item in obj:
                visit(item)
        elif isinstance(obj, dict):
            typ = obj.get("@type", "")
            types = typ if isinstance(typ, list) else [typ]
            if any(str(t).casefold().endswith("product") for t in types):
                offers = obj.get("offers") or []
                offer_list = offers if isinstance(offers, list) else [offers]
                prices = []
                for o in offer_list:
                    if isinstance(o, dict):
                        prices.append({
                            "price": str(o.get("price") or "")[:40],
                            "currency": str(o.get("priceCurrency") or "")[:20],
                            "availability": str(o.get("availability") or "")[-75:]
                        })
                out.append({
                    "name": str(obj.get("name") or "")[:150],
                    "sku": str(obj.get("sku") or obj.get("mpn") or "")[:65],
                    "offers": prices[:6]
                })
            for key in ("@graph", "mainEntity", "itemListElement"):
                if key in obj:
                    visit(obj[key])
    visit(entries)
    return out[:7]

async def crawl(url):
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    browser = BrowserConfig(cdp_url=CDP,
                            headless=True, verbose=False,
                            ignore_https_errors=False,
                            enable_stealth=False)
    config = CrawlerRunConfig(page_timeout=20000, wait_until="domcontentloaded",
                              verbose=False, check_robots_txt=True,
                              delay_before_return_html=0.3)
    async with AsyncWebCrawler(config=browser) as worker:
        result = await worker.arun(url=url, config=config)
        return (result.html or ""), result.status_code, (
            "" if result.success else str(result.error_message or "")[:200]), False

def fetch(engine, url):
    if engine == "scrapling_http":
        from scrapling.fetchers import Fetcher
        p = Fetcher.get(url, timeout=17)
        return str(p.html_content or ""), getattr(p, "status", None), "", False
    if engine == "scrapling_browser":
        from scrapling.fetchers import StealthyFetcher
        p = StealthyFetcher.fetch(url, headless=True, solve_cloudflare=False,
                                 retries=1, timeout=20000, wait=0.5,
                                 executable_path=CHROME)
        return str(p.html_content or ""), getattr(p, "status", None), "", False
    if engine == "crawl4ai":
        return asyncio.run(crawl(url))
    if engine == "pricestalker_browser":
        req = urllib.request.Request(
            PRICE_SIDECAR,
            data=json.dumps({"url": url, "options": {
                "timeout": 20000, "waitUntil": "domcontentloaded",
                "interstitialRetries": 0, "delay": 0}}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=29) as r:
            obj = json.load(r)
        return obj.get("html") or "", None, "", bool(obj.get("challengeUnresolved"))
    raise ValueError(engine)

def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("engine", choices=("scrapling_http", "scrapling_browser",
                        "crawl4ai", "pricestalker_browser"))
    parser.add_argument("target", choices=TARGETS)
    opts = parser.parse_args()
    start = time.monotonic()
    record = {"engine": opts.engine, "target": opts.target,
              "url": TARGETS[opts.target], "http_status": None,
              "html_bytes": 0, "sha256": None, "title": None,
              "structured_products": [], "meta_prices": [],
              "rendered_quote_count": None,
              "price_evidence_count": 0, "result": "ERROR", "error": None}
    try:
        html, status, error, challenge = fetch(opts.engine, TARGETS[opts.target])
        raw = html.encode("utf-8", errors="replace")
        record["html_bytes"] = len(raw)
        record["sha256"] = hashlib.sha256(raw).hexdigest() if raw else None
        record["http_status"] = status
        parser = StructuredHTML()
        parser.feed(html[:4_000_000])
        record["title"] = parser.title
        record["rendered_quote_count"] = parser.quote_divs
        record["structured_products"] = products_from_ld(parser.ldjson)
        record["meta_prices"] = parser.meta_prices[:12]
        record["price_evidence_count"] = sum(
            bool(str(offer.get("price") or "")) for p in record["structured_products"]
            for offer in p["offers"]) + sum(
            x["key"] in ("price", "product:price:amount", "og:price:amount")
            for x in record["meta_prices"])
        if challenge or "captcha" in (record["title"] or "").casefold():
            record["result"] = "BLOCKED_CHALLENGE"
        elif status in (401, 403, 429):
            record["result"] = "HTTP_BLOCKED"
        elif error:
            record["result"] = "ERROR"
            record["error"] = error[:280]
        elif record["structured_products"]:
            record["result"] = "PRODUCT_STRUCTURED"
        elif record["html_bytes"] > 500:
            record["result"] = "HTML_ONLY"
        else:
            record["result"] = "EMPTY"
    except Exception as exc:
        record["error"] = type(exc).__name__ + ": " + str(exc)[:260]
    record["elapsed_s"] = round(time.monotonic() - start, 2)
    print(json.dumps(record, ensure_ascii=False))

if __name__ == "__main__":
    run()
