# Store-agnostic product URL intake (2026-11-01)

## Requirement

TraceCart must accept a single product URL from **any public HTTPS
store**, not require a specialized adapter for each store. The preferred
path is extraction of the actual page, followed by background research.
A blocked product page should not abort *all* decision research when a
safe, clearly incomplete identity can be derived from the supplied URL.

## Actual processing order

1. **Validate and normalize user URL.** Only HTTPS DNS hosts; no embedded
   credentials, local/internal IP hosts, nonstandard ports or fragments.
   Drop marketing/search tracking parameters and path segments such as
   `/ref=...`. Keep a strictly validated numeric offerId when provided.
2. **Public HTTPS page fetch.** DNS resolution is checked for public IPs
   and pinned to the socket; TLS certificates are checked. Bounded size
   and timeouts, no cookies. Check `robots.txt` before the product page.
3. **Limited HTTP redirects.** Follow at most two redirects within the
   *same hostname*, rechecking target path against the robots policy.
   Never automatically follow cross-origin redirects, redirects to
   blocked paths or redirect loops. A blocked redirect leads to step 5.
4. **Use real structured source content when available.** Parse a single
   Product JSON-LD object; fall back to limited OpenGraph/HTML.
   Preserve source URL, retrieval timestamp, page digest, seller-claimed
   price/currency, availability and EAN when present. Decode HTML entities
   in titles. The publisher's price does not equal a completed checkout.
5. **General, store-independent URL-only recovery.** If page retrieval
   fails due to 301/403/404/429, robots policy, unsupported MIME or
   missing/ambiguous product metadata, extract only a readable
   product-name candidate from the URL path (e.g., words in Amazon,
   Allegro, or other stores' human-readable slugs). Retain path-based
   identifiers as *URL identifiers, never as barcodes*. Price, stock,
   full description and EAN remain **unknown**. Mark
   `intake_status=URL_ONLY_UNVERIFIED` and preserve the precise failure
   *code*, never an invented page digest. If URL is only an opaque
   identifier, use `INSUFFICIENT_URL_DESCRIPTION`, not a guessed name.
   This fallback is local parsing of the user's input and does not
   fetch the blocked page or evade access restrictions.
6. **Continue conditional research** using any available evidence and
   product-specific questions. No automatic payment. Offer candidates
   without actual verified retailer prices are NOT shop offers and must
   not be compared as if prices are known.
7. **Show concise summary + expandable audit tree** with the original
   source status, what was retrieved versus inferred and all unknowns.

## Live case: actual Amazon URL

The customer provided a lengthy `www.amazon.pl/.../dp/B0FNPZQKMF/ref=sr_1_6?... `
link. The old app failed on HTTP 301 for the tracking-heavy URL.
After *generic* URL normalization, the same source was successfully
retrieved as
`https://www.amazon.pl/Ariel-Proszek-rozpuszczanie-usuwanie-zapach%C3%B3w/dp/B0FNPZQKMF`.
On 2026-11-01 Amazon's Product JSON-LD supplied a seller-claimed
**Ariel Color 5.5 kg, 100 washes**, price **76.99 PLN** and
`InStock`. No EAN was found. This is historical source evidence and
is NOT a guarantee of current price or actual checkout total.
Live research continued with 17 questions and eight *catalog*
alternatives; no independently verified competing store prices.

## Scope and production limitations

We cannot guarantee that **every web shop permits extraction**.
JavaScript-only data, authentication gates, CAPTCHAs, legal restrictions,
robots exclusions, site outages and cross-origin redirects may stop
page retrieval. No general software can bypass those restrictions
legitimately. Where permitted, an authorized store connector/API is
the robust source for current offer prices and availability.

Do not add per-store scraper branches as the default reaction to
a failure. Add an authorized adapter only where the merchant has
provided a documented interface or the generic extractor cannot
meet product requirements.

**The initial link and research run are not a payment authorization.**
