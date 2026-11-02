# Source-qualified SalePrice from Product JSON-LD (2026-11-02)

## Concrete result

TraceCart previously returned **UNKNOWN** for the price of the accessible
MAXPRONET product page:

https://maxpronet.pl/product-pol-84304-Proszek-do-prania-Persil-Color-75-pran-4-5-kg.html

Live retrieval on 2026-11-02 at 00:07:49 UTC (01:07:49 CET), after a
robots.txt preflight, revealed one Product JSON-LD object containing an
individual Offer with two distinct `UnitPriceSpecification` values:

- `https://schema.org/ListPrice`: **153.99 PLN** (reference/list price,
  **not** the active seller price);
- `https://schema.org/SalePrice`: **78.90 PLN** (seller-declared current
  promotional price).

The updated extractor now selects the explicit **SalePrice**, preserves
the reference price separately, and records the exact evidence method.
The seller's product title declares **75 washes**, yielding an arithmetic
**78.90 / 75 = 1.0520 PLN per wash** before shipping or discounts.
This is a seller claim, not a confirmed checkout price or independent
measurement of washing performance.

The observed HTML page SHA-256 was
`3836671d74329af846740697f28a3b1cc9558a5d234e36ee81d42da3405ceafd`.
The page JSON-LD stated `InStock`; real-time inventory was not independently
verified. It did not expose a GTIN in supported Product metadata. Although
the source HTML included a vendor-specific `code_producer` field, this
iteration **does not treat that field as a verified GTIN**.

## Conservative selection rules

1. A unique explicit `SalePrice` can establish the current *seller-listed*
   price; `ListPrice`, `StrikethroughPrice`, `RegularPrice` are reference
   prices only and are never used as the current offer.
2. If a direct `Offer.price` exists, it must agree with any explicit
   `SalePrice`; contradictions or multiple distinct sale prices produce
   **CONFLICTING_SELLER_PRICE_METADATA**, not a fabricated compromise.
3. A unique untyped `priceSpecification` is accepted as an offer price;
   multiple contradictory specifications are not.
4. `AggregateOffer.lowPrice` is not a purchasable merchant offer and is
   never accepted as a verified current seller price.
5. The original public-HTTPS, pinned DNS, robots, redirect and size limits
   remain unchanged. No private URL, login, 403 bypass, payment or capture.

## Comparison limits and next research step

Other public pages (StrefaChemii, Zawadzcy, NJ Drogerie) mention the same
manufacturer code **4015200031828**, but current structured extraction
does not establish a GTIN match for MAXPRONET. Therefore TraceCart does
**not** assert an identical product or calculate cross-store savings.
Next: source-scoped, collision-safe EAN/GTIN extraction from product details,
followed by direct re-fetch and a matching-GTIN two-store comparison.
Also include delivery and stock evidence before a delivered-price claim.
