# Progressive input-first source graph and single-batch Qwen — 2026-11-03

## Problem verified on live RYOBI job
`zDIj50-SoxhL_r63lh6CJqS9` was recorded as READY. SQLite already
contained 18/18 completed source checks and 18/18 model-question rows
with status OK, including #9. The browser's old `#9 · MODEL WRITING`
indicator was not an actual ongoing inference.

Previously, the initial research path ran one synchronous local AI call,
then a second post-Shopping AI call, and only *after READY* started up to
18 **sequential** per-offer Qwen prompts (each with its own timeout and
possible retry). The local llama-server was observed running with only
`-np 1` inference slot; 18 concurrent GPU HTTP requests would just
queue behind one another. There was also no event-resync endpoint in
case the browser lost an SSE event.

## Implementation

1. **First offer drawn immediately.** A new URL starts as the input node.
   After `extract_product_page` returns the real seller-asserted title,
   one selected-product **source read** starts immediately on the
   independent evidence pool, in parallel with the base catalog/Shopping
   pipeline. This reads the real manufacturer/merchant page through the
   same robots, pinned public HTTPS and identity rules.
2. **Product identity corrected.** The Ryobi manufacturer Product JSON-LD
   has the exact marketing name from the user URL and an explicit
   `model: RPI18-0`, but the marketing name alone lacks the string RPI18.
   The generic parser now accepts an *exact normalized Product schema
   name* as source-page identity without claiming an exact seller SKU at
   checkout. `-` placeholders are rejected; SKU, MPN, EAN, voltage,
   weight and supplied accessories outrank noise uncertainty fields.
   This is a **generic schema-identity rule**, not a hard-coded Ryobi
   parser.
3. **No duplicate source read.** The full evidence coordinator reuses
   the persisted first offer result instead of resetting it to QUEUED.
   Other offer pages are checked by up to **16 parallel I/O workers**,
   with one SQLite coordinator and existing shared-URL dedup.
4. **Visible graph grows only from real work.** The live projection
   displays input `offer-0` first, then progressively adds additional
   offers as their actual source tasks finish. Pending tasks remain
   visible by name/state in the left sidebar through a compact
   `offer_queue`, even before those nodes enter the graph. On
   completion, the full graph is visible. The original report and
   source provenance remain unchanged.
5. **Qwen no longer blocks source reads or the first graph.**
   Per-request base and post-index sequential local inference are
   deferred to the background worker; the worker makes **one** bounded
   Qwen batch request for up to four distinct brand/model identities,
   including the selected product. Other indexed variants receive
   `SKIPPED_DUPLICATE_MODEL` or `SKIPPED_MODEL_BUDGET`.
   Only one `QWEN · BATCH · INFERENCE` card is shown, never 18
   fabricated simultaneous writing tasks. No extra model retries.
   The saved original report is not rewritten to include generated
   suggestions; these remain separate SQLite rows.
6. **No stale WRITING indicator.** Startup turns orphaned `RUNNING`,
   `BATCH_RUNNING` and `QUEUED` model jobs into
   `INTERRUPTED_RESTART`. A same-origin, no-store
   `/cart/status/<job_id>/live.json` snapshot endpoint supports the
   EventSource stream; the browser automatically resynchronizes if
   SSE updates stop for >6.5s or a server restarts. Event IDs alone
   no longer suppress changed snapshots after reconnect.

## Real RYOBI page verification

URL: `https://pl.ryobitools.eu/elektronarzedzia/kompresory-i-pompy/rpi18/rpi18-0/`

The live site returned one Product JSON-LD with the marketing name
`Kompresor wysokociśnieniowy 18V ONE+`, model `RPI18-0`,
EAN `4892210230478`, voltage `18V`, manufacturer product attributes
and documented accessory claims.

A new job replay in an **isolated SQLite backup**, with
`SERPAPI_API_KEY` and `BRAVE_API_KEY` removed to avoid paid calls,
reported:

- t=0.05s — one input offer, source fetch in progress
- t=1.41s — source pipeline executing independently, one input offer
- **t=1.87s — 12 real source document declarations in the input graph**
  while the single Qwen inference batch was still running
- t=5.02s — one-offer research READY, source and Qwen work complete
- no paid search, no guessed checkout price, no independent benchmark
  or confirmed variant at payment.

These are measurements for **one input product without Shopping
discovery**. End-to-end time for 18 indexed offers depends on paid
search and third-party network delays, and is not claimed to be 5s.

## Verification

Includes existing full test suite plus focused tests for first-source
priority under a deliberately blocked catalog worker; one Qwen call
instead of 16; persistence and duplicate-suppression; source-graph
progression from 1 of 16 offers to 16 of 16 while checks overlap;
matching the exact Product schema name without false lab/SKU claims;
batch status semantics and browser SSE fallback JSON endpoint.

The original job `zDIj50-SoxhL_r63lh6CJqS9` can be enriched with the
new first-product source receipt without new Shopping queries and
without touching its immutable original report. Graph references and
real returned price remain merchant *declarations* until validated
against current checkout and variant.
