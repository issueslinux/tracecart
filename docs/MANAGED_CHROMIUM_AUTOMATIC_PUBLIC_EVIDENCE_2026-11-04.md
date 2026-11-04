# Automatic managed Chromium — no per-store permissions

Release: 2026-11-04; first end-to-end confirmed on an **isolated** working copy of TraceCart, port **8811**. Built in response to product research jobs ending `SITE_PERMISSION_REQUIRED` when no merchant host grants were installed in the old MV3 extension.

## Contract

- A new user's product URL automatically triggers bounded source research and **up to 3** background Chromium workers. A stored opt-out of automatic browser research is respected.
- No extension installation, pairing token, Chrome profile, manual merchant list or per-host permission dialog is required. Optional MV3 Companion is retained as a separate diagnostic option.
- Each browser runs with a disposable Chromium profile and separate Xvfb display; the request is explicitly checked against site `robots.txt`, DNS-pinned to a public IPv4, and network requests are restricted to the precise HTTPS hostname. Redirects to other products/hosts are rejected. Remote code has no access to the host's cookies or saved browser credentials.
- Every visit produces either a constrained Product/Offer JSON projection or a terminal status (`ACCESS_CHALLENGE`, `ROBOTS_DISALLOWED`, `NO_STRUCTURED_PRODUCT`, `REDIRECTED`, etc.). A security challenge is **not** solved or bypassed and never becomes a price observation. Search-card quotes are never promoted to checkout prices.
- Receipt validation, exact-URL identity guard, evidence graph, discount interpretation and purchase-decision algorithm are unchanged. New receipts retain the existing `USER_BROWSER` compatibility field but include `browser_execution_mode=ISOLATED_MANAGED_CHROMIUM` for correct attribution.
- Queue reservations are held until SQLite graph/index links have been committed; background workers cannot consume them during setup. Retrying clears stale batch task counts, but durable browser evidence is retained.
- The app starts managed Chromium workers automatically when launched with `python3 app.py --port 8810 --db ...`; only Node.js 22+, Chromium and Xvfb are needed. There are no paid shopping API calls inside the browser capture path. If these prerequisites are missing, the browser task ends with an error; it does not fabricate facts.

## Verified live smoke: no manual browser setup

- **Adafruit:** Submitted URL `https://www.adafruit.com/product/1083` as a normal cart event to clean local server on port 8811. Automatically reached `READY`, batch `COMPLETE`, Product price `9.95 USD`, `browser_execution_mode=ISOLATED_MANAGED_CHROMIUM`, one graph browser claim, zero verified checkout prices. No Chrome extension or merchant permission was installed.
- **eBay:** Submitted `https://www.ebay.com/itm/880062986898` to the same server. Automatically reached `READY`, batch `COMPLETE_WITH_FAILURES`, per-source `ACCESS_CHALLENGE`, zero confirmed checkout prices. Isolated Chromium was redirected to an eBay `/splashui/challenge` security page. **The current environment cannot obtain a verified seller price from this page** without permitted evidence from another source. This is access-control behavior, not a missing user permission.
- The testing database and browser profiles were isolated. The live staging server 8810 was not mutated during the smoke tests. Production 8781 must never be changed for this task.

## Regressions and policy tests

```sh
TRACECART_SERPAPI_CONFIG_FILE=/nonexistent/tc-deny-api.env PYTHONPATH=.:tests \
  python3 -m unittest discover -s tests -p 'test_*.py' -q
node --test browser-extension/*.test.mjs
```

Tests verify robots denial prevents Chromium launch; private IP is rejected; secret environment variables are not forwarded to Chromium; wrong-source receipts and ambiguous prices are discarded; challenge is terminal; queue release occurs only after durable links; graph gets managed-browser provenance without changing cart input or making any checkout claim.

## Known limitations

- Sites may enforce anti-automation challenges even when a user is allowed to browse them interactively. The engine **does not** attempt to circumvent those challenges; an official authorized data source or another permitted retailer is necessary for independently verifiable information.
- JS code loaded exclusively from third-party origins may not execute because cross-host network access is prohibited by design. The result must be a source failure, not a guessed price.
- A search-index card with no concrete merchant URL has nothing to open in Chromium. It remains an index lead.
- PayPal Sandbox OAuth/payer approval and contest submission are **separate unresolved gates**. Managed Chromium is solely a product-information capture component.
