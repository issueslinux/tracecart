# TraceCart — purchase value, functional alternatives and HTTP 403 evidence

Date: 2026-11-03.

## Product outcome, not a deficit inventory

A research result must answer **which different or similar product offers merit checking and why**.
The buyer did not ask for a lab-audit log, nor specifically for identical SKUs.
Exact seller identity still matters for confirmed checkout prices and claims, but **is not a
prerequisite for suggesting a functional alternative**. Never confuse those two tasks.

The new `purchase_insights.py` computes a deterministic comparison from the
immutable `guided_decision` offer projection. It reuses `similar_tier.read_specs()`
and `evaluate_alternative()`; it never creates new URLs, prices or review sources.

- Classify the whole product before recognizing components: a *laptop with an SSD*
  is still a **laptop**. The old SSD-first classifier misread *16 GB RAM* as
  *16 GB of storage*. The new parser recognizes 1 TB, 512 GB, Core i5/i7
  tiers and displays a difference if a title states it.
- Present up to four **similar-title-spec tier** candidates. For laptops with
  known RAM, storage, and CPU tier, require all three to match; shared Intel
  architecture or screen size alone is not enough.
- Present up to two **partial / specification-tradeoff** candidates separately:
  e.g. 512 GB instead of 1 TB, or unknown precise CPU. These are not
  promoted to equivalent hardware.
- Compare index prices to an index-only median from at least three reasonably
  comparable quotes in the same currency. This is **not** the selected seller's
  price. If input seller HTTP is blocked, do **not** claim any competitor is
  cheaper than that seller, because the input price is unknown.
- Index quotes below 40% of the credible peer median are labeled
  **extremely suspicious**, excluded from the recommendations, and remain
  in the immutable index audit. Never silently rewrite or drop the quote.
- Any "interesting" attributes such as touch display, 120 Hz, IPS or Windows
  Pro must come from actual indexed title words and be explicitly labeled
  unverified title claims.
- `purchase_insights` includes offer IDs and price-node IDs that are already
  present in the evidence graph; clicking a card opens its corresponding node.
  A direct retailer URL is shown **only if one is present** in the indexed record.

## Final verdict and source documents

- Local Qwen is still used for a short JSON **verdict classification**.
  It does not generate SKU matches, factual claims, rankings, prices or
  citations. Those are computed from the saved offer index and source graph.
- `model_verdict.insufficient_verdict` and `generate_final_verdict` both
  attach the same source-based `purchase_insights`; if Qwen times out, the
  comparison is still shown, clearly labeled model-independent.
- The final finding cards prefer documented CPU, RAM, storage, battery,
  display and power. Bare product IDs/SKUs are retained in the full graph
  but do not become meaningless primary findings.
- All source declarations are from their **own documented retailer pages**,
  not automatically transferred to the input seller's actual SKU.
- New results persist comparison data in the existing
  `cart_final_verdict.result_json` without modifying `cart_offer_evidence`
  receipts or the original research report.

## Dell example, with actual saved data

The URL-submitted Media Expert Dell DC15250 i7-1355U/16GB/1TB job has no
verified seller price. Indexed results include:

- Dell 15 DC15250 i7-1355U, 16 GB, 1 TB, declared touch screen:
  **3399.96 PLN in the SEARCH INDEX**; no direct seller URL in the card.
- Dell DC15250 i7-1355U, 16 GB, 1 TB: **3499.99 PLN in the SEARCH INDEX**;
  linked seller page access restricted.
- Other indexed variations with different screens, SSD capacity or CPU.
- **139.95 PLN** index quotes are extreme anomalies compared with laptop
  peers (around 3500 PLN), not promoted as laptop purchase prices.
- Documented specifications from another retailer include CPU, RAM,
  storage, battery, screen. They are not independent lab measurements.

These facts support **possible value candidates**, not "cheaper than
Media Expert" (the selected seller's final price is unknown).

## Media Expert 403 vs cookies

A real, unmodified Chromium navigation to the user's specific Media Expert
product URL returned HTTP 403 and rendered a page headed "Media Expert"
asking the visitor to confirm they are human ("prosimy o potwierdzenie,
że nie jesteś robotem"). **The page had no cookie-consent button**.
Thus the immediate blocker was a bot verification challenge, not a cookie
consent banner. TraceCart must NOT bypass it. It continues the comparison
from other permitted documentary sources and unverified indexed leads.

## Test / operations

- `python3 -m unittest discover -s tests -p 'test_*.py' -q`
- `node --test tests/*.cjs`
- Check the sample completed Dell job in Chromium: comparison cards,
  suspicious low quote flag, sourced CPU and memory findings, all graph
  nodes and absence of false confirmed price/checkout.
- If reprojecting an existing completed job, change ONLY the stored
  assessment JSON, preserving `origin` and Qwen's original
  classification, plus the original full source audit and all receipts.
- No paid source discovery/search is enabled by these changes.
