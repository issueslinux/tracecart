# TraceCart — Universal Product Snapshot Extractor v1 (2026-11-03)

## Result and scope

The **first provider-neutral, network-free parsing contract** is implemented in
`universal_product_extract.py`:

`extract_snapshot(source_url, body, content_type="text/html", acquisition_method="STATIC_HTML", http_status=200, acquired_at=None)`

The parsing function does **not access websites**, solve CAPTCHA, execute scripts, log in,
verify the seller's current checkout total, or use an external inference API. A
fetcher/browser/feed must first obtain an authorized source snapshot. The module
then analyzes that same source with deterministic, bounded parsing.

A separate `universal_source_acquisition.py` adapter provides
`acquire_public_product(url, fetch=None, render=None, enable_render=False)`
for **explicitly requested** public-page acquisition. It reuses the existing
DNS-pinned HTTPS and robots-checking transport from `product_intake`, permits
only same-host robots-checked redirects, and returns explicit blocked/failed
receipts instead of masking errors. It can optionally call the existing isolated
Chromium renderer only after a successful robots-approved HTML response.
It does not accept or forward browser credentials, and does not retry 403/CAPTCHA.

Supported transport *origins* (labels only; no implied trust): `STATIC_HTML`,
`RENDERED_DOM`, `AUTHORIZED_JSON`, `USER_BROWSER`, `INDEX_SNAPSHOT`.
Supported MIME types: `text/html`, `application/xhtml+xml`,
`application/json`, `application/ld+json`. No new dependencies.

Extraction reuses **TraceCart's preexisting product_intake and visible-offer
safety gates**. Specifically, it preserves fail-closed treatment of:
- multiple Product JSON-LD records and multi-Offer listings;
- JSON-LD vs primary visible-price / OpenGraph contradictions;
- sale price vs crossed-out ListPrice;
- conflicting product identity across explicit page claims;
- invalid GS1 GTIN checksum and explicitly contradictory identifiers.

It also reads bounded Product JSON-LD `@graph` and named JSON API `product`
roots; requires an actual Product or explicitly supported HTML seller metadata;
captures title, brand, model, SKU, GS1-normalized GTIN, seller, explicit Offer
price/currency, condition, availability and **country-scoped** shipping rate.
Arbitrary numbers in page text do not establish a price. JS DOM is consumed only
after an external renderer supplies HTML; scripts are **not** executed by this
extractor.

## Provenance contract and failure states

Every output contains `status`, `fields`, `evidence`, `conflicts`,
`shipping_claims`, `source_url`, `snapshot_sha256`, `acquired_at`,
`acquisition_method`, and explicit `seller_verified=false`,
`checkout_verified=false`. Evidence rows preserve a method, JSON pointer
(where applicable), snapshot hash and time for **each claimed field**.

A successful extraction is
`PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED`: it indicates a structured
page declaration, **not confirmed merchant availability or checkout price**.
`INDEX_SNAPSHOT` always yields `INDEX_ONLY_UNVERIFIED` for identified
products; an index price is never promoted into current seller evidence.

Failures are explicit: `ACCESS_DENIED`, `ACCESS_CHALLENGE`, `HTTP_ERROR`,
`CONTENT_EMPTY`, `UNSUPPORTED_CONTENT_TYPE`, `INVALID_JSON`,
`PRODUCT_NOT_IDENTIFIED`, `MULTIPLE_PRODUCTS_AMBIGUOUS`,
`IDENTITY_CONFLICT`, `PRICE_CONFLICT`, `PRODUCT_FOUND_NO_PRICE`.

The caller must perform its own acquisition policy, origin/redirect,
robots and network safety checks, and must confirm variant/offer ID, seller,
stock, shipping location and final checkout amounts before recommending an
actual purchase. This module is *not wired into checkout or production*.

## Offline verification

Frozen cases:
`benchmarks/fixtures/universal_product_extract_v1.json`

- **18 synthetic** cases; five formats (HTML, microdata, JSON-LD, JSON API,
  rendered DOM), multiple unrelated fictional merchants;
- price crosschecks, list-versus-sale, condition, GTIN, explicit destination
  shipping rate, multi-product/multi-offer ambiguity, index-only observation,
  plain unstructured numbers, HTTP 403, HTTP 200 with challenge, invalid JSON.
- Source URLs and prices in this corpus are **synthetic**, not scraped live
  merchant results. This suite verifies extraction logic, **not market recall**.

Commands (offline):

```sh
PYTHONPATH=. python3 -m unittest tests.test_universal_product_extract tests.test_universal_source_acquisition tests.test_universal_extract_cli -v
python3 benchmarks/evaluate_universal_extract.py
PYTHONPATH=.:tests python3 -m unittest discover -s tests -p 'test_*.py' -q
```

Example from a previously saved snapshot (no network):

```sh
python3 scripts_extract_snapshot.py --url https://shop.example.org/p/1 --input /tmp/product.html --content-type text/html --method STATIC_HTML
```

## Next increments / acceptance gates

1. Broaden permitted acquisition beyond the new strict HTTPS/Chromium
   adapter with audited seller-feed JSON. Do **not** reinterpret a 403 as
   a parser failure or turn HTTP 200 into proof of price truth.
2. Add a one-time opt-in local browser companion with scoped sites and queue,
   explicit capture receipts and no credential/cookie export. Actual accessible
   DOM may become the `RENDERED_DOM` or `USER_BROWSER` snapshot. This is not
   a guarantee of bypassing inaccessible stores.
3. Measure *separately* on legal, genuinely accessible live merchants:
   (i) acquisition success, (ii) product identity/variant precision,
   (iii) exact offer price precision, (iv) seller-time freshness, (v) transport
   latency and cost. Do not confuse synthetic fixture passes with live recall.
4. Introduce an adapter into the TraceCart application only after its
   source-validation and checkout gates can consume this evidence contract
   without promoting unverified price claims.

**No paid APIs, automatic CAPTCHA bypass, production deployment or
GitHub Actions in this stage.**
