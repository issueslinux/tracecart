# TraceCart — AI suggestions behind a PayPal consent firewall

**Development status: public MIT-licensed, testable MVP; NOT A CONTEST SUBMISSION.**

**Public source:** https://github.com/issueslinux/tracecart — this repository contains only TraceCart; no private Hunter data or PayPal credentials.
Project for [PayPal AI Hackathon 2026](https://paypalaihackathon.devpost.com/rules), deadline **November 12, 2026, 12:00 p.m. Pacific** (21:00 CET). Entire implementation created after the contest started; no existing TraceCart product reused.

## The problem

AI-assisted checkout is dangerous when a natural-language model can hallucinate prices, quantities or buyer consent. TraceCart separates those powers: a small local Qwen model can only suggest a catalog SKU and a bounded quantity, while trusted Python code derives the exact payable amount from a server-controlled catalog and requires an explicit, short-lived human approval before calling the **PayPal Sandbox Orders v2 API**. It never captures payments. Network uncertainty is reconciled manually instead of retrying blindly.

## Current end-to-end paths

- Natural-language request → **real** local Ollama inference → schema validation → server-side catalog price → persisted quote.
- Explicit human approval requires typing `I APPROVE SANDBOX CHECKOUT` **and** the exact USD amount. AI cannot approve or set arbitrary price.
- Approved quote → OAuth 2.0 token `/v1/oauth2/token` → `POST /v2/checkout/orders` using `PayPal-Request-Id`. **Fixed sandbox host:** `https://api-m.sandbox.paypal.com`.
- PayPal sandbox response is validated, including `https://www.sandbox.paypal.com` payer approval URL. State becomes `PAYER_ACTION_REQUIRED`; **no capture route exists**.
- A failed OAuth preflight leaves the approved quote safely retryable; no order API call is made. A timeout, crash, or unknown response after the create attempt → persistent `CREATE_UNCERTAIN` requiring **manual READ-ONLY GET** reconciliation by sandbox order ID, never another POST to avoid duplicates.
- Structured local audit journal for quote creation, explicit consent and request outcome. No credentials or request tokens in the journal.
- PayPal Orders API responses are rejected unless they echo the exact server-approved reference, USD currency and amount. Sandbox approval links must match the returned order ID and authorized host; HTTP redirects carrying secrets are disallowed.
- UI defends against cross-origin forms, CSRF and DNS-rebinding Host headers; runs loopback only.

## Running locally

Prerequisite: Python 3.8+; no dependencies beyond the standard library. Local Ollama at `http://127.0.0.1:11435` (alternatively `11434`) with model `qwen2.5:1.5b-instruct`. `core.py` supports local model parsing, while `app.py` binds to **127.0.0.1 only**.

```bash
git clone https://github.com/issueslinux/tracecart.git
cd tracecart
python3 -m unittest discover -s tests -v
python3 app.py --port 8765
# On that same machine: http://127.0.0.1:8765
```

PayPal **sandbox** credential provisioning (once an authorized developer account exists):

```bash
export PAYPAL_CLIENT_ID=...         # sandbox REST app client ID
export PAYPAL_CLIENT_SECRET=...     # sandbox REST app secret; do not commit
python3 app.py --port 8765
```

The application has **no live PayPal switch**. Credentials must be for a sandbox app; `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` are unset on the testing host. Do not disclose them in repo or demo. For a successful sandbox checkout, a payer uses the PayPal-provided approval URL; no sandbox payment has been created or approved in this implementation yet.

## Recorded checks — Nov 1, 2026

- Python stdlib `unittest`: **20 PASS**, including LLM price injection, exact amount consent, quote expiry, no duplicates after timeout, read-only reconciliation, OAuth contract, exact PayPal amount/reference checks, blocked live redirects, CSRF, hostile Origin/Host and complete loopback HTTP flow against an in-memory fake PayPal gateway. **No fake response is reported as a real PayPal transaction.**
- Actual local Qwen inference with `I would like two vintage ceramic pendants, please`: returned `ceramic-pendant`, quantity 2, server-priced USD **58.00**.
- Adversarial prompt asking for a cent-priced charge without confirmation: model returned an invalid selection, **fail-closed** as a `ValueError`; no quote, approval or payment.
- `python3 -m py_compile core.py app.py` passes; `GET /` on the local web UI returned HTTP **200**.
- End-to-end real-browser **Chromium + local Qwen → consent review** PASS: natural-language request for two pendants generated a server-priced quote of **58.00 USD**, shown with the real `QUOTED` state; screenshot below. A same-origin POST issue in the initial UI was found and corrected by using `Referrer-Policy: same-origin` while retaining strict `Origin` and CSRF checks. No approval or sandbox order was placed by the browser run.
- **Not yet verified:** *real* PayPal Sandbox OAuth/order creation, buyer approval, deployed judge-accessible instance, external model quality metrics, <3-minute video with professional narrator, YouTube upload or Devpost submission.

## References and constraints

- [PayPal Checkout Standard back-end integration](https://developer.paypal.com/platforms/checkout/standard/integrate): server creates an order, payer approves it, server optionally captures later. TraceCart deliberately stops before capture.
- [Official hackathon rules](https://paypalaihackathon.devpost.com/rules): PayPal sandbox + AI must both be central; source must be publicly available under an OSS license, demo actually runnable, and the competition requires a **public YouTube** demonstration video under three minutes. This public repository fulfills the source-availability step; it does **not** substitute for an authenticated PayPal Sandbox transaction, video or Devpost submission.
- All files in this standalone TraceCart project are provided under the [MIT license](LICENSE). No owner credentials are included.
- The three catalog items and user prompts are test examples, not market demand data. Validation under real inputs and additional differentiating capabilities are necessary before calling TraceCart an innovative contest entry.

### Real-browser screenshot (real Qwen quote, no payment)

![Actual local AI-generated, server-priced quote](media/tracecart-real-browser-quote.png)

## Next concrete milestone

Provision an authorized PayPal sandbox REST app, execute OAuth → create order → buyer approval in a test account, build a logged and repeatable UI journey, test timeout/duplicate and amount integrity, then produce a professionally narrated real-browser YouTube demonstration under three minutes, with only verified functionality, and complete the owner-approved Devpost entry. Only the owner may approve account registration, personal terms, account creation and final Devpost submission.

**Never use live payments or create unauthorized transactions.**
