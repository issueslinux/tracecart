# TraceCart — autonomous evidence-first research milestone (2026-11-02)

## What changed

Previously, the default result page asked the **buyer** a fixed sequence of four
questions and the apparent best lead changed when they clicked ARM/x86 or a
verification declaration. That was not the intended research agent. The new
English UI requires **only one product URL**. After the research job finishes,
the browser draws the evidence path and conditional outcome on its own.
There are **zero buyer-choice buttons**.

The server-side read-only projection now has:
- `questions: []` (deprecated buyer questionnaire);
- `research.questions`: research/critic questions with `finding`,
  `verdict`, `origin`, `source_ids`, and `addressed_to=RESEARCH_AGENT_NOT_BUYER`;
- `research.sources`: URL, publisher, source type, variant scope, method,
  limitation and whether it actually verifies the submitted seller SKU;
- `research.conclusion`: explicit **ABSTAIN** in the absence of verified
  current seller prices and exact variants.

The pre-existing local Qwen2.5 1.5B question planner is preserved. Each new
saved question is now tagged `LOCAL_LLM` versus `RULE_BASED`. **After**
indexed Shopping results, one additional bounded local Qwen pass asks at most
four evidence-specific questions (no answers). It receives only item / listing
titles and a generic warning, **not customer data, checkout context, URLs,
barcodes, product prices or PayPal tokens**. Model outage is recorded and
never promoted into fake facts. A real local Qwen run on the saved Lenovo
Shopping titles generated four questions in approximately four seconds after
a first cold-start attempt timed out. The local model is asked only to pose
research questions: answers come from evidence or remain **OPEN**.

No market search API credits are consumed when replaying a saved case.
Historic report hashes and raw reports remain unchanged; newer completed
jobs incorporate the post-index question branch into their own saved hash.

## Actual Lenovo Snapdragon vs Intel investigation

Input was a real prior x-kom URL:
`https://www.x-kom.pl/p/1521342-laptop-15-16-lenovo-ideapad-slim-3-15-snapdragon-x1-26-100-16gb-512-win11-oled.html`.

The saved x-kom extraction failed `SOURCE_TOO_LARGE`, so **product title,
OLED, price and current stock are not verified by the seller page**.
The saved Shopping response had 12 cards, 3 indexed store links, 4
conditionally comparable leads, and 0 checkout-verified competing prices.

**Official manufacturer specifications (manufacturer claims, not tests):**
- [Lenovo PSREF — IdeaPad Slim 3 15Q8X10](https://psref.lenovo.com/Product/IdeaPad/IdeaPad_Slim_3_15Q8X10):
  Snapdragon X X1-26-100, with a **15.1-inch OLED 2560×1600 500 nit**
  option and a different **15.3-inch IPS 1920×1200 300 nit** option.
  Neither the URL nor search index established the precise Lenovo MTM
  for the selected x-kom listing.
- [Lenovo PSREF — IdeaPad Slim 3 16IPH11](https://psref.lenovo.com/Product/IdeaPad/IdeaPad_Slim_3_16IPH11):
  Intel Core Ultra 5 322 x86 family offers 16-inch IPS (400 nit) and
  OLED (300 nit) configurations, with 16 GB SODIMM and 512 GB SSD options.
  An indexed Intel listing cannot establish its exact MTM/display.

**Independent tests (tested configurations only, not the submitted OLED SKU):**
- [Notebookcheck — 15Q8X10 Snapdragon X review](https://www.notebookcheck.net/This-affordable-ARM-laptop-must-worry-AMD-and-Intel-Lenovo-IdeaPad-Slim-3-15Q8X10-review.1093361.0.html),
  Benjamin Herzig, 20 August 2025: tested a **15.3-inch IPS, 60 Wh**
  machine. Under its Wi-Fi browsing protocol (Edge 138, 150 cd/m²),
  **19 h 01 min**; native Cinebench 2024 **708 multi / 96 single**.
  Those results must **not** be attributed to the unverified OLED/other-battery unit.
  The review additionally reports weak integrated GPU and poor IPS gamut,
  which also cannot be copied onto an OLED panel.
- [Notebookcheck — 15IRH10R Intel Core 5 210H review](https://www.notebookcheck.net/Lenovo-IdeaPad-Slim-3-15IRH10R-laptop-review-Intel-Core-5-210H-debut.1037669.0.html),
  Allen Ngo, 4 July 2025: tested a **different Intel 15IRH10R**
  configuration, IPS/60 Wh. Wi-Fi **16 h 59 min** and Cinebench 2024
  **404 multi / 105.4 single**. These are **not** performance scores
  for the indexed **16IPH11 / Core Ultra 5 322** listing.

**Research result:** architecture is materially different (ARM vs x86).
An indexed offer for Intel x86 can be a valid functional alternative for a
buyer needing x86 software, but the project does not know which programs the
buyer will run; it cannot manufacture an individual preference. A measured
19 h vs 17 h comparison across tested models is background context, **not a
measured 2 h advantage between the actual listings**. Price-band eligibility
is provisional because the original x-kom price and exact SKUs are unknown.
The only honest conclusion is a **shortlist for further verification**, not
a cheapest-price recommendation or purchase permission.

The static referenced case is **curated research as of 2026-11-02** and is
selected by its known product family. It does not imply TraceCart automatically
retrieved Notebookcheck or PSREF during that user's historic search. A
general-purpose live independent-review collector is **not implemented**.

## Observed verification and boundaries

- Python 3.8-compatible tests: **375 tests passed** after changing the UI
  contract and adding source-scope cases.
- Node built-in test runner: **8 tests passed**, JavaScript syntax checked.
- Browser: headless Chromium on a **copy** of the real saved local SQLite
  job, separate server port **8792**, no SerpApi call. The DOM contained
  generated research nodes, Notebookcheck source links and the final
  ABSTAIN conclusion; it contained **no buyer choice buttons**.
- The original source report remains read-only; the runtime test database is
  a copy. The existing port 8781 instance was not restarted or altered.
- No source URLs or AI text are injected as HTML; browser rendering uses
  `textContent`, safe HTTPS-only links, local scripts/styles, existing CSP.

**Not verified:** live retailer checkout totals, source automatic retrieval of
independent reviews for arbitrary products, real exact-MTM matching, live
PayPal Sandbox approval, publicly available demo, uploaded demo video or
Devpost form submission. No claim of general marketplace coverage or
measured model accuracy.

## PayPal AI Hackathon — actual entry requirements

Official rules: https://paypalaihackathon.devpost.com/rules

Deadline: **2026-11-12 12:00 Pacific / 21:00 CET**.
Required: integration of **PayPal developer sandbox plus an AI system**;
English description and testing instructions; **functional demo** usable
by judges through a hosted build **or complete runnable repo instructions**;
public open-source repository with visible license; publicly available
YouTube demo **under 3 minutes**, showing the real working application; and
completed Devpost entry before the deadline. Sponsor judging includes
technical PayPal/AI integration, product experience, impact, originality,
and end-to-end video/pitch quality. Private localhost port 8781 alone does
not satisfy accessible demo requirements.

**Immediate submission blockers** still require direct evidence:
1. Execute and record a real sandbox OAuth → order creation → PayPal approval
   roundtrip under explicit human consent. No live card charging.
2. Prepare deterministic judge-friendly setup (without publishing secrets),
   or a hosted accessible instance, and complete a full safe URL → research →
   conditional outcome → explicitly consented sandbox approval demonstration.
3. Record and publish a <3-minute **English** YouTube video, then complete
   Devpost project fields, repo link, AI model disclosure and demo instructions.
4. Confirm account submission and maintain judge access through judging.

Do not close issues #2, #38 or #43: independent evidence, repeatable
marketplace source validation, seller-price freshness and SKU matching remain
work in progress. No GitHub Actions or access-control bypasses were used.
