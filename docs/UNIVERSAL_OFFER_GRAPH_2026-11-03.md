# Universal offer graph and evidence-limited value comparison

**TraceCart / PayPal AI competition · 2026-11-03**

## Design constraint

TraceCart must work for arbitrary product categories, not just laptops.
The submitted product is the price/value baseline when a source-observed
price is available. Alternative models and brands may be relevant if
functionally comparable; identical SKU is not required to find
candidates, but *is* required to substantiate exact same-item savings.

The UI and model-facing copy must be in **English**. Source product titles
and original source properties remain verbatim as evidence.

## Diagnosis from saved detergent job

Job `GGgjk0v5CCPunQxh7Umtx8Bm` is Bryza Color 4-in-1 powder, NOT a
laptop. The previous graph held 136 nodes and 583 edges, including 80
empty per-offer checks, 24 generic research dimensions, 16 offers and 15
indexed quote nodes, but zero extracted title specifications. That
created a grid of mostly empty checks instead of comparisons.

## Implemented generic pipeline

1. `title_facts.py` extracts **explicitly advertised** mass, volume,
   bundle count, wash/usage count, piece count, important product variant,
   and conservative generic electrical/physical properties. No SKU,
   checkout price or measured performance is inferred. Ambiguous URL
   slug `8 45 kg` is NOT assumed to mean 8.45 or 45 kilograms.
2. `generic_value.py` groups only listings with informative shared
   family tokens and matching declared variants, using the same currency
   and same measurable unit. Unknown variant gets a caution group;
   opposite WHITE/COLOR variants are **not** treated as equivalent.
   Sorting uses *price per explicit indexed quantity*, not package total.
   These results remain unverified leads, not merchant price guarantees.
3. `purchase_insights.py` keeps the already existing technical-tier
   comparator for laptop/bike/tool categories and invokes the generic
   measured-goods comparator for previously unknown/accessory categories.
   Where an observed selected price exists, a more expensive comparable
   offer is not promoted as "better value" without verified advantages.
4. `offer_knowledge_graph.py` preserves complete provenance,
   verification gaps and price nodes in JSON but connects alternate
   search results to the input as **unverified leads**. Extracted title
   attributes and price/unit facts attach to each offer without
   creating fictitious technical specifications.
5. `assets/offer-graph.js` renders an **offer/value landscape** with
   cards containing the actual indexed quote, explicit quantity/variant,
   and an optional unit quote. Standalone source facts and documents
   remain visible below. Price nodes are represented in the parent offer
   card, not duplicated as disconnected bubbles; generic unanswered
   research tasks stay in the audit/right research panel. There are
   clickable source receipts, offer details, keyboard navigation,
   optional zoom, and vertical graph scrolling.
6. `assets/live-workspace.css` reserves enough height for the graph,
   prevents the earlier CSS flex shrink that crushed a 1407-pixel graph
   into 482 pixels, and switches to a single-column network when the
   graph pane is narrow.

## Actual Bryza index illustration (saved result)

- 8.45 kg COLOR powder: **59.99 PLN** indexed (7.10 PLN/kg).
- 2 × 8.45 kg COLOR bundle: **109.99 PLN** indexed (6.51 PLN/kg).
- 8.45 kg COLOR powder: **89.99 PLN** indexed (10.65 PLN/kg).
- WHITE variants are not equivalent to COLOR.
- A 2-pack can be cheaper per kg while costing **more in total**.
- These prices are indexed, not verified at the actual shop; availability,
  coupon eligibility, seller legitimacy and checkout totals remain open.
- Input slug `8 45 kg` is too ambiguous to normalize its price/unit
  without additional source confirmation.

## Input price and retailer security (parallel work in same release)

The `cart_input_price_observation` table allows a user to record a
price visible in their browser if the retailer blocks automated access.
It is marked `USER_OBSERVED_NOT_VERIFIED`; the original seller report,
Qwen classification, model receipts and source evidence are preserved.
Promotion codes can be recorded, but final checkout eligibility is not
inferred. The updated Dell example with 2799.00 PLN input shows that
3399.96 PLN index quotes are **more expensive**, not recommended as
a lower-priced alternative.

The independent `cart_link_safety` pipeline performs bounded public-DNS,
TLS/certificate and official domain RDAP checks asynchronously, without
delaying the final verdict or bypassing HTTP 403/CAPTCHA. TLS and an older
domain **do not prove a legitimate shop**. No fraud/chargeback complaint
database or external Safe Browsing API has been checked; a confirmed
`SAFE_SHOP` label must not be emitted.

## Verification and deployment

- Complete Python/Node unit and UI suites.
- Chromium at 1680×950: 16 offer cards, 25 diagram nodes (detergent),
  unit prices displayed, no overlapping offer cards; 55 meaningful nodes
  (Dell), 2799 PLN selected-price baseline, no overlapping offer cards.
- Responsive Chromium checks: widths 390, 768 and 1024.
- Tests use a **copied** SQLite database, never overwrite source records.
- Live service binds 127.0.0.1:8781; no GitHub Actions, paid provider
  search, automatic purchases or verification bypass.
