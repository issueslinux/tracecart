# TraceCart — AI suggestions behind a PayPal consent firewall

**Development status: public MIT-licensed, testable MVP; NOT A CONTEST SUBMISSION.**

**Public source:** https://github.com/issueslinux/tracecart — this repository contains only TraceCart; no private Hunter data or PayPal credentials.
Project for [PayPal AI Hackathon 2026](https://paypalaihackathon.devpost.com/rules), deadline **November 12, 2026, 12:00 p.m. Pacific** (21:00 CET). Entire implementation created after the contest started; no existing TraceCart product reused.

## New workflow: automatic research after the item enters the cart

The shopper has **already chosen a product**. When the merchant records
"Add to Cart", TraceCart can accept its details in a local background job and
prepare an evidence-based comparison before checkout. Its job is to show
alternatives, differences, missing evidence and critic questions, not force
a buyer into a different product or trigger a payment.

**Run the demo:** `python3 app.py --port 8770`, then open
[http://127.0.0.1:8770/cart](http://127.0.0.1:8770/cart).
The sample cart input is ILLUSTRATIVE. The research job, by contrast,
actually searches **Open Products Facts** for similar and cross-brand
products and tries **Open Prices** historical prices for a selected EAN;
both outcomes are preserved. The local Qwen model (when available) proposes
additional questions about sources. Public product catalog entries are NOT
shop offers. Without verified competing store prices, the UI states that
zero competing offers were price-verified and never claims imaginary savings.

**Store integration interface:** authorized server-side
`POST /api/cart/added` with `X-TraceCart-Event-Token`, configured using
`TRACECART_CART_WEBHOOK_TOKEN`; responds immediately with HTTP 202 and a
job/status ID. Product data only; no buyer details or payment instructions.
Results persist in SQLite and export as a complete evidence/critic JSON tree.
The sample server remains loopback-only and **is not yet wired to WooCommerce
or any real remote checkout**. See
[full cart-hook integration and data limitations](docs/CART_TRIGGERED_RESEARCH.md).

If `BRAVE_API_KEY` is configured, a bounded public web-search request
attempts discovery of competitor-store links. Search links/snippets remain
UNVERIFIED until actual merchant offers, prices and stock can be confirmed.
Brave requires an authorized API key; without one the step is reported
`SKIPPED_NO_API_KEY`, not silently presented as success.

**Source attribution:** Open Products Facts / Open Prices are external
community databases. Original application code is MIT-licensed;
[external data attribution and licensing](examples/DATA_SOURCES.md)
are separate. The captured snapshot below is historical, not live prices.

![Real browser: automatic detergent cart research](media/cart-triggered-powder-research-browser.png)

[Observed source-linked cart report (historical snapshot)](examples/live_cart_persil_2026-11-01.json)

## NEW: conditional comparisons instead of a forced purchase verdict

**Product direction:** TraceCart is a comparative purchasing analyst, not a
machine that insists on choosing a winner. Offer A may be cheaper; B can have
higher advertised specs whose usefulness is unknown; C may be used and cheaper
but need seller confirmation about repairs, condition, battery and returns.
The buyer sees the trade-offs first, then the **complete evidence/critic tree**.

Open **http://127.0.0.1:8765/compare** after starting the local app. It accepts
structured offers, price, currency, condition, comparable specifications and
source URLs. It computes price deltas with an explicit denominator and
identifies missing specs; no spurious overall quality score is produced.
The comparator's final status is **NO_FORCED_WINNER**, not a forced abstention
from useful comparative analysis. The full traceable decision tree remains
available below and as a JSON export. PayPal checkout remains unrelated and
requires explicit human approval.

View the **FICTIONAL illustrative example**:
- [Three offers, original hypothetical inputs](examples/comparison_three_laptops_FICTIONAL.json)
- [Full expandable comparative report](examples/comparison_three_laptops_FICTIONAL.html)
- [Full comparative JSON audit](examples/comparison_three_laptops_FICTIONAL_report.json)
- [Chromium screenshot](media/comparison-conditional-real-browser.png)
- [Permanent product direction / next milestones](docs/DECISION_SUPPORT_VISION.md)

These sample offers use reserved example domains and are not current retailer
listings, independently measured performance, verified user needs or real
seller statements. The next step is feeding **actually comparable real offers**
and their evidence into this presentation, not polishing isolated SHT40 spec checks.

## Two-publisher product specification cross-check (2026-11-01)

**New evidence source beyond the retailer:** TraceCart now reads the official
[Sensirion SHT40 chip specification](https://sensirion.com/products/catalog/SHT40)
and compares it with the actual
[Adafruit SHT40 breakout listing](https://www.adafruit.com/product/4885).
The cross-check is invoked via **/research → Cross-check SHT40 against Sensirion**.
Two separate URLs have fixed HTTPS domains, robots.txt checks, no redirects, size
and timeout limits, and page SHA-256 + retrieval timestamp provenance. The
merchant Product/Offer JSON-LD determines **current** price/stock; Sensirion is
technical documentation, **not a seller offering the same breakout board**.

Verified actual values on 2026-11-01:
- Typical SHT40 chip relative-humidity accuracy: retailer **1.8 %RH**, OEM **1.8 %RH**.
- Typical SHT40 chip temperature accuracy: retailer **0.2 °C**, OEM **0.2 °C**.
- The merchant listed the assembled breakout for **USD 5.95** at capture time.

Both sources are distinct **publishers of nominal component specifications**,
NOT independent lab tests or reviews. Their numerical agreement corroborates
the documentation values only; it does not measure this specific board, verify
power/regulator behavior or certify a unit. The critic explicitly opens follow-up
questions about the finished board and its measurements and the decision remains
**ABSTAIN** until important unknowns are resolved. If the two documents
disagree, the criterion becomes **CONFLICTED** and the critic objects.

Reproducible source-linked example:
- [Complete actual two-publisher decision tree (offline HTML)](examples/live_sht40_two_publishers_2026-11-01.html)
- [Full signed-by-hash analysis JSON](examples/live_sht40_two_publishers_2026-11-01.json)
- [Real source input snapshot](examples/live_sht40_two_publishers_2026-11-01_input.json)
- [Screenshot from actual browser](media/live-sht40-oem-crosscheck-browser.png)

Scope remains deliberately limited: this is **not** yet broad autonomous review
search, an independent comparative product test, measured reliability or a
validated decision-rank model. Real PayPal Sandbox credentials and a Devpost
submission are also still pending.

## LIVE offer source collector — first verified merchant integration (2026-11-01)

The /research interface now offers two paths: import previously collected
offers/reviews as JSON, or **fetch live product pages directly** from the
explicitly allowlisted merchant Adafruit. Enter 1–5 full HTTPS product URLs,
one per line. This is a concrete external data integration, not a fabricated
example. The connector is **not a general web search engine yet**.

**Technical safeguards:** Python standard-library HTML/JSON-LD Product/Offer
extraction, robots.txt preflight, non-public host rejection, strict Adafruit
product URL allowlist, HTTP redirect refusal, timeout/response-size caps, a
minimum 2-second spacing between product fetches, and no login or authentication.
Sources retain the original link, retrieval timestamp, publisher domain, source
type, SHA-256 of the exact downloaded page bytes and the extracted field.

**Evidence discipline:** listed price, stock and declared condition are
**merchant assertions**, not independently confirmed facts. Multiple URLs at
one publisher do not count as independent corroboration. External customer
reviews and third-party tests **are not collected** in this initial connector
(and are counted as zero in its reports). The separate deterministic critic
runs on every result; the optional local Qwen researcher and critic can propose
new **open questions** about these real source records, not facts or payments.
Every failed fetch is visible in the full tree and source report. We never
silently replace missing sources with model text. With unresolved claims the
final recommendation remains **ABSTAIN**, and no payment can be authorized
from the report.

**Live-verified historical example:** On 2026-11-01 the collector read real
Adafruit pages for ADS1015 (1083, merchant price USD 9.95, InStock),
SHT40 (4885, USD 5.95, InStock), and Raspberry Pi Zero W (3400,
USD 15.00, OutOfStock). These items are different products; do **not**
interpret the three prices as directly comparable purchase alternatives.
Prices and availability may have changed since that snapshot.

- [Offline expandable full tree from actual source retrieval](examples/live_adafruit_2026-11-01.html)
- [Audited live tree JSON with provenance and final abstention](examples/live_adafruit_2026-11-01.json)
- [Actual external evidence input JSON](examples/live_adafruit_2026-11-01_input.json)
- [Real Chromium screenshot of source-linked tree](media/live-merchant-evidence-browser.png)

The local full workflow was verified with 3 real HTTP fetches, 9 extracted
merchant claims, an expandable 68-branch report, a persistent JSON download,
and a final ABSTAIN. **No reviews, independent testing, ranking calibration,
payment or hackathon submission was completed in this step.**

## Evidence Critic and Complete Decision Tree (experimental)

TraceCart now builds a transparent, expandable decision tree from supplied
search results, product listings, reviews and test excerpts. Users are not asked
dozens of questions: the analysis questions target the OFFERS and EVIDENCE.

The researcher proposes new investigations. The independent critic challenges
unsupported or contradictory interpretations. A deterministic critic always
flags missing sources, single-source assertions, contradictory excerpts and
remaining evidence gaps. Local Qwen can optionally generate further questions
in two separate researcher/critic passes. AI proposals are OPEN QUESTIONS,
never trusted answers. Duplicate and over-budget proposals are documented in
the tree audit. The engine does not use source counts as an automatic quality
score and abstains when material evidence remains uncertain.

After analysis, the user can inspect EVERY tree branch, including each offer,
question, evidence URL and excerpt, critic objection, proposed follow-up and
final decision. Reports persist locally across restarts and export as complete
JSON snapshots with a SHA-256 digest.

Run the local app (python3 app.py --port 8765) and open
http://127.0.0.1:8765/research . Paste source data as JSON or start from the
clearly FICTIONAL demo fixture. Enable optional AI-generated follow-ups if
Ollama is running. Review the expandable results; click Export complete JSON.

Artifacts:
- [Fictional example input](examples/sample_research_fixture.json)
- [Full example decision-tree JSON](examples/sample_decision_tree.json)
- [Standalone offline expandable HTML](examples/sample_decision_tree.html)
- [Real-browser view of the tree](media/tracecart-critic-tree-browser.png)

![Expandable evidence/critic tree](media/tracecart-critic-tree-browser.png)

CURRENT LIMITATION: This module does NOT yet discover or search across
arbitrary marketplaces or review sites. The new connector only fetches explicitly
specified product URLs from one supported merchant.
The sample offers and reviews use reserved example domains and are not real
product evidence. Automated source collection, publisher deduplication,
independent source verification and calibrated multi-criteria rankings remain
future milestones. The decision report is informational and cannot authorize
or trigger a PayPal order.


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
