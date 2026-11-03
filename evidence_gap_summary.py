"""Evidence-aware research queue for the graph detail panel.

This is not the legacy 12-probes-per-axis catalog. The graph shows a small
set of *remaining actionable verification gaps* and source-backed facts
already retrieved. No claim is marked as independently tested unless its
persisted evidence explicitly says so.
"""
from generic_source_research import product_identity


def _has_field(properties,*terms):
    return any(any(term in value for term in terms) for value in properties)

def graph_research_summary(offer,category,evidence=None,intake=None):
    evidence=evidence or {}
    intake=intake or {}
    refs=[ref for ref in (evidence.get("reference_answers") or [])
          if isinstance(ref,dict) and ref.get("source_sha256")
          and ref.get("source_url")]
    fields={str(r.get("property_family") or "").casefold() for r in refs}
    fields.update(str(r.get("source_property") or "").casefold() for r in refs)
    maker={str(r.get("source_kind") or "") for r in refs}
    # Manufacturer/retailer claims are documented answers, not verified
    # hardware identity and not independently instrumented results.
    independent=any(r.get("source_kind")=="INDEPENDENT_TEST" and
                    r.get("verified_for_exact_offer") is True and
                    r.get("status")=="EXACT_SKU_INDEPENDENTLY_VERIFIED"
                    for r in refs)
    own_input=offer.get("kind")=="INPUT_PRODUCT"
    seller_identity=bool(own_input and
                         (intake.get("sku") or
                          intake.get("barcode_status")=="FOUND_CHECKSUM_VALID"))
    has_model=(seller_identity or _has_field(fields,"sku","model","mpn",
                                             "barcode","ean"))
    has_power=_has_field(fields,"power","voltage","current","battery","motor")
    has_performance=_has_field(fields,"performance","pressure","speed","range")
    has_bundle=_has_field(fields,"included","accessories","charging","charger",
                          "w zestawie","wyposażenie")
    has_warranty=_has_field(fields,"warranty","gwaranc")
    has_servicing=_has_field(fields,"spare","repair","service","parts")
    actual_price=bool(evidence.get("verified_checkout_prices"))
    title=str(offer.get("title") or "this product")
    ident=product_identity(title)
    model=(ident or {}).get("model")
    if not model and seller_identity:
        model=str(intake.get("sku") or "")[:40]
    product=("model "+model.upper()) if model else "this offer"
    questions=[]
    def add(key,question,reason):
        questions.append({"id":offer.get("id","offer")+"-research-"+key,
                          "dimension":key,
                          "question":question,"reason":reason,
                          "status":"OPEN_REQUIRES_NEW_EVIDENCE",
                          "priority":"P0" if len(questions)<4 else "P1"})
    if not has_model:
        add("identity","What exact manufacturer model/SKU is offered, and where is it published?",
            "No matching model identifier was found in a fetched document.")
    elif not seller_identity and offer.get("kind")!="INPUT_PRODUCT":
        add("seller_variant","Does the indexed seller really supply "+product+
            " with the same documented revision and accessories?",
            "A model family on another page does not identify the seller's exact item.")
    if not has_power and category in ("E_BIKE","OTHER"):
        add("technical","What are the actual power, electrical and functional specifications for "+product+"?",
            "No adequate power/voltage technical fields have been retrieved.")
    if not independent:
        if category=="E_BIKE":
            prompt="Which independent ride tests measure battery range and braking for "+product+"?"
        elif category=="LAPTOP":
            prompt="Which independent tests measure sustained performance and battery life for "+product+"?"
        else:
            prompt="Is there a reproducible independent performance or accuracy test for "+product+"?"
        add("independent_test",prompt,
            "Retrieved product descriptions do not establish instrumented performance.")
    if category=="OTHER" and not has_performance:
        add("operating","What usable performance limits and test conditions apply to "+product+"?",
            "No comparable performance figure and method was retrieved.")
    if not has_bundle and category=="OTHER":
        add("contents","Which accessories, batteries or chargers actually ship with "+product+"?",
            "Exact delivered kit contents have not been documented.")
    if not has_warranty:
        add("warranty","What documented warranty, exclusions and return conditions apply to "+product+"?",
            "No complete warranty/returns document is linked.")
    if not has_servicing:
        add("repair","Are spare parts, battery replacements or authorized repairs available for "+product+"?",
            "No verified service and replacement-parts data is linked.")
    if not actual_price:
        add("checkout","What is the current total price including delivery at checkout for "+product+"?",
            "Seller and Shopping index prices do not prove the current payable amount.")
    if category=="E_BIKE":
        add("legality","Does a test verify assistance cutoff and regulatory compliance for "+product+"?",
            "Published motor ratings do not prove road-use compliance.")
    elif category=="LAPTOP":
        add("compatibility","Which compatibility or driver issues are confirmed for "+product+"?",
            "Product description alone does not independently test software compatibility.")
    return {
        "open_questions":questions[:9],
        "documented_field_count":len(refs),
        "source_documents":len({(r["source_url"],r["source_sha256"]) for r in refs}),
        "manufacturer_or_seller_declarations":len([r for r in refs
            if r.get("source_kind")!="INDEPENDENT_TEST"]),
        "independent_exact_offer_measurements":int(independent),
        "documented_fields":sorted(fields)[:16],
    }
