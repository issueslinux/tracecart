# Shipping break-even and explicit stock evidence

Implemented 2026-11-02. TraceCart can now give a useful **conditional
delivery-cost threshold** when two independent merchants have source-retrieved
pages with the same checksum-valid seller-declared GTIN, same currency,
seller-declared listed prices, nonconflicting wash counts and **both pages
explicitly claim stock**.

## Practical result

If selected listing = 80.00 PLN and another independent seller lists the
same claimed GTIN at 72.00 PLN, the second seller's **listed-price advantage
is 8.00 PLN for one pack**. The cheaper listing remains cheaper after shipping
and fees **only if** its shipping+fees are **less than 8.00 PLN more** than
the selected seller's shipping+fees. At exactly 8.00 PLN extra the totals tie.
This is a *mathematical conditional scenario*, NOT a claim that either
delivery fee is known, that the product is authentic, or that checkout
pricing will match. The 80.00/72.00 example is an artificial test fixture.

If the selected offer is cheaper, the threshold reverses direction. Equal
listed prices leave shipping/fees as the deciding unknown. The source
report and UI expose the threshold and preserve the complete provenance.

## Availability evidence

- `schema.org/InStock` or `LimitedAvailability` is accepted as an explicit
  seller stock claim, **not an independent inventory verification**.
- `OutOfStock`, `SoldOut`, `Discontinued` are explicitly unavailable.
- `PreOrder`, `PreSale`, `BackOrder`, missing, unrecognized or malformed
  values are NOT confirmed immediately purchasable.
- Missing stock claims for **either** merchant prevent the listed-price
  comparison and shipping break-even; the second seller's observed price
  remains visible separately without any savings assertion.
- A different/missing GTIN, missing/contradictory price, unknown currency,
  conflicting dose count, or the same merchant also blocks comparison.

## Public-source discovery (2026-11-02, NOT machine-verified pair)

A public search for Persil Color 4.5 kg / 75 washes, GTIN
4015200031828, surfaced these *candidate* sources:

- [RAWAX](https://www.rawax.com.pl/product/Persil-proszek-do-prania-4-5kg-Color-s4087):
  listed 109.90 PLN and 1 item in stock, but identifies the 13-digit number
  as **Kod produktu**, not explicitly GTIN/EAN. The automated GTIN identity
  gate must not silently promote that vendor code to a barcode.
- [StrefaChemii](https://www.strefachemii.pl/pl/p/Persil-Color-DE-4%2C5-kg-75-pran-Proszek-do-koloru/2321):
  listed 97.48 PLN and explicit EAN 4015200031828, but **temporarily out
  of stock**.
- [Allegro](https://allegro.pl/produkt/persil-color-pulver-proszek-do-prania-kolor-4-5-kg-75-pran-niemcy-c57e870f-64f0-49db-91de-502a3f216264?offerId=18955499980):
  public search displayed 72.00 PLN and EAN 4015200031828; direct
  TraceCart access previously received HTTP 403, so this **is not an
  admissible live verified offer** and must not be used in the engine.
- [Czysto-shop](https://czysto-shop.pl/produkt/persil-45kg-proszek-do-prania-kolor-75pr-de/):
  unavailable and shows a **different** barcode 4015200034980.

None establishes a machine-retrieved, available, same-GTIN pair for
a claimed checkout saving. Prices and stock may change.

## Next research milestone

Find two robots-allowed, publicly retrievable, independent retailers with
explicit identical GTINs, current listed prices and explicit stock claims.
Read delivery rates only where source data identifies an applicable
delivery destination/method and eligibility. Otherwise retain the break-even
threshold and `actual_delivered_price_comparison = UNKNOWN`. No PayPal
capture, no automated purchase, no bypass of 403 or robots.txt.
