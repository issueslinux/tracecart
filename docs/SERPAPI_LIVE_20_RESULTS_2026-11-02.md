# Real SerpApi Google Shopping test: 20 products — 2 November 2026

**Status: completed real authorized Google Shopping API research, with explicit source-quality limitations.**

The user configured SerpApi credentials in a private local environment file on
the project host. These credentials were used only for bounded, opt-in
Google Shopping API research. The secret, account identifier and full raw
provider JSON were **not committed** to the public repository. The committed
JSON contains a compact derived evidence audit and five public seller checks.
The original normalized indexed snapshots remain local on the authorized host.

## Observed coverage — not completeness of the marketplace

| Metric | Actual result |
|---|---:|
| Research products submitted | 20/20 |
| Successful products with indexed seller rows | 17/20 |
| Products with direct Allegro links in the index | 12/20 |
| Products with Allegro-named Google Shopping cards | 17/20 |
| Indexed seller-price observations | 58 |
| Provider response errors | 2 |
| Clearly suspicious low index-price observations (flagged) | 3 |
| Non-comparable variant or non-retailer source exclusions | 11 |
| API calls attempted including failed retry requests | 42 |
| Cases with at least one nonflagged preliminary indexed candidate | 14/20 |

**Why two attempts failed at first:** the generic collector allowed only 200 KB
for API JSON, but a real Raspberry Pi Shopping result was 355,668 bytes.
The collector now permits at most 2.5 MB **only for the SerpApi adapter**,
with the legacy 200 KB limit retained elsewhere. Two failed initial calls
were retried after this fix. The separate total of 42 attempted calls
includes these earlier failed requests. The provider quota counter may
count fewer calls due to its own accounting.

**Critical independent warning:** on 2 November the SerpApi status page
reports that Google Shopping may return irrelevant or poisoned results.
This is corroborated by suspiciously low indexed prices in our sample.
Provider status: https://status.serpapi.com/

## Full 20-product result table

Every shown amount below is the lowest **remaining index-price hypothesis**
after conservative model/capacity/bundle checks and outlier detection.
It is NOT verified at checkout, does NOT establish exact GTIN identity
and is NOT claimed to be the lowest price in the whole market.

| ID | Product target | Indexed store rows | Direct Allegro link | Lowest remaining indexed hypothesis | Quality flags |
|---|---|---:|:---:|---|---|
| P01 | Stanley Air Kit OL 195 kompresor bezolejowy 8215190STN595 | 3 | Yes | Allegro — 260.00 PLN | 1 source/variant warning(s) |
| P02 | Raspberry Pi 5 8GB | 2 | No | None (insufficient comparable evidence) | 2 source/variant warning(s) |
| P03 | Apple iPhone 16 128GB | 5 | Yes | abfoto.pl — 3469.00 PLN | 2 extreme price warning(s) |
| P04 | Logitech MX Master 3S | 3 | Yes | RTV Euro AGD — 339.99 PLN | — |
| P05 | Samsung SSD 990 PRO 2TB | 3 | No | Morele.net — 1973.69 PLN | — |
| P06 | Sony WH-1000XM5 | 3 | Yes | Allegro — 939.00 PLN | — |
| P07 | Bosch GSR 12V-15 wiertarko-wkretarka | 4 | Yes | Kaufland.pl - DINOTECH — 309.99 PLN | — |
| P08 | Makita DDF482 wiertarko-wkretarka | 3 | No | None (insufficient comparable evidence) | 3 source/variant warning(s) |
| P09 | Garmin Forerunner 265 | 5 | No | Komputronik.pl — 1455.00 PLN | 1 extreme price warning(s) |
| P10 | Nintendo Switch OLED | 5 | Yes | Allegro — 1449.00 PLN | 2 source/variant warning(s) |
| P11 | WD Black SN850X 2TB | 4 | Yes | Allegro — 1987.36 PLN | 1 source/variant warning(s) |
| P12 | Dyson V15 Detect | 3 | Yes | Allegro — 2600.56 PLN | — |
| P13 | Philips OneBlade QP2724 | 3 | Yes | Allegro — 84.96 PLN | — |
| P14 | Kindle Paperwhite 12 generacja 16 GB | 0 | No | None (insufficient comparable evidence) | API error |
| P15 | Xiaomi Redmi Note 13 Pro 8GB 256GB | 2 | Yes | Allegro — 499.00 PLN | — |
| P16 | LG 27GP850-B 27 cali | 2 | Yes | None (insufficient comparable evidence) | 2 source/variant warning(s) |
| P17 | Samsung T7 Shield 1TB | 3 | No | Foto - Plus — 1099.00 PLN | — |
| P18 | DeWalt DCD796 wiertarko-wkretarka | 0 | No | None (insufficient comparable evidence) | API error |
| P19 | ASUS TUF Gaming A15 FA507 laptop | 0 | No | None (insufficient comparable evidence) | search cards only |
| P20 | Oral-B iO Series 6 szczoteczka | 5 | Yes | Allegro — 489.99 PLN | — |

## Why price validation matters

- Stanley Air Kit (P01): **Allegro 260.00 PLN** was indexed; the same
  result group also indexed OBI 320.52 PLN and Bricomarché 439.00 PLN.
  The queried Allegro offer ID differs from an earlier independently
  observed Allegro offer. A price change for the *same listing* was NOT
  established. The index alone does not confirm seller GTIN or stock.
- Apple iPhone 16 128 GB (P03): the index returned **349.90 PLN** and
  **399.90 PLN** alongside 3469–3999 PLN. The two extreme low records
  are explicitly flagged as *unverified anomalous prices*, not endorsed.
- Garmin Forerunner 265 (P09): the index returned **48.79 PLN** alongside
  offers around 1455–1535 PLN. 48.79 PLN is flagged and excluded from
  the provisional lowest-price calculation, but remains in the evidence.
- A direct link to E-Katalog gave HTTP 404 and does not identify an
  actual retailer listing. Such aggregators are excluded from ranked
  seller-page candidates, rather than silently treated as merchants.
- A *bundle* or product with conflicting capacity/model is not compared
  to a bare product even when the search index displays a lower price.
  This conservative gate can also defer genuine offers to manual review.

## Independent spot checks of five indexed URLs

| Case | Source | Index product price | Direct retailer source result |
|---|---|---:|---|
| P03 | Media Expert | 349.90 PLN | HTTP_403 |
| P09 | RTV Euro AGD | 48.79 PLN | HTTP_403 |
| P17 | Foto - Plus | 1099.00 PLN | FETCHED — seller-listed 1099.00 PLN, price matched index |
| P01 | OBI.pl | 320.52 PLN | HTTP_404 |
| P10 | E-Katalog | 999.00 PLN | HTTP_404 |

**Only 1/5 checked retailer pages was retrievable**, and its listed
price matched the indexed quote. The other four pages returned HTTP 403
or 404; they must NOT be counted as incorrect or correct prices.
The fetched Foto-Plus seller page declared a Samsung T7 Shield 1 TB
at **1099.00 PLN** and included a seller-claimed GTIN.
This does not establish the indexed price accuracy rate across 20 products.

## Reproduction, code, and remaining acceptance gate

- Full derived 20-product audit: [JSON](../examples/serpapi_shopping_20_real_2026-11-02.json).
- Five independent retailer requests and source SHA-256 where available:
  [JSON](../examples/serpapi_shopping_5_spotchecks_2026-11-02.json).
- Bound and checkpoint API usage: [serpapi_live_capture.py](../benchmarks/serpapi_live_capture.py).
- Re-evaluate normalized observations without consuming API credits:
  [audit_serpapi_live_capture.py](../benchmarks/audit_serpapi_live_capture.py).
- No DataForSEO credentials were configured, so comparative provider
  coverage and accuracy remain NOT MEASURED.
- The 20-product sample is purposive, not representative of the Polish
  online retail market.
- A seller name or model token alone cannot establish exact SKU/EAN,
  seller availability or checkout totals.

**P0 outcome:** Search-First is viable for discovering Allegro offers:
12/20 products had a clickable Allegro-indexed offer, despite the direct
Allegro server-side 403 barrier. However the current shopping index has
quality and freshness risks; TraceCart must not claim an automatically
verified cheapest offer until independently checked same-SKU pricing
is consistently available. This is not an approval to automate purchases.

Shipping/ETA parser expansion remains paused.
