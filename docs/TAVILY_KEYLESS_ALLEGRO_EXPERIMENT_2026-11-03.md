# Tavily keyless experiment: Allegro indexed leads (2026-11-03)

## Decision

**Conditional GO for bounded Allegro lead discovery, NO-GO for live seller verification.** Tavily's official keyless API works from `hexagony-01` with no API key or payment. Four Search queries returned HTTP 200 (7 results apiece). The indexed Allegro product page includes a **197.90 PLN** model-level price claim. No result established that **offer 18457369262** currently sells at that amount. A direct Extract request for the offer URL failed by timeout. **Do not put an indexed price into the verified-offer ranking or checkout flow.**

## Real API trials

- API: `POST https://api.tavily.com/search`, fixed `X-Tavily-Access-Mode: keyless`; `search_depth=basic`, `max_results=7`. No `TAVILY_API_KEY` available or used.
- Real test case: Ryobi **RPI18-0**, EAN candidate `4892210230478`, Allegro offer ID `18457369262`.
- Query 1, exact quoted offer ID: **7 results**, including **one Allegro product landing page**, which mentioned `Numer oferty: 18457369262` in the excerpt. Two result URLs containing the numeric offer ID **were external Ukrainian aggregators**, `spolshy.com.ua` and `automotive.org.ua`, NOT Allegro. These must not count as two independently verified listings.
- Query 2, exact model + Allegro domain: **7 results**; an Allegro `/produkt/` landing page with a `197.90PLN` indexed claim, another `/produkt/...?...offerId=18928160412` with **89.00 PLN, used**; a third `offerId=18740910894` with **249.90 PLN**, and a search results page showing **197.90 PLN / 208.39 PLN including a particular delivery context**. None of these proves a live price for target offer `18457369262`.
- Query 3, EAN + Allegro domain: **7 results**, overlapping product and different-offer pages.
- Query 4, generic model/merchant: **7 results**, including canonical Allegro product page, other stores, and a Ceneo price index. This is discovery, not merchant confirmation.
- Extract of `/oferta/...-18457369262` and official Ryobi product page in a single request: **HTTP 200 from Tavily**, **one successful extraction (Ryobi)** and **one per-URL failure (Allegro: Request timed out)**. Do not interpret the batch HTTP 200 as an Allegro fetch success.
- Results do **not** include a reliable index-refresh timestamp or seller identity, and do **not** prove availability, total landed cost, offer condition (except explicit `Used` text), or checkout price.

Evidence: `benchmarks/results/tavily_keyless_allegro_20261103.jsonl`; replayable fixed-case runner: `benchmarks/tavily_keyless_allegro_probe.py`.

## Module

`tavily_allegro_index.py` implements `search_tavily_allegro(brand, model, offer_id, ean, enabled=True)`, **explicitly opt-in** (disabled by default) and limited to at most three Search requests per invocation; no scheduled calls or hidden production changes. Uses only the official keyless header unless an API key is *explicitly passed*. Never logs credentials. Returns bounded `leads` with separate categories:

- `PRODUCT_PAGE_WITHOUT_SINGLE_OFFER_ID`: index price attached to a **product-group** page, NOT to the target offer.
- `DIFFERENT_OFFER_ID_NOT_COMPARABLE_AS_SAME_OFFER`: exact URL ID differs from target; includes used-condition warnings.
- `EXACT_OFFER_ID_IN_URL_NOT_LIVE_VERIFIED`: a matching URL, if any, is still **only index evidence**.
- All results: `source_page_retrieved=false`, `seller_verified=false`, `price_verified_by_seller=false`, `payment_authorized=false`.
- A result from external aggregators, a generic search listing, a different brand/model, or an unsafe/non-HTTPS URL is excluded.
- Duplicate canonical URLs can contribute an indexed price from a later query without assigning that claim to a particular offer ID. Contradictory prices on the same URL invalidate that indexed claim.

The module is a **research adapter, not yet wired into the production cart endpoint**. An application integration should be gated, cache/deduplicate individual item results and show them in the *unverified lead* section only. It must not silently convert the rows into existing `marketplace_leads` origins because their provenance contract is different; updating that contract requires a separate reviewed change.

## Reproduce

`python3 benchmarks/tavily_keyless_allegro_probe.py` (this intentionally makes live remote calls; respects the public Tavily rate limit; no key needed).
`python3 -m unittest tests.test_tavily_keyless_allegro -v` (offline, **no API usage**).

Official SDK: https://github.com/tavily-ai/tavily-python — keyless Search and Extract.
Docs: https://docs.tavily.com/documentation/api-reference/endpoint/search and https://docs.tavily.com/documentation/api-reference/endpoint/extract.
Free account tier: 1,000 monthly credits without credit card (a separate mode; **not required for this experiment**).

## Next gate

Run a representative labeled benchmark (at least 10–20 known offer IDs, multiple categories and sellers). Measure exact ID-in-URL precision, real product/condition identity, extract success, price claim presence, source freshness and index lag before selecting Tavily for any automatic production path. The present four-query benchmark establishes technical feasibility and a non-zero indexed price signal — **not market-wide accuracy**.
