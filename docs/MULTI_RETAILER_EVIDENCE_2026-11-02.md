# Multi-retailer evidence audit — 2026-11-02 07:00 CET

## User-facing improvement

The cart pre-checkout page now accepts **1–4 competitor product URLs** from
distinct merchant hosts, one URL per line. Previously only one competitor
could be checked. Each candidate is independently evaluated against the
original selected source using the existing source retrieval and guards:
public HTTPS, robots.txt, no redirect bypass, seller-declared GTIN checksum,
pack/variant consistency, seller stock, seller-listed price and currency.

All outcomes, including denied pages, unknown prices, stock conflicts and
currency mismatches, are preserved in separate full-tree branches with
retrieval timestamps and SHA-256 where downloaded. The summary counts
retrieved pages separately from source-qualified comparisons. It never ranks
by delivered cost when shipping, fees or destination are unknown. Legacy
single-URL POST remains supported. There is no purchase or PayPal capture.

Up to four URLs, at most one per host, are validated before any network
request. A failure on one merchant does not erase evidence from the others.
Different domains do not necessarily imply independent legal ownership;
cross-domain ownership corroboration is a later research task.

## Fresh live-source investigation, 2026-11-02

Two pages were fetched by TraceCart's own permitted public-page retriever
on 2026-11-02 at 06:04 UTC (07:04 CET). These are seller claims, not
confirmed checkout totals.

- DMA: https://dma.sklep.pl/produkt/persil-kolor-proszek-do-prania-color-75pr-45kg/
  Seller-listed **89.26 PLN**, 75 declared washes, EAN **4015200031828**,
  seller claims InStock. Retrieval timestamp 2026-11-02T06:04:50.455562+00:00.
  Page SHA-256: `1dfd8880eb81dd9c178c1e1f5d26b3a4aa66f850188ddaef39a27e157406d804`.
- MOOP Market Latvia: https://moop.lv/collections/pulveri/products/persil-velas-pulveris-krasainai-velai-color-pulver-75
  Seller-listed **22.00 EUR**, 75 declared washes, seller claims InStock.
  TraceCart returned **barcode NOT_FOUND**. Retrieval timestamp
  2026-11-02T06:04:48.815708+00:00.
  Page SHA-256: `89debeaf53376adbc4d8c708a85b497c8e6ce5cb05c4dc126e9f97ef492387bc`.

### Important contradiction in search discovery

MOOP's **category listing** associates the product card with an image named
`4015200031828`, but the **actual product detail page** displays
`4015200034027` as a bare identifier. Neither should be silently
promoted to an explicitly seller-labelled GTIN on the product page.
This illustrates why a search result/card is only a discovery lead and why
the engine requires actual product-page identity evidence. Moreover,
MOOP prices in EUR and describes Latvian shipping, which does not
establish delivery to a Polish address. It is **not** an eligible
same-GTIN, same-currency, delivered-price comparison with DMA.

Source URLs and the exact content hashes above are retained as an audit
record; they do not imply price or availability after retrieval.

## Next research objective

Find another independently retrievable **Polish PLN** retailer offer
for EAN 4015200031828 with seller-declared in-stock status, no
conflicting pack/form claims, and shipping to the buyer's destination.
Then compare delivered costs with explicit provenance and expiry.
No invented offer or currency conversion; no PayPal capture.
