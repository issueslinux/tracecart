# Tavily keyless — 20 Allegro offers, 15 categories (2026-11-03)

## Research decision: NO-GO as an offer-price verifier

**One HTTP 200 response from Tavily is not successful offer retrieval.** With 20 independently sourced real-world Allegro offer URLs, the fixed baseline search found the exact requested `offerId` inside an official Allegro result URL in **5/20 (25%)** cases and an indexed price on that exact result URL in **3/20 (15%)** cases. **Zero live seller prices, stock status, checkout totals or index refresh timestamps were verified.** An adaptive model-only fallback broadened product recognition, **not exact-offer retrieval**. Do not use Tavily index prices to calculate a verified cheapest-offer claim or authorize purchases.

## Corpus and methodology

- 20 distinct Allegro `/oferta/` URLs in **15 product categories**, collected independently from public search-index results on 2026-11-03 (not selected from Tavily output). Multiple brands, cheap and expensive items, new/used/outlet variants. The source URLs and case metadata are frozen in `benchmarks/tavily_allegro_20_cases_20261103.json`. This is a **purposive research sample, not random market-wide sampling**; source pages may themselves be stale.
- Initial query fixed *before observing results*: `"<offerId>" <brand> <model> allegro.pl`, `search_depth=basic`, `include_domains=["allegro.pl"]`, `max_results=8`. One request per seed, no retry or challenge solving.
- API: Tavily keyless `POST /search` with `X-Tavily-Access-Mode: keyless` (no key, no payment). **20/20 HTTP 200, 8 results each**; median latency **1.33 s**. HTTP success alone does not imply offer success.
- Exact hit only when the *official Allegro URL* identifies the requested `offerId` and the *result title* contains the expected brand + complete model. An ID in a snippet on a generic `/produkt/` URL remains a weaker link; a model-group price **cannot be attributed** to one offer.
- Prices must be explicit leading price claims in an exact-URL result snippet. We did not infer them from installments, transport fees, unrelated descriptions or an index's general search/list page.
- All provider responses have no reliable **index-crawl timestamp**; publication dates, when provided, are not equivalent to fresh seller verification (none present in this test).
- Results and analysis are frozen in `benchmarks/results/` (no secret tokens or cookies).

## Baseline results

| Metric | Result |
|---|---:|
| HTTP 200 / searches | 20 / 20 |
| Total Search result objects | 160 |
| Cases with brand + exact model in official Allegro result title | **7 / 20 (35%)** |
| Cases with exact `offerId` inside official result URL | **5 / 20 (25%)** |
| Exact-offer URL with explicit indexed price | **3 / 20 (15%)** |
| `offerId` only in product-group result snippet, without price linkage | 1 / 20 (Ryobi) |
| Direct seller-page listed price verified | **0 / 20** |
| Stock, checkout price or index refresh time verified | **0 / 20** |
| Median API request duration | **1.33 s** |
| Exact-offer indexed prices independently cross-compared | 3 |
| Agreed with separately retrieved indexed seller page | 2 / 3 |
| Disagreed | **1 / 3** |
| One separate index contained an *inactive-offer* notice | **1** (Philips) |

### The 20 offer-ID outcomes (baseline)

| Case | Product | Offer ID | Result class | Price claim on exact offer URL |
|---|---|---|---|---:|
| 01 | Ryobi RPI18-0 | 18457369262 | ID only in product-group snippet | — |
| 02 | Samsung Galaxy S24 128GB | 15786504314 | No official matching model | — |
| 03 | Garmin Forerunner 265 | 18316161235 | No official matching model | — |
| 04 | LEGO Technic 42116 | 10813601665 | No official matching model | — |
| 05 | Bosch GSR 18V-55 | 18148846227 | **Exact URL and price claim** | **969.00 PLN** |
| 06 | Philips NA555/00 | 17438881015 | **Exact URL and price claim** | **754.48 PLN** |
| 07 | Lavazza Crema e Gusto 1kg | 11719773053 | No official matching model | — |
| 08 | Xiaomi Redmi Note 13 Pro | 18730711242 | Model match, no exact offer URL | — |
| 09 | Apple AirPods Pro 2 | 18865549874 | **Exact URL and price claim** | **649.90 PLN** |
| 10 | DeLonghi ECAM290.51.B | 18563251687 | No official matching model | — |
| 11 | Sony WH-1000XM5 | 18567665509 | No official matching model | — |
| 12 | Nintendo Switch OLED | 18545129960 | No official matching model | — |
| 13 | IKEA KALLAX 77×147 | 16103573466 | No official matching model | — |
| 14 | Fiskars Plant Care 7w1 | 18654761523 | Exact offer URL, **no price** | — |
| 15 | Purina PRO PLAN Gastrointestinal | 10770308819 | No official matching model; seed URL has index-ID discrepancy | — |
| 16 | Oral-B iO6 | 12673320328 | No official matching model | — |
| 17 | Logitech MX Master 3S | 17788953294 | Exact offer URL, **no price** | — |
| 18 | Nivea Men Creme 75ml | 16019374660 | No official matching model | — |
| 19 | Tefal OptiGrill GC705D16 | 18724219675 | No official matching model | — |
| 20 | Michelin CrossClimate 2 235/50R19 | 18704751959 | No official matching model | — |

**These are indexed claims, NOT seller-verified prices.** The price for a product-group `/produkt/` page might belong to another offer, even if the snippet mentions the requested ID.

### Cross-index discrepancy: actual examples

- **Bosch `18148846227`**: Tavily exact-offer snippet **969.00 PLN**. Separately indexed seller-page text (crawled ~one week earlier) shows **599.00 PLN** for the same offer ID. Difference **370.00 PLN**; cannot determine the currently valid amount without direct seller access. Source: https://allegro.pl/oferta/bosch-gsr-18v-55-wiertarko-wkretarka-55nm-body-l-boxx-18148846227 .
- **Philips `17438881015`**: Tavily and separately indexed page both quote **754.48 PLN**, but the separate indexed page also contains the notice **"szukana oferta jest nieaktualna - może podobny przedmiot?"**. Price agreement does NOT prove the listing is active. Source: https://allegro.pl/oferta/frytkownica-beztluszczowa-airfryer-philips-9l-2750w-na555-00-dwa-kosze-17438881015 .
- **Apple `18865549874`**: Tavily index and a separate page index both give **649.90 PLN** for an `Powystawowy` item. This is cross-index consistency, not a confirmed live seller price. Source: https://allegro.pl/oferta/sluchawki-apple-airpods-pro-2-gen-magsafe-usb-c-bt-mtjv3zm-a-dokanalowe-18865549874 .
- **Purina `10770308819`**: an independently indexed URL ending with that ID displays `Numer oferty: 13349963303` on the page — an instructive example of a stale/canonicalized/relinked URL, **not a valid independent exact-offer verification**. Source: https://allegro.pl/oferta/sucha-karma-dla-psa-z-nadwrazliwoscia-pokarmowa-purina-pro-plan-en-12kg-10770308819 .

## Adaptive fallback (same corpus, not a new independent test)

A subsequent model-only query `<brand> <model> Allegro cena` was attempted **only** where the initial exact-ID search failed (15 cases). It returned:

| Metric | Result |
|---|---:|
| Fallback cases eligible | 15 |
| Fallback API requests attempted | 11 |
| HTTP 200 | 10 |
| HTTP 429 (keyless rate limit) | **1** |
| Not attempted after rate limit | **4** |
| Fallback cases with brand/model result | 10 / 10 successful requests |
| Additional exact offer IDs recovered | **0** |
| Combined brand/model recognition | **15 / 20** |
| Combined exact offer URL recognition | **5 / 20 (unchanged)** |
| Fallback cases with unlinked product-group price | 5 |

Fallback model-group price claims included Ryobi, Garmin, LEGO, Sony and Nintendo. **None can be attached to the seeded offer ID**. A small pilot additionally tried stricter `exact_match=true` on three missing exact offer IDs (Samsung, Garmin, LEGO): each returned HTTP 200 with zero results. There is no evidence that a stricter query fixes the retrieval gap.

The runner **stopped immediately at HTTP 429**; subsequent invocation with these frozen receipts also stops (circuit breaker). No retry storm, no paid credits. We cannot infer the exact daily/hourly quota of Tavily keyless from this one run.

## Recommendation / action gates

1. **Keep Tavily opt-in only for low-rate product discovery.** A result should be labelled `SEARCH_INDEX_LEAD_NOT_SELLER_VERIFIED`; preserve source URL, offer ID if present, snapshot time, match quality, and indexed condition claim. A product-group price must NOT populate the price field for an exact `offerId`.
2. **Do not enable automatic Allegro price comparison, ranking, discounts or checkout from Tavily.** The exact-ID recall of 25%, stale price discrepancy and inactive offer warning are unacceptable as direct decision evidence.
3. **Add a TTL/circuit breaker when integrating in a separate PR.** Stop on HTTP 429/403, dedupe by offer/model, cap queries and use a cached no-result receipt; never silently spend paid credits or add repeat requests. Verify provider terms and limits before scheduled use.
4. **Use seller-confirmable sources for the final gate:** authorized seller API, live page genuinely available to the user via browser companion, or other permitted retailer feed; check offer ID, condition, seller, price, shipping and stock together. If unavailable, display the candidate with `NOT_VERIFIED_AT_SELLER`, not a recommendation to purchase.
5. Larger unbiased benchmarks are needed before declaring domain-wide performance; this is a **20-item purposive sample**.

## Reproduction (explicitly networked only when instructed)

- `python3 benchmarks/tavily_allegro_20_live.py` — **may generate live keyless API calls** only for missing snapshots; fixed 20-case budget, stops after access/rate errors.
- `python3 benchmarks/tavily_allegro_20_model_fallback.py` — **may generate live calls** only for 15 original misses; refuses to continue with a previous HTTP 429 receipt.
- `python3 benchmarks/analyze_tavily_20_offers.py` — offline baseline summary.
- `python3 benchmarks/analyze_tavily_20_adaptive.py` — offline fallback summary.
- `PYTHONPATH=.:tests python3 -m unittest tests.test_tavily_allegro_20case_benchmark tests.test_tavily_allegro_20_adaptive -v` — offline automated verification.

Code and experiments are isolated from the production TraceCart checkout, no GitHub Actions or production deployment changes.
