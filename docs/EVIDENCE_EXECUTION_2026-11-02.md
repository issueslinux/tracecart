# Evidence execution: independently fetched results — 2026-11-02

## Problem and truthful milestone

TraceCart previously expanded **288 planned questions per offer**, but did
not execute independent test-source investigations. This milestone implements
the first **actual robots-aware source retrieval and provenance checked
question resolution**, without relabeling deterministic plans as answers.

The initial source registry is deliberately narrow. It supports the Lenovo
IdeaPad Slim 3 **15Q8X10** family when a real listing contains that exact
family identifier. Other laptops and all products without a supported
independently tested family remain **unanswered**. Generic "Lenovo Slim 3",
the Intel **16IPH11** and older **15IRH10R** are not silently treated as the
same tested product.

## Real source and method

Bounded, optional source: Notebookcheck independent review of the Lenovo
IdeaPad Slim 3 15Q8X10:
https://www.notebookcheck.net/This-affordable-ARM-laptop-must-worry-AMD-and-Intel-Lenovo-IdeaPad-Slim-3-15Q8X10-review.1093361.0.html

Actual host test **2026-11-02**, using an HTTPS request pinned to a DNS
validated **public IP** and checked against Notebookcheck's robots.txt:

- Direct HTML retrieval succeeded; response size was around **1.59 MB**,
  previously excluded by the 1.2 MB product-page cap. A separate independent
  reference cap of 2.5 MB is now applied; the seller-page cap is unchanged.
- The *retrieved source itself* contained the reviewed 15Q8X10 model in
  article header, "IPS display" in text, a Cinebench 2024 CPU Multi Core
  value of **708 points**, and the **WiFi Websurfing (Edge 138)**
  table value of **19h 01min**.
- The executor explicitly ties these observations to the **reviewed IPS
  reference configuration**, not to an unconfirmed OLED seller SKU.
  A seller title naming OLED produces the machine-readable contradiction
  `MISMATCH_LISTED_OLED_REVIEWED_IPS`.
- Each observation stores an **actual fetched page SHA-256**, retrieval time,
  HTTPS URL, independent publisher, methodology and reviewed-variant scope.
  This is an **ANSWERED_REFERENCE_ONLY_NOT_EXACT_SKU** observation,
  **never** a verified answer about the exact listed device.
- Relevant planned questions now receive these actual findings on demand
  (`offer-{i}-28` Cinebench, `offer-{i}-124` WiFi); `verified_answers=0`
  remains true until exact MTM/panel/battery equivalence can be established.
- Source failure/robots disallow/oversized document/missing markers leads to
  explicit `SOURCE_NOT_VERIFIED_*` or no-match status. No article value is
  read from remembered benchmark numbers or search snippets.

Lenovo PSREF's `robots.txt` returned **HTTP 404** during the host check.
The evidence executor therefore does **not** scrape PSREF or substitute its
previously curated family-level citations for successfully retrieved pages.
The earlier family references remain visible in the original audit and stay
distinguished from independently fetched evidence.

## Runtime

On NEW URL-based research jobs, after the original report reaches READY,
TraceCart starts a **separate single-worker independent-evidence executor**.
It is unrelated to the local Qwen question worker and cannot delay the
initial graph, model generation, original report, or price-safety boundary.

- Independent source check targets the **prioritized high-impact subset**:
  exact variant, measured battery life, CPU sustained performance, actual
  seller price, display variant. An unsupported or unverified question
  remains OPEN, rather than invented as verified.
- All 16 indexed Lenovo leads are classified individually.
- The same article/robots response is cached inside each job; multiple
  indexed references to 15Q8X10 cause **only one remote article fetch**.
  Cached failed fetches are not spam-retried.
- SQLite `cart_offer_evidence` holds per-offer reference receipts;
  `cart_evidence_runs` tracks execution progress and marks abandoned
  RUNNING records INTERRUPTED at server startup.
- Old immutable `cart_research_jobs.result` and its research SHA remain
  untouched. Historical jobs need an explicit replay to add new evidence;
  opening the page never causes a network request.
- The decision projection includes `evidence_offers` and
  `evidence_progress`. The browser displays source URL, SHA, retrieval
  timestamp, test method, model/variant relationship and actual measured
  values as background updates. It does not infer a cheapest product or
  authorize payment.
- Paginated questions from
  `/cart/status/{job}/questions.json?offer=N&offset=24&limit=24`
  show reference-only answers for the matching question IDs, while all
  other questions remain `PLANNED_NOT_INVESTIGATED`.

## Saved Lenovo replay (real, independently fetched HTML)

An isolated SQLite backup of the historical Lenovo job was executed through
the exact production adapter on **2026-11-02**. It processed all 16 offer
entries in **0.57 s**, fetched the Notebookcheck page once, and created **4
offer-linked reference observations** across **2 separately indexed leads**
which explicitly contained the family code 15Q8X10. Those four links refer
to only **2 distinct measurements** from **1 independent source**, not four
independent tests. The selected original x-kom URL did not expose a
reliable exact family/MTM; it was not automatically assigned either result.
No indexed 16IPH11/Core Ultra 5 322 offer inherited a result from a
different Intel review.

The historical `cart_research_jobs.result` was compared byte-for-byte and
remained **unchanged**. No SerpApi/paid search invocation was made in replay.
Headless Chromium on port 8796 showed 16 offer cards, the documented 708
Cinebench points and 19h01 WiFi measurement, review URLs, non-exact-SKU
qualification, and conditional ABSTAIN. No buyer question buttons or
JavaScript runtime exceptions.

## Validation

- **388 Python unittests and 10 Node tests passed** after implementation.
- Real HTML downloaded and parsed on hexagony-01 via the same safe
  robots-aware, pinned-public-IP pipeline.
- Tests cover robots policy, HTML identity mismatch, invalid measurement
  markup, Intel/ARM variant separation, cached one-fetch-per-job behavior,
  original audit immutability, per-offer receipt persistence, HTTP paging
  and zero payment authorization.
- No SerpApi calls, checkout, bypass of prohibited websites, GitHub Actions
  or changes to Hunter's `data/solver-demos/` were needed.

## Research work still required

This is a tested **first evidence adapter**, not a general multi-category
independent-review collector. Most of the 4608 planned checks remain OPEN.
Do **not** claim 4608 completed investigations or a comparison of actual
submitted SKU battery runtimes. The next iteration should implement
authorized, bounded independent-source discovery for arbitrary products,
robust exact-MTM and option matching, conflicts across independent publishers,
relevance-weighted scheduling, and seller/checkout price verification.
