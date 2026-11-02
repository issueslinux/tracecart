# Product variant contradiction gate — 2026-11-02

**Problem:** Two product pages may carry the same checksum-valid, seller-declared
EAN/GTIN but contradict each other about which product is offered. A marketplace
may attach a product card for a colour detergent to an offer whose title
advertises a white detergent in a different pack size. GTIN equality alone
must not authorize a claim of savings.

## Observed research lead

Public search results for the Persil Color 4.5 kg / 75-wash product group,
EAN 4015200031828, included an archived marketplace listing whose offer title
advertised **"PERSIL PROSZEK DO PRANIA BIAŁEGO 7kg"**, while the product
attributes in the same listing showed **Color / 4.5 kg / 75 washes**.
Source candidate (not a TraceCart-verified retail offer):
https://allegro.pl/produkt/persil-color-pulver-proszek-do-prania-kolor-4-5-kg-75-pran-niemcy-c57e870f-64f0-49db-91de-502a3f216264?fromInactiveOffer=archived

This is a discrepancy in published product claims, **not evidence of
counterfeit goods**. The bot must not bypass HTTP 403 or robots restrictions
to inspect this marketplace. Prices shown by search results are unverified
and are not used in comparisons.

## Implemented outcome

`product_variant.check_variant_consistency` extracts only explicit claims
from the two seller titles: recognized brand, detergent form, white vs colour
use, and net pack weight normalized to grams. It reports conflicts and
ambiguous titles with the exact conflicting attributes.

`compare_live_offer` now blocks price-difference percentages and conditional
delivery break-even when either title is ambiguous or the two titles
explicitly contradict each other, **even when GTINs are identical and
both sellers claim stock**. The full tree/JSON records the variant evidence.

The gate is intentionally narrow: missing fields are UNKNOWN, not
invented; no contradiction is not proof of equivalence. It does not
attempt generic brand recognition or decide whether product formulations
are physically identical. It does not affect non-detergent categories.

## Next source-collection milestone

Retrieve two permitted, currently available seller pages with explicitly
labelled matching EANs, stock, and prices. Cross-check page title against
product structured data and on-page specification tables for internal
contradictions. Then obtain seller-declared shipping costs where available;
otherwise retain only a conditional delivery threshold. Never use a search
snippet as proof of a current purchasable offer.
