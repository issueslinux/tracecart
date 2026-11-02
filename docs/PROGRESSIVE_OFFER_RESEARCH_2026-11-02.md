# Progressive per-offer research — 2026-11-02

## Problem resolved

The previous JavaScript waited for `state=READY` before drawing anything.
Source retrieval, SerpApi, the catalog collector and local Qwen could block
the page for 10–45 seconds. It then animated only 12 questions in a single
global research path, not a research plan for each indexed seller.

## Implemented data and interaction contract

On page load, **before the first network response**, the UI immediately
renders a product/source research node. The read-only
`GET /cart/status/{id}.decision.json` now includes `state`,
`progress_stage`, `progress_revision`, `offers` and bounded evidence
counts even while the research job is QUEUED/RUNNING.

The server commits incremental SQLite progress snapshots at:
`SOURCE_FETCH` → `CATALOG_AND_BASE_RESEARCH` →
`BASE_RESEARCH_AVAILABLE` → `SHOPPING_EVIDENCE_AVAILABLE` →
`LLM_SOURCE_QUESTIONS_IN_PROGRESS` → `RESEARCH_COMPLETE`.
These snapshots are a **separate table**, not a rewrite of the historical
research report or its SHA.

The browser polls the first 12 status requests every 450 ms, then
continues at the previous 1800 ms rate. It does not rerun SerpApi or
checkout. Once indexed offers are known, it draws **one research queue
per listing**, including Shopping cards without confirmed seller links;
not just the four ranked alternative configurations.

Each known offer receives a **288-question structured research backlog**
(24 functional dimensions × 12 different source validation operations).
For the saved x-kom/Lenovo Snapdragon case:

- 1 submitted product + 3 indexed retailer links + 12 indexed search
  cards = **16 separate offer research queues**.
- **288 planned questions per queue**, **4608 total**. All 288 questions
  within an offer are text-distinct and grouped by explicit product
  dimension, evidence probe and priority.
- The planner's initial projection of this saved job took about **0.012 s**
  on hexagony-01 (Python 3.8; local snapshot, **not** a network metric).
- `GET /cart/status/{id}/questions.json?offer=1&offset=24&limit=8`
  returns only the requested page. Maximum 24 questions per request;
  no thousands-of-elements upfront DOM.
- The UI automatically requests the first page for every offer and
  loads more as its scroll viewport becomes visible. **No buyer question
  buttons.** The full 288-question plan is accessible in ordered pages.

**Crucial evidence integrity:** all 288-per-offer questions are
`STRUCTURED_RESEARCH_PLAN_NOT_LLM` / `PLANNED_NOT_INVESTIGATED`.
The app does not falsely claim that 4608 independent source checks were
performed, that each question was produced verbatim by Qwen, or that any
question already has a documented answer. Old reference evidence and
independent tests still have their precise, variant-scoped provenance.

**True per-offer AI additions:** after a **new URL job** reaches READY,
a separate one-worker local Qwen process starts, without blocking
normal user jobs, the READY verdict or the page. It asks up to six
additional targeted source questions for **each listing**, one offer at
a time, using only unverified title, category and listing type. No
product URLs, indexed prices, EANs, checkout state, buyer identifiers or
PayPal credentials are sent to the model. Each result is stored
separately in `cart_offer_model_questions` with `OK` or a concrete
`UNAVAILABLE_*` failure. The page polls asynchronously for changes.
Historical saved jobs are **not silently re-run through the local
model** merely because somebody opens their report.

Model-created source questions and deterministic planning checks are
visually separate. All model questions are still **OPEN_RESEARCH_GAP**
until sourced evidence is fetched and matched; no invented answers.

## Tests, real browser, outstanding work

Verified on an isolated server (port 8795), on a **copy** of the user's
existing local SQLite database and without new SerpApi calls:

- Saved READY Lenovo: the read-only projection contained 16 offers and
  4608 structured questions; pagination returned the correct offset.
- Real Chromium headless, READY: 16 offer cards, 288 questions indicated
  on each, 456 question elements actually loaded in bounded pages, source
  links and final conditional ABSTAIN. No choice buttons or JavaScript errors.
- Real Chromium headless, artificially persisted RUNNING/SOURCE_FETCH:
  product/source tree and one 288-question backlog visible **before READY**;
  no fabricated completed conclusion.
- Existing security, status routes, payment authorization barrier and
  original raw research reports retained.
- Python 3.8: **381 tests** passed. Node: **9 tests** passed. JavaScript
  syntax and `git diff --check` passed. The new tests include a blocked
  local-model stage with visible Shopping snapshot, per-offer question
  uniqueness, bounded paging, model-origin provenance and model-data
  storage separate from the research report.

Remaining limitations: the 4608 questions are a research *work plan*, not
4608 completed independent investigations. The generic 24×12 expansion
needs future evidence-driven pruning and priority calibration to avoid
unproductive repetitive checks. The local model may be slow; its per-offer
follow-ups therefore run separately and are displayed as they arrive.
No seller checkout verification, complete external-review retrieval
pipeline or PayPal Sandbox approval proof was added in this milestone.

## Next substantive stage

Implement **evidence-driven question execution** instead of increasing
the raw count: choose the top unresolved high-impact questions for each
shortlisted offer, retrieve legally available OEM and genuinely independent
test documents, identify exact variants, record source URLs/method/dates
and contradictions, then mark a question ANSWERED only when its evidence
matches the offer. Abort duplicate and unanswerable branches. Keep
marketplace index quotes distinct from verified merchant prices and
preserve the PayPal consent boundary.
