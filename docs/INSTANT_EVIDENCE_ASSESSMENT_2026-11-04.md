# Instant, source-based purchase assessment — 2026-11-04

## Changes

The current purchase assessment is available without waiting for Qwen.
An additional instant_assessment field is rebuilt from the same persisted
research evidence and graph projection as the live SVG. It is separate from
the original persisted final_verdict and source audit.

- At the first nonempty base report or preview, even during RUNNING, the
  screen displays a PRELIMINARY assessment. New research can be submitted
  without waiting for the optional model call. Source workers and live
  progress continue independently.
- When source workers finish, it becomes CURRENT. Every actual persisted
  evidence update that signals the in-memory live bus triggers recomputation.
  This includes Browser Companion seller receipts, new search-index offers,
  and user-reported input price corrections.
- Previously generated Qwen classifications are shown only as historical,
  optionally useful information; they cannot overwrite current price,
  promotion or product-evidence evaluations. Browser price with a coupon
  remains conditional and not checkout-verified.
- Qwen is skipped with an explicit SKIPPED_NOT_NEEDED terminal status if
  there is no *documented semantic conflict* or ambiguity involving
  functional alternatives and sourced specifications. Missing checkout
  receipts and suspicious index quotes are rule/evidence-gathering problems,
  not an LLM inference task.
- Genuine documentary conflicts and functional variants with sourced
  specifications can still trigger the existing asynchronous Qwen worker.
  A timeout or missing model does not remove the initial assessment.

The in-memory view has origin
DETERMINISTIC_CURRENT_EVIDENCE_NOT_LLM, an evidence-driven summary,
observations, purchase_insights and next_step. Payment remains unauthorized;
no code pretends to have applied the coupon or verified the exact SKU.

## Trust boundaries and caveats

An HTTP 403 from the seller server does not prove the product is unavailable.
The saved Dell index quote of 139.95 PLN is not a verified purchase price;
the 2799.00 PLN coupon is not checkout-verified either. Published specs are
not independent lab tests. The semantic-skip gate is an explicit heuristic,
not a trained or calibrated decision system; additional seller/variant
verification may still be necessary. A model probability never promotes a
claim to a verified source.

Live projection recomputation causes no additional SerpAPI requests, no
merchant visits and no Ollama inference. The source and model audits remain
immutable; this is a derived presentation layer.

## Tested

Python unit tests cover the source assessment before model completion,
preview during source RUNNING, live invalidation after new price evidence,
a no-LLM path, and semantic-conflict routing. Node tests cover display
precedence over complete, unavailable, stale and pending model statuses.

Real Chromium UI on a copied staging database on port 8811 displayed the
source-based assessment and 2799.00 PLN conditional Dell coupon with the
prior Qwen classification correctly marked historical. A CSRF-protected
manual price change in that isolated database updated Ryobi's comparison
from 239.99 PLN to 222.22 PLN immediately in live.json, without modifying
the saved model verdict or authorizing payment. This was a controlled
update test, NOT a newly fetched Ryobi merchant offer.

Production port 8781 remained unchanged during development.
