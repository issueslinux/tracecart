# Purchase-stage evidence, transport and first live same-EAN compressor comparison

Date: **2026-11-02**. This feature does not purchase anything, access buyer
accounts, or authorize PayPal. All store data is a **seller assertion**, not an
independent measurement or a checkout-confirmed total.

## Six independent evidence groups

Cart research now retains all existing product/category/AI questions, nested
under six explicit audit branches: `product`, `offer`, `seller`, `delivery`,
`payment`, `total_cost`. Every question remains `OPEN` until supported by a
permitted source. The group labels are not quality scores and do not request
private information from the buyer.

The `delivery` group asks about shipping to the actual destination, carrier,
arrival time and pickup travel/time; `payment` asks about mandatory fees and
buyer protections; `total_cost` asks whether eligible discounts and final
checkout amount are actually confirmed. No invented answers are inserted.

## Optional, seller-declared transport evidence for `/compare`

The existing comparison JSON remains valid without modification. Each offer
may optionally contain:

```json
"fulfillment": {
  "method": "courier",
  "cost": "26.00",
  "currency": "PLN",
  "eta_min_days": null,
  "eta_max_days": null,
  "source_url": "https://fabryka-narzedzi.pl/stanley-kompresor-sprezarka-bezolejowa-air-kit-ol-195-1-1kw-8-bar-p-70017.html",
  "evidence_status": "SELLER_DECLARED"
}
```

Valid methods: `courier`, `parcel_locker`, `unspecified_delivery`, `pickup`.
The shipping cost is a **string decimal** (up to two places) or `null`;
its currency must match the product currency, or be `null` when cost is
unknown. ETA must be a pair of integer day bounds (0–365) or both `null`.
The source URL must be public HTTPS. This input is **not fetched by**
`/compare`: it is a source link supplied by the researcher. `SELLER_DECLARED`
does not mean independently verified. Unrecognized evidence statuses, invalid
numbers, contradictory currency, missing ETA bounds and malformed URLs fail
closed. `pickup` cannot specify a seller shipping fee because the buyer's
travel expense and time are unknown; never infer zero-cost pickup.

When **both** offers have a source-declared delivery charge, comparison
shows `product + shipping` and a difference. It **does not** claim a final
checkout price or winner: payment fees, destination, eligibility, returns,
quantity, condition and actual delivery remain unverified. Dispatch time is
not an arrival-time guarantee. Without shipping evidence, comparison stays
`UNKNOWN_TRANSPORT_COST` rather than silently using zero.

## Live case: Stanley Air Kit OL 195 / EAN 8016738753899

Both pages were downloaded directly on 2 November 2026 after `robots.txt`
preflight using the bounded HTTPS collector. The resulting source timestamp,
full-page SHA-256, item fields and source-declared stock are preserved in
[`examples/live_stanley_two_shop_2026-11-02.json`](../examples/live_stanley_two_shop_2026-11-02.json).

| Seller | Listed product | Claimed shipping | Conditional product + shipping | Stock claim |
|---|---:|---:|---:|---|
| Fabryka Narzędzi | 382.28 PLN | 26.00 PLN courier | 408.28 PLN | InStock |
| xDom | 490.14 PLN | 17.99 PLN, method unspecified | 508.13 PLN | InStock |

**Conditional difference: 99.85 PLN**, with Fabryka lower **for the shown
shipping methods and amounts only**. Both directly retrieved pages declare
valid EAN `8016738753899`, and the existing comparator returns
`SAME_GTIN_SELLER_LISTED_PRICE_COMPARISON`. This is a successful source-level
identity and price comparison, not proof of delivery eligibility or final
checkout savings. Both shipping amounts were found in the public product
HTML during the research iteration; they were entered into the optional
transport comparison as seller claims, not automatically extracted by the
application. Product condition and kit contents need separate confirmation.

The Fabryka page advertises dispatch in 1–2 days, xDom in 24 hours; these
are **not** customer delivery-time measurements, so `eta_*` remains `null`.
The original Allegro offer is not considered a directly verified price when
its product page returns HTTP 403. No access restrictions were bypassed.

## New product identity coverage

A narrow parser now accepts `itemprop=gtin13` inside a schema.org **Product**
scope, and labelled EAN within a Magento `product-attributes` widget. This
closes the actual missing-EAN gap on Fabryka Narzędzi and EMAST. It rejects
unscoped GTIN strings, unrelated recommendation cards and generic SKU/MPN
numbers; conflicting or checksum-invalid seller claims still block equality.

## Next work

1. Automate **source-scoped** shipping price and method extraction from
   permitted schema.org `shippingDetails` or a primary product delivery widget.
   Preserve destination/quantity conditions; never extrapolate checkout fees.
2. Extend source discovery by GTIN and MPN to more independent Polish shops,
   verifying product condition, variant and kit contents before comparing.
3. Add explicit seller, return-policy and payment-fee evidence, including
   source provenance and critic objections. Keep every unknown visible.
