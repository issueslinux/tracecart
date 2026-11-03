# TraceCart — empirical retailer-fetch benchmark and Allegro diagnostic

Date: **2026-11-03** (Europe/Warsaw). Host: `hexagony-01`.

## Executive decision

**Use Scrapling 0.5 as a candidate for a self-hosted Python 3.12 acquisition sidecar** with HTTP-first/browser-fallback operation. On three live product pages in this experiment, its HTTP mode extracted source-attributed `Product` / `Offer` JSON-LD in **0.43–0.88 s** without a browser. Browser mode rendered JavaScript when required.

**Do not assume any scraper supports Allegro automatically.** All four tested acquisition methods failed on the specific Allegro URL, and a separate network diagnostic showed **DataDome HTTP 403 even at the site root**. The failure occurs before the product page becomes accessible.

Do not deploy to production until retry policy, source access receipts, legal/site policy, budget, feature isolation and multi-product validation are implemented.

## Tooling and method

- Host Ubuntu 20.04, production TraceCart Python 3.8. Tests isolated in Python **3.12.15** virtual environments.
- Scrapling **0.5**; Crawl4AI **0.9.5**; PriceStalker standalone `stealth-scraper` **1.0.36** (only its Chromium HTML sidecar, **not** its complete price consensus pipeline); Chromium **143.0.7499.4**.
- The shared benchmark parser inspected `<script type="application/ld+json">` Product + Offer (SKU, currency, price, seller-declared availability) and page meta prices. No LLM inferred prices. No payment, account login, CAPTCHA solving, proxies or paid services were used. PriceStalker's challenge retry was disabled, and Scrapling's challenge solver was disabled.
- Crawl4AI used a local loopback Chromium CDP endpoint; native Playwright browser download for Ubuntu 20.04 failed. PriceStalker's browser-only TypeScript component built in a standalone directory; root npm workspace installation hit a frontend peer dependency conflict. The isolated component returned HTML but **did not return the original HTTP response status**.
- **Single run** per tool × target; no statistical timing conclusions. Source HTML hashes and timestamped case outputs are recorded in `benchmarks/results/oss_scraper_20261103.jsonl`. Hashes differ between renderers due to DOM/script differences.

## Product extraction results

| Target | Official or retailer-declared JSON-LD data | Scrapling HTTP | Scrapling browser | Crawl4AI browser | PriceStalker browser |
| --- | --- | ---: | ---: | ---: | ---: |
| Ryobi R18PI-0 (manufacturer) | SKU R18PI-0, 239.99 PLN, InStock | 0.88s | 2.95s | 3.70s | 2.30s |
| Ryobi RPI18-0 (manufacturer) | SKU RPI18-0, 249.99 PLN, InStock | 0.88s | 2.35s | 2.66s | 2.95s |
| Media Expert RPI18-0 | Merchant SKU 1259301, 243.71 PLN, InStock; matching price meta | 0.43s | 2.17s | 3.45s | 3.36s |
| Allegro RPI18-0 product URL | No product HTML or price obtained | 403 / 0.20s | 403 / 1.56s | 403 / 2.07s | blocked challenge / 2.59s |

Every method extracted the same price and SKU for the three accessible retailer pages. **InStock and prices are seller claims, not checkout confirmation.** Media Expert's numeric `1259301` is a merchant-specific SKU, not the manufacturer's RPI18-0 model identifier.

JavaScript control `https://quotes.toscrape.com/js/`: Scrapling HTTP observed **0** rendered quote nodes (0.60s), while Scrapling Chromium **10** (2.01s), Crawl4AI **10** (2.87s), and PriceStalker Chromium **10** (2.72s). This demonstrates browser rendering, not its reliability on arbitrary shops.

## Allegro root-cause investigation

Using the same host, without changing identity, bypassing controls or accessing any account:

| URL | HTTP | Diagnosis |
| --- | ---: | --- |
| `https://allegro.pl/` | **403** | DataDome-associated refusal |
| `https://allegro.pl/robots.txt` | **200** | robots accessible; no general network/TLS outage |
| `/produkt/kompresor-...?...offerId=18457369262` | **403** | Refused before product data |
| `/oferta/kompresor-...-18457369262` | **403** | URL path change does not resolve |
| Headless Chromium, root and `/oferta/` | **403** | JavaScript-enabled browser also refused |

The 403 responses included the **`datadome` cookie**, `x-datadome-cid` and `x-dd-b: 2` along with generic challenge HTML saying “Please enable JS and disable any ad blocker”. **Chromium also received 403**, so the banner alone is not evidence that JavaScript was disabled. The response is consistent with a DataDome protection decision at the edge. The available logs **cannot identify the exact trigger** among IP/ASN reputation, browser/network fingerprint, missing or rejected session token, traffic patterns, geographic rules or other policy signals. No claim of a specific IP ban is justified.

`robots.txt` disallows `/offer/` and `/produkt/warianty/`, but not these two tested paths as exact-prefix rules; the HTTP 403 at the site root and DataDome markers are the decisive diagnostic.

**Official API is a separate constraint:** in the Allegro developer issue **#14126**, an Allegro representative stated on **2026-10-07** that public `GET /offers/listing` access is no longer granted, and on **2026-10-08** that equivalent public offer/lowest-price endpoints are not offered. References:
- https://github.com/allegro/allegro-api/issues/14126
- https://docs.datadome.co/docs/cookie-session-storage
- https://docs.datadome.co/reference/validate-request
- https://policies.allegro.com/doc/f86a1a793dc4f5bc4b695b0ff0d54d974badab4169f5aaaddad89585c2c90690

The DataDome correlation header can be supplied privately to Allegro/DataDome support if a legitimate integration is refused, but raw response cookies/session identifiers were **not** stored in this repository.

## Engineering next steps

1. **HTTP-first with bounded browser fallback** for permitted retailer pages. Preserve URL, actual HTTP status, source timestamp, SHA-256 of source HTML, document scope, model/GTIN evidence, seller-declared price, currency, availability and shipping provenance separately. Do not convert search snippets to checkout-verified prices.
2. **Host-specific circuit breaker:** for Allegro `403` with DataDome evidence, stop automated retrying in this workflow and mark `BLOCKED_BY_RETAILER_PROTECTION`. Show indexed leads with `NOT_VERIFIED_AT_SELLER` and keep alternate-store comparisons.
3. Respect shop terms and available official permissions; explore licensed feeds/partner arrangements as distinct authorized channels. Do not try to bypass CAPTCHA, hard blocks or the retailer's access rules.
4. Parse any claimed coupon **only when evidenced by attributable page content**; keep final delivered price unverified until legally accessible seller checkout evidence exists.
5. Test on a broader retailer corpus, multiple runs and cold/warm starts before deciding whether to integrate Scrapling, Crawl4AI or the price-selection component of PriceStalker.

## Reproduction

`benchmarks/oss_scraper_benchmark.py` accepts an acquisition engine and named target and emits one JSON record with selected evidence and timings. It requires isolated third-party dependencies and local loopback browser services; no production service or database is needed. This is a research harness, not a production-ready integration test.

The code runs against an explicit set of public product page URLs only. Do not run large/recurring sweeps on Allegro.
