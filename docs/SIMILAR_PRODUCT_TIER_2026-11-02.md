# Similar-tier shopping alternatives: brands and model numbers may differ

Implemented and run on **2 November 2026**. The default Search-First shopping
UI now includes an alternative-product layer, *separate from exact-GTIN/variant
seller-price verification*. It compares indexed products for comparable
functional specifications and price bands; it **does not** require an identical
model number or brand.

## What has changed

- A bounded model-independent classifier detects a supported product category
  before comparing numerical claims. Example categories include **electric
  bicycle, bicycle, electric scooter, compressor, SSD, smartphone** and several
  basic consumer-electronics groups. Unknown category or accessories cannot be
  advertised as a functional equivalent.
- For e-bikes, title-level claims are compared: rated motor power (W), battery
  amp-hours (Ah), wheel diameter (inches), number of gears, assist speed and
  advertised range. Range is *marketing*, not independently tested.
- When **both battery voltage and Ah** are supplied, a nominal Wh figure is
  derived to compare batteries. Equal 15 Ah at 36 V and 48 V is **not proof of
  equal energy**. Missing voltage is explicitly disclosed.
- A matching product category with a **different model/brand** can be marked
  `SIMILAR_TECHNICAL_TIER_INDEX_ONLY` when there are enough comparable
  specifications. Missing important specs cause
  `POSSIBLE_ALTERNATIVE_NEEDS_SPEC_CHECK`, not silent equality.
- Large core-feature differences (e.g. 250 vs 500 W, 15 vs 5 Ah, 1 vs 2 TB
  SSD) are kept in the evidence but not recommended as the same technical tier.
  Used/refurbished status in a title is disclosed and not equated to 'new'.
- A price band is **independent of technical fit**. When the selected seller's
  listed price is unavailable (HTTP 403), the system can use the median of
  three or more technically similar indexed prices as a clearly marked
  *approximation*. This is a local index cohort, not the current price of the
  selected offer or an estimate of true product quality.
- Search-result anomalies and incomplete information remain visible. Results
  do not obtain an invented EAN, seller stock, shipping total, manufacturer
  documentation or checkout authorization.

## Actual URL-first end-to-end result

Source: user-submitted Allegro electric bicycle, offer
`18482612668`. The original marketplace source was inaccessible to the
TraceCart reader (HTTP 403), but the authorized SerpApi Google Shopping
response returned 12 bounded index cards. Google Product details returned an
error; the search cards were preserved.

The new alternative layer returned:

| Indexed example | Price from Google Shopping | Classification |
|---|---:|---|
| Rower 250 W / 15 Ah / 27.5 in / Shimano 7S (Allegro) | 2469.05 PLN | Similar declared technical tier |
| Another 250 W / 15 Ah Shimano 7S indexed card (Allegro) | 2469.00 PLN | Similar declared technical tier |
| ALLGOBIKE AM27 250 W, 15 Ah (Allegro) | 2599.00 PLN | Similar declared technical tier |
| Orzel C27 250 W, 15 Ah, 27.5 in (Allegro) | 3399.00 PLN | Similar declared technical tier |
| Evercross EK15 250 W, 27.5 in (Decathlon) | 3028.99 PLN | Possible alternative; battery capacity unconfirmed |
| iwobike 250 W MTB 27.5 in | 3919.00 PLN | Possible alternative; battery capacity unconfirmed |

**6/12** result cards have close declared technical specifications;
**4/12** are potentially useful alternatives with missing technical fields;
**2/12** have too few fields for a reliable classification.

The only available price reference was the **2534.03 PLN median of similar
indexed cards**. It is NOT the verified purchase price of the originally
submitted bicycle (an external indexed listing for the submitted offer had
displayed 2649 PLN). Multiple indexed cards may be from the same marketplace;
the cohort median is neither representative of all Polish retailers nor proof
of a discount.

### What the score means

Technical matching figures, such as 85/100, are **heuristic agreement of
explicit title specifications**, not product quality, safety, reliability
or laboratory-performance scores. Components missing from title-only index
data include battery cell brand and actual Wh (if voltage unknown), brake
type/quality, bike frame construction, warranty, real-world measured range,
battery degradation and seller condition. They must be investigated separately
before a purchase decision.

### Evidence and acceptance

- [Actual e-bike result, all ranked candidates, evidence status and
  provenance](../examples/live_bike_similar_tier_2026-11-02.json).
- The exact-model/GTIN comparisons and safety gates remain in the existing
  architecture. The alternative ranking is separate and **does not** elevate
  an indexed price into a seller-verified price.
- [Earlier provider failure and preserved 12-card search results](ALLEGRO_BIKE_SHOPPING_FALLBACK_2026-11-02.md).

The full running local app was tested through its real `/cart/add` form,
background URL-first job, persisted JSON and HTML output on a separate test
port. **359/359 Python tests pass**. No secret or provider API request URL
containing a key is written into version control.

**Next meaningful research:** finding independent test/review sources for
component quality and validating indexed prices with real offer pages. These
capabilities have not been implemented as part of this technical-tier update.
