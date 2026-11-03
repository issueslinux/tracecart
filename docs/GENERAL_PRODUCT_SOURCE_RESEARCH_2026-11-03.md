# General product-source research and graphical page fallback — 2026-11-03

## Scope change: no model-specific scraping

This phase deliberately moves away from building a separate review scraper
for each bicycle/laptop model. The common evidence extractor applies to
**electric bicycles, laptops, smartphones, SSDs, printers, compressors,
headphones, tools, appliances, accessories, consumables, and UNKNOWN
categories**. It reads reusable patterns in actual product pages rather
than relying on fixed hardware specifications.

The original bounded Notebookcheck 15Q8X10 independent-review adapter is
preserved for its two measured laboratory results. The NEW generic path
does not assume that manufacturer marketing figures are lab measurements.

## Inputs and discovery strategy

For each indexed offer, run up to three independently documented source
checks using already available information:

1. **Actual supplied product URL** or real merchant link supplied by the
   original Shopping index. A Google Shopping search link is not a retailer
   product page.
2. **Existing search discovery records** from the saved report, but only if
   the search result states an explicit matching brand and model; a
   matching battery/motor/price alone is insufficient.
3. **Hypothesized brand .com homepage**, accepted only as a discovery
   candidate. The homepage must visibly identify the same brand AND
   contain a *real same-origin* product hyperlink matching the offer's
   model token. If no direct link is present, inspect a bounded sitemap
   and at most two product sub-sitemaps. Do not construct or guess a
   model-specific product URL. Ambiguous links are rejected.

A strong brand+model candidate can be recognized even when the brand
occurs in the middle of a Polish title. Numeric model identifiers such
as Samsung 990 and Garmin 265 are supported; "250 W", "100 km" or
"15 Ah" are deliberately NOT treated as model numbers.

No per-product manufacturer domain registry was introduced, and no new
paid SerpApi searches are run. Manufacturer sites without a suitable
homepage/sitemap link, sellers withholding direct URLs and sites denying
robots access remain honest missing-source cases. A future search
provider can supply URLs via the existing `source_discovery.web_hits`
contract, with the same verification gates.

## Evidence extraction across categories

Parse JSON-LD Schema.org Product/ProductModel/IndividualProduct,
`additionalProperty`, real HTML tables, description lists and
visible `Field: value` lines. Fields include:

- **Electronics:** CPU/GPU, RAM, storage, capacity, display, network,
  power, battery, connectivity, resolution, warranty, repairability.
- **Vehicles/tools/appliances:** motor, range, brake, frame, voltage,
  current, pressure, noise, energy, volume, dimensions, durability.
- **Household/consumables:** ingredients, materials, filter/cartridge,
  capacity, lifetime, color, size and other named specifications.

At most 12 source facts are retained from each page. A Product schema
must match the strong model token in its own product name/model, not
only in an unrelated sidebar or metadata; model-ambiguous pages do not
become confirmed source facts. Simple title-overlap matches remain
explicitly **unverified identities**.

Each extracted fact stores the **actual retrieved URL, SHA-256 of the
downloaded HTML, retrieval timestamp, field name, field value, page
identity status, source kind and exact-SKU caveat**.

**Source declarations are not independent measurements.**
The graph now has `source_declaration` nodes and an independent
`documented_product_declarations` statistic. Manufacturer-domain
candidates, sellers and other publishers are kept separate from
`INDEPENDENT_TEST` sources. Sourced values never become checkout
prices or verified exact-retailer-SKU answers.

## Graphical browser, not a 403 bypass

When an ordinary source fetch has **already passed robots.txt, public-IP
HTTPS validation and returned a non-challenge HTTP 200**, but HTML
does not expose usable product properties, TraceCart can optionally
render it using a **real graphical Chromium inside a temporary Xvfb
display**. It uses no personal browser profile or cookies.

To enable:

`TRACECART_GRAPHICAL_BROWSER_FALLBACK=1`

Safety and capacity rules:
- Only a single concurrent browser renderer (no 16 simultaneous Chrome
  instances). Timeout 14 seconds in the Node renderer / 19 seconds in
  Python; isolated disposable profile and strict output limits.
- Browser DNS is pinned to a validated publicly routed IPv4 for the
  approved hostname; CDP request interception blocks **all other
  origins**, including private IP hosts, redirects and third-party
  subresources. Only same-origin HTTPS is allowed.
- Does not handle CAPTCHA, Cloudflare challenges, logins or 403
  responses. Those remain `NOT_RETRIEVED` or `NO_MATCHED_SOURCE`.
- Rendering may be less complete when a page requires third-party JS
  assets, scripts or external API calls. This is a deliberate privacy
  and SSRF constraint, not a reason to disable network isolation.
- Chrome on the authorized host was tested in graphical Xvfb mode;
  DOM extraction completed successfully in about 3.3 seconds on a
  publicly accessible manufacturer product page.
- Node 22+ with built-in WebSocket, Chromium and `xvfb-run` are needed
  for this *optional* fallback. Static extraction and the rest of the
  app work without them.

## Verified replay, not fabricated results

Saved **13-offer Allegro e-bike job**
`LoHWENthHlgccaUCtbOdQkCO` was replayed on an **isolated SQLite
backup**. This generic, non-model-specific engine found the real
ALLGOBIKE homepage product link, fetched the manufacturer's AM27 HTML
and extracted **12 named declared specifications**, including the
maker's advertised pedal-assist range **50–85 km**, electric-only
range **40–50 km with a 65 kg rider**, 36 V/15 Ah battery and 250 W
motor rating. The selected generic Allegro item was NOT silently
declared an identical SKU. The family-linked candidate index card is
only a research lead.

**Graph counts:** 13 offers, 12 distinct documented claims from one
fetched page, zero independent instrumented tests for this bike, zero
exact-SKU confirmations, zero verified seller checkout prices.
The original saved report remained byte-for-byte equivalent and
no paid search queries were sent. The source still must be independently
checked; a 100 km seller title is not a proven measured range.

Six different category fixtures plus native HTML tables and JSON-LD
were exercised using a shared extractor, including security tests for
wrong-model pages, inaccessible robots policies, unsafe URLs, false
model identity from numbers, false lab status and GUI-renderer
provenance. All legacy independent Lenovo findings remain separate.

## Next engineering priorities

1. Add a legitimately configured cross-domain web search provider
   with a strict per-job query budget and caching, because broad
   discovery cannot reliably identify all public manufacturer/test
   sources using existing Shopping links and sitemaps alone.
2. Add robust testing-specific extractors for independent performance
   methodologies that name the exact tested SKU; generic manufacturer
   specs must not be reclassified as lab results.
3. Add second-source corroboration, contradiction detection and
   current seller/checkout price verification. Missing sources remain
   unresolved questions, not negative product findings.
