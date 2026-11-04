# TraceCart — one-click PayPal Sandbox from recommended offers

Updated on 2026-11-04. This change is for the Sandbox demonstration only.

## User-facing behavior

The existing evidence graph and recommendations at
`/cart/status/<research-id>` are unchanged. Each eligible suggested
product has an English **Pay with PayPal** button with a visible
**SANDBOX** badge.

**One explicit click** starts the new checkout path. There is no input
field for the amount, no manually entered consent phrase, and no second
confirmation button in TraceCart.

The modal remains above the existing graph and displays four stages:

1. **Product** — retrieve the offer title and exact indexed price from
   the server's saved and recomputed recommendation. Never accept a
   price, currency or seller from browser input.
2. **Order** — atomically record the click's request for a *test*
   checkout in a server-side quote, then start a single PayPal Sandbox
   Orders v2 creation request. Display the amount already locked by
   the server. No extra user action is required in TraceCart.
3. **PayPal** — open the secure PayPal-hosted Sandbox page in a
   separate window for the buyer's own required Sandbox approval.
   The modal polls existing order status using read-only API calls.
4. **Result** — once PayPal confirms `APPROVED`, show success with
   the order ID. If status is uncertain, never retry creating an order.

The PayPal-hosted buyer approval is a mandatory external step; it is
**not** silently bypassed. The new modal shows only English labels and
messages.

## Backend routes and safety

- `POST /cart/status/<job>/paypal/start`: requires the existing CSRF
  token and a selected `offer_id`. Uses `OfferSandboxOrders.start` to
  select the server-owned product and price, persist an `APPROVED`
  test quote, and record the user's explicit button-click intent.
  No typed amount or consent token is fabricated.
- `POST /cart/sandbox/<quote>/create`: still accepts **only one**
  PayPal Sandbox order request after server-side intent is recorded.
  It never retries a potentially uncertain creation.
- `GET /cart/sandbox/<quote>.json?verify=1`: read-only status check
  against the existing Sandbox order; no `capture` call.
- The earlier `/paypal/select`, `/approve` and fallback HTML routes
  remain available for legacy sessions, without altering historical
  orders or preventing recovery.
- Quote identifiers are stored in session storage for resumption on
  reopening the modal. An existing `CREATE_UNCERTAIN` state cannot
  be retried. The PayPal approval URL is checked against the official
  Sandbox host and bound PayPal order ID.
- Private REST credentials stay in the server process, never in
  browser scripts, request payloads, documentation or GitHub.

**Boundary:** The selected price is a third-party indexed listing
price, not a verified merchant checkout total. The Sandbox Business
account is not that retailer. A successful Sandbox approval does not
purchase an item or transfer real money.

## Verification

- 20 Python checkout/demo tests PASS, including one-click checkout
  without typed amount, invalid CSRF, server price locking,
  one-shot PayPal order creation and read-only verification.
- Chromium E2E with a copied Ryobi research job
  (`45njvY2FStBkk9WwLDQ_grQ0`) and a completely fake payment
  gateway: a single **Pay with PayPal** click locked `132.60 PLN`,
  opened the simulated hosted approval link, and reached
  `VERIFIED_APPROVED` by automatic polling. No manual form or
  extra confirmation was present, and no real Sandbox order was
  created in this regression test.
- PR #93 separately records a previous real Sandbox buyer approval
  from the earlier checkout UI. That receipt is not proof of a new
  live hosted PayPal session after this UI change.
- The overall research test suite has known unrelated asynchronous
  and source-recovery failures; do not describe it as fully green.
