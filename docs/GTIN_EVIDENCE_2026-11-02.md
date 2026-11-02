# Source-qualified GTIN identity and stock gates — 2026-11-02

## Concrete improvement

TraceCart now accepts product GTIN claims from Product JSON-LD
(`gtin8`, `gtin12`, `gtin13`, `gtin14`, `gtin`), explicitly named
`additionalProperty` entries, explicit product metadata and EAN/GTIN-labelled
product specification table rows (when one Product JSON-LD is present).
It records the evidence method, checks the GS1 modulo-10 check digit,
rejects conflicting claims and normalizes valid UPC-A/EAN-13 leading-zero
representations to the same GTIN-14 identity for comparisons.

**Not EAN evidence:** numeric SKU, MPN, `code_producer`, generic
"Kod produktu", arbitrary page numbers, URL slug IDs and search snippets.
They are not promoted to a matching GTIN merely because they contain
13 digits. A checksum is necessary, **not proof of genuine product
identity or authenticity**. Seller declarations can be wrong.

The comparison now also rejects an explicitly unavailable selected
product, mismatched selected source URLs/identities, and `www` vs
non-`www` links to the same merchant. No automatic purchase is possible.

## Actual public-source recheck (2 November 2026)

Pages were fetched by TraceCart's robots.txt-respecting HTTPS reader.
The times and hashes below describe **the downloaded HTML** and its
seller-declared structured fields, not a verified checkout transaction.

1. MAXPRONET, Persil Color 4.5 kg / 75 washes:
   https://maxpronet.pl/product-pol-84304-Proszek-do-prania-Persil-Color-75-pran-4-5-kg.html

   At **01:08:19 UTC**, `SalePrice` **78.90 PLN**,
   `InStock` seller claim, but **no explicitly declared GTIN** in
   supported fields. A vendor-specific `code_producer` value
   `4015200031828` was present in the page, but is deliberately
   **not** upgraded to a GTIN. Page SHA-256:
   `5fcf3bca18768953a2f49f5a0849c4ea8a7109228b4ef2f8f06f971760ee7726`.

2. NJ Drogerie, Persil Color Pulver 4.5 kg / 75 washes:
   https://njdrogerie.pl/proszki-do-prania/3877-persil-75-pran-45kg-color-pulver-niemiecki-proszek-do-prania--4015200031828.html

   At **01:08:21 UTC**, `Offer.price` **99.00 PLN**,
   `Product.gtin13` **4015200031828** with valid check digit,
   but the machine-readable offer declared **OutOfStock**.
   Page SHA-256:
   `9356ae3f7e2fb150d08c8289fff1d2fd450ea036b832248b395d7ffbe09e8233`.

3. RAWAX, Persil Color 4.5 kg:
   https://www.rawax.com.pl/product/Persil-proszek-do-prania-4-5kg-Color-s4087

   At **01:08:22 UTC**, a table displayed `Kod produktu:
   4015200031828`, but no explicit GTIN and no current machine-readable
   price in supported fields. TraceCart correctly leaves both unknown.
   Page SHA-256:
   `b59e7c29b6298c69a6cd724dccdacb391aed8d1dc2b209df0921c62487f73b81`.

**Outcome:** two independent merchants publish different numeric
seller-listed prices for a similarly named Persil product, but the
first lacks a directly asserted GTIN and the second says OutOfStock.
Therefore the system still **does not calculate a savings percentage**
or declare an equivalent purchasable alternative. The numeric price
difference must not be confused with a defensible buyer recommendation.

## Next useful research

Locate two currently accessible and in-stock retailer product pages
that explicitly publish the same valid GTIN and separately source their
actual listed prices. Then check delivery charges, coupon/loyalty
conditions, freshness, formulation, and seller identity before any
*delivered-cost* claim. Keep counterevidence in the critic tree.
