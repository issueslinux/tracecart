# Replay audit of SerpApi and DataForSEO responses (20 shared research cases)

The **online** 20-product provider experiment is implemented in
benchmarks/shopping_search_eval.py; it calls providers only when the
operator has configured credentials and explicitly permits billable
queries. benchmarks/search_first_provider_benchmark.py is its
**offline replay/quality-control companion**. It **never** accesses a
search engine, retailer, marketplace or API itself.

## Why a separate offline audit?

Comparing counts of search hits is not sufficient to choose a reliable
product comparison provider. A price might concern a different model,
a stale promotion, or an item for which there is no retailer link. A
Google Shopping search card is not the same source as an individual
store listing. A DataForSEO carousel parent is not an offer. A
pending async response must not be scored as zero coverage.

The replay normalizes raw response shapes and reports, for each product
and provider, indexed-priced rows, model-token-qualified hypotheses,
marketplace observations and unverified direct merchant links. A
Google Shopping indexed price NEVER becomes a seller-verified price.

The audit excludes supplied unsafe merchant URLs, and does not infer
product GTIN from Google product ID or model words. The model token
status is not proof of a matching GTIN.

All 20 entries use the SAME product dataset
benchmarks/shopping_20_products.json as the online experiment, with
additional conservative model_tokens for repeatable variant testing.
Only Stanley Air Kit has a previously documented seller-claimed GTIN;
the other 19 remain blank rather than invented.

## Usage with previously captured genuine provider responses

Create a directory per provider with one raw JSON file for each product:
P01.json through P20.json. SerpApi accepts a Shopping and/or Product
response; DataForSEO accepts a full Products Advanced task GET response.

    python3 benchmarks/search_first_provider_benchmark.py \
      --serpapi-dir /path/to/serpapi-raw \
      --dataforseo-dir /path/to/dataforseo-raw \
      --output /tmp/tracecart-shopping-provider-audit.json

Missing files are NOT_EXECUTED_NO_RESPONSE, NEVER fabricated zero
market coverage. Pending tasks are PROVIDER_RESPONSE_PENDING_NOT_MEASURED.
Invalid responses are recorded separately. Require all 20×2 real
responses using the extra flag --require-all-responses; the command
exits nonzero if any actual successful response is missing. This audit
never makes billable queries itself.

Offline fixture tests cover API contract shapes, carousel nesting,
duplicates, variant mismatch, invalid prices, unsafe URLs, absent
currencies and pending tasks. Synthetic tests are NOT real shopping
offers or provider performance evidence.

## Observed status — 2 November 2026

Neither provider's credential set is present on the project host.
Real SerpApi responses: 0/20. Real DataForSEO responses: 0/20.
Therefore comparative marketplace coverage, live price accuracy,
cost per usable offer and completeness are NOT MEASURED.

The earlier Stanley/Allegro indexed price observed through an external
public search is NOT attributed to either provider.

API formats:
- https://serpapi.com/google-shopping-api
- https://serpapi.com/google-product-api
- https://docs.dataforseo.com/v3/merchant-google-products-task_get-advanced/
- https://docs.dataforseo.com/v3/merchant-google-overview/

**Decision gate:** choose a provider only after actual model-matched
PLN-priced marketplace results, valid retailer links, observed
freshness and independent same-SKU/current-price spot checks.
Even 20 successful queries are not a comprehensive market scan.

No changes to shipping/ETA parser, marketplace access control or payment.
