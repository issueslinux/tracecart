# Live coverage probe

Explicit opt-in only. Provide a JSON array of public HTTPS product URLs and run:

`python3 benchmarks/live_coverage.py --urls /path/to/urls.json --output /path/to/report.json`

The probe uses the existing HTTPS/robots preflight and safety checks. It does not bypass 403, robots.txt, redirects or authentication, and never enters checkout. Each URL is evaluated independently; inaccessible URLs count as unavailable, not successful extraction. Reports contain URL, timestamp, page hash and extraction flags, not copied page content. Avoid publishing personal URLs or proprietary HTML.

Initial manual observation (2026-11-02): one public Adafruit product URL (`https://www.adafruit.com/product/1083`) was fetched; product and price were extracted, but destination-specific shipping and delivery were not. **This single observation is not a representative multi-store coverage estimate.** Future comparisons need an explicitly documented, diverse URL sample and repeated runs with dates.
