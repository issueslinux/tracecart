# P0 marketplace access — what can and cannot work (2 November 2026)

**Status: feasibility prototype, NOT a solved unattended Allegro integration.**

TraceCart's server-side HTTPS client and an ordinary external fetch service both
received **HTTP 403** for the same Allegro product page. The 403 is a
source-access limitation, not a parser bug; it must not be solved by evading
anti-bot restrictions.

The Allegro team confirmed in June/July 2026 that they **no longer grant new
applications access to marketplace-wide GET /offers/listing**. The
GET /sale/offers endpoint is for the authorized seller's own offers.

Sources:
- https://github.com/allegro/allegro-api/issues/13603
- https://github.com/allegro/allegro-api/issues/13771
- https://developer.allegro.pl/documentation

## Experimental fallback: capture one product already visible in the user's browser

The separate Chrome/Chromium MV3 extension lives in `browser-extension/`.
It is **not** a stealth browser, crawler, account integration, automatic search
or authorization to scrape a marketplace. It uses only `activeTab`,
`scripting` and clipboard-write permissions and has no persistent host/site
permissions or background service worker.

After a *user* opens a permitted product page in a normal browser:
1. In Chrome/Chromium navigate to `chrome://extensions/`, enable
   "Developer mode", then "Load unpacked" and select the
   `browser-extension/` directory. **Review code and permissions first.**
2. Open a product page that is already accessible to your normal browser.
   Clicking the extension action makes a **single explicit active-tab read**.
3. It first accepts one unambiguous `Product → Offer.price` JSON-LD record.
   A crossed-out `ListPrice` or `AggregateOffer.lowPrice` is *not* the current
   per-offer price.
4. For JS-heavy marketplaces or an absent/possibly stale JSON-LD price,
   highlight the exact currently visible price **including currency**
   (for example `229,00 zł`), and press Capture. Deliberate visible selection
   takes priority over schema data. If neither yields an unambiguous price,
   the extension refuses to fabricate one.
5. Press Copy JSON. In an already READY TraceCart product cart report,
   open "Compare up to four other stores", paste the captured JSON into
   "Browser capture JSON" and submit. If no other competitor URL is entered,
   the existing safe source retriever separately attempts the listing; its
   HTTP 403 remains visible. The separate browser observation still appears
   in the tree and JSON report.

No cookies, local storage, login state, credentials or full HTML are copied.
No browser observation is sent anywhere automatically. The export contains
only selected URL, title, observed price/currency, optional seller-declared
GTIN, capture method and timestamp.

**Trust level:** `USER_BROWSER_ACTIVE_TAB_NOT_SERVER_VERIFIED`.
The browser itself might be showing the wrong variant, stale data or an
advertised/reference price. It is *not* retailer-API verification,
independently confirmed stock, final checkout cost or global lowest price.
The server validates the capture schema and recency and prevents elevation
of such observations into source-qualified offers.

## What has actually been tested

- Eight Node.js tests cover extraction of unique schema prices,
  reference-price exclusion, explicitly selected current price overriding
  JSON-LD, Polish currency/number syntax and ambiguous-product rejection.
- Python tests cover strict JSON schema, freshness limits, unsafe URLs,
  source classification and a real localhost TraceCart POST/export flow
  with simulated Allegro HTTP 403.
- **The extension has NOT been validated in a real logged-in user's Allegro
  browser session.** Static fixtures and simulated HTTP 403 are not that
  acceptance test; feasibility issue #38 remains open.

## Parallel authorized-data route

A licensed data feed/API is the only credible path to unattended,
reproducible market-wide offer discovery and price verification. Ceneo has
a partner API with a key-application process, separate terms and potentially
paid access; it is not automatically a direct Allegro data feed.

- https://pp.ceneo.pl/api
- https://partnerzyapi.ceneo.pl/
- https://biznes.ceneo.pl/api

**Do not start a new market-wide automatic crawling pipeline until an
authorized data source is confirmed.** The user's core objective remains
unmet until a real browser acceptance test or a licensed feed produces
fresh accurate marketplace prices repeatedly.
