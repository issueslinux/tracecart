# Intra-page evidence crosschecks (2026-11-02)

## User-visible consequence

The selected product's retailer page is **not one trusted record**.
It can simultaneously publish a Product JSON-LD name for Persil Color
4.5 kg, an OpenGraph product title for Persil White 7 kg, a price
for a different variant, or contradictory stock and pricing metadata.

TraceCart now audits *within the same page* before attributing a
seller-listed price and GTIN to a particular product. It crosschecks:

- Product JSON-LD name versus product-scoped `og:title` for explicitly
  stated detergent brand, color/white use, powder/liquid/capsules form,
  and net weight (normalizing kg and g).
- Explicit Product.brand against an explicitly named brand in either
  product title.
- Product JSON-LD Offer price against primary WooCommerce/schema.org
  visible price, when both are present. Two differing prices are
  **unknown**, not a choice of the cheaper one.
- JSON-LD availability against primary product stock widget, when both
  are explicit and their statuses contradict.

A contradictory or ambiguous product identity blocks attribution of
price and GTIN. Metadata preserves the observed-but-unattributable
price and the exact conflicting claims, while the selected offer
receives no usable price, GTIN, or availability for comparison.
A stock contradiction clears the availability claim, preventing a
false assertion of immediate stock. A price contradiction clears
the listed price. No payment operation is added.

This is a conservative deterministic critic, not a proof that two
matching titles or seller claims identify authentic goods. It does
not compare generic page `<title>` SEO text or recommendation widgets
to product identity, because those can contain unrelated names.
The check applies only to detergent identities with recognizable
attributes. Other categories retain the existing stricter GTIN,
source, availability and price requirements.

## Evidence and test scope

Nine focused tests cover the real-world Color 4.5kg / White 7kg
conflict pattern, explicit brand mismatch, internally ambiguous title,
unit-normalized matching titles, missing OpenGraph, conflicting and
agreeing seller prices, conflicting stock, and integration with
second-offer comparison. All cases use **synthetic HTML fixtures**
constructed to reproduce the patterns; they are NOT claims that a
specific live retailer currently has these contradictions.

## Current external-source research

A fresh public search on 2026-11-02 for GTIN `4015200031828`
identified a public Allegro listing for Persil Color 4.5 kg / 75 washes
advertising 72.00 PLN plus a stated 10.49 PLN shipping option (or 0
PLN under an eligibility-dependent Smart condition). This is a
**search-index observation**, not a TraceCart verified merchant fetch;
previous direct automated access to Allegro was HTTP 403. It must not
be promoted to a verified comparison or final delivered price.
Reference:
https://allegro.pl/produkt/persil-color-pulver-proszek-do-prania-kolor-4-5-kg-75-pran-niemcy-c57e870f-64f0-49db-91de-502a3f216264?offerId=18955499980

A StrefaChemii product page shows EAN 4015200031828 and a delivery
starting at 14.90 PLN, but explicitly marks the product temporarily
unavailable. It is not an eligible in-stock competitor.
Reference:
https://www.strefachemii.pl/pl/p/Persil-Color-DE-4%2C5-kg-75-pran-Proszek-do-koloru/2321

Next research objective: find another **directly accessible**, in-stock,
same-GTIN seller offer with verified current price and delivery for the
chosen destination, or transparently report that such evidence is absent.
