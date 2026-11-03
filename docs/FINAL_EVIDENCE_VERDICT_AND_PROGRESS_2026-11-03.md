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
- Input: compact model view of **all identified offers and indexed prices**
  and the available published source declarations, within a bounded context.
  The original source evidence (including exact URLs, hashes and full labels)
  remains available in the audit; omitted observations are counted.
- Untrusted page text is data, never model instructions. CPU-bound Qwen
  returns **only the conditional verdict classification**. The explanation,
  next step, fact cards and citations are composed from persisted evidence,
  not generated text. It cannot invent source citations or verified prices.
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

## Latency and source status correction (2026-11-03)

- The latest Dell job `2NpxOO3WuElr61xUIev66G2F` completed 16/16
  source checks, collected 15 vendor declarations from one document,
  then timed out in the final model call. Its preliminary per-offer
  question batch had already made four model attempts and all timed out.
- New jobs **skip** that redundant question-generation model batch,
  retaining deterministic evidence gaps. The single local Qwen worker
  is reserved for synthesis after source checks.
- The final Qwen request is constrained to a single JSON verdict,
  at most 42 output tokens and a 24-second bounded HTTP timeout
  (the previous verbose summary used up to 360 tokens/85 seconds).
  In a measured replay of the 16-offer Dell job Qwen completed in
  18.08 seconds; this is still CPU-bound, not an instantaneous response.
  On timeout the fallback includes 15 real source declarations and their
  saved evidence links rather than an empty generic summary.
- Repeated manufacturer home-page probes for search-index-only cards
  are de-duplicated per model family; direct seller URLs still get real
  permitted source checks.
- Source rail groups incomplete index cards without eligible direct
  URLs into one explicit `INDEX LEADS` summary and groups duplicated
  blocked seller URLs. It distinguishes `ACCESS RESTRICTED`,
  `WRONG MODEL`, `NO STRUCTURED DATA`, `NO FETCH RECEIPT`, and
  available source `SPECIFICATIONS`. The full graph/audit still
  retains every offer, price observation and every source receipt.
- This **does not** cause blocked seller pages to be fetched; HTTP 403
  and robots restrictions remain enforced. No additional paid source
  search service is enabled.
