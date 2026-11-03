# E-bike source-question repair — 2026-11-03

## User-observed failure

Reported job: `LoHWENthHlgccaUCtbOdQkCO`
(`/cart/status/LoHWENthHlgccaUCtbOdQkCO`) using an Allegro
product URL for a generic "250W 15Ah 100km 27.5" Shimano 7s 25kmh"
electric bicycle.

Actual saved SQLite audit:

- `READY`, product identity `URL_ONLY_UNVERIFIED` because
  Allegro page access returned **HTTP 403** in the application.
- Google Shopping search supplied **12 indexed cards**, **0**
  verified direct seller offers, and no verified checkout price.
- The per-offer Qwen worker attempted all **13 queues** (input + 12 cards):
  **11 successful**, **2 `UNAVAILABLE_JSONDecodeError`**.
- All **288 source questions per offer** came from a mechanical
  24-dimension × 12-probe expansion; questions like "Has an independent
  laboratory measured manufacturer frame and variant identity?" were
  nonsensical.
- No independent laboratory was matched to the exact item; that finding
  remains true after this fix.

## New relevant investigation plan

`ebike_research.py` defines **24 domain-specific leading questions** covering
24 DIFFERENT aspects of the bike, then **12 cross-claim contradiction
checks**, then eight source-appropriate investigative checks for each
of the 24 dimensions. That is **228 questions per offer** (13 × 228 =
2964 in this historical case). They remain `PLANNED_NOT_INVESTIGATED`,
not LLM-written answers.

The first page asks, in order, about exact OEM/frame identity, battery
voltage and Wh, independent range conditions, motor-assistance cut-off,
actual motor continuous power, charger and battery safety, repairability,
brakes, Shimano component SKUs, frame geometry, load, legal conformity,
seller condition, real total price, independent tests, and other distinct
questions. **No laboratory measurement of model identity** or twelve
templated variants of the same question.

The question plan is **title-dependent**. A different bicycle without
15 Ah, 100 km, 250 W, Shimano or 27.5-inch wheel labels will not
inherit those claims. Other product categories retain their existing
source-queue semantics and deterministic question IDs, preserving the
Lenovo independent-test receipt links.

## New source-scope signals

The API and UI show **unverified title claims**, not "verified specs".
For the reported product these are 250 W, 15 Ah, advertised 100 km,
27.5-inch wheel, seven gears and advertised 25 km/h; the original title
does not name battery voltage or total energy in Wh.

The related search-index titles produce **alternative identity leads**:
`Allgobike AM27` and `Orzel C27`. These are **not** exact-seller-SKU
identification. The UI makes that explicit; no matching retailer page
was retrieved or identity verified.

Conditional battery arithmetic (not source measurements): **IF** 15 Ah
and 36 V, then 540 Wh and 5.4 Wh/km at the advertised 100 km; **IF**
48 V, then 720 Wh and 7.2 Wh/km. The user cannot use these numbers as
evidence that the seller's battery has either voltage or reaches 100 km.

The absence of a matched independent e-bike review is recorded as
`NO_MATCHED_INDEPENDENT_EBIKE_REVIEW`, with concrete unresolved tasks
(OEM/model, battery voltage/Wh, independently measured range, legal
motor cutoff, brakes/service and seller price). No fabricated quality
or purchase recommendation.

## Qwen robustness

Changed the local `qwen2.5:1.5b-instruct` per-offer question prompt to
request **up to four short** English source questions and increased the
model output token budget from 220 to 340. On syntactically invalid
JSON or invalid question-list structure, the caller retries **once**
with a smaller two-question JSON request. The parser accepts a valid
JSON object inside Markdown fences, but does not guess truncated
facts or produce made-up fallback "LLM" responses.

**Real local Qwen check:** the problem product's sanitized title
produced four well-formed domain-relevant questions in **7.12 s**,
including motor continuous power, battery V/Ah/Wh, range test
conditions and brakes. Qwen question generation stays asynchronous.
The UI now explains model unavailability without exposing a raw
`JSONDecodeError` to the buyer.

## Verification and limitations

- An isolated copy of the historical SQLite report on port 8798:
  `E_BIKE`, 13 offers, **2964** prioritized source tasks; 24 distinct
  high-impact dimensions on first page; input price remains unknown.
- Headless Chromium rendered 13 offer cards, 228 questions per offer,
  `Allgobike AM27`/other indexed leads with explicit identity caveats,
  and conditional 540 Wh/5.4 Wh/km values, without JS exceptions or
  buyer-choice controls.
- **397 Python tests + 11 Node tests** passed, including generalized
  rower title scenarios, 228 unique questions, no category leakage,
  Qwen retry with malformed JSON, and HTTP projection/pagination.
- No paid SerpApi calls, source-access bypass, price invention, PayPal
  authorization, modifications to historical report hashes, or GitHub
  Actions were needed.

**Still missing:** independently verified seller page and checkout price,
actual manufacturer/model identity, battery and brake component identity,
real-world e-bike laboratory results, and general independent-source
discovery. A cleaner queue does not automatically mean its 2964
investigations have been performed.
