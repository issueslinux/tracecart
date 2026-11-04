# TraceCart — local LLM connected to a changing source graph

## Architecture

A model does not import a mutable knowledge graph into its weights.
TraceCart instead sends the local Qwen model a **bounded read-only projection**
of the latest graph, then evaluates proposed questions against graph IDs.

Flow: persisted source evidence -> current decision projection -> offer graph
-> bounded sourced-fact projection + revision SHA-256 -> existing serial
model queue -> local Qwen -> validated, source-anchored research question ->
saved SQLite receipt -> live SVG graph and right Questions rail.

The model cannot read databases, browse stores, run checkouts, authorize
payments or write source graph evidence. A suggested question is never a
sourced answer, verified product claim, seller offer or checkout receipt.

## Triggers and budgets

- Refresh after meaningful source checks, authorized browser receipts,
  price observations and completed shopping refreshes.
- Ignore SVG viewport position and layout changes.
- Stable SHA-256 fingerprints material source nodes and verification gaps.
  In-flight questions are dropped if the graph changed before they arrived.
- Maximum **two local Qwen calls per cart**, counting failures and updates.
  At most four cart jobs can wait in the existing serialized model queue.
- One compact question per request, with an **18-second timeout**. The
  immediate source assessment never waits on this request.
- Pending model tasks are marked interrupted after a server restart. They
  are not automatically retried merely because the process was restarted.
- A question is attached only if both its target offer ID and source/gap
  anchor ID exist in the current graph. It is labeled UNVERIFIED.
- No additional SerpAPI, merchant HTTP or browser requests.

## Context minimization

At most four offer names, seven sourced claims, five open gaps and two
short peer comparisons are sent to local Ollama. No raw HTML, full seller
page, authentication values, cookies or merchant URLs are transmitted.
The revision digest tracks up to 256 material graph entries, so even
evidence omitted from the compact prompt invalidates a stale question.

The source evidence, prior Qwen classifications and source audit stay
unchanged. Proposed questions are additional graph nodes and do not become
fact nodes. They are saved with status and a graph evidence fingerprint.

## Fast independent checks

The deterministic, no-LLM purchase assessment now prioritizes open
questions about documentary conflicts, suspicious search-index prices,
conditional coupon eligibility, technical feature differences, and the
unverified delivered total. Such tasks are shown before the generic research
backlog and are automatically recalculated on source changes.

On the saved Dell DC15250 example, TraceCart separately displays the
suspicious 139.95 PLN index quote, the seller-visible conditional
2799.00 PLN code BW1610-0112, and missing checkout confirmation.
The model can add a further source-anchored *question*; it cannot silently
promote any quote or code to a confirmed purchase total.


## Measured verification

The real local Qwen 2.5 1.5B (via Ollama 0.40.13) generated a new
source-anchored question from the saved Dell graph in approximately 6 seconds
in a preliminary probe. A subsequent isolated end-to-end invocation saved
the question to SQLite and displayed it as an unverified verification-gap
node connected to the original browser declaration in the live graph.
Both live.json and the standalone knowledge-graph.json expose the node
on the isolated staging copy (port 8812). Real headless Chromium showed the
generated question, with the conditional Dell code and suspicious index quote
still displayed separately. No checkout was marked verified.

Tests also cover a false source anchor, a stale graph digest, a durable
two-call quota, no-LLM deterministic prioritization, and source verification
boundaries. Model outcomes are suggestions requiring further sources;
no independent study of question quality has been completed.
