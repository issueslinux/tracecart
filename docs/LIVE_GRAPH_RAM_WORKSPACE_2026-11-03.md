# TraceCart live graph workspace — RAM, SSE and bounded parallel source checks
**Implementation: 2026-11-03**

## Interface

`/cart` and `/cart/status/<job_id>` share ONE minimal workspace.
Only a product URL field and submit control are above the research area.
The centre shows the evidence graph immediately: one input node is
drawn before source discovery; as saved progress changes, the same
graph is rebuilt from the actual discovered offers and evidence.

The side rails show a bounded, rotating set of tasks:
- **Sources**: up to 20 actual persisted offer-level source checks.
  `RUNNING` means a worker is actively checking; `QUEUED` means
  scheduled; `NO MATCHED SOURCE` means no independent source was
  verified and no answer was fabricated.
- **Questions**: up to 18 high-priority OPEN source questions,
  locally generated model questions, and clearly marked reference-only
  findings. A Qwen `RUNNING` row is marked as *question formulation*,
  not independent research or evidence.

When the stored worker states change, the visible queue may replace
old questions, and the graph acquires actual nodes and links. No
background animation asserts that source research completed.

All old APIs, full audit, immutable reports, original source hashes,
question pagination and payment safeguards remain accessible. The
old decorative entry template is no longer used by `/cart`.

## State architecture: RAM vs GPU vs browser

- **Durable SQLite** remains the authoritative location for original
  reports, real source receipts, question/model states and purchase
  safeguards. A restart does not delete the research.
- **Server RAM**: `MemoryLiveGraphCache` is an `OrderedDict` with up
  to **24 active graph snapshots**. Per-job revision signals invalidate
  the changed entry and wake subscribers. Snapshots are reconstructed
  deterministically from SQLite on a cold start and after restart.
  The revision table is also bounded.
- **Browser RAM**: current graph structure and visible node selection,
  pan and zoom live in browser memory. Each `EventSource` update
  supplies a new read-only graph snapshot, never a raw server address
  or a pointer to shared process memory. Existing selection/zoom
  persists between snapshots. Recently added nodes animate in.
- **Streaming**: `GET /cart/status/<job_id>/live` uses same-origin
  Server-Sent Events (SSE), with real `graph` events, heartbeats and
  a terminal `settled` event when both actual workers finish. Browser
  auto-reconnects. The endpoint is loopback-only and all routes still
  pass the HTTP Host check.
- **Thread safety**: `StreamingHTTPServer` dispatches **only SSE**
  connections to daemon threads, while all legacy payment/quote and
  general HTTP routes stay in the server's original serialized thread,
  preserving `CheckoutStore` SQLite connection affinity. Long-lived
  SSE does not block ordinary GET/POST responses.
- **Parallel source I/O**: each source-research job runs up to
  **16 active per-offer checks** with a bounded
  `ThreadPoolExecutor`; only the coordinating thread persists SQLite
  changes. Per-URL `Future` cache deduplicates robots.txt and review
  downloads for shared model families. These are actual source checks;
  where no authorized matching source exists, the honest result is
  `NO_MATCHED_INDEPENDENT_SOURCE`.
- **GPU / VRAM**: GPU memory is appropriate for local Qwen inference
  (depending on actual model-server configuration) and potentially
  browser-side WebGPU rendering at *much larger* graph sizes. It is
  not a safe or practical persistent graph database or a directly
  addressable browser storage area. TraceCart keeps the single
  GPU-heavy question-generation lane separately rate-limited.
  The existing small graph uses responsive SVG and browser RAM;
  no unsupported claim of GPU computation/VRAM persistence is made.

## Verification

Executed against saved e-bike
`LoHWENthHlgccaUCtbOdQkCO` and laptop
`w8MOeW8uE7pCqDYKf48-lXxy`, without new paid search calls.
The new `/cart` shows a graph node immediately, no marketing
hero. The live job shows all saved offers and prior independent
reference observations, with exact-SKU verification still **0**
for these datasets.

- SSE first event delivered read-only structured graph from RAM,
  without changing original report.
- An ordinary HTTP `/cart` GET completed while SSE connection was
  already open, proving no blocking of the server request loop.
- Source worker parallel test starts >=8 real source checks
  simultaneously and persists all 16 statuses after completion.
- RAM cache bounded-size eviction, cold historical replay,
  change notifications and no fabricated answers tested.
- Front-end semantic unit tests ensure rails display
  `RUNNING`, `QUEUED`, `NO MATCHED SOURCE` or OPEN honestly.

## Not implemented / next meaningful work

This milestone optimizes visibility, local state and scheduling.
It **does not** invent manufacturer records or independently test an
electric bicycle. Future workers must discover permitted manufacturer
documents, read independent reviews, match exact hardware revisions,
resolve conflicting evidence and verify current merchant prices.
As those workers begin to produce real observations, existing SSE
signals make the graph evolve without redesigning the interface.

PayPal order authorization remains explicitly disallowed by the
research graph and cannot be bypassed through SSE.


### Final automated checks

**408 Python tests + 17 Node tests passed**, including: SSE framing and a
simultaneous normal HTTP request, 16-worker true I/O concurrency,
24-slot cache eviction and wake-ups, historical read-only report
reconstruction, client source-question rail semantics, and the old
checkout/payment safety tests. Native Chromium screenshots confirmed
the clean entry surface and the saved rower graph with offer and
source-question panels; no newly verified product facts are claimed.
