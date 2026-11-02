# Offer Research Critic — actionable research after seller-price comparison

TraceCart's next milestone is **evidence-centered product research**, not further
shipping/ETA parsing. This is a deterministic, explicit **critic**, not a claim
that an LLM has independently verified product quality or customer reviews.

## Behavior

- Following a live single- or multi-merchant comparison, the critic inspects
  existing **source-gated** results. It never fetches private pages, bypasses
  robots.txt, invents review/test findings or initiates a purchase.
- An offer with a lower listed price becomes a **research lead** only if the
  original comparison passed its source, GTIN, variant, availability, price and
  currency gates. Its monetary difference is in seller-listed product price,
  NOT a verified checkout saving or a purchase recommendation.
- A blocked comparison produces an evidence-specific next question: missing
  GTIN, conflicting variant, unavailable stock, stale or inaccessible offer,
  incompatible currency, and so on. Even unrecognized future statuses have a
  safe fallback question instead of a fictitious verdict.
- Questions are ordered by a transparent research priority, with an explicit
  budget and **audited deferred questions**. Every original candidate,
  research status, source URL, retrieval timestamp and available page SHA-256
  remains in the complete exportable tree. No buyer questionnaire is required.
- The report and browser show `RESEARCH CRITIC` and distinguish the number of
  plausible seller-listed price leads from unresolved research questions.
  Seller assertions **do not constitute independent lab tests**. Independent
  tests and reviews have not been retrieved by this new module.
- The existing PayPal consent firewall remains untouched. No purchase winner
  or payment authorization is produced from the critic.

## Real source observation — Stanley Air Kit, 2 November 2026

Two publicly accessible seller pages were retrieved with the existing
robots-aware safe HTTPS intake at ~15:58 UTC. Their **seller-declared** GTINs
matched (`8016738753899`), both pages declared stock, and the comparison
returned `SAME_GTIN_SELLER_LISTED_PRICE_COMPARISON`.

| Merchant | Seller-listed product price | TraceCart source evidence |
|---|---:|---|
| xDom | 490.14 PLN | Real page + SHA-256 + retrieval timestamp |
| Fabryka Narzędzi | 382.28 PLN | Real page + SHA-256 + retrieval timestamp |

From the **xDom** selected baseline, the alternative has a **107.86 PLN lower
seller-listed product price**. The critic's result is
`LOWER_SELLER_LISTED_PRICE_ONLY`, with a prioritized question about independent
product tests, condition and seller policies. No quality, final cost,
checkout saving, seller trustworthiness or warranty conclusion was verified.

Machine-readable snapshot: [`examples/live_stanley_offer_research_critic_2026-11-02.json`](../examples/live_stanley_offer_research_critic_2026-11-02.json).

## Next research goal

Retrieve verifiable external manufacturer documentation and genuine independent
product tests/reviews for the same exact model, establish whether they are
about the same product version, and attach them to evidence and critic nodes.
Track failed searches and lack of genuinely independent testing as gaps, not
negative ratings. Focus on decision-relevant differences, with a bounded
research budget rather than unlimited question expansion.
