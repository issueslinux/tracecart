# TraceCart — scoped local browser research companion v1

**Implemented 2026-11-03 as research-only.** The browser companion adds a
user-controlled, opt-in acquisition channel to the provider-neutral extractor
from PR #70. This is not a way around access restrictions.

## Architecture

1. **Local TraceCart** (`app.py`, bound to `127.0.0.1`) exposes the
   research-only `/research/companion` page. The user explicitly enqueues up
   to **12 HTTPS product URLs**, atomically per submission. Each job has a
   random identifier, status, bounded one-time lease and evidence JSON.
2. **The optional, unpacked Chrome/Chromium MV3 extension** from
   `browser-extension/` is **disabled by default**. The user pastes a local
   pairing token once and grants **per-site optional host permissions** via
   a browser dialog. No wildcard merchant permission is granted by default.
3. When enabled, the extension polls **only**
   `http://127.0.0.1:<configured port>/api/browser-companion/next` about once
   a minute. The local broker requires a 64-digit random hex bearer token
   (never a query parameter, cookie or site request).
4. For a queued site with explicit permission, the extension opens one
   **background product tab**, waits for load with a 30-second bound, checks
   exact URL equality and runs a restricted projection in the tab.
   The tab closes after capture or failure. Unexpected redirects fail closed.
5. The page projection is restricted to an **unambiguous Product with one
   individual Offer in JSON-LD**. It returns name, brand, model, SKU, optional
   GTIN, offer price/currency, seller name, condition and declared availability.
   It does **not** export entire HTML, all JSON-LD fields, requests, cookies,
   browser storage, shopping baskets, account data or payment state. A product
   requiring visual price selection or lacking an individual Offer produces
   `NO_STRUCTURED_PRODUCT` rather than a guessed price.
6. The local server validates an exact job URL, receipt schema, recency and a
   narrow field allowlist, then forwards only the filtered Product/Offer JSON
   to `extract_snapshot(..., acquisition_method="USER_BROWSER")`.
   Each result preserves field evidence, JSON pointers, SHA-256 digest,
   acquisition timestamp, conflicts and original browser price-selection
   origin (direct Offer.price versus SalePrice specification), and
   **seller_verified=false,
   checkout_verified=false**. An indexed price is never silently promoted.
7. The local UI lists status and **unverified** prices, with an Evidence JSON
   link per job. The queue is **in-memory** in v1; restart clears jobs but not
   the local pairing token. A failed/expired job is not retried automatically.

The SHA-256 in the report hashes the **filtered product projection**,
not the complete seller page. JSON pointers refer to that projection; the
original extraction origin is separately identified for price fields.

No portion of this transport is connected to checkout, quote amounts, order
creation, merchant accounts or payment authorization.

## Setup (explicit human actions)

The user must start the TraceCart development instance themselves. From an
updated development worktree:

```bash
python3 app.py --port 8765
```

In Chromium open `chrome://extensions/`, enable Developer mode, select
**Load unpacked** and choose the repository's `browser-extension/` directory.
Review `manifest.json` and the source code first.

Visit `http://127.0.0.1:8765/research/companion`. In the extension popup:
enter port `8765` (or the development server's port) and paste the token
shown on the local page. Click **Save local pairing**. The token is stored
inside Chrome extension local storage; a corresponding file is kept with
filesystem permission 0600 at
`<app --db parent directory>/browser_companion.token`. Do not share the
token or commit it to Git.

Enter a real merchant product URL in **Merchant origin to authorize** and
click **Grant access to this shop**. Approve the explicit browser permission.
Repeat only for additional origins you choose. Then enable queued research.

Enter one or more product URLs on `/research/companion` and submit.
Refresh the page to see `QUEUED`, `IN_PROGRESS`, extracted claims or an
explicit failure. Open **Evidence JSON** for per-field provenance.
**Disable queued research** in the extension popup to stop new polling.

Note: `app.py` runs as a local server. Merely merging this PR does not
update the currently running older production service. Do not deploy or
restart production without separately evaluating the new application version.

## Security and failure behavior

- Browser permission is requested through a user-click popup action.
  Worker code cannot request permission silently and does not run when
  explicitly disabled.
- Strict `127.0.0.1` loopback endpoint, fixed API paths, bearer-token
  authentication, Host filtering, CSRF-protected local enqueue form.
  Broker rejects unsolicited remote JSON and unexpected fields.
- No network request is made by the server to the merchant on the browser
  path. The user's authorized browser accesses a queued URL under its normal
  browser session; authorization does **not** imply that every site permits
  automation. Respect site terms; never bypass challenges or CAPTCHAs.
- Challenge screens are explicit `ACCESS_CHALLENGE` or
  `NO_STRUCTURED_PRODUCT` outcomes. Missing site permission is
  `SITE_PERMISSION_REQUIRED`. Cross-page URL change is `REDIRECTED`.
- One leased job can be in flight per local service worker; 90-second lease
  expiry prevents infinite held jobs, with **no hidden retries**.
- Merchant product declarations are **not** verified checkout totals, live
  availability, shipping costs or price guarantees.
- This is a **development feature**. Automated installation, fully signed
  extension package, browser E2E in a real logged-in merchant environment,
  audited commerce-site permission policy and live-store extraction accuracy
  remain **unverified**.

## Offline verification

```bash
PYTHONPATH=. python3 -m unittest tests.test_browser_companion_queue tests.test_browser_companion_http -v
node --test browser-extension/capture_core.test.mjs browser-extension/queue_capture.test.mjs browser-extension/companion_worker.test.mjs
PYTHONPATH=.:tests python3 -m unittest discover -s tests -p 'test_*.py' -q
```

The tests use synthetic products and a local fake queue/permissions. Browser
worker tests exercise refusal without site permission, a single permitted
capture and a disabled queue; HTTP tests exercise CSRF, bearer token, Host
filter, queue, receipt validation and evidence output. They **do not**
demonstrate successful live Allegro extraction or bypass an HTTP 403.

## Subsequent real Chromium permission lifecycle tests

See `BROWSER_COMPANION_PERMISSION_LIFECYCLE_2026-11-03.md`:
actual Chromium native permission **Deny**, **Allow**, and extension popup
**Revoke** were tested in a disposable Xvfb profile, followed by a
real MV3 queue refusal after revocation. The extension version is
`0.2.1`. No user browser profile was changed.

## Subsequent live Chromium MV3 validation

See `BROWSER_COMPANION_MV3_E2E_2026-11-03.md`: the real MV3 worker,
ephemeral local server, CSRF enqueue and bearer-authenticated result path
were successfully tested on two explicitly selected, robots-approved public
merchant pages. Denied permission rejected the task; a **test-only
pre-granted site permission** allowed the full flow and produced browser
source evidence. User-facing grant/revoke popup dialogs remain unverified.

## Subsequent DOM extraction work

See `BROWSER_COMPANION_DOM_EXTRACTION_2026-11-03.md` for schema.org
microdata / WooCommerce primary DOM support, strict crosschecks, and the
11/11 actual-Chromium fixture smoke. A single public Adafruit page also
returned the same 9.95 USD declared price via static and browser parsers.
The MV3 extension service-worker + queue path is not yet fully E2E verified
with an installed browser extension.

## Next work

Validate in a real Chromium instance on a safe, authorized public merchant
page, measure permission/redirect edge cases and broaden extraction (visible
primary offer, page-specific JSON/embedded application state) without
collecting personal data. For comparison claims, independently verify
variants, offer identity, shipping, availability and final checkout total.
