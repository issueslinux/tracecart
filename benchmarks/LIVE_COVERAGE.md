# Live coverage probe

Explicit opt-in only. Provide a JSON array of public HTTPS product URLs and run:

`python3 benchmarks/live_coverage.py --urls /path/to/urls.json --output /path/to/report.json`

The probe uses the existing HTTPS/robots preflight and safety checks. It does not bypass 403, robots.txt, redirects or authentication, and never enters checkout. Each URL is evaluated independently; inaccessible URLs count as unavailable, not successful extraction. Reports contain URL, timestamp, page hash and extraction flags, not copied page content. Avoid publishing personal URLs or proprietary HTML.

Initial manual observation (2026-11-02): one public Adafruit product URL (`https://www.adafruit.com/product/1083`) was fetched; product and price were extracted, but destination-specific shipping and delivery were not. **This single observation is not a representative multi-store coverage estimate.** Future comparisons need an explicitly documented, diverse URL sample and repeated runs with dates.

## Evidence diagnostics

The report now distinguishes `EXTRACTED`, `NOT_ASSESSED_PAGE_UNAVAILABLE`, and `UNDETERMINED_ABSENT_OR_UNRECOGNIZED`. **Failure to extract shipping is not evidence that the seller's page lacks shipping information.** Distinguishing missing page content from unrecognized visible text requires separately reviewed evidence; the probe does not invent that conclusion.

Additional 2026-11-02 manual observation: three Adafruit product URLs (`/product/1083`, `/product/326`, `/product/64`) returned 3/3 product identities and prices but 0/3 destination-specific shipping and delivery claims. All six missing shipping/delivery fields were classified as `UNDETERMINED_ABSENT_OR_UNRECOGNIZED`. All three URLs belong to **one merchant**, so this does not measure cross-store coverage.

## Cross-merchant exploratory observation (2026-11-02)

Four previously recorded public product URLs were probed once, one per merchant. The sample is purposive, **not random or representative**; extraction is seller-declared and not checkout-verified. No access controls were bypassed.

| Merchant host | Fetched | Product | Price | Destination shipping | Delivery window |
|---|---|---|---|---|---|
| www.adafruit.com | yes | yes | yes | no | no |
| maxpronet.pl | yes | yes | yes | no | no |
| fabryka-narzedzi.pl | yes | yes | yes | yes | no |
| www.amazon.pl | yes | yes | yes | no | no |

Totals: **4/4 fetched, 4/4 product, 4/4 price, 1/4 destination shipping, 0/4 delivery**. A `no` means **not extracted**, not proven absent from the seller's page. URLs are in prior research examples; this measurement does not establish that offers remain available or prices match checkout.
