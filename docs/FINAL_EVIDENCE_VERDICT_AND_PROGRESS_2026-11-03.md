# TraceCart — final evidence verdict and live progress (2026-11-03)

## Contract

- `Analyze` has an actual busy indicator and remains busy while source checks,
  representative question generation and the final local model verdict run.
  A browser animation never decides job completion.
- `cart_final_verdict` is separate from the immutable source audit. Values:
  `QUEUED`, `RUNNING`, `COMPLETE`, `UNAVAILABLE`, `INTERRUPTED`.
  The worker runs only after source fetching completes. It is queued behind
  existing model-question generation on the **single** model worker.
- `FINAL_VERDICT_QUEUED` → `FINAL_VERDICT_RUNNING` →
  `FINAL_VERDICT_COMPLETE` or `FINAL_VERDICT_UNAVAILABLE`.
  SSE must not emit `settled` while a verdict receipt is pending.
- After process restart, pending records become `INTERRUPTED`; the system
  does not make an unlogged second attempt or pretend a model completed.
- `final_verdict` is returned by `CartResearchJobs.read()`, the live
  `/cart/status/<id>/live.json` snapshot and the decision projection.

## Local LLM

- Uses the existing localhost Ollama Qwen `qwen2.5:1.5b-instruct` and a
  JSON-schema-constrained single inference call.
- Input: **all indexed offer identities and source-check statuses** plus
  attributed real source observations and primary title facts, respecting a
  10,000-character budget for the loaded 4096-token context. Full source audit
  and source IDs remain available separately; omitted observations are counted.
- Untrusted page text is data, never model instructions. The Qwen result only
  determines the **conditional assessment, summary and next research step**.
  It **cannot invent evidence nodes, citations or verified prices**.
- Any fact cards and clickable evidence links are constructed directly from
  document-backed graph nodes. During tests the smaller Qwen erroneously cited
  indexed **price** nodes as proof of laptop RAM; this was rejected by design.
- A missing/unavailable/invalid model response receives a clearly identified
  `DETERMINISTIC_FALLBACK_NOT_LLM` summary, not a fake Qwen verdict.
- Neither a model classification nor a search-index quote proves a purchase
  winner, checkout total, exact SKU, instrumented test or warranty condition.
  No payments or checkout actions are authorized.

## UI

- On job submission: button shows a spinner and `Analyzing…`.
- When the job URL is opened while running, the spinner is restored from the
  authoritative snapshot; the user can monitor source and Qwen stages.
- On true terminal state: spinner stops; `Final evidence assessment`
  appears above the evidence graph. Where a documentary finding is displayed,
  its evidence button opens the exact matching graph source node.
- Historical jobs without a stored final verdict are explicitly labeled as
  earlier saved jobs, **not retroactively called a Qwen synthesis**.
- The evidence graph keeps empty verification questions out of the layout.

## Regression and operations

- Tests: `python3 -m unittest discover -s tests -p 'test_*.py' -q`
  and `node --test tests/*.cjs`.
- Verify a job through its `/live.json` response (look for
  `final_verdict.status`) and through the browser. `/decision.json` contains
  the same persisted result without changing old source receipts.
- The model uses loopback only; no extra paid search or external API is
  required by the final verdict worker. Production process restarts must
  preserve the original DB and explicitly disabled optional paid searches.
