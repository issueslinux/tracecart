# Marketplace price leads must remain visible — 2 November 2026

## Problem confirmed on a real product

The previous comparison covered two directly retrievable Stanley Air Kit
offers: xDom (490.14 PLN) and Fabryka Narzędzi (382.28 PLN). **Those two
prices were not a market-wide search.** The public Allegro page for offer
**18637535530** displayed an active promotion of **229.00 PLN** on
2 November; **265.00 PLN** was displayed as the earlier reference price.
Prices can change before checkout.

The observed listing presents Stanley Air Kit model **8215190STN595**,
with product EAN claim **8016738753899**. Exact product equivalence and
condition are still seller/platform assertions, not independent testing.

Public product page:
https://allegro.pl/produkt/kompresor-bezolejowy-1100-w-stanley-air-kit-1-5km-8-bar-sprezarka-zestaw-e4cae746-3f65-411f-a748-e715e2d02305

The TraceCart safe HTTPS retriever independently returned **HTTP 403** for
this Allegro page; it must not evade this restriction. The public-page
price is an EXTERNAL observation, not seller HTML fetched by TraceCart.

| Source | Product price | Evidence tier |
|---|---:|---|
| xDom | 490.14 PLN | Direct seller page fetched by TraceCart |
| Fabryka Narzędzi | 382.28 PLN | Earlier direct seller page fetched by TraceCart |
| Allegro offer 18637535530 | 229.00 PLN | Public page observation outside TraceCart; direct collector HTTP 403 |

The **261.14 PLN** difference versus xDom is arithmetic between a directly
retrieved price and a separately observed marketplace price. It is NOT a
verified checkout saving, universal lowest-price ranking, or quality verdict.
Search aggregators can show additional offers and fluctuate significantly.
An Allegro product rating is not an independent product laboratory test.

## Implementation

The marketplace_leads.py module stores up to four explicitly unverified
price observations with their URL, amount, currency, observation origin,
optional claimed GTIN/condition and observation time. No such observation
is promoted to a source-qualified competing offer, even with matching GTIN.

The UI accepts an optional marketplace URL and the price visible in the
user's browser. When no other candidate is supplied, TraceCart attempts its
usual robots-aware source retrieval too. HTTP 403 remains auditable and does
NOT erase the unverified observed price lead. The on-screen report and full
JSON/critic tree include three verification questions per lead.

If the same URL was successfully fetched as a seller page, the module
checks the observed price against the seller-declared price. Contradictions
are recorded as CONFLICTING_OBSERVED_AND_DIRECT_PRICE and are not counted
as lower-price leads; matching price observations are not double counted.

No new shipping/ETA parsing, access-control bypass, automatic purchase,
PayPal action or background scheduling was introduced.

## Reproducible real observation

The compact audit snapshot, including retrieval timestamps, page hashes,
Allegro HTTP 403 and separate external observed price:

[Stanley / Allegro source snapshot](../examples/live_stanley_allegro_marketplace_lead_2026-11-02.json)

## Follow-up

Discover candidate seller links using permitted search/index or an authorized
merchant feed. Preserve three tiers: discovery only, observed listing, and
verified seller page. Collect genuinely independent product tests and review
evidence separately, with exact-model and provenance checks.
