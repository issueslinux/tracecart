# TraceCart: decision support, not automatic verdicts

## Product requirement — November 1, 2026

**TraceCart must make options and trade-offs understandable, not force a single winner.**
Its automated questions address search results, offers, reviews, specifications
and seller claims. They are NOT a questionnaire for the buyer. A separate critic
challenges weak conclusions, and the entire decision/evidence tree remains
available after each analysis.

## Default presentation: actionable comparative summary

Show relative prices with the baseline stated explicitly. For A=900 PLN and
B=990 PLN: B is 10.0% more expensive relative to A; A is 9.1% cheaper relative
to B. Do not mix currencies or assert that advertised amounts include delivery.

Show practical differences between genuinely comparable specifications, with
the distinction between higher numeric values and useful outcomes. More RAM
or storage may offer headroom but is not necessarily worth the extra cost.
When the product's intended use is unknown, say the utility is unknown.

Include new, refurbished, and used alternatives. For used items, list specific
questions for the SELLER or listing evidence: battery wear, repairs, photos,
testing, original proof and return terms. Do not fabricate responses. Do not
claim undocumented condition, reliability or seller trustworthiness.

Clearly separate observed claims, interpretation and unknowns, without blocking
the whole comparison whenever one question cannot be resolved.

## Second layer: full auditable evidence tree

Every offer, price/spec source, critic objection, contradiction, rejected
question, useful follow-up and incomplete branch remains inspectable. Export
the complete result in JSON. Do not discard complexity from the audit merely
because the summary is short.

Payment is a separate, explicitly human-approved operation in the PayPal
sandbox. A research or comparative report cannot approve or capture money.

## Implemented proof of concept

The /compare route accepts 2–12 structured offers with prices, original URLs,
conditions and comparable quantitative specifications. Decimal arithmetic is
used for percentages. Different currencies and incompatible units are not
compared. Used-product follow-ups are attached to the full decision tree, while
the top-level result is NO_FORCED_WINNER instead of a forced purchase verdict.

Example A=900 PLN, B=990 PLN, used C=650 PLN uses ONLY FICTIONAL listings on
reserved example.org/com/net domains. It is a reproducible demonstration of
the output format, not actual sourcing or independent technical measurement.

## Next research direction

Search for 10–20 genuinely comparable offers for one real buyer task. Reuse
the critic and evidence store to add external reviews, tests and counterclaims.
Evaluate whether any extra research materially changes the trade-offs before
spending resources on more questions. Stop when further inquiry has marginal
value and return the best-supported comparison available, including unknowns.

Avoid getting trapped in meticulous analysis of one technical product when the
decision-support framework itself is the main goal.