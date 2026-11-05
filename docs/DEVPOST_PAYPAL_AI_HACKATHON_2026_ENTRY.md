# Devpost entry — TraceCart (ready-to-paste English copy)

**STATUS (2026-11-05): entrant reports submitting the TraceCart project on Devpost.** Public project URL and acceptance receipt have not yet been provided or independently verified. This document preserves the original submitted-copy draft, not proof of acceptance.
YouTube link is public and verified (see below).
YouTube link supplied and its public no-login playback endpoint verified 2026-11-05.
The entrant reports completing the account/login and submission actions
within the entry window ending **2026-11-12 12:00 PST (21:00 CET)**.
The signed-in Devpost project confirmation still needs to be checked.
Eligibility and third-party media rights remain the entrant's responsibility.

## Project name

TraceCart — Evidence-First AI Shopping With a PayPal Consent Firewall

## Elevator pitch / tagline

A shopping assistant that reveals the evidence behind a better deal — then
keeps AI, uncertain prices and payment authorization strictly separated.

## Project description

### Inspiration

The modern shopping journey has an accountability problem. Shopping agents can
compare product offers in seconds, but search results and merchant descriptions
can overstate equivalence, omit delivery costs and encourage checkout before
a buyer has seen the evidence. A generative model also shouldn't decide both
what to recommend and how much money to send. TraceCart was built to test a
different approach: **AI for analysis, deterministic software for amounts and
buyer consent, and PayPal Sandbox for auditable approval.**

### What it does

TraceCart starts from an actual shopping-cart event or a product URL. It
progressively researches product claims and potentially cheaper listings,
arranges sources, offers and unanswered verification questions in an
interactive evidence graph, and produces an evidence-limited recommendation.
As the browser checks complete, the live interface updates rather than
waiting for a single opaque AI response. It explicitly distinguishes
manufacturer claims, search-index prices and incomplete web pages from
independent measurements and verified checkout totals.

The one-click demonstration storefront starts the same research workflow.
A small local Qwen model prepares an **advisory** risk plan; a trusted Python
catalog independently computes the fixed demo amount. The user must approve
that amount before the server can create a **PayPal Sandbox Orders v2** order.
The payer uses PayPal-hosted approval. TraceCart performs read-only order
verification before allowing a fictional store to mark its **simulated**
order as accepted. **No money is captured and no actual external merchant is
paid.**

A separate real-product example uses a RYOBI inflator URL. In a fresh live
recording TraceCart examined 17 potential offers and displayed the source
checks and gaps. A **131.99 PLN** same-model-code search-index card became
the lowest conditional lead, **not a verified retailer price**: the seller
URL, product equivalence and delivered total remained unconfirmed. The
demonstration shows an explicitly sandbox-only PayPal quote for that amount,
without pretending a purchase took place.

### How we built it

- **Backend:** Python 3.8+ standard library, local HTTP server,
  source-specific research jobs, SQLite persistence, bounded concurrent
  evidence workers, strict validation and safety policy.
- **AI:** local Ollama + **Qwen 2.5 1.5B Instruct** for constrained product
  selection, risk/explanation and sourced advisory questions. Qwen does
  not set amounts, override evidence or approve spending.
- **Front end:** browser-native JavaScript and interactive SVG knowledge
  graph; progressive same-origin live updates expose the status of each
  source, offer and unanswered question.
- **PayPal:** **Sandbox OAuth 2.0** and **Orders v2**
  create/get/hosted approval links; server-side amount validation,
  quote expiration, idempotency and strict host/reply checks. No live
  API configuration, no capture endpoint, and no uncontrolled retry
  after an uncertain create-order response.
- **Testing:** Python unittest and Node tests for authorization, graph
  contracts and fail-closed paths; actual browser evidence and a historical
  real PayPal-hosted Sandbox buyer approval were separately verified.

### Challenges we ran into

**Prices are not facts simply because an API returns a number.** Search
index listings may represent the wrong model, missing accessories, old
prices or sellers that cannot be accessed for verification. We expose the
provenance of each claim and keep missing information visible. We also had
to prevent an asynchronous AI worker from blocking an evidence-limited
decision the UI could already make, and ensure PayPal order POST uncertainty
does not cause duplicate attempts.

### Accomplishments

- A working **cart → live research → evidence graph → conditional
  comparison** interaction, using a real browser.
- A unified **fictional** cart event → local Qwen risk advisory → trusted
  price → explicit user consent → PayPal Sandbox path.
- Verified actual PayPal Sandbox buyer approval for a recommended offer
  on 2026-11-04 via a separate historical run, followed by read-only
  `APPROVED` status and matching reference/amount/currency.
- The payment API cannot be redirected to live PayPal and no payment
  capture exists. An AI assertion or search-index price is never sufficient
  proof of buyer authorization.

### What we learned

Showing uncertainty is useful product design. The most important output
may be a precise missing question, not a product suggestion. Payment is
safer when the model can only advise while the server controls the
catalog, amount, beneficiary, one-time consent and subsequent sandbox
verification.

### What's next

Extend to authorized merchant integrations, independent variant
verification, real shipping/checkout totals and user-initiated order
flows — **only with merchant authorization**. No third-party purchase,
shipping arrangement, completed real payment or universal equivalence
claim is made by the current MVP.

### AI tools and disclosures

The application uses **local Ollama/Qwen 2.5 1.5B Instruct** to suggest
catalog items/quantities and classify evidence and risk under strict
server-side constraints. Retrieval and price comparisons are primarily
deterministic and source-driven; not all results are AI-generated.
The English demo voiceover was synthesized using **ElevenLabs TTS
through fal**. Audio generation is a presentation tool, not the
production application's decision engine.

### Impact and intended users

Consumers buying complex products or comparing unfamiliar sellers; small
retailers exploring AI-powered checkout without handing pricing authority
to a model; and developers building transparent agentic-commerce safeguards.
The demonstration is an MVP and does **not** establish measured customer
savings or conversion uplift.

## Technology tags

Python, JavaScript, HTML, CSS, SQLite, Ollama, Qwen, PayPal Sandbox,
PayPal Orders v2, OAuth 2.0, Chromium, SVG, AI, Fintech, Agentic Commerce.

## Public source code

https://github.com/issueslinux/tracecart

## Working application for judges

**Run locally**, using [Judge Quick Start](PAYPAL_HACKATHON_JUDGE_QUICKSTART.md).
The project is not publicly hosted. Judges should follow the repository
instructions to set up their own Ollama/Qwen model and a free PayPal Sandbox
REST app + Sandbox Personal buyer credentials. The localhost screenshots
in the film do not constitute a publicly accessible URL.

## Demo video (mandatory YouTube link)

**YouTube video:** https://www.youtube.com/watch?v=SSsUvSXVhCk

**Public visibility VERIFIED 2026-11-05:** signed-out YouTube watch page
and YouTube oEmbed returned HTTP 200. Player metadata explicitly declares
`isUnlisted: false`, `isPrivate: false`, `playabilityStatus: OK`, and
`lengthSeconds: 130`. Video: **PayPal TraceCart LIVE EN** by
**Linux Issues**. This confirms a publicly watchable YouTube video within
the contest's three-minute limit, **not** acceptance by Devpost.

Local original video (archived on developer machine):
`/home/daniel/Pobrane/TraceCart_RYOBI_R18PI0_LIVE_EN.mp4`;
length **2:10**, **English narrated**, authentic 58-second browser capture
of the newly initiated analysis, and separate Sandbox quote/login stage.
YouTube upload and public playback are verified. The entrant must still
review **rights to third-party trademarks/logos/screenshots** (RYOBI,
Allegro and other brands displayed in the browser capture) and narration
before submitting. The link must be entered in the
authenticated Devpost form; adding it to this document is not submission.

## Potential prize fit

The project is eligible for the **general** prizes if all rules are met.
Relevant honorable-mention themes (awarded by judges, not guaranteed):
**Best Use of PayPal + AI** and **Best Use of Agentic Commerce**.
Do not claim partner sponsor-prize eligibility without using the named
partner's tools.

## Entry owner checklist — still required

- [x] Owner reports authenticated Devpost login and contest submission; no independent receipt yet.
- [ ] Adult eligibility / conflicts of interest / ownership and license
      and third-party visual rights are reviewed and confirmed.
- [x] YouTube watch URL recorded; public metadata verified
      (`isUnlisted=false`, `isPrivate=false`, duration 130 s).
- [ ] Full judge setup tested from clean clone; no secrets embedded.
- [ ] Project title, full English description, AI-tool disclosure,
      GitHub URL and functional-demo instructions entered into Devpost.
- [x] Owner reports submission completed before the deadline.
- [ ] Official Devpost project URL + acceptance receipt independently recorded.
