## Allegro product links — 403-safe limited analysis

**Observed on 2026-11-01:** the actual page linked by a user,
`https://allegro.pl/produkt/persil-color-pulver-proszek-do-prania-kolor-4-5-kg-75-pran-niemcy-c57e870f-64f0-49db-91de-502a3f216264?offerId=18675491436`,
returned HTTP **403** to the TraceCart HTTP client. robots.txt was reachable;
the actual product page content was not.

Instead of marking the whole research as FAILED:

1. First attempt the original public HTTPS URL through the existing
   DNS-pinned, TLS-verified, robots-aware fetcher. **Never bypass 403**.
2. For strictly validated `allegro.pl/produkt/<slug>-<UUID>` links only,
   **derive an *unverified* product label from the user-provided URL path**,
   retain its UUID and optional numeric `offerId`, discard tracking query
   parameters. This uses NO Allegro page content.
3. Preserve **unknown price (null)**, **unknown stock**, **unknown EAN**,
   **no content SHA-256** and **no page retrieval timestamp**. Record
   `access_problem=HTTP_403` and `intake_status=URL_ONLY_UNVERIFIED`.
4. Continue the bounded product-category research using the available
   text. Show catalog candidates only as possible products, **not verified
   alternatives or cheaper retail offers**. Do not imply they are identical
   to the 4.5 kg / 75-wash original.
5. Render a prominent page-blocked notice above the research tree and
   retain the failure reason within the persistent JSON audit.

### Limits and genuine Allegro API integration

The Allegro REST resources `GET /sale/product-offers/{offerId}` and
`GET /sale/product-offers/{offerId}/parts` require authorized bearer
tokens; standard seller offer retrieval is scoped to authorized seller
accounts. Publicly pasting an arbitrary Allegro link does **not** grant
such access. No attempt is made to bypass it or to fabricate stock or
prices. Production support for current offers requires an **authorized
data provider or appropriate public API permissions**. Until then, this
is limited research based on user-supplied URL wording, not a verified
Allegro product snapshot.

Source: https://developer.allegro.pl/documentation and
https://developer.allegro.pl/faq

To retry an earlier FAILED job created by old code, submit the product
link **again**. Previously failed records are immutable; updated software
does not silently rerun them.
