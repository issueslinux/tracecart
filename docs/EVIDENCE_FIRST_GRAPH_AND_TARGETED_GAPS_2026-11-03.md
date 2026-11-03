# Evidence-first central graph; remove 24 repetitive questions — 2026-11-03

## Problem and measured cause

In the actual RYOBI job `zDIj50-SoxhL_r63lh6CJqS9`, source research
**has finished**: 18/18 source checks, and all model tasks are terminal.
The old GUI nevertheless displayed repetitive `Does the OEM publish an
exact-model specification for...` questions, giving the false impression
that the research had stopped mid-run.

The persisted research report was **not empty**. The old implementation
had a hard `slice(0,13)` visibility cap for source-related graph nodes,
a generic, unfiltered 24-dimension question catalogue in the offer detail
drawer, and a broken projection: `offer_knowledge_graph.py` had already
implemented seller-page declarations but `guided_decision.py` failed to
pass `selected_source_intake` and `selected_item`. Thus SKU, EAN,
seller price, shipping and delivery records were saved but invisible
in the central network.

## Behavior and changes

**A. Real seller data finally reaches the graph.**

`guided_decision.build_decision_projection()` now passes
`selected_item` and `selected_source_intake` for both READY and
in-progress records. `offer_knowledge_graph` can render claims as
distinct seller-page declaration nodes, each linked to the original
fetched page URL and actual SHA-256 receipt.

For RYOBI RPI18-0, this yields seven *seller-page declarations*:
manufacturer/brand, SKU, EAN, advertised price, stock status,
conditional shipping cost and a delivery window. A published price of
249.99 PLN, InStock and 0 PLN to Poland are **retailer page claims**,
not certified checkout totals or guarantees about availability.

**B. Concrete source values and document provenance.**

The generic extractor accepts up to 24 source fields, rather than
dropping the later values after 12. The graph retains up to 28
reference rows per offer. Source declaration nodes now carry the
original field name, value, provenance and SHA. The source facets
(e.g. `Identity`, `Electrical`, `Equipment`, `Weight`,
`Noise`, `Vibration`) make
`offer → evidence facet → source value → downloaded document`
explicit. Every provenance relationship remains in the JSON; the
visible SVG favors the facet route over drawing redundant direct
offer-to-every-field links.

The actual original RYOBI manufacturer HTML exposes at least **15
usable structured source fields** after generic extraction: SKU
`RPI18-0`, MPN `5133006315`, EAN `4892210230478`,
declared 18 V, weight, included accessories/charger, noise,
and vibration. Some other shopping-index pages mention other
performance values; **they do not become evidence of the exact
submitted variant** without a separate model/variant match.

**C. Relevant remaining evidence gaps, not hundreds of prompts.**

`evidence_gap_summary.py` reads the actual retrieved source fields,
which product was selected and whether it has any independently tested
exact-SKU results. If model, power, kit contents, etc. are documented,
their repetitive generic questions **do not appear** in the graph
detail drawer. A missing independent test remains OPEN: published
specifications never become benchmark proof.

For the RYOBI input, four current relevant gaps are displayed:
independent performance/accuracy test; warranty/returns; spare parts
and authorized repair; verified total checkout price.

The legacy 12-probes-per-dimension question catalogue remains
accessible in historical paginated research/audit APIs, with its
original status **PLANNED_NOT_INVESTIGATED**. It is neither an active
queue nor shown as 24 unanswered facts in the offer detail panel.

**D. Central SVG is richer but still readable.**

The old 13-observation rendering cap was eliminated. The default
Input focus now shows up to 32 fetched fact/statement nodes,
seller-page claims, facet groups, sources, real unresolved gaps and
selected related offers. All source links and all original graph
nodes still exist in the downloaded JSON.

The graph lays out the actual evidence in four columns, increasing
height to use more of the center pane: offers → documented categories
→ specific values → original pages and verification gaps. Redundant
direct lines are not rendered, but their provenance is kept in the
graph. The header explicitly displays the number of *visible nodes*
against the full graph node count. `All` switches to the overview;
`Input` restores the initial product; selecting an alternative
updates its relevant question list in the right sidebar.

The details drawer shows the original attribute name and value,
source link/hash and source interpretation. It no longer says
`no numeric configuration could be extracted from title` when there
are fetched source-page facts.

**E. Honest research lifecycle.**

After the final SSE `settled` event, the status remains
`Completed · 18/18 checked · no active tasks` instead of reverting
to `Ready`. The question rail shows the selected offer's
`UNRESOLVED` verification gaps and already documented facts, not
hundreds of rotating generic prompts that imply active work.
No artificial progress animation or stealth source request is used
after all real tasks finish.

## Verification

Tested against the user's saved 18-offer RYOBI job via a **separate
SQLite backup and preview server**. The original report remains
unchanged; historical job receipts are projected read-only.

After projection:
- 18 saved offers; 7 seller-page declaration nodes.
- 15+ actual extracted technical fields associated with source receipts,
  depending on individual source offers; multiple documents may differ.
- 10+ evidence facets and four *specific* remaining verification
  questions for the input model.
- **0** exact-SKU independently tested answers or verified checkout
  totals—this release does not manufacture either.

Chromium graphical verification on the preview page confirmed that
the default Input-focus SVG renders the seller facts, downloaded
source values, evidence facets, document links and four short
evidence-gap nodes, without any JavaScript exception. Visual links
are now grouped by documented source families.

The full automated suite passed: Python 439 tests, Node 22 tests.
No new paid SerpApi/Brave queries, no GitHub Actions, and no automatic
purchase/payment.

## Remaining work

Broad independent laboratory research needs legitimately configured
search access or another authorized index. The graph deliberately
displays `COMPLETE` when all accessible checks have terminated,
rather than pretending to work indefinitely. A future rescan should
be explicitly rate/budget bounded and yield new source receipts;
re-generating generic questions is not useful research.
