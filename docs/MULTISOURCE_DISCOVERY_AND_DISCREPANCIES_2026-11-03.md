# Multi-source discovery and discrepancy graph — 2026-11-03

## Research goal

The question bank is a *work plan*, not source answers. This release adds
two reusable capabilities across categories: paid-search-*URL discovery*
with a strict cost/identity gate, and comparing actual fetched documentary
claims with each other and with the indexed listing title.

No per-model source parser was introduced. The generic source reader
remains responsible for robot-checked fetch, HTML/JSON-LD extraction,
source URL, timestamp and SHA256. Existing independent Notebookcheck
data remain independent reference-only measurements, not retailer-SKU proof.

## 1. Search discovery provider

`source_search.py` provides optional **Brave Web Search** integration;
the API's configured provider is the *only* source of search result URLs
in this stage. Google/Bing/DDG scraping was intentionally rejected when
robots denied search endpoints or returned challenges. No stealth
browser is used for web-search pages.

Operator configuration (optional):

```sh
export BRAVE_API_KEY='<operator-key>'
export TRACECART_SOURCE_SEARCH_ENABLED=1
```

The service must be restarted for these settings to take effect.

Rules:
- **OFF by default**. No key or no explicit enablement means **zero**
  API calls. On the currently deployed host, this provider is disabled:
  no additional paid discovery calls occurred.
- **Maximum 6 provider queries per research job**: one manufacturer/
  technical search and one independent-review query for up to three
  distinct model identities in the input + Shopping alternatives.
- Search-result titles must visibly contain the exact parsed
  brand and model token; a generic "250 W 15 Ah" match is rejected.
  Host, scheme, credentials and path are validated; shopping search
  engines/marketplaces are not treated as independent technical sources.
- Search results are stored as **unverified leads**, NOT facts, prices,
  technical specs or independent laboratory reviews.
- Every lead must independently pass the generic `robots.txt`,
  public-IP pinned TLS and exact model match when fetched.
- **SQLite receipt** `cart_source_search` stores the provider outcome,
  leads, count and per-query statuses outside the immutable original
  report. Re-running or restarting the same job reuses its receipt
  instead of repeating paid queries. An interrupted in-flight query
  is NOT automatically retried; that prevents uncertain duplicate
  charges.
- The graph has `source_lead` nodes and
  `SOURCE_DISCOVERY_LEAD` edges, which are linked to the actual
  `fetched_source` node only after its document is independently
  fetched and parsed. This visibly grows the network as research
  progresses, without claiming that a search hit is evidence.
- Live SSE snapshots surface discovery state and counts alongside
  source worker activity. No purchase or checkout authorization changes.

## 2. Evidence contradictions, not model confidence inflation

`source_discrepancies.py` compares compatible title and real document
attributes only where names, quantities, measurement units and
conditions are sufficiently identified. Initial support:

- E-bike: *pedal-assisted* range in km, rated motor W, battery Ah.
  Pure-electric/throttle-only range is **not** compared to
  pedal-assist range. A mere unspecified range is flagged as a
  **potential variant or test-condition difference**, not a failed
  product or a false advertising finding.
- Laptop: installed RAM GB and storage capacity GB/TB.
- Smartphone/SSD: storage GB/TB.
- Compressor: maximum pressure in bar and tank capacity in litres.
- Rounded TB/GB labels are compared with tolerance to avoid false
  positives (e.g., 1000 GB vs 1024 GB).
- Source-vs-source discrepancies require two **different fetched
  document hashes and different publisher hostnames**; two pages
  from the same manufacturer domain do not count as independent
  corroboration. Even two independent hostnames are published
  claims, not scientific verification.
- The numeric gap must exceed a 7.5% tolerance with non-overlapping
  values/ranges. Ambiguous dimensions or missing units abstain.

Persisted flags are
`TITLE_VS_PUBLISHED_SPECIFICATION` or
`PUBLISHED_SOURCES_DISAGREE`, with both original values, source
URLs, SHA256 and `not_fraud_or_exact_sku_proof: true`.
The original source declarations remain unchanged.

The graph has `source_disagreement` nodes linked to the source
document(s) by `DISCREPANCY_REQUIRES_SOURCE_REVIEW`; clicking
the related offer displays the warning. The right research rail
shows `CHECK SOURCES` as **OPEN**, not `VERIFIED`. Summary stats
separate `unresolved_source_discrepancies`,
`documented_product_declarations`,
`independent_reference_measurements` and
`verified_exact_sku_answers`.

## 3. Actual saved-job replay

Tested against an **isolated full SQLite backup** from
`/tmp/tracecart-serpapi-e2e-20261102.sqlite3`.
Previously saved 13-offer e-bike
`LoHWENthHlgccaUCtbOdQkCO` was read and generic sources rechecked,
with the optional paid provider disabled.

- **13** separate offers; **12** documented manufacturer-page
  declarations from the real ALLGOBIKE website (one URL).
- For indexed **offer #4, AM27**, seller title claims **100 km**
  while the actual fetched manufacturer's pedal-assist range
  declaration is **50–85 km**. Marked as **1 potential discrepancy**,
  not an independent range measurement or verified same retailer SKU.
- **0** independently tested e-bike range values, **0** confirmed
  exact retailer SKU identities, **0** verified checkout totals,
  **0** newly paid search requests.
- The original immutable report content was unchanged; the enhanced
  evidence receipt and contradiction nodes are separately stored.

The range comparison is deliberately conditional because different
battery revisions, riding conditions and advertised range modes can
explain the difference. A purchase decision must still abstain.

## 4. Verification and limitations

Automated tests cover 6-query limits, model deduplication, bad URL/
wrong-model/hallucinated-hit rejection, no API key zero calls,
per-job durable search receipts after repeated worker execution,
real source-to-graph lead edges, source-vs-title range discrepancy,
misleading throttle-mode filtering, generic RAM/SSD/compressor
numeric comparisons, cross-document domain checks, graph links,
and JavaScript research rail provenance.

No broad source search runs without a configured provider.
No article's *search snippet* becomes proof, and generic product
specification pages are not arbitrarily labeled independently
tested laboratories. Inaccessible pages and exact variant gaps
remain explicit research questions.

Next work should add a second legitimately configured search provider
or OpenSearch/SearxNG instance with its own index, evidence merging
for exact-SKU laboratory reviews, and current seller checkout totals.
These are not claimed as implemented in this release.
