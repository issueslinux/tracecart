# TraceCart — autonomous conditional alternatives and retailer access (2026-11-03)

## User-facing requirement

The buyer submits a **single product URL**. The application must research seller
prices, promotional conditions and functional substitutes without asking the
buyer to copy prices or coupon codes into a form. No transaction or payment
may be made without explicit authorization.

## Root-cause reproduction

Saved job: `mJ6gqBpVglUZfOrxpNjsx_PF`, selected seller: Ryobi R18PI-0,
`239.99 PLN` from seller JSON-LD (seller declaration, not checkout).
The research snapshot contained 17 offers, including a direct Allegro
indexed RPI18-0 listing at `197.90 PLN` and an R18PI-0 index-only
card at `131.99 PLN`. Earlier `purchase_insights` returned
`SELECTED_PRICE_UNDERCUTS_AVAILABLE_INDEX_PEERS` and zero comparable
offers because the selected title had no numerical motor/pressure specs.

This was a classification bug, not evidence that no cheaper alternatives
existed. R18PI-0 and RPI18-0 are **distinct model identifiers**; the latter
may be a functional substitute, never an automatically asserted exact SKU.

## Implemented (PR corresponding to this document)

- `functional_value.py`: deterministic fallback only when selected
  category is recognized and no selected technical specifications are
  extractable. Uses source-attributed selected SKU and conservative
  function + operating-voltage title overlap.
- Prefer direct listing URLs, and show title-only same-model search cards as
  explicitly unverified leads. Avoid unrelated category, voltage or revision.
- `purchase_insights.py`: expose a conditional verdict, prices relative to
  a fetched seller declaration, and evidence gaps instead of false
  `none cheaper` conclusion.
- `cart_research.py`: read-only live projection upgrade for historical
  reports; **does not mutate the saved report, original LLM classification,
  SQLite audit or source receipts**.
- `assets/decision-page.html`: remove manual seller-price / promo-code
  entry and the separate correction form. Keep only the product URL.
- `assets/live-workspace.js`: distinguish conditional leads from confirmed
  technical comparables, and label historical reinterpretation.
- `model_verdict.py`: category-neutral next step (no laptop-only specs for
  compressors).

## Verified

In an isolated checkout and SQLite backup at port 8799, live snapshot for
the saved job contained `FUNCTIONAL_INDEX_LEADS_NEED_SPEC_VERIFICATION`
with direct `offer-1` (197.90 PLN) and index-only `offer-6` (131.99 PLN).
Headless Chromium rendered both, and manual-price/promo fields were absent.
Python and Node test suites must be rerun against the final commit.

## Browser intermediary: findings, not an invented capability

A connected TinyFish *Fetch* check could read the Ryobi manufacturer's
R18PI-0 and RPI18-0 descriptions. It returned HTTP 403 for the direct
Allegro product URL and bot-blocked for Media Expert; a broker is therefore
**not a guaranteed workaround** for retail access restrictions.

The metered TinyFish browser agent is not usable without funds / explicit
budget (wallet negative at check). Do not launch paid automation or bypass
CAPTCHA, paywalls or access control. Continue to ingest permitted retailer
JSON-LD and legal search-index leads; mark index prices as NOT CHECKOUT.

## Next engineering increment

Introduce a provider-neutral, evidence-storing browser/fetch adapter with
per-host access policy, timeouts, bounded rate, optional budget cap,
attributable timestamps and immutable response hashes. Use direct retailer
JSON-LD or permitted browser rendering where possible. If a page denies
access, preserve the 403 receipt and present indexed alternatives, without
silently claiming the browser read succeeded. Implement coupon extraction
only from actual attributed retailer content; do not guess codes or
expiration dates. Check shipping and basket totals before making stronger
recommendations. User should never have to retype a seller price.

The stored result can justify a conditional purchase lead, never purchase
execution, confirmed merchant safety, or a guaranteed final price.
