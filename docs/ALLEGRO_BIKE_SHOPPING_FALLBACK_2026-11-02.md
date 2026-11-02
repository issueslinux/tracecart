# Allegro e-bike 18482612668 — search-first failure and real fix

Date: 2 November 2026. User-supplied input:

https://allegro.pl/produkt/rower-elektryczny-meski-damski-250w-15ah-100km-27-5-ebike-shimano-7s-25kmh-d0481fa2-8a35-4009-871d-108ca1cc1d78?offerId=18482612668

## Reproduced defect

The URL-only intake correctly marked Allegro's public page **HTTP 403**.
SerpApi's official Google Shopping API returned **40 indexed product cards**,
including multiple results from Allegro. However, the follow-up
`google_product` request for the first candidate returned a provider
error. Search-First caught that error in one catch-all handler, created
a blank result, and replaced all successful Shopping cards with
`FAILED_ValueError` and **zero displayed offers**.

This was **data loss in our own error handling**, not evidence that the
bicycle wasn't for sale.

## Production code fix

1. Keep the 12 top bounded Google Shopping cards in the report even when
   a *separate* Google Product details request fails.
2. Give these cards status
   `ONLY_GOOGLE_SHOPPING_CARDS_DETAIL_FAILED`; preserve the sanitized
   detail-failure class and actual provider-call count (2).
3. Show per-card indexed seller name, price, title, model uncertainty and
   a **user-clickable Google Shopping search**. This link is a Google
   Shopping search, **not an asserted direct merchant offer URL**.
4. Do not invent a direct seller URL, EAN, stock, price or selected-offer
   equivalence from a search card. Label any minimum as strictly
   `MINIMUM_OF_INDEXED_SEARCH_RESULTS_NO_DIRECT_SELLER_LINK`.
5. Preserve all cards as `indexed_search_card` nodes in the full evidence
   tree, alongside the original inaccessible seller page. Payment
   authorization remains false.
6. If the **primary** Google Shopping query itself fails, the system still
   returns a real source failure, not invented cards.

## Actual app verification on provided link

A new TraceCart instance, with the privately configured SerpApi key,
was started on `http://127.0.0.1:8782/cart`. Submitting this **exact**
Allegro URL to its real `/cart/add` form produced:

| Field | Actual output |
|---|---|
| Job | READY |
| Intake | URL_ONLY_UNVERIFIED (HTTP 403) |
| SerpApi calls | 2 |
| Returned indexed search cards | **12** |
| Direct seller-page offers in this query | 0 |
| Page status | ONLY_GOOGLE_SHOPPING_CARDS_DETAIL_FAILED |
| Evidence tree | All 12 search cards retained |
| Checkout verified | No |
| Payment authorized | No |

Selected examples from those **real** Shopping-index cards:

| Indexed source | Google Shopping displayed price |
|---|---:|
| Allegro (one indexed product) | 2469.05 PLN |
| Allegro (a separately indexed product) | 2469.00 PLN |
| Allegro (ALLGOBIKE AM27 listing) | 2599.00 PLN |
| Decathlon (different Evercross candidate) | 3028.99 PLN |
| Allegro (Orzel C27, different model candidate) | 3399.00 PLN |

These are **not all the same bicycle**, and even the similar-sounding
Allegro cards may be different color/model/condition variants.
The **supplied offer ID 18482612668** appeared in a public Allegro
page/search index with price **2649.00 PLN**, EAN **0746121153095**,
ALLGOBIKE 27.5 MTB, Shimano 7-speed, 250 W, 36 V 15 Ah.
TraceCart could **not** independently read that particular Allegro
offer. A card at 2469 PLN cannot be equated to that precise offer.

Public indexed source:
https://allegro.pl/oferta/rower-elektryczny-meski-damski-250w-15ah-100km-27-5-ebike-shimano-7s-25kmh-18482612668

The source snapshot and all 12 search leads with their Google Shopping
search links are recorded in
[real bike E2E JSON](../examples/live_bike_allegro_shopping_fallback_2026-11-02.json).
No SerpApi key, API request URL containing a key, credentials, or
personal details are included.

## Next research gap

The application can now **show what the Shopping API actually found**
instead of erasing it. The remaining P0 need is an authorized way to
resolve each indexed card into a true, current, exact-SKU/GTIN merchant
listing. A Search card is not sufficient for a verified cheapest offer.

No HTTP 403 bypass, login automation, delivery/ETA parser changes,
checkout or background recurring crawler were added.
