# TraceCart browser companion — DOM extraction beyond JSON-LD

**Research increment, 3 November 2026.** Extends the consent-gated companion
from PR #71. No merchant anti-bot bypass, no checkout integration, no payment
operations, no production deployment. The browser extension remains disabled
until a user pairs it and explicitly approves each merchant site.

## Extraction decision

`browser-extension/queue_capture.mjs` still runs within the current
*already rendered* product tab. Only a small whitelisted Product/Offer
projection is returned to the loopback broker. It does not transmit the HTML,
cookies, local/session storage, account details, cart contents or network
responses. Three deterministic source paths now exist:

1. **Single JSON-LD Product → individual Offer** (existing): direct price,
   explicit SalePrice specification or single untyped specification. Never
   treat ListPrice or AggregateOffer as current individual offer price.
2. **schema.org Product + Offer microdata** (new): exactly one Product
   `itemscope itemtype` and one nested `itemprop=offers` Offer. Requires
   a unique explicitly labeled product name, price and priceCurrency.
   Optional explicitly labeled brand, SKU, model, GTIN, seller, availability
   are allowed; arbitrary text/other product cards are not read.
3. **WooCommerce single-product primary price widget** (new): requires
   `body.single-product`, a unique explicit product heading
   (`h1.product_title` or `h1.entry-title`), exactly one
   `.elementor-widget-woocommerce-product-price` or
   `.summary.entry-summary` fallback, one `.price` and one current amount.
   An `ins bdi` sale price supersedes `del bdi` reference prices;
   crossed-out-only prices and multi-amount price ranges fail closed.
   This is not generic OCR or full-page number guessing.

When JSON-LD is present, an additional explicit primary DOM price is used
as a **conflict check**, not as a silent override. If current price/currency
or product title differs, extraction returns
`CONFLICTING_OFFER_EVIDENCE` or `CONFLICTING_PRODUCT_IDENTITY`.
Several JSON-LD Products or several microdata Products yield
`MULTIPLE_PRODUCTS_AMBIGUOUS`.

The broker (`browser_companion_queue.py`) accepts the new source labels
`PRODUCT_OFFER_MICRODATA` and `WOOCOMMERCE_PRIMARY_PRICE`, tags exact
price-field evidence with the original method, and retains
`seller_verified=false` and `checkout_verified=false`.
The SHA-256 hash covers the **filtered projection**, not the entire
merchant page. Variant, seller, live availability, shipping and checkout
still require separate verification.

## Real Chromium verification (no merchant access required)

`benchmarks/browser_companion_chromium_smoke.py` runs the **same actual
extraction function** in isolated Chromium using the Chrome DevTools
Protocol on **eleven synthetic locally served HTTPS pages**. This is a real
JavaScript engine and DOM, not mocked Node objects:

| Local HTML case | Expected observation | Result |
|---|---|---|
| JSON-LD | direct 49.90 PLN | PASS |
| JSON-LD inserted via page JavaScript | direct 49.90 PLN | PASS |
| schema.org microdata | 70.50 EUR | PASS |
| WooCommerce sale/list-price markup | sale 119.00 PLN | PASS |
| JSON-LD vs WooCommerce mismatch | CONFLICTING_OFFER_EVIDENCE | PASS |
| Non-product page with incidental numbers | NO_STRUCTURED_PRODUCT | PASS |
| Two microdata Product roots | MULTIPLE_PRODUCTS_AMBIGUOUS | PASS |
| One microdata Product with two offers | NO_STRUCTURED_PRODUCT | PASS |
| WooCommerce main price plus unrelated product card | main sale 119.00 PLN | PASS |
| WooCommerce crossed-out list price only | NO_STRUCTURED_PRODUCT | PASS |
| JSON-LD versus WooCommerce product-title mismatch | CONFLICTING_PRODUCT_IDENTITY | PASS |

**11/11 passed on hexagony-01** using the installed Chromium.
This script starts an ephemeral, TLS-enabled server bound to
`127.0.0.1`, generates a one-day local test certificate, launches a
disposable headless Chromium profile, and deletes its test files afterward.
The flag `--allow-insecure-localhost` is restricted to this local TLS
fixture. It does **not** suppress certificate verification globally.

Run only on the designated development host, if `chromium`, `openssl`,
Python `websocket-client`, and Chromium's Snap user profile directory are
available:

```sh
python3 benchmarks/browser_companion_chromium_smoke.py
```

This is **not** a fully installed MV3 extension E2E: the isolated browser
executes the same exported function via CDP. Background worker, optional
permissions and pairing are verified by separate JS and Python tests but not
yet end-to-end in an actual logged-in user session.

## Opt-in public merchant probe

For a **single approved public product URL**, the smoke harness can run an
additional explicit acquisition with the existing `robots.txt` preflight
and DNS-pinned HTTPS transport and then read the same page in Chromium:

```sh
python3 benchmarks/browser_companion_chromium_smoke.py --public-adafruit
```

Observed 2026-11-03 on
`https://www.adafruit.com/product/1083`:
- public static acquisition: `PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED`;
- robots checked: true;
- browser DOM: Product title `ADS1015 12-Bit ADC - 4 Channel with
  Programmable Gain Amplifier`;
- declared Offer price: **9.95 USD**;
- static HTTP / browser DOM price/currency: **AGREE**;
- final seller checkout, shipping and stock: **NOT VERIFIED**.

The external probe is entirely optional, uses no credentials and does
not run in the standard offline tests. **It is one public merchant sample,
not a representative coverage/accuracy metric for arbitrary sites.**

## Safety and remaining work

- Run Python regression, the 20+ Node tests and optional 6-case Chrome smoke
  before integration. Preserve old one-tab manual capture and opt-in behavior.
- Real Chrome **extension service-worker + site permission + broker** E2E
  remains unverified. Do not conflate direct CDP DOM tests with that path.
- Other embedded application-state formats, cross-domain redirects and
  retailer-specific price semantics are deliberately not guessed here.
- Do not convert this merchant-declared price into a guaranteed/current
  checkout amount. User payment authorization remains separate.
