# Scrapling HTTP: Allegro transport experiment (2026-11-03)

## Decision

**No-go for deploying standalone Scrapling HTTP as an Allegro verifier on `hexagony-01` without a permitted external data source.** A controlled test of HTTP/TLS client profiles and a cookie-retaining session obtained **zero product pages**. Allegro returned HTTP 403 with DataDome indicators for Chrome-like clients, and Firefox timed out. Do not label index quotes as retailer-verified prices.

This is a transport investigation, not proof of a permanent IP ban, and not a test of the paid Scrape.do service.

## What exactly was tested

Environment: Ubuntu 20.04, Python 3.12 virtual environment, Scrapling **0.5**, backed by `curl_cffi`. The target was the specific product URL containing offer ID **18457369262** for **Ryobi RPI18-0**.

| Scrapling HTTP mode | HTTP / error | Time | DataDome evidence | Actual product data |
|---|---|---:|---|---|
| Chrome 142 impersonation | 403 | 0.09 s | `datadome` cookie, `x-datadome-cid`, `x-dd-b` | none |
| Chrome 131 impersonation | 403 | 0.07 s | same | none |
| Chrome 131 Android impersonation | 403 | 0.08 s | same | none |
| Firefox 133 impersonation | timeout | 11.00 s | no response | none |
| Same-session Chrome 142, `robots.txt` then product | 200 (robots), **403** (product) | 0.11 s | same | none |

The one-off reference request to Media Expert with Chrome 142 returned **403**, whereas earlier tests of the *same* merchant product using Scrapling 0.5 returned **200** and seller-declared price **243.71 PLN**. This demonstrates that retailer response depends on more than page URL and browser profile. It does not negate the earlier valid receipt or establish a stable success rate.

All outcomes and source HTML body hashes (truncated, no raw cookies/tokens) are recorded in `benchmarks/results/scrapling_http_allegro_20261103.jsonl`; the reproducible bounded runner is in `benchmarks/scrapling_http_allegro_diag.py`.

## What can and cannot be transplanted from GitHub projects

1. **Scrapling's HTTP/TLS impersonation:** already implemented and tested with Chrome desktop, Firefox, Android clients. None opened the actual Allegro offer. Different headers alone are therefore not a demonstrated solution.
2. **Market-scout persistent profiles:** `bbence84/market-scout` uses a **real browser**, a visible one-time DataDome challenge and a persisted browser profile. An HTTP cookie jar (tested above) is *not* a substitute for obtaining valid browser-issued clearance. Without a permitted, valid existing authenticated session, this cannot operate fully autonomously in pure HTTP mode.
3. **Scrape.do `super: true`:** `usestring/web-data-frontier-benchmark/src/providers/scrapedo.ts` calls a **remote vendor API** with its own residential/mobile transport network, `render: false`. The vendor-side network, reputation, proxy authentication and request handling are not bundled with Scrapling. Setting `render=False` in a local HTTP client is not equivalent to the benchmarked Scrape.do route.
4. **Other hosted benchmark providers:** five successful provider requests in a different Allegro-offer experiment are useful vendor evidence but **not** evidence that the host's locally routed Scrapling HTTP can fetch this Ryobi offer, and not checkout price confirmation.

## Integration design, if a permitted transport becomes available

Scrapling's `FetcherSession` supports an explicit `proxy`/`proxies` argument. A separately authorized access provider could in principle be wired in without replacing TraceCart's structured-data parser, but this needs a specific host policy, access terms, budget, credentials handling, and a real test that verifies **offer ID, seller, current price, availability and date**. Do not ingest an HTTP 200 response as valid without confirming it contains the *requested* product.

For now, keep `BLOCKED_BY_RETAILER_PROTECTION` separate from `NOT_FOUND` or `PRICE_NOT_AVAILABLE`, suppress repeated blocked requests, and prefer legally accessible retailer pages (e.g. Ryobi) and independently sourced index leads clearly labeled `NOT_VERIFIED_AT_SELLER`.

## Boundaries and reproduction

- Small, fixed request budget; no automated challenge solving, evasion, paid API, logins or checkout.
- No production TraceCart code, process or database changed.
- Script requires Scrapling 0.5 in a Python 3.11+ environment and runs explicit public page GETs. It intentionally does not accept arbitrary URL or proxy configuration, preventing accidental bulk scans or credential leakage.
- Related test and diagnostic: `docs/OSS_SCRAPER_ALLEGRO_DIAG_2026-11-03.md`.
