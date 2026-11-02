# TraceCart Search-First Shopping providers — 2 November 2026

**Implemented and unit-tested. A live SerpApi vs DataForSEO benchmark has
NOT been executed because neither provider has credentials on the host.**

## Search-first evidence

TraceCart's URL-first cart job can now use Google Shopping indexed merchant
prices even when the marketplace returns HTTP 403 to a direct HTTPS request.

With SERPAPI_API_KEY configured, search_first.py calls the documented:
1. GET https://serpapi.com/search.json?engine=google_shopping
2. GET https://serpapi.com/search.json?engine=google_product&product_id=...
   (at most one product group per item)

Docs:
https://serpapi.com/google-shopping-api
https://serpapi.com/google-product-api

The result includes: seller, product title, index price, explicitly displayed
currency, condition when present, direct store URL if available, separate
shopping search-card price when no direct store link is available, timestamp
and a provisional minimum **only among returned indexed candidates**.

- Source trust: GOOGLE_SHOPPING_INDEX_NOT_DIRECT_SELLER_PAGE.
- A Google product ID is not a verified GTIN or exact seller variant.
- Search-indexed prices may be stale, incomplete, inaccurate or conditional.
- All selected-product-vs-store model conflicts remain visible.
- No index price is promoted to a verified seller-page claim, final checkout
  amount, real saving, or global lowest-price declaration.
- The existing payment firewall is unchanged.
- The cart UI now lists index prices without requesting blocked retailer
  pages or dropping Allegro listings.

SerpApi currently advertises 250 searches/month on its Free plan, subject
to its own account plan, terms and quota:
https://serpapi.com/pricing

## DataForSEO — optional secondary provider

dataforseo_shopping.py implements explicit paid asynchronous research:
- POST https://api.dataforseo.com/v3/merchant/google/products/task_post
- GET https://api.dataforseo.com/v3/merchant/google/products/task_get/advanced/{id}

Docs:
https://docs.dataforseo.com/v3/merchant-google-products-task_post/
https://docs.dataforseo.com/v3/merchant-google-products-task_get-advanced/
https://dataforseo.com/pricing/merchant/google-shopping-api

This source provides indexed seller/price/currency/Google product IDs; it
often returns null for the direct merchant URL. No link is invented. Normal
priority tasks are asynchronous (potentially tens of minutes) and charged
when submitted, so this adapter is **not** invoked automatically in carts.
The task queue requires an explicit allow-paid flag; a separate subsequent
collection retrieves existing task IDs without submitting duplicate tasks.
The provider pricing page currently quotes $0.001 per normal-priority
product/seller/SERP task (subject to current billing).

## Reproducible 20-product benchmark

Dataset: benchmarks/shopping_20_products.json — twenty recognizable
products in several categories. Only Stanley Air Kit has a GTIN supported
by earlier direct seller evidence; all other EANs remain intentionally
blank rather than invented. These are query targets, NOT 20 confirmed
current retailer offers.

No credentials or API calls needed to inspect:

    python3 benchmarks/shopping_search_eval.py --mode preview --output /tmp/shopping-preview.json

When account credentials have been configured LOCALLY on the host, a
limited or complete SerpApi experiment requires explicit consent to
consume credits:

    python3 benchmarks/shopping_search_eval.py --mode serpapi --limit 20 --allow-paid --output /tmp/serpapi-20.json

DataForSEO is intentionally two-stage:

    python3 benchmarks/shopping_search_eval.py --mode dataforseo-enqueue --limit 20 --allow-paid --output /tmp/dataforseo-tasks.json
    python3 benchmarks/shopping_search_eval.py --mode dataforseo-collect --queue /tmp/dataforseo-tasks.json --output /tmp/dataforseo-results.json
    python3 benchmarks/shopping_search_eval.py --mode compare --serpapi-results /tmp/serpapi-20.json --dataforseo-results /tmp/dataforseo-results.json --output /tmp/shopping-comparison.json

Source access requires SERPAPI_API_KEY or DATAFORSEO_LOGIN and
DATAFORSEO_PASSWORD as local environment variables. Never put API
credentials in the repository or conversation.

Metrics: indexed prices per product, number of indexed shops and
marketplace candidates, percentage of products with usable offers,
missing/ambiguous variants and an explicit record of pending tasks.
**Price accuracy is NOT established by agreement between indexes.**
True price accuracy requires independent same-SKU, same-condition
current seller/browser evidence with timestamps.

## Results actually observed today

On the project host, both provider credential sets were absent.
The dataset and benchmark are ready but the benchmark status is:

- SerpApi official API queries completed: **0/20**.
- DataForSEO tasks submitted/collected: **0/20**.
- Independent live price accuracy: **NOT MEASURED**.
- Provider adapters and URL-first integration are tested with synthetic
  provider JSON; these tests are NOT proof of real provider coverage.

Machine-readable credential/coverage audit:
examples/search_first_20_protocol_2026-11-02.json

The earlier Stanley/Allegro external public search snippets are legitimate
indexed search observations but are neither SerpApi nor DataForSEO executions.

P0 issue https://github.com/issueslinux/tracecart/issues/38 remains OPEN
until real marketplace coverage, correctness, pricing and licensing are
measured. Shipping/ETA parser work remains paused.

## Offline quality replay of provider JSON (no API credentials needed)

For genuine previously downloaded SerpApi and DataForSEO raw responses,
[the separate offline replay benchmark](../benchmarks/SEARCH_FIRST_OFFLINE_AUDIT.md)
checks the shared 20-product model tokens, rejects malformed URLs and prices,
retains pending-task status and audits how many actual marketplace price
observations each source delivered. This does not initiate billable requests,
and a missing response is never reported as zero market coverage. The first
complete 20×2 real provider-response set is still pending credentials.
