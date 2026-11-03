# TraceCart — full Chromium MV3 worker → local queue → seller-page extraction

**Date:** 2026-11-03. **Research-only, not production deployment.**

This increment resolves the outstanding verification gap after PRs #70–72:
a real Chromium Manifest V3 **service worker** was loaded and exercised
together with the loopback TraceCart HTTP interface, the live seller page
and the universal extraction/broker contract. Earlier tests only executed
the in-tab function through CDP or mocked the worker in Node.

## Exact verified path

The reproducible harness is
`benchmarks/browser_companion_mv3_e2e.py`. It runs a disposable Chromium
session under Xvfb, an unpacked copy of the real extension, and an isolated
`127.0.0.1` TraceCart HTTP server with an in-memory companion queue.

For each selected public merchant product it performs **two stages**:

1. **No merchant permission:** loads the unmodified MV3 manifest and registers
   a real `companion_worker.mjs`; configures the extension through its actual
   popup/storage and sends `configureCompanion`; adds a product URL through
   TraceCart's **real CSRF-protected form**; the service worker polls the
   local broker using its ephemeral bearer token. The worker reports
   `SITE_PERMISSION_REQUIRED` and no merchant result is produced.
2. **One test-only merchant permission:** copies the unpacked extension to a
   different temporary directory, adds **only the selected public merchant
   origin** to that temporary copy's `host_permissions`, and starts a fresh
   disposable browser profile. This models an approved site permission; it
   does **not** test the actual browser's permission dialog. The worker
   receives one queued URL, opens a background tab, reads the already
   rendered page via `chrome.scripting.executeScript`, returns a whitelisted
   Product/Offer projection to `/api/browser-companion/result`, then
   closes the tab. The local broker saves `USER_BROWSER` claim evidence.

Both scenarios verify MV3 registration, popup-to-worker messaging,
token-protected polling and result submission, and locally readable job
receipts. No checkout, PayPal, cookies, localStorage or browser credentials
are exported. The temporary browser profile and extension copies are deleted
by the harness afterward.

**Important:** The test-only manifest modification is **never written to the
repository extension**. In a normal browser the user must approve each
optional site permission through the extension popup; that UI dialog remains
an unverified step.

## Public merchant evidence (2026-11-03)

Each public merchant is checked by the existing pinned-HTTPS,
`robots.txt`-aware source adapter **before** Chromium is started.
No denied merchant, protected account or CAPTCHA challenge was accessed.

| Merchant | Product | Static declared offer | Real MV3 browser result | Price declaration method |
|---|---|---:|---:|---|
| Adafruit | ADS1015 ADC, product #1083 | 9.95 USD | 9.95 USD | DIRECT_OFFER_PRICE |
| Maxpronet | Persil Color, 75 washes, 4.5 kg | 78.90 PLN | 78.90 PLN | EXPLICIT_SALE_PRICE_SPECIFICATION |

For **each** merchant, the no-permission case returned
`SITE_PERMISSION_REQUIRED`. The approved test-only origin case returned
`PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED` with five evidence
rows, the correct original browser price source and
`seller_verified=false`, `checkout_verified=false`.

Both static and browser extractions read the **same seller's declarations**.
Agreement is a useful parser cross-check, **not** independent confirmation of
seller price validity, stock, delivery charge, availability or total checkout.
These are two selected public examples and not a general accuracy estimate.

## Repeat manually on development host

No persistent service is started. The tests use installed Chromium (Snap),
`xvfb-run`, Python `websocket-client` and standard Python application
modules, with an Xvfb display isolated from the real desktop.

```bash
cd /mnt/nvme_fast/tracecart
# One optional public sample per explicitly chosen command:
python3 benchmarks/browser_companion_mv3_e2e.py --public-adafruit
python3 benchmarks/browser_companion_mv3_e2e.py --public-maxpronet
```

Running without a merchant flag **fails before making external requests**.
The test does not enable or install the extension in the user's normal
Chromium profile and does not deploy the TraceCart server to production.

Related offline checks:

```bash
node --test browser-extension/*.test.mjs
PYTHONPATH=.:tests python3 -m unittest discover -s tests -p 'test_*.py' -q
python3 benchmarks/browser_companion_chromium_smoke.py
```

## Remaining gates

- Test the **actual user-granted permission dialog** in an isolated real
  browser, including denial and revocation after grant.
- Evaluate additional safely accessible retail sites and product types,
  recording both access and price/variant identity failures.
- Support merchant pages without JSON-LD, microdata or WooCommerce primary
  price only via additional **explicitly scoped** extractors, with
  conflicts and field-level provenance, not arbitrary text price guessing.
- Add persistent queue/audit state and restart recovery before long-running
  use. Keep the research connection separate from checkout and payments.
- Production deployment requires a separate explicit readiness review.
