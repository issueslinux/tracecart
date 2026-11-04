# TraceCart hackathon: one-click retail cart -> AI -> PayPal Sandbox -> simulated shop

**Purpose:** One seamless, coherent *demonstration*, not a real remote-merchant purchase. The user **does not paste a URL**. They see an invented retailer product page with a normal **Add to cart** button. That click starts the existing, immutable research pipeline and opens the risk/payment interstitial automatically.

## Start

```sh
# Install/start local Ollama (qwen2.5:1.5b-instruct expected on 127.0.0.1:11435).
# Use a private PayPal Sandbox REST app (not live credentials) for an authentic hosted order.
PAYPAL_CLIENT_ID='YOUR_SANDBOX_APP_ID' PAYPAL_CLIENT_SECRET='YOUR_SANDBOX_APP_SECRET' \
python3 app.py --port 8810 --db ~/.tracecart/quotes.sqlite
# Visit http://127.0.0.1:8810/demo/store and click Add to cart.
```

Sandbox credentials must be provided privately by an authorized account owner. They are **not** committed, embedded in page JS, or sent to the model. Without them, the buyer can still see the automated research and real local AI plan, but no PayPal order is created. There is no live-mode toggle, no capture endpoint, and no real-money transaction.

## User journey

1. At `/demo/store`, fictional **Demo Retailer** shows a **Vintage ceramic pendant** for **USD 29.00**, quantity 1, with no direct PayPal option. **Add to cart** POST is CSRF-protected and contains only a fixed SKU — no URL input or arbitrary price.
2. The local server emits the same trusted cart event as `/api/cart/added`, via `CartResearchJobs.submit`, then immediately redirects to `/demo/order/<research-id>`. The real graph and research run asynchronously without user intervention. The fake merchant URL is in reserved `.example`, clearly not an actual retailer. No search results or failed source checks are disguised as proof of real stock.
3. After `READY`, a bounded local Qwen task produces **advisory** `risk_level`, risk note and buyer questions. The app auto-refreshes while AI is working. AI cannot output the amount, consent, merchant destination or purchase action. Non-available/invalid Qwen output is explicitly `AI_UNAVAILABLE`, **not** a claimed AI success; sandbox payment is blocked until a real plan exists.
4. A trusted catalog price of **USD 29.00** is calculated independently from AI, saved as a one-time PayPal quote *during the Add to Cart event* (this does **not** create a PayPal order). The buyer must type the exact amount and consent phrase before a single Sandbox Orders v2 POST. The **intended fictional intermediary** is named `TraceCart Demo Intermediary`; the actual Sandbox merchant is controlled by the business account behind the provided REST app credentials, which is **not independently identified as TraceCart**. This is a modeled future brokerage business, not actual brokerage.
5. Real PayPal Sandbox OAuth and order creation require actual authorized Sandbox credentials. The browser displays the returned sandbox-only hosted approval link. The buyer approves in the PayPal test account. The app can make bounded, read-only GET order checks (15 checks, one per 12 s) from the still-open demo page. A manual status-check fallback exists if the page is suspended. **No capture or payment charge occurs.**
6. Only when PayPal reports an `APPROVED` Sandbox order with the **same id, reference, amount and USD currency** does the fictional Demo Retailer become `SIMULATED_ACCEPTED`. It is a persisted simulated status only — no actual remote store, inventory, order placement, payment capture, payout or delivery. Timeout/uncertain order creation never retries the POST automatically.

## Source and consent boundaries

- Existing shopping search, graph, decision algorithm, confidence and offer ranking are unchanged. New code is isolated in `demo_purchase.py`, `demo_purchase_pages.py` and separate local `/demo/...` endpoints.
- No merchant checkout is claimed. Fixed fictitious product/store URLs are explicitly labeled. The `USD 29.00` number is a *demo catalog* amount, not a scraped retail price and cannot be substituted by a model.
- Client cannot send arbitrary SKUs, quantities, merchant recipients, payment API hosts or amounts from Add to Cart. Invalid CSRF or quoted amount fails closed.
- **No paid retailer-discovery calls for the fictional demo.** The demo submits the exact fixed item with `allow_paid_shopping=False`; the normal CartResearchJobs worker skips SerpAPI reservation and returns `SKIPPED_FICTIONAL_DEMO_NO_PAID_SHOPPING`. Other real-merchant cart and research events retain their existing configured discovery. This is a narrowly scoped P0 cost/correctness exception to the graph/search freeze, not a ranking or retrieval redesign.
- PayPal Sandbox approvals are confirmed through read-only GET; a status other than `APPROVED`, even `CREATED`, does not authorize simulated merchant acceptance. A modified purchase unit fails strict matching.
- Production 8781 is not changed. No real retailer plugin/extension hooking has been deployed. To run on a real WooCommerce/Shopify checkout, an authorized merchant backend must use `POST /api/cart/added` with its private integration token and display the resulting job status in its own cart UI. The local store is the *demonstration of that user experience*.

## Verification and remaining contest gate

Offline HTTP tests use a substitute PayPal Sandbox gateway; they demonstrate consent and exact-amount/confirmation logic, **not** real PayPal transactions. Real Qwen and a real browser run demonstrate the auto-created risk plan. For hackathon scoring, an authorized developer must still provision Sandbox API credentials, prove OAuth → POST order → hosted buyer approval → strict GET verification in a real sandbox account, and prepare a short English demo video. No payment capture is needed for this intentionally approval-only prototype.
