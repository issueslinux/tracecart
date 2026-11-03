# Connected offer knowledge graph — 2026-11-03

## What changed

TraceCart now projects an **interactive, provenance-labelled offer graph** from
an existing saved research job. It joins all indexed offers, each
title-derived technical value, **unverified** indexed price quotes, open
high-priority research dimensions, independent source observations and
the source documents those observations came from. It also shows a
**decision gate**: where purchase advice must abstain for lack of exact
variant evidence and verified seller checkout price.

This is **not** a graph inferred by a language model. Its links are deterministic
and inspectable, generated from the saved report and persisted SQLite
evidence/model-question records. It does not require Neo4j, paid services or
new external fetches; future graph persistence/export to Neo4j is optional.

### Read-only JSON/API

`GET /cart/status/<job_id>.knowledge-graph.json`

Returns:
- `schema_version: tracecart.offer-knowledge-graph.v1`
- typed `nodes`: `offer`, `title_claim`, `derived_claim`,
  `indexed_quote`, `research_gap`, `reference_observation`,
  `fetched_source`, `decision_gate`.
- typed `edges`: `TITLE_MENTIONS`, `CALCULATED_FROM_TITLE_CLAIMS`,
  `ARITHMETIC_INPUT`, `INDEXED_PRICE_CLAIM`, `EVIDENCE_NEEDED`,
  `RESEARCH_GAP_PREVENTS_VERIFIED_DECISION`, `HAS_SOURCE_OBSERVATION`,
  `OBSERVED_IN_SOURCE`, `INFORMS_DIMENSION`,
  `SIMILAR_INDEX_MODEL_NAME_LEAD`.
- `offer_details` including unverified claims, listed/index quote price
  if any, high-priority unanswered questions, local LLM question
  *proposals* (never answers), review references and exact identity
  mismatch/provenance conditions.
- `stats`, `decision_status`, `provenance` and `limitations`.

Node and edge IDs are stable for the same input and contain no
untrusted HTML. The graph is **computed when requested**, leaving the
original immutable report, stored snapshots and saved source SHA intact.
The old `.decision.json`, `/questions.json`, `/audit` and raw JSON
continue unchanged. No PayPal/payment actions are added.

### Critical epistemic rules

1. Two offers advertising 250 W and 15 Ah share a **claimed value hub**,
   NOT a verified OEM identity. Similar name hints (Allgobike AM27,
   Orzel C27) are linked only with `SIMILAR_INDEX_MODEL_NAME_LEAD` and
   `NOT_VERIFIED_SAME_PRODUCT`. A number in a URL slug is not a
   manufacturer datasheet.
2. Battery Wh derived from unverified voltage and Ah is a
   `derived_claim` **per offer**, with two `ARITHMETIC_INPUT`
   provenance links. **36 V × 15 Ah = 540 Wh** is arithmetic, not a
   measured pack capacity, independently tested range or proof that
   the input rower even has a 36 V pack.
3. Indexed prices produce `INDEXED_PRICE_CLAIM` only, not verified
   checkout totals. The graph cannot rank a "best buy" with unverified
   prices or unconfirmed exact variants.
4. Real fetched reviews carry source URL, published author/publisher,
   retrieval time, SHA256 and reviewed hardware variant. When the
   reviewed configuration differs from or cannot be matched to the
   retailer offer, observations are **REFERENCE_ONLY_NOT_THIS_OFFER**.
   Matching model-family strings never upgrade them to exact-SKU tests.
5. Open research dimensions are **missing evidence**, not proof the
   product failed a test. The graph does not manufacture answers out
   of planned questions, Qwen output or similar variants.
6. All external source URLs are validated for HTTPS and nonlocal
   hostnames before being rendered as links. Labels are text content,
   not HTML; no code or buyer inputs are injected.

### UI

The network appears above the legacy research path in the existing
English `/cart/status/<job_id>` view. All offer nodes remain
visible; the right-hand neighborhood displays declared specs,
open investigation dimensions, indexed quotes, independent
observations and the decision gate.

- **Input product**: focus the exact submitted URL item.
- **All offers**: reveal shared quoted-value hubs and prices across
  the Shopping index without treating them as facts.
- **Click/Enter on an offer**: read the unverified technical
  comparison, saved price caveat, exact-model leads, actual linked
  source observations and 12 most urgent research questions. A link
  jumps to that offer's full paginated question queue.
- **Click/Enter on a value or research dimension**: list all connected
  offer nodes and its own evidence/provenance restrictions.
- **Zoom/pan**: mouse wheel, +/−/reset buttons, pointer drag. The
  UI preserves selected node, current graph mode and zoom when the
  asynchronous source/LLM status refreshes.
- **Export graph JSON**: raw, auditable, structured projection.

Built without external rendering frameworks or dependencies, consistent
with the existing TraceCart layout.

### Verification on actual saved jobs

Using a separate SQLite backup and Chromium on test port **8798**:

**Allegro e-bike job** `LoHWENthHlgccaUCtbOdQkCO`:
- 13 offers; 12 unverified index price quotes.
- 10 distinct *advertised* attribute values (plus one per-offer
  derived Wh value), 55 offer-to-attribute/derived links.
- 13 × 24 = **312 unresolved high-priority offer/issue edges**.
  The complete prior backlog is still **2964** planned questions,
  not 2964 answered questions.
- **0** independently measured reference results for these exact
  e-bikes, **0** verified exact-SKU answers, **0** checkout prices.

**Lenovo job** `w8MOeW8uE7pCqDYKf48-lXxy`:
- 16 offers; independent Notebookcheck source is still represented by
  **one distinct fetched document** with SHA256 and **two distinct
  measurements** (CPU and WiFi battery).
- Four offer-linked **reference-only** observations across compatible
  model-family indexed titles, **0** measurements verified for exact
  retailer SKU and **0** checkout prices verified.

**Interactive Chromium CDP** on the e-bike saved job:
- Graph appeared with 26 visible SVG nodes in input focus.
- Clicked Allgobike offer #4; detail pane showed its indexed price
  `2599.00 PLN` explicitly as NOT a checkout price, plus title
  parameter claims.
- Clicked the shared 250 W attribute; neighbor pane showed 11
  linked offers, without claiming identical hardware.
- Switched to all-offers mode: 37 visible nodes; zoom control applied
  scale 1.2; focus/zoom persisted after a scheduled refresh; zero
  browser JavaScript exceptions.

### Research work still required

A network of existing claims is valuable for discovering comparisons,
contradictions and priority gaps. **It does not substitute for retrieving
primary manufacturer technical documents, current seller pages or
independent instrumented tests**. The next substantive milestone is a
source-research agent that executes high-impact graph gaps, attaches
actual source receipts and revises each node's provenance, including
contradictory-source and exact-SKU checks. Real verified answers will
then change the graph, rather than merely increasing question counts.
