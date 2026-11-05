# TraceCart — PayPal AI Hackathon 2026 judge quick start

**Project:** [TraceCart](https://github.com/issueslinux/tracecart)
**Platform:** desktop browser + Python 3.8+ loopback server (Windows/macOS/Linux with local Ollama where supported)
**License:** [MIT](../LICENSE)
**Hackathon:** [PayPal AI Hackathon 2026](https://paypalaihackathon.devpost.com/rules)
**Entry state (2026-11-05):** source code available; local demo verified;
YouTube video https://www.youtube.com/watch?v=SSsUvSXVhCk verified
public by signed-out player metadata (`isUnlisted=false`,
`isPrivate=false`); a direct inspection of the entrant's signed-in Devpost tab shows
**DRAFT, 3/5 steps completed**. Personal eligibility and rules
attestations plus final submission are pending.
This document is **not** proof of entry.

## What to run first

The project has two intentionally distinct modes:

| Route | Purpose | PayPal action |
| --- | --- | --- |
| `/demo/store` | Fictional **Demo Retailer**, one-click Add to Cart → actual graph/AI research → fixed trusted USD 29.00 Sandbox consent path. No product URL to paste. | Sandbox Orders v2 **create / host approval / read-only verify**, no capture, no external retailer purchase. |
| `/cart` | Paste a public product URL; watch source and price evidence progressively populate the SVG graph; select a conditional shopping lead. | A selected indexed price may be passed to a **Sandbox-only** order, not the merchant's real checkout. Never treat this as a completed purchase. |
| `/` | Natural-language catalog experiment; local Qwen selects only an allowed SKU/quantity and trusted server code computes the total. | Explicit consent before Sandbox order creation; no capture. |

### 1. Clone and run the no-credential UI

Requires Python **3.8 or newer**, no pip dependencies for the core server:

```sh
git clone https://github.com/issueslinux/tracecart.git
cd tracecart
python3 --version
python3 app.py --port 8765 --db /tmp/tracecart-hackathon-judge.sqlite3
```

Then, in a browser **on the same computer**, open:
- http://127.0.0.1:8765/demo/store — start here.
- http://127.0.0.1:8765/cart — open the live evidence graph.
- http://127.0.0.1:8765/ — view the separate model-priced demo catalog.

The server must bind to **127.0.0.1 only**. Do not expose it on the internet or put real PayPal secrets into a browser page.

**Without extra credentials:** the public pages and deterministic quote safeguards work, but the fictional storefront's local-AI stage and real Sandbox order creation remain blocked as designed. A full demonstration requires both of the next two setups.

### 2. Enable the actual local AI engine

Install and start [Ollama](https://ollama.com/download) on the same machine. Pull the actual model used by the demo:

```sh
ollama pull qwen2.5:1.5b-instruct
ollama serve
```

The app tries local Ollama at `127.0.0.1:11435` and `127.0.0.1:11434`, depending on the local service configuration. If your Ollama instance already runs, do not start a second server. Verify it:

```sh
curl http://127.0.0.1:11434/api/tags
```

Then reload `/demo/store`, click **Add to cart**, and watch the actual research/graph and the local Qwen advisory risk plan. Qwen cannot set the amount or consent and cannot initiate an order itself. Model inference can take additional time on CPU-only computers; an unavailable model is shown as unavailable, not presented as a successful AI result.

### 3. Enable PayPal Sandbox (never use live API keys)

Create a free PayPal Developer account and a **Sandbox REST application** at
[developer.paypal.com](https://developer.paypal.com/). Obtain **sandbox-only**
Client ID / secret and a separate **Sandbox Personal buyer account** (do not use
live user credentials or share them with the project team). In your own terminal:

```sh
export PAYPAL_CLIENT_ID='YOUR_SANDBOX_CLIENT_ID'
export PAYPAL_CLIENT_SECRET='YOUR_SANDBOX_CLIENT_SECRET'
python3 app.py --port 8765 --db /tmp/tracecart-hackathon-judge.sqlite3
```

Use the same server command but only one active process on a port. Do **not**
commit secrets, add them to a project screenshot, paste them into Devpost or
give them to a model. The app is hardcoded to PayPal's **sandbox** OAuth and
Orders v2 endpoints; it has no live-payment switch.

In the **fictional Demo Retailer**:
1. Click **Add to cart** to create the research job and fixed **USD 29.00** internal quote.
2. Wait for the source assessment and real Qwen risk-plan stage.
3. Explicitly review and enter the exact amount and buyer-consent phrase shown by the app. The seller is a **fictional intermediary**, not an actual merchant.
4. Create a single PayPal Sandbox Orders v2 order. If it times out after submission, **do not press again**; reconcile the request ID and/or the order with a read-only GET.
5. In the **Sandbox Personal** account, approve the order on PayPal's hosted sandbox page. The app validates the PayPal order reference/currency/amount via read-only GET and may update the simulated retailer's order status. It **never captures** funds, purchases an external retailer's item, pays the manufacturer or ships a product.

This deliberately enforces the limit that model advice and indexed shop prices must not become charge instructions.

### 4. Run source tests without paid provider requests

```sh
# Run with no PayPal/Shopping keys; tests use mocked integrations.
env PAYPAL_CLIENT_ID='' PAYPAL_CLIENT_SECRET='' SERPAPI_API_KEY='' \
    python3 -m unittest discover -s tests -p 'test_*.py' -q
node --test browser-extension/*.test.mjs
```

**Verified on 2026-11-05 in a clean, isolated branch:** `652 Python
unittest cases PASS` (with no PayPal/Shopping credentials). Three stale,
short test deadlines were adjusted to tolerate concurrent worker completion;
a brittle test was corrected to locate the source-intake node by semantic
kind rather than an index. No research/checkout production logic was changed.

A fresh `git clone --depth 1` from public `main`, with empty PayPal and
Shopping credentials, started normally with Python 3.8.10, and returned
HTTP **200** for `/`, `/cart`, and `/demo/store` on localhost. This is
an independent **basic startup check**, not proof of a brand-new judge's
Ollama model or PayPal Sandbox setup.

### 5. How the buyer-safe flow works

1. **One-click event:** an actual form POST from a fictional store creates a
   research job; the UI renders real progressive tasks instead of a prerecorded
   graph.
2. **Retrieval and evidence:** individual source claims, indexed listings and
   browser evidence are recorded with provenance, not presented as verified
   performance measurements. Inaccessible stores remain visible as failures.
3. **AI:** a bounded local Qwen model performs **advisory** selection/risk
   classification. No model can overwrite prices or approve a purchase.
4. **Server-owned quote:** validated Python chooses amount from an immutable
   fictitious demo catalog, not from model text or unverified internet prices.
5. **PayPal:** explicit buyer consent precedes the sandbox order; PayPal-hosted
   approval and read-only order verification come before any simulated store
   status transition. No capture endpoint exists. Duplicate uncertain POSTs
   fail closed rather than retrying.

### 6. Real historical Sandbox evidence vs. the film

The historical RYOBI research path was verified **2026-11-04** with an
**actual** sandbox buyer approving an order and a subsequent PayPal read-only
GET returning `APPROVED`, matching reference and amount **132.60 PLN**
(see [submission readiness audit](PAYPAL_HACKATHON_SUBMISSION_GATE_2026-11-04.md)).
This was **not** payment capture, a merchant purchase or shipping.

A fresh live analysis recorded **2026-11-05** showed **17/17** indexed offers
checked, **113** graph evidence/offer cards and visible gaps. Its lowest
same-model-code index card was **131.99 PLN**, with **no direct retailer URL**.
The 2:10 English demo shows a real Sandbox-only quote for this later amount,
but **stops at the PayPal hosted login/approval step**. No buyer approval
was performed for the later `131.99 PLN` demo. Do not conflate the two runs.

### 7. Data, security and limitations

- This is **research, not an authorized retail checkout integration**.
- Marketplace names, third-party store cards and prices are not evidence of
  identical variants, stock, delivery costs or a reliable final total.
- Do not bypass CAPTCHAs or site access challenges. Avoid entering personal
  purchaser data into public support tickets or repository issues.
- Real service credentials and private database files must stay outside the
  public repository. The judge should use **their own** fresh Sandbox app,
  Sandbox Personal buyer, Ollama instance and (if desired) optional shopping
  discovery service.
- The optional shopping index may require a provider key and impose billing.
  The fictional store demo explicitly **skips paid shopping discovery**.
- No remote hosted demo is claimed; the fully functional build runs locally.
  `127.0.0.1` addresses in screenshots cannot be opened from the judge's machine
  unless they install and run this repository.

For historical implementation evidence, including sandbox contracts and
fail-closed behaviors, see [Sandbox implementation](RECOMMENDED_OFFER_PAYPAL_SANDBOX_2026-11-04.md)
and [one-click demo integration](ADD_TO_CART_PAYPAL_SANDBOX_DEMO_2026-11-04.md).
