# Automatic competing-offer discovery — 2 November 2026

## Outcome

TraceCart's URL-first background job now **uses search-discovered product
links to attempt actual, bounded seller-page checks**, instead of leaving
all search results as unverified links in a passive list.

The steps are separate evidence tiers:

1. Selected product is fetched safely. If it cannot be attributed to a
   retrieved seller page, discovered links stay research leads and are not
   automatically fetched.
2. When BRAVE_API_KEY is configured, **two small official Brave Web Search API
   queries** run: general product/EAN search and a targeted
   `site:allegro.pl` marketplace search. This is only site discovery;
   **snippets are NEVER promoted to product prices or product facts**.
3. Up to **3 distinct candidate merchant hosts** are selected, with a
   valid Allegro product/offer link prioritized in the research queue.
   Ceneo comparison listings are kept as discovery leads, not treated as
   direct seller-page offers. All search results (including rejected,
   deferred and unsafe links) remain in the audit tree.
4. Only the existing source-verified comparator is allowed to process
   candidates: HTTPS, public-IP-pinned DNS, robots.txt, same-host redirects,
   bounded HTML responses, GTIN checksum, product variant, seller-declared
   stock, current price and currency gates.
5. A seller HTTP 403 is **preserved as a discovery lead**, not discarded or
   treated as a zero-price offer. No CAPTCHA bypass, session impersonation
   or unauthorized API access is attempted.
6. The user's current cart view and export show the source-check results,
   lower-priced seller-claim research leads and unresolved critic questions.
   The full evidence tree is retained; checkout/payment remains unchanged.

## Actual source-check demonstration

The project host did **not** have BRAVE_API_KEY configured when this module
was implemented. To demonstrate live source verification without suggesting
an API search occurred, public search results were **manually seeded** into
a reproducible 5-link discovery sample, then processed by the same module
using TraceCart's actual safe HTTPS transport.

Selected Stanley Air Kit source: **xDom**, seller-listed **490.14 PLN**,
seller-declared EAN `8016738753899`.

| Discovered source | Fetch status | Result |
|---|---|---|
| Allegro product offer 18637535530 | HTTP 403 | Link retained, price not verified through TraceCart |
| Narzedzia.pl | Retrieved | **367.99 PLN**, seller-claimed same EAN and stock; **source-qualified seller-price comparison** |
| EMAST | Retrieved | **370.84 PLN**, seller-claimed EAN, **stock not confirmed**; excluded from source-qualified comparison |
| Mensura.pl | Not fetched in this run | Deferred under 3-source budget |
| Ceneo | Not fetched as merchant | Aggregator discovery lead only |

**Five search hints, three candidate checks, two seller pages retrieved,
one source-qualified price comparison**, one preserved Allegro discovery
lead. This is one selected product and a non-random, manually seeded sample,
not a comprehensive price scan or proof of the lowest price.

The same product's public Allegro page was previously observed outside
TraceCart with a promotional price (229 PLN at the time, versus 265 PLN
seen earlier). Allegro may now display a different price, and TraceCart's
reader received HTTP 403. This implementation **does not** claim to
reconfirm either number. The earlier external price observation remains
separately recorded by marketplace_leads.py.

Raw source audit, hashes and retrieval times:
[Stanley search-seeded live verification](../examples/live_stanley_search_seed_discovery_2026-11-02.json).

## Hard limits and next step

- One selected source + up to 3 seller-page checks in a background cart job.
  No recurring crawling and no general page spider.
- Without an authorized search provider key, TraceCart does not invent
  discovered offers. Previous URL-first product analysis still works.
- The search and the price-verification stages are intentionally distinct.
  Seller-declared price comparisons are not independently measured product
  quality, delivered checkout totals or purchase recommendations.
- Extend independent evidence research next: product-specific tests and
  reviews, with a clear distinction between seller marketing, aggregate
  reviews and independent laboratory results.

**Cost and delivery-time parser expansion is paused.**
