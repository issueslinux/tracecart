# TraceCart — PayPal AI Hackathon submission gate and feature freeze

**UPDATE (2026-11-04, after original audit): P0-1 real Sandbox payer approval is VERIFIED for the existing recommended-offer pathway.** The historical blocker text below describes the original audit and is superseded by the evidence receipt in section P0-1 below. Judge-access, video and final Devpost submission gates remain open.

Audit date: **2026-11-04**. Official deadline: **2026-11-12 12:00 PST = 20:00 UTC = 21:00 CET (Poland)**. Judging ends **2026-12-15**. This is an evidence-based readiness review, **not** proof of Devpost submission or real PayPal Sandbox approval.

## A. Frozen product baseline — do not restart feature development

- Baseline Git commit: `97c751fed41afc88de9a3933b98a5df4f310cc7a` (TraceCart PR #85, current selected-offer browser coupon 2799.00 PLN).
- Immutable Git tag: `tracecart-core-freeze-2026-11-04`.
- **Frozen behavior:** shopping/search and offer extraction, automatic seller-browser evidence, interactive SVG knowledge graph, evidence attribution, source questions, price/coupon interpretation, purchase-decision logic and recommendation ranking. The existing graph and selection UI are the submitted product experience.
- Relevant code includes `search_first.py`, `source_search.py`, `automatic_offer_discovery.py`, `automatic_browser_verification.py`, `browser-extension/`, `offer_knowledge_graph.py`, `guided_decision.py`, `graph_*.py`, `purchase_insights.py`, `instant_evidence.py`, `model_verdict.py`, `similar_tier.py`, `assets/live-workspace.js`, and affected parts of `cart_research.py` and `app.py`.
- **Allowed after freeze:** PayPal Sandbox verification and separate checkout/demo integration, reproducible setup, presentation-only demo assets, deployment, video, English Devpost materials, and fixes for demonstrable P0 security, correctness or demo blockers. A core change requires a concrete failing regression and explicit reason in the PR; do not redesign the graph/search/decision model or spend on speculative provider coverage.
- Freezing is a project policy and a version anchor, not GitHub branch protection. Any future changes to these modules must be reviewed against this policy.

## B. Audited as functioning (not equivalent to contest submission)

| Item | Evidence and status |
| --- | --- |
| Public original repository and MIT license | **PASS.** GitHub `issueslinux/tracecart` is public and GitHub identifies the MIT license. Git history starts 2026-11-01, inside the competition period. |
| Search, SVG graph and evidence-limited decision | **FROZEN/TESTED.** Saved Media Expert Dell job `k5UU_xqmr8zQKPsj44gXwUKA` on local staging port 8810 shows conditional price **2799.00 PLN**, code `BW1610-0112`, list price **3499.99 PLN**, and a separate **3399.96 PLN** non-checkout index quote. A genuine headless Chromium UI test saw the current summary and no stale missing-price warning. Promotion redemption at checkout remains unverified. |
| Automated regressions | **PASS as of PR #85.** 620 Python unittest cases, 32 Node tests. No paid shopping-provider request was made for the coupon fix. Tests include mock/stub PayPal flows; a passing mock is not a real PayPal transaction. |
| Local AI available to developer | **LOCAL SERVICE RESPONDS.** Ollama on `127.0.0.1:11435/api/tags` listed `qwen2.5:1.5b-instruct` on 2026-11-04. A prior real-Qwen quote-to-consent browser flow was documented in README. This does **not** prove that a judge can run Ollama without setup. |
| Sandbox-only payment implementation | **IMPLEMENTED / MOCK-TESTED ONLY.** `core.py` uses fixed `https://api-m.sandbox.paypal.com` OAuth and Orders v2 endpoints, price locked by a trusted catalog, explicit human amount consent, idempotency token and no capture route. `/` offers the quote/payment journey; `/cart` offers retailer research. |

## C. Submission blockers — ordered gates

### P0-1. Real PayPal Sandbox proof — BLOCKED

**Observed:** `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` are not configured in the active local app processes on ports 8781 or 8810; no successful PayPal-hosted sandbox OAuth, create-order or buyer approval receipt was found in current project documentation. Test doubles are not sufficient evidence of integration.

**Need:** owner provisions/authorizes a PayPal **Sandbox REST app** and sandbox buyer account. Run *without live payments* the real flow `Qwen suggestion -> catalog-locked quote -> explicit amount approval -> OAuth -> POST /v2/checkout/orders -> PayPal-hosted sandbox payer approval`. Capture sanitized order ID, order state, environment, request/response validation and UI/video evidence; never publish secrets or buyer session details. Preserve existing safety rule: **no capture**, **no silent retries** after uncertain POST.

**Acceptance:** real sandbox API order creation and buyer approval demonstrated in a repeatable browser run; test both wrong-price rejection and missing/invalid credentials. A successful fake PayPal reply is **not PASS**.

### P0-1 evidence update — VERIFIED on actual PayPal Sandbox (2026-11-04)

The actual interactive user journey was verified after PR #91 and PR #92
were merged to `main` and deployed exclusively on localhost staging 8810.
Original product research and the evidence graph remained intact; the
buyer selected a suggested indexed retailer offer rather than using the
unrelated demo catalogue:

- Research job: `45njvY2FStBkk9WwLDQ_grQ0`, Ryobi R18PI-0.
- Suggested option: `offer-1`, indexed/listing price `132.60 PLN`.
- Human explicitly approved the illustrative amount in TraceCart,
  then created a single PayPal **Sandbox** Orders v2 order.
- The Sandbox Personal buyer completed PayPal-hosted approval and returned
  to the bound TraceCart quote URL (`GET /cart/sandbox/<quote>?token=...`).
- TraceCart durable order state: `VERIFIED_APPROVED`.
- A subsequent, independent **read-only** API call to the real
  `api-m.sandbox.paypal.com/v2/checkout/orders/<id>` returned
  `status: APPROVED`. Reference ID, amount `132.60` and currency `PLN`
  all matched the server-persisted quote.
- Sandbox order ID is intentionally redacted in this public document
  (`…5513`). No API keys, buyer identity, session token or PayerID
  are published.
- **No `/capture` request, no real money transfer, and no purchase at
  Allegro/TIM/Media Expert** was performed. The Sandbox account's
  business payee is not the seller from the offer index. The listed price
  is expressly *not a verified merchant checkout total*.
- Test evidence: 16 focused Python PayPal/demo tests PASS, 40
  JavaScript tests PASS, and headless Chromium confirmed the
  recommendation button in the actual Ryobi research graph.
- Full unrelated Python regression suite is **not green**: 646 tests
  executed with 5 failures and 1 error involving async timing/source
  recovery. The deterministic `price_is_confirmed_checkout_total`
  error reproduces on unmodified `main` baseline.

**Gate result: P0-1 PASS for real Sandbox OAuth + Orders create +
hosted buyer approval + read-only verification on recommended offers.**
This is proof of PayPal integration, **not** proof of payment capture,
actual merchant purchase, a public judge-accessible deployment, public
demo video, or Devpost submission. Do not repeat the Sandbox create
request just to reconfirm the same receipt.

### P0-2. Judge-accessible working application — BLOCKED

**Observed:** the working URLs `http://127.0.0.1:8810` and `http://127.0.0.1:8781` are loopback URLs on the developer machine, not publicly accessible to judges. README has basic clone/start commands, but real search needs provider access/caches and browser permission grants, Ollama needs a local model, and PayPal needs a Sandbox account.

The **official rules do not require public hosting**, provided a judge can run an actual functioning build from complete, clear repository setup instructions. Choose one tested path:

1. Public judge-safe hosted demo (no real credentials exposed, no production funds; keep available through 2026-12-15); **or**
2. Tested clean checkout/clone installation with English end-to-end steps, sample data that does not require billed provider calls, exact Ollama model/startup, Browser Companion pairing/permissions when needed, sandbox test access instructions and troubleshooting.

**Acceptance:** an independent clean environment reaches working AI, graph, human consent and PayPal Sandbox interaction using the provided instructions. Do not confuse static screenshots with an interactive build.

### P0-3. A coherent PayPal + AI story — PRESENTATION GAP

**Observed:** retailer research (`/cart`) and authorized sandbox checkout (`/` with a *server-owned USD demo catalog*) are currently separate flows. A PayPal order is **not** a way to purchase an arbitrary Media Expert/Allegro product, and no integration with those retailers' checkouts is present. Do not imply otherwise.

**Need:** record a truthful, coherent user journey showing evidence-backed selection, what remains unverified, and the **separate controlled sandbox purchase demonstration** with Qwen + server-pricing + explicit user approval. If a minimal UI handoff is added, keep the frozen decision/search/graph untouched and never assert payment for third-party listings. Demonstrate PayPal as a central piece of the safety/consent architecture, not an unrelated button.

### P0-4. Public YouTube film under 3 minutes — MISSING

**Need:** real browser screen recording, English narration or full English translation, and a **publicly visible** YouTube URL entered on Devpost. No unlicensed music, third-party trademarks or copyrighted visuals. Judges are not required to watch past 3 minutes.

Recommended honest storyboard (<180 s): problem and buyer-consent risk (0–20 s); one saved live research input and interactive evidence graph (20–75 s); visible coupon vs index quote and abstention before unverified checkout (75–105 s); **separate** real Sandbox quote → explicit consent → PayPal approval (105–160 s); safety and audience/impact (160–175 s). Only demonstrate steps actually verified before recording.

### P0-5. Devpost entry and owner identity — NOT CONFIRMED

**Need:** participant joins the hackathon, confirms adult eligibility/no conflict of interest, completes English project description, AI tooling disclosure, source URL, runnable demo, public YouTube video, prize category selection where appropriate, and presses Submit **before 2026-11-12 21:00 CET**. Save screenshot/receipt of completed submission. Owner performs personal account registration, terms acceptance and final submission; the assistant must not claim these occurred. Poland is **not explicitly excluded** by the current rules, subject to the participant's own eligibility.

### P0-6. Rights, credentials and source transparency — REVIEW REQUIRED

Public repository/demo must not expose PayPal or shopping-provider secrets, buyer data, browser tokens, private database contents, or assets without publishing rights. Respect third-party data licenses and website terms. Show scraped/index prices as observations, not verified seller checkout or exact-SKU proof. Document the precise difference between deterministic price comparison and local Qwen inference. The README and English Devpost text must not claim that the agent autonomously pays for external retailer offers.

## D. Not release blockers unless they fail the chosen demonstration

- Wider Allegro coverage, automatically resolving every Google Shopping card, more retailer connectors, new model benchmarks, more question templates, new graph UI work, and additional ranking features: **DEFERRED by freeze**.
- Real shipping totals and coupon application for all external merchants: **remain evidence gaps**, not claimed as complete; demo must label them honestly.
- External market validation and performance numbers: useful for judging impact, but a carefully defined problem/use case is enough for submission; do not invent impact metrics.
- A hosted demo is desirable but **optional under the rules** if a genuinely reproducible local build is supplied.

## E. Verification and evidence collection

Run from a clean, known branch **without paying search providers**:

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -q
node --test browser-extension/*.test.mjs
python3 app.py --port 8765
```

AI setup and product inputs must follow README; `GET http://127.0.0.1:8765` is the separate sandbox catalog workflow, and `GET http://127.0.0.1:8765/cart` is the frozen research UI. Do not publish credentials in command transcripts. The headless/fake gateway tests alone cannot close P0-1.

**Evidence required to mark gate PASS:** sanitized PayPal Sandbox order receipt and buyer-approved state; judge-access verification or complete tested clean-room instructions; under-3-min public YouTube link; English Devpost submission URL/receipt.

## F. Official rules used in this audit

- https://paypalaihackathon.devpost.com/rules
- https://paypalaihackathon.devpost.com/details/dates
- https://paypalaihackathon.devpost.com/details/faqs
- https://developer.paypal.com/community/blog/PayPal_AI_Hackathon/

Judging is **Stage One pass/fail** on theme and API/SDK applicability, then equally weighted implementation, design, impact, innovation, and presentation. Prioritize a genuine working PayPal Sandbox demonstration rather than polishing frozen search features.

## G. Post-audit implementation update: one-click storefront demo

A separate *fictional* local retailer at `/demo/store` now has a real
**Add to cart** HTML button, and clicking it dispatches the existing cart
research event without URL entry, automatically launches the frozen evidence
engine and the local-Qwen risk plan, and renders an explicit-amount PayPal
Sandbox quote for the fictional intermediary. A validated Sandbox buyer
approval can update the **simulated** store state, but no actual merchant
order or payment capture is possible. A bounded client-side status poll uses
read-only Sandbox GET requests, not create-order retries. The fixed USD
catalog amount is independent of AI and any scraped offer. See
[one-click demo integration](ADD_TO_CART_PAYPAL_SANDBOX_DEMO_2026-11-04.md).

Offline mocked-gateway tests and an actual Chromium button-click + live
local-Qwen plan were verified. **These do not close P0-1**: real authorized
PayPal Sandbox credentials, OAuth, hosted buyer approval and a real Sandbox
`APPROVED` GET response remain necessary. Likewise a judge-accessible demo,
video and final contest submission remain outstanding.

**Cost safety correction:** Fictional storefront add-cart events explicitly
skip the paid SerpAPI shopping provider even if a credential is configured
for normal research. A separate regression checks that no paid discovery
callback is invoked for this demo. This safety exception touches only the
one-job dispatch flag; the frozen search/ranking behavior for ordinary
retailer research is unchanged.

## H. Updated contest submission status — November 5, 2026

This update supersedes the earlier "missing video" and "missing runnable
judge instructions" statements above without rewriting their historical
audit context.

- **YouTube public video: PASS.** [PayPal TraceCart LIVE EN](https://www.youtube.com/watch?v=SSsUvSXVhCk)
  has signed-out YouTube player metadata `isUnlisted=false`,
  `isPrivate=false`, `playabilityStatus=OK` and duration 130 seconds.
  The actual full real-time RYOBI run in this video is recorded from the
  browser; the subsequent sandbox quote stops before payer approval.
- **Code and OSS license: PASS.** Public GitHub repository
  `issueslinux/tracecart`, MIT license recognized by the GitHub license API.
- **Judge local installation: BASIC VERIFIED.** A fresh independent
  `git clone --depth 1` and Python 3.8.10 process (with no credentials)
  served `/`, `/cart`, and `/demo/store` with HTTP 200. The newly written
  [Judge Quick Start](PAYPAL_HACKATHON_JUDGE_QUICKSTART.md) describes Ollama
  and Sandbox setup. This is **not yet an independent full Qwen + Sandbox
  clean-room test**.
- **Automated regressions: PASS after test-only stabilization.**
  652 Python tests and 40 Node tests passed on a dedicated isolated
  worktree with no PayPal/Shopping provider keys. Previously, three timing
  tests relied on short bounded waits under load and one obsolete assertion
  relied on a fixed graph-child index despite newer nodes preceding it.
  Only test waiting windows and stable node selection were adjusted;
  frozen research/checkout logic was not changed.
- **English Devpost content: DRAFT READY**, see
  [prepared entry](DEVPOST_PAYPAL_AI_HACKATHON_2026_ENTRY.md).
- **Actual contest submission: ENTRANT REPORTS SUBMITTED 2026-11-05.**
  The entrant said they had logged in and submitted the TraceCart entry.
  This has **not been independently verified** by a Devpost project URL or
  confirmation receipt. Do not claim independent confirmation. A publicly
  viewable YouTube link is not, on its own, a Devpost entry.
- **Rights review: PENDING.** The video depicts third-party product
  pages and marks (e.g. RYOBI, Allegro). Official contest rules prohibit
  including third-party trademarks/copyrighted media without permission.
  Entrant must confirm sufficient rights, obtain permission or replace
  problematic material. Do not implicitly claim rights.
- **Deadline remains 2026-11-12 12:00 PST / 21:00 CET**.

## I. Entrant's Devpost reference supplied — November 5, 2026

The entrant shared their Devpost management link containing contest identifier
**31302** and submission identifier **1283840**, and stated that the project
had been submitted. This is a **private management URL**, not the public
`devpost.com/software/...` project permalink. The private management URL
is intentionally not copied into this public repository.

An unauthenticated request to this management URL was redirected to
`https://secure.devpost.com/users/login`. As of this check, the project
title, final submission state, YouTube/repository fields and acceptance
receipt **could not be independently inspected** from a signed-in Devpost
account. A public `https://devpost.com/software/...` page was also not
confirmed by the current public search results.

**Recorded state:** entrant reports submission; submission reference exists;
public entry URL and authenticated confirmation remain unverified. Do not
represent an admin edit link as a public project page or infer acceptance
from the numeric submission ID. The entry owner can confirm the Devpost
dashboard shows **Submitted** and share the `View project` permalink,
at which point this record can be updated.
