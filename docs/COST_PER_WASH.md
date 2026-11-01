# Cost per wash — normalized source-qualified comparison

TraceCart computes the selected detergent's **seller-declared cost per wash**
only when the selected offer supplies BOTH a positive listed price/currency and
exactly one unambiguous wash/dose count stated in its product title.

## Reproducible actual observation — 2026-11-01

Ariel Color laundry powder 5.5 kg / 100 washes was retrieved from Amazon.pl
using the actual customer's link (ASIN B0FNPZQKMF). Amazon's structured
source data declared **76.99 PLN**; therefore the normalized seller-claimed
unit cost is **0.7699 PLN per wash** (before any delivery/discount/checkout
adjustments). The claim of 100 washes is from the product title, NOT an
independent measurement. The resulting value is not a quality score or
evidence of cleaning performance.

For the user-provided Allegro Persil URL, the path declared 75 washes,
but Allegro responded HTTP 403 and no price was verified. The correct
answer is **cost per wash unknown**, not zero and not an invented discount.

## Safety gates

Never infer doses from powder weight alone. Multiple conflicting wash
counts yield AMBIGUOUS_DECLARATION and no unit price. Missing or invalid
prices, currencies, or non-detergent products do not yield a wash cost.

The unit economics report is visible first in the pre-checkout UI and
preserved as a source-qualified node in the full decision tree and JSON.
No component authorizes a payment. Actual comparison between sellers
requires separately sourced, independently linkable, fresh retail
offers and equivalent detergent formulations/packages.
