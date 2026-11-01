# Second live merchant URL — auditable pre-checkout comparison

TraceCart's original /cart flow needs only the selected product URL. After
the initial research is READY, a **second optional retailer product URL** can
be supplied in the pre-checkout report. The server uses the existing
public-HTTPS-only, pinned-public-DNS, robots.txt-respecting product-page
extractor. It never relies on a search result snippet as an offer.

The resulting durable report contains both product claims, exact URLs,
retrieval timestamps, source page SHA-256, declared prices and currencies,
GTINs when present, per-wash costs when explicitly declared, a conservative
identity gate, critic limitations and the full original research tree.
It is exportable as JSON. No PayPal order or capture is initiated.

## Actual two-store source trial — 2 November 2026

Selected source: Amazon.pl Ariel Color 5.5 kg, 100 washes, originally
retrieved 1 November 2026. Seller-listed **76.99 PLN** or **0.7699
PLN/wash**. Its product page did not publish a usable GTIN.

Second source: Granes Ariel **Professional** Color 5.5 kg, 100 washes,
https://granes.pl/pl/products/ariel-professional-proszek-do-prania-kolor-100-pran-5-5-kg-248.html
retrieved live 2 November 2026 around 00:03 CET. Product JSON-LD
declared **87.99 PLN**, EAN **8700216908856**, InStock. The same 87.99
amount also appeared repeatedly in the downloaded product page HTML;
the earlier indexed web search price of 94.99 was stale. Seller-declared
unit cost: **0.8799 PLN/wash**.

**Crucial outcome:** status GTIN_IDENTITY_NOT_ESTABLISHED, listed-price
delta **null**, no cheaper-equivalent assertion. The Amazon listing did
not provide an EAN and the Granes listing explicitly says Professional,
so the products cannot be certified as identical. The two seller
prices are evidence of two listings, not a reliable direct savings
comparison or final checkout totals.

The full original research plus new live-source evidence is archived in
`examples/live_amazon_vs_granes_2026-11-02.json`.

## Other direct live source outcomes (2 November)

- Zawadzcy Persil 75 washes: page accessible, title retrieved, **price
  and GTIN not present in supported metadata**.
- Maxpronet Persil 75 washes: page accessible, Product JSON-LD name
  and stock statement retrieved, **no supported machine-readable price/GTIN**.
- StrefaChemii Persil 75 washes: page accessible, **no supported
  machine-readable price/GTIN**.
- Castorama Ariel Professional: HTTP 503, no source content used.
- E-dyskont Ariel Professional: page accessible, **price/GTIN not extracted**.
- StolicaZakupów Ariel Professional: source read timed out.

Those are *limitations of this extractor at that retrieval time*, not
claims that the stores have no price. No 403/robots bypass was attempted.

## Identity and price policy

A numeric price comparison is permitted only when BOTH source pages were
retrieved, each seller declares a price, both currencies match, the two
stores differ, both GTINs are present and equal, and no contradictory
declared wash count is detected. The percentage is relative to the
selected product's seller-listed price, **excluding delivery, promotions
and actual dosage**. Without matching GTIN, source-backed evidence is
shown but no savings percentage or winner is produced.

Search listing discovery is currently a voluntary external shopping-search
link. Automatically finding and verifying multiple permitted competitor
pages requires an authorized search feed and careful bounded crawling.
The next research iteration should improve generic structured-price
extraction for stores where the HTML is available but the metadata is
incomplete, then verify a truly matching GTIN across two sellers.
