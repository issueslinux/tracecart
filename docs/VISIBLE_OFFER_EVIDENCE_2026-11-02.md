# Real HTML offer evidence: 2026-11-02 (03:01 UTC / 04:01 CET)

## Practical change

TraceCart now reads **primary product price and stock** from two bounded,
generic markup forms when Product JSON-LD is absent:

1. A schema.org `Product > Offer` microdata scope with explicit
   `price`, `priceCurrency` and `availability` attributes.
2. A WooCommerce *primary product price widget* and explicit product
   stock widget, excluding minicart totals, related-product prices and
   crossed-out regular prices.

It also reads an **explicit EAN/GTIN-labelled specification table row**
even without JSON-LD, checks the GS1 check digit and rejects conflicting
identifiers. SKU, manufacturer code and generic `Kod produktu` are still
**not** EAN evidence. Conflicting/multiple visible prices fail closed;
no general-purpose text scraping or private endpoint is used.

The abbreviated seller-title form `75pr` is recognized as 75 declared
washes for the detergent unit-economics calculation. This is still a
seller claim, not a measured cleaning dose.

## Live, robots-compliant retrievals

All values below came from TraceCart's own `extract_product_page`,
which checks robots.txt and pins a public HTTPS address. They are
**seller declarations observed once**, not promises of current stock or
final checkout totals. No purchase or PayPal capture occurred.

| Retailer | Seller-listed price | GTIN evidence | Stock evidence | SHA-256 of retrieved page |
|---|---:|---|---|---|
| [DMA sklep](https://dma.sklep.pl/produkt/persil-kolor-proszek-do-prania-color-75pr-45kg/) | **89.26 PLN** | **4015200031828**, explicit `EAN (GTIN)` HTML table, valid checksum | WooCommerce `stock in-stock` | `98b14070237a69787e494b4bfb7886a6759f5f102be2d41e3a6ab0f104f636a8` |
| [RAWAX](https://www.rawax.com.pl/product/Persil-proszek-do-prania-4-5kg-Color-s4087) | **109.90 PLN** | **UNKNOWN**: `Kod produktu` is not GTIN evidence | schema.org Offer microdata `InStock` | Page content varied between requests; hashes retained in per-run provenance |
| [NJ Drogerie](https://njdrogerie.pl/proszki-do-prania/3877-persil-75-pran-45kg-color-pulver-niemiecki-proszek-do-prania--4015200031828.html) | **99.00 PLN** | **4015200031828**, JSON-LD GTIN13, valid checksum | JSON-LD `OutOfStock` | `a7af3c8175f87a35128580f0287f091cfe71eacb48dd9a6251488959c77b4ff0` |

DMA's `75pr` title + 89.26 PLN price yield **1.1901 PLN per declared
wash** before shipping. Note that search-indexed DMA price was older;
the direct live product page was **89.26 PLN**, not 88.33 PLN.

## Full comparison gate

- **DMA vs NJ Drogerie**: both seller pages claim matching EAN
  `4015200031828`, but NJ's JSON-LD explicitly says `OutOfStock`.
  Status: `SECOND_OFFER_NOT_AVAILABLE`; **no savings claim**.
- **DMA vs RAWAX**: both seller pages claim stock and show prices, but
  RAWAX exposes only `Kod produktu`, not an explicit EAN. Status:
  `GTIN_IDENTITY_NOT_ESTABLISHED`; **no savings claim**.

The selected product and competitor source metadata include URL, UTC
retrieval timestamp, SHA-256 and extraction method. The decision tree
retains the refusal reasons and source provenance. Actual shipping
prices and final checkout totals remain **UNKNOWN**.

## Next research

Find a second *currently available* retailer that explicitly declares
the same GTIN and price in permitted HTML/JSON-LD, then verify shipping
for one identical pack. Do not infer GTIN from vendor SKU, rely on stale
search snippets or bypass HTTP 403/robots restrictions.
