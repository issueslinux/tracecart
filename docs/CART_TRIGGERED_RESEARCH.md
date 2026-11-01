# TraceCart — analysis triggered by an existing cart item

**Product direction as of November 1, 2026.** A customer has already selected
a product and may be proceeding to checkout. TraceCart runs a bounded research
job **after Add to Cart**, independently of the payment flow. The result is
intended to be shown **before final checkout**, while leaving the customer's
original cart unchanged.

## URL-only entry point (current default)

The initial customer-facing form at **/cart** asks for **only the
original product link**. `POST /cart/add` starts an async extraction +
research job with `product_url`. The product page is fetched only
after a strict HTTPS DNS/IP validation and robots.txt preflight.
Product JSON-LD / OpenGraph yields item title, price and currency,
EAN when present, stock/brand/source and a page SHA-256. If price/EAN
is missing, analysis still runs with null price / empty EAN; no
fictitious price is substituted.

The protected backend `POST /api/cart/added` supports
`{"product_url":"https://www.adafruit.com/product/1083"}`, or
the previous full product-information event for platforms with trusted
backend cart records. The endpoint uses a backend-only
`TRACECART_CART_WEBHOOK_TOKEN` and returns a job ID immediately.

**Only public HTTPS pages are accessed**, with per-request resolved-IP
pinning (protection against DNS rebinding), TLS verification, no
redirects, robots.txt policy, and a bounded HTML response. Product
websites without parsable metadata or that block bots yield an
explicit FAILED state; never bypass authentication/robots policy.

## Workflow

1. The user supplies a product URL. TraceCart retrieves original
   seller metadata for title, price, EAN and availability. A merchant
   backend may alternatively supply trusted cart details directly.
2. **Immediately** respond with a job ID; run research asynchronously in a
   local thread pool (max 2), persisted in SQLite.
3. Detect broad product category; instantiate decision questions appropriate
   to that category, e.g. for **washing powder**: cost per wash, hard water,
   stain removal at 20–40°C, doses, allergens, enzymes, current formulation,
   colour/white suitability, independent tests.
4. Attempt source discovery: Open Products Facts catalog (brand variants and
   one bounded cross-brand search for laundry powders); Open Prices historical
   crowdsourced price lookup for the selected EAN. The source query outcomes
   are recorded, including empty and failed responses.
5. If `BRAVE_API_KEY` is configured, perform a bounded, authorized web search
   for alternative store URL candidates. **A search hit is not a verified
   store offer or price.** No pricing assertions are extracted from snippets.
6. Local Qwen (if available) proposes up to four additional open questions
   related to the actual cart item and sources. These cannot become answers
   or directly change prices. A failed model leaves the deterministic tree.
7. The customer sees a compact **conditional research summary FIRST**, source
   candidates, important questions, critic caveats, and an expandable COMPLETE
   tree / JSON audit underneath. Never force a winner or block informational
   analysis just because a reviewer might have missing information.
8. **Payment remains separate**, with explicit consent and PayPal Sandbox.
   Neither the cart event nor the research result can create or capture a payment.

## Local manual demo

```bash
python3 app.py --port 8770
# Open on that machine: http://127.0.0.1:8770/cart
```

The default form contains an **illustrative** Persil powder cart item and
fictitious 34.90 PLN price; Open Products Facts and Open Prices calls do use
real public APIs. Click "Add to cart & start asynchronous research", watch the
job state change from QUEUED/RUNNING to READY, and inspect sources, questions
and audit JSON. No customer purchase will be made.

For a server-side checkout event, configure a long random
`TRACECART_CART_WEBHOOK_TOKEN` on the machine, then send a POST to
`/api/cart/added` from an **authorized application backend**, including:

```http
POST /api/cart/added HTTP/1.1
Host: 127.0.0.1:8770
Content-Type: application/json
X-TraceCart-Event-Token: <backend-configured-secret>

{"title":"Persil washing powder 45 washes",
 "price":"34.90","currency":"PLN","barcode":"8712561344494",
 "merchant_url":"https://merchant.example/product/powder"}
```

A successful accepted event responds HTTP **202** with `job_id` and a
`status_path`. Read `/cart/status/<job_id>` for the full report or append
`.json` for structured integration. Without a token the JSON endpoint is
disabled (503); invalid tokens receive 403. Do not put the token in frontend
JavaScript; it belongs in trusted backend configuration. Request body is capped.

**Production integration is not installed.** The reference server binds to
127.0.0.1 only. Actual WooCommerce/Shopify/shop checkouts require a backend
adapter that posts the item event, polls the research job securely and renders
the report in a pre-checkout interstitial. Production needs HTTPS, per-buyer
authorization, privacy/data-retention controls, deduplication and explicit
timeouts, caching and sustainable search quotas. Do not expose the demo server
publicly or send personal buyer details to search APIs.

## What is verified, and what is not

- Confirmed on hexagony-01: a live Add-to-Cart HTTP request returned in **0.2
  seconds**, with the research running in a separate worker. A test Persil
  powder led to 17 category/adaptive questions and a genuinely fetched catalog
  of alternative package identities; the real local Qwen added questions.
- Open Prices lookup for the selected real EAN returned **zero** historical
  prices in the sampled test, so **zero verified competing retailer prices**
  and no claim that any store is 10% cheaper. These are possible products
  to investigate, not actionable offers with validated stock or shipping.
- Brave search is an OPTIONAL provider: no `BRAVE_API_KEY` was configured
  on the test host, so cross-store URL search was **SKIPPED** and labelled as
  such in the report. This is not fabricated online offer discovery.
- Real metadata is attributed to Open Products Facts / Open Prices. See
  `examples/DATA_SOURCES.md` for data origins and ODbL considerations.
- Only a few product families are calibrated so far (laundry powder,
  laptops, generic baseline); Qwen may add questions but cannot promise
  complete category ontology or reliable external source coverage.
- Existing comparison support for 2–12 actual price-bearing offers remains
  usable via `/compare`. The cart pipeline must *not* claim a comparison of
  priced stores until it has verified, equivalent retailer offers.

## Next highest-value outcome

Connect an authenticated retail price feed or licensed shopping search API,
and validate prices and available stock from authorized retailer sources for
the same EAN/package or genuinely equivalent alternatives. Compare normalized
**cost per wash** for detergents once there is verified package dose and
delivered price evidence. Then ship the compact summary into a real checkout
via a backend integration; do not spend many iterations polishing unrelated
single-product spec tests.
