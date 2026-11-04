# TraceCart — PayPal Sandbox from existing recommended offers

Status: implementation candidate for staging, 2026-11-04.

## Product flow

The existing `/cart/status/<research-id>` SVG graph, evidence processing,
ranking, live source updates and final proposed products are unchanged.
In the **existing recommendation cards**, the user sees **PayPal Sandbox demo**
next to the existing graph and listing actions. **No Final Analysis button,
new recommender, manual URL paste, or separate AI quote journey** is required.

When the user chooses a recommended offer:

1. The browser sends only `offer_id` and existing form CSRF to
   `POST /cart/status/<research-id>/paypal/select`.
2. The backend recomputes the latest selected proposal from persisted research
   and graph projection; the client never supplies the amount, currency,
   title or merchant target. Selection is restricted to `options` and
   `tradeoffs` actually present in the current recommendations.
3. The server stores a persisted one-time Sandbox quote and redirects to
   `/cart/sandbox/<quote-id>`; only the supported `USD`, `PLN` and
   `EUR` indexed listing amounts are eligible.
4. The buyer sees the original offer title, illustrative indexed price and
   explicit warning that this is **not checkout verified**. Buyer must type
   the exact price and consent text `I APPROVE SANDBOX DEMO`.
5. A *separate* button creates a single PayPal Sandbox Orders v2 order,
   directed only to the developer-linked Sandbox Business account.
   The PayPal-Request-Id is stored per quote. On timeout/uncertainty,
   the quote is stuck in `CREATE_UNCERTAIN` and does not retry the POST.
6. The buyer can approve using a PayPal Sandbox Personal account.
   A read-only GET validates matching order ID, currency, value and quote
   reference. Nothing is captured and the external merchant is not paid.
   PayPal Sandbox returns to the same localhost review page after buyer
   approval or cancellation; this is no guarantee that an order was captured.

The gateway domain is pinned to `api-m.sandbox.paypal.com`; approval
links are accepted only on `www.sandbox.paypal.com/checkoutnow` and with
the matching token. No live PayPal endpoints, capture endpoint, merchant
checkout, automated fulfillment or real-money transaction are present.

## Limitations and evidence boundary

- The index listing amount (for example 132.60 PLN for offer-1 in Ryobi
  research 45njvY2FStBkk9WwLDQ_grQ0) is **not** a verified order total.
  PayPal Sandbox only demonstrates the UX of an intermediary, not a real
  price guarantee or direct PayPal payment at Allegro/TIM/Media Expert.
- The actual Sandbox recipient is the business account attached to the
  authorized REST app, *not* any indexed retailer.
- The existing standalone `/` catalog quote, `/demo/store`, old
  product analysis and production 8781 remain untouched for compatibility.
  The intended user-facing flow is the existing `/cart` / graph UI.
- Only staging may be deployed for evaluation. Private REST credentials
  stay on the host, outside GitHub.

## Verification

Run without external provider calls or real Sandbox order creation:

```sh
python3 -m unittest -q tests.test_offer_sandbox_checkout tests.test_demo_purchase
node --test browser-extension/*.test.mjs
python3 -m unittest discover -s tests -p 'test_*.py' -q
```

The offline tests use fake PayPal replies and test invalid price/CSRF/
consent, order-id/amount binding, one-shot create and read-only verification.
They **do not** assert live PayPal payer approval. A live Sandbox buyer test
must be completed by the authorized account owner, with no capture.
