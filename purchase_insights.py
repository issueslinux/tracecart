"""Evidence-limited purchase alternatives: different models ARE allowed.

Always distinguish advertised/indexed specifications and prices from fetched
seller prices, independent lab results, and checkout totals. Never manufacture
exact-model equivalence or a checkout recommendation.
"""
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from statistics import median

from similar_tier import (
    category_of, read_specs, evaluate_alternative, STATUS_SIMILAR, STATUS_POSSIBLE,
    STATUS_DIFFERENT, PUBLIC_SPEC_NAMES,
)

MIN_PEERS=3
MAX_OPTIONS=4
MAX_TRADEOFFS=2
SIMILAR={STATUS_SIMILAR,STATUS_POSSIBLE}


def _number(value):
    try:
        if value is None or isinstance(value,bool):
            return None
        d=Decimal(str(value).replace(" ","").replace(",","."))
        if not d.is_finite() or d<=0 or d>Decimal("100000000"):
            return None
        return d
    except (InvalidOperation,ValueError,TypeError):
        return None


def _money(value,currency):
    return "{} {}".format(value.quantize(Decimal("0.01"),rounding=ROUND_HALF_UP),
                          currency)


def _text(value,limit=140):
    return str(value or "")[:limit]


def _title_highlights(title,category):
    """Extract only *advertised* features from listing text; not lab data."""
    import re
    t=_text(title,260).casefold()
    result=[]
    if category=="LAPTOP":
        for pattern,label in (
            (r"\b120\s*hz\b","120 Hz display (advertised in listing title)"),
            (r"\bips\b","IPS display (advertised in listing title)"),
            (r"\b(?:dotyk|touchscreen|touch)\b","Touchscreen (advertised in listing title)"),
            (r"\b(?:win(?:dows)?\s*11\s*pro|w11\s*pro)\b",
             "Windows 11 Pro (advertised in listing title)"),
        ):
            if re.search(pattern,t):result.append(label)
    return result[:3]


def build_purchase_insights(projection,graph=None):
    """Rank technical peer leads, NEVER claim a verified cheapest purchase."""
    offers=projection.get("offers") or []
    if not isinstance(offers,list):
        offers=[]
    selected=offers[0] if offers else {}
    title=selected.get("title") or projection.get("title") or ""
    cat=category_of(title)
    selected_specs=read_specs(title,cat)
    if cat in ("UNKNOWN","ACCESSORY"):
        from generic_value import generic_unit_value
        return generic_unit_value(projection)
    ranked=[]
    rejected=[]
    all_relevant=[]
    for entry in offers[1:]:
        if not isinstance(entry,dict):
            continue
        ident=_text(entry.get("id"),60)
        text=_text(entry.get("title"),185)
        test=evaluate_alternative(title,text)
        currency=_text(entry.get("currency"),8).upper()
        amount=_number(entry.get("indexed_price"))
        if test.get("category")!=cat or cat in ("UNKNOWN","ACCESSORY"):
            continue
        if amount is None or currency not in ("PLN","EUR","USD"):
            continue
        good=len(test.get("matched_features") or [])
        different=len(test.get("different_features") or [])
        dimensions=test.get("evidence_dimensions_compared") or 0
        # Not all laptops with "Intel" are comparable; require multiple
        # explicitly comparable specifications from index titles.
        candidate_specs=read_specs(text,cat)
        if cat=="LAPTOP":
            # "Intel x86 + 16 GB RAM" alone is NOT enough to claim a
            # similarly equipped laptop when CPU tier/storage are unknown.
            required=[k for k in ("ram_gb","capacity_gb","cpu_tier")
                      if k in selected_specs]
            core_matches=sum(k in candidate_specs and
                             candidate_specs[k]==selected_specs[k]
                             for k in required)
            same_cores=(len(required)>=2 and core_matches==len(required))
        else:
            same_cores=True
        if (test["status"]==STATUS_SIMILAR and good>=2 and
            dimensions>=2 and same_cores):
            tier="SIMILAR_TITLE_SPEC_TIER"
        elif (good>=2 and dimensions>=2 and test["status"] in SIMILAR) or (
              test["status"]==STATUS_DIFFERENT and good>=1 and different>=1):
            tier="PARTIAL_SPECS_OR_TRADEOFF"
        else:
            rejected.append({"offer_id":ident,"reason":"SPECIFICATIONS_NOT_COMPARABLE"})
            continue
        record={
            "offer_id":ident,"title":text,
            "price":str(amount.quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)),
            "currency":currency,"price_source":"SEARCH_INDEX_QUOTE_NOT_CHECKOUT",
            "price_node_id":"price:"+ident,
            "source_url":entry.get("url"),
            "has_direct_url":bool(entry.get("url")),
            "similarity_status":test["status"],
            "similarity_score":test.get("technical_score"),
            "tier":tier,
            "matched_features":list(test.get("matched_features") or [])[:6],
            "different_features":list(test.get("different_features") or [])[:5],
            "unconfirmed_features":list(test.get("unconfirmed_features") or [])[:5],
            "highlights":_title_highlights(text,cat),
            "identity_verified":False,"checkout_verified":False,
            "value_status":"CANDIDATE_NOT_VERIFIED",
        }
        all_relevant.append((record,amount))
    # The reference is a peer median from all reasonably comparable
    # listing prices, not the selected retailer price. At least 3 unique
    # product rows are required; a 139.95 PLN laptop quote is an outlier,
    # not a "bargain" when peers cluster around 3500 PLN.
    currency_counts={}
    for row,amount in all_relevant:
        if row["tier"]=="SIMILAR_TITLE_SPEC_TIER":
            currency_counts.setdefault(row["currency"],[]).append(amount)
    selected_currency=(max(currency_counts,key=lambda k:len(currency_counts[k]))
                       if currency_counts else None)
    peers=currency_counts.get(selected_currency,[])
    median_raw=median(peers) if len(peers)>=MIN_PEERS else None
    # All same-category quotes inform anomaly detection, including
    # partial candidates. Compare against the above strong peer median.
    anomalies=[]
    clean=[]
    for row,amount in all_relevant:
        if (median_raw is not None and row["currency"]==selected_currency and
            amount<median_raw*Decimal("0.40")):
            anomalies.append({
                "offer_id":row["offer_id"],"indexed_price":row["price"],
                "currency":row["currency"],
                "reason":"VERY_LOW_PRICE_RELATIVE_TO_COMPARABLE_INDEX_OFFERS",
            })
            continue
        clean.append((row,amount))
    # Also identify impossible looking cheap search index cards with laptop
    # markers but missing storage/CPU details. These are NOT promoted.
    if median_raw is not None:
        seen={r["offer_id"] for r in anomalies}
        for entry in offers[1:]:
            if entry.get("id") in seen:continue
            price=_number(entry.get("indexed_price"))
            if (price is not None and
                _text(entry.get("currency"),8).upper()==selected_currency and
                price<median_raw*Decimal("0.40")):
                anomalies.append({
                    "offer_id":entry.get("id"),"indexed_price":str(price),
                    "currency":selected_currency,
                    "reason":"VERY_LOW_PRICE_RELATIVE_TO_COMPARABLE_INDEX_OFFERS",
                })
                seen.add(entry.get("id"))
    # Recompute anchor without extreme outliers.
    strong=[amount for row,amount in clean
            if row["tier"]=="SIMILAR_TITLE_SPEC_TIER" and
               row["currency"]==selected_currency]
    anchor=median(strong) if len(strong)>=MIN_PEERS else None
    strong_options=[]
    tradeoffs=[]
    for row,amount in clean:
        if anchor is not None and row["currency"]==selected_currency:
            delta=anchor-amount
            row["market_reference_kind"]="MEDIAN_OF_COMPARABLE_INDEX_QUOTES"
            row["market_reference_price"]=_money(anchor,selected_currency)
            row["vs_index_median"]=(
                 "below the indexed peer median by "+_money(delta,selected_currency)
                if delta>0 else
                 "above the indexed peer median by "+_money(-delta,selected_currency)
                if delta<0 else "at the indexed peer median")
        else:
            row["market_reference_kind"]="NO_VALID_COMPARABLE_PRICE_MEDIAN"
            row["market_reference_price"]=None
            row["vs_index_median"]="no reliable price reference"
        if row["tier"]=="SIMILAR_TITLE_SPEC_TIER":
            strong_options.append((row,amount))
        else:
            tradeoffs.append((row,amount))
    strong_options.sort(key=lambda x:(
        x[0]["currency"]!=selected_currency,
        x[1],
        -len(x[0]["matched_features"]),
        x[0]["offer_id"]))
    tradeoffs.sort(key=lambda x:(x[1],x[0]["offer_id"]))
    top=[r for r,_ in strong_options[:MAX_OPTIONS]]
    extra=[r for r,_ in tradeoffs[:MAX_TRADEOFFS]]
    # A promotion can make the input product substantially cheaper than
    # prices indexed before the coupon. Never replace that input price with
    # an unrelated product median. Manual/user-reported observations remain
    # explicitly unverified until checkout.
    observed=projection.get("input_price") or {}
    from_source=projection.get("selected_item") or {}
    source_intake=projection.get("selected_source_intake") or {}
    input_price=_number(observed.get("price"))
    input_currency=observed.get("currency")
    input_provenance=observed.get("origin")
    promotion=observed.get("promotion_code")
    promotion_until=observed.get("valid_until")
    # A browser receipt must be attached to offer-0 by the knowledge graph:
    # that projection validates the selected URL and rejects SKU/GTIN conflicts.
    # It is a seller-visible quote, never a verified checkout or an overwrite
    # of an explicit user price observation.
    if input_price is None:
        selected_detail=((graph or {}).get("offer_details") or {}).get("offer-0") or {}
        browser=selected_detail.get("browser_observation") or {}
        if (browser.get("status")=="PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED"
                and browser.get("checkout_verified") is False):
            base=_number(browser.get("declared_price"))
            currency=browser.get("currency")
            if base is not None and currency in ("PLN","EUR","USD"):
                input_price,input_currency=base,currency
                input_provenance="BROWSER_SELLER_LISTED_PRICE_NOT_CHECKOUT"
                conditional=browser.get("promotion") or {}
                coupon=_number(conditional.get("price"))
                until=conditional.get("valid_until")
                valid_date=(until is None)
                if isinstance(until,str):
                    try:
                        valid_date=date.fromisoformat(until)>=date.today()
                    except ValueError:
                        valid_date=False
                if (conditional.get("condition")=="CODE_REQUIRED" and
                    conditional.get("currency")==currency and
                    isinstance(conditional.get("code"),str) and
                    1<=len(conditional["code"])<=48 and
                    coupon is not None and coupon<base and valid_date):
                    input_price=coupon
                    input_provenance="BROWSER_VISIBLE_CONDITIONAL_CODE_PRICE_NOT_CHECKOUT"
                    promotion=conditional["code"]
                    promotion_until=until
    if input_price is None and source_intake.get("price_status")=="SELLER_DECLARED":
        input_price=_number(from_source.get("price"))
        input_currency=from_source.get("currency")
        input_provenance="FETCHED_SELLER_DECLARATION_NOT_CHECKOUT"
    if input_price is None:
        input_currency=None
        input_provenance="NOT_AVAILABLE"
    input_price_label=(_money(input_price,input_currency) if input_price and
                       input_currency in ("PLN","EUR","USD") else None)
    if input_price_label:
        for item,amount in clean:
            if item["currency"]!=input_currency:continue
            diff=amount-input_price
            item["relative_to_selected_price"]=_money(abs(diff),input_currency)
            item["vs_selected_price"]=(
                "higher than selected price by "+_money(diff,input_currency)
                if diff>0 else
                "below selected price by "+_money(-diff,input_currency)
                if diff<0 else
                "equal to selected price")
            item["price_comparison_basis"]=input_provenance
        # Higher prices are NOT the "best value" shortlist unless there is
        # independently supported proof of a meaningful improvement.
        expensive_options=[r for r,amount in strong_options
                           if r["currency"]==input_currency and amount>=input_price]
        expensive_options.sort(key=lambda r:Decimal(r["price"]))
        top=[r for r in top if r["currency"]==input_currency and
             _number(r["price"])<input_price]
        extra=[r for r in extra if r["currency"]==input_currency and
               _number(r["price"])<input_price]
    else:
        expensive_options=[]
    # If the input title omits numeric specs (common for manufacturer pages),
    # do not conclude that no cheaper products exist. Surface distinguishable
    # same-SKU or function+voltage title leads with explicit uncertainty.
    # No index listing is promoted to a verified functional equivalent.
    functional=[]
    if not selected_specs and not top and not extra:
        from functional_value import functional_leads
        functional=functional_leads(projection,input_price,input_currency)
    if functional:
        top=functional[:4]
        extra=functional[4:]
        first=functional[0]
        status="FUNCTIONAL_INDEX_LEADS_NEED_SPEC_VERIFICATION"
        message=(
            "Potentially cheaper offer requiring specification verification: "+
            first["title"]+" — "+first["price"]+" "+first["currency"]+
            ". "+("Observed selected seller price: "+input_price_label+". "
                   if input_price_label else
                   "Selected seller price not independently established. ")+
            "This is a search-index lead, not a confirmed equivalent or "
            "checkout price. Compare manufacturer specifications, variant, "
            "included accessories and delivered cost before purchase."
        )
    # The submitted seller page may be HTTP 403. Even if its listing title
    # and an indexed price happen to match, no checkout has been verified.
    elif input_price_label and not top and not extra:
        status="SELECTED_PRICE_UNDERCUTS_AVAILABLE_INDEX_PEERS"
        higher=expensive_options[0] if expensive_options else None
        message=(
            "The selected product is listed at "+input_price_label+
            (" with promotion code "+promotion if promotion else "")+
            (" (listed as valid through "+promotion_until+")" if promotion_until else "")+
            ". None of the currently comparable indexed listings is cheaper."
        )
        if higher:
            message+=(" The lowest comparable indexed quote is "+
                      _money(_number(higher["price"]),higher["currency"])+
                      " ("+higher["vs_selected_price"]+
                      "), with no documented advantage justifying that premium.")
        message+=(" Verify coupon eligibility and delivered checkout total before purchase.")
    elif top:
        first=top[0]
        message=(
            ("Potentially cheaper comparable listing: " if input_price_label else
             "Comparable indexed listing (savings unknown): ")+first["title"]+
            " — "+_money(_number(first["price"]),first["currency"])+
            ". Similar advertised specifications: "+
            ", ".join(first["matched_features"][:3])+". "
            "The indexed price is not a verified checkout amount. "
        )
        if input_price_label:
            message+=("Selected seller price is "+input_price_label+
                      " ("+str(input_provenance)+"); differences may change in checkout.")
        else:
            message+=(
                "The selected seller price is unavailable; no confirmed "
                "saving can be calculated.")
        status=("CHEAPER_INDEX_COMPARABLE_LEADS" if input_price_label else
                "COMPARABLE_INDEX_OFFERS_FOUND")
    elif extra:
        message=(
            "Lower-priced but technically different listings were found. "
            "They are not equivalent products; compare the specification trade-offs "
            "and verify both prices before purchase.")
        status="CHEAPER_BUT_DIFFERENT_INDEX_LEADS"
    elif strong_options:
        message=(
            "Comparable products were found in the search index, but no "
            "selected-store price baseline is available. They are NOT confirmed "
            "cheaper or better value. Provide a seller-observed price or find "
            "a permitted primary offer price before ranking by savings.")
        status="INPUT_PRICE_UNKNOWN_NO_VALUE_RECOMMENDATION"
    else:
        message=(
            "No available listing has enough explicitly comparable "
            "specifications for a meaningful value comparison. "
            "This does not prove cheaper alternatives do not exist.")
        status="NO_RELIABLE_COMPARABLE_INDEX_LEADS"
    return {
        "status":status,"selected_title":_text(title,175),
        "category":cat,
        "selected_price_verified":False,
        "selected_price":input_price_label,
        "selected_price_source":input_provenance,
        "selected_price_available_in_seller_page":(
            input_provenance in ("FETCHED_SELLER_DECLARATION_NOT_CHECKOUT",
                                  "BROWSER_SELLER_LISTED_PRICE_NOT_CHECKOUT",
                                  "BROWSER_VISIBLE_CONDITIONAL_CODE_PRICE_NOT_CHECKOUT")),
        "promotion_code":promotion,
        "promotion_valid_until":promotion_until,
        "pricing_basis":"SELECTED_UNVERIFIED_PRICE_VS_UNVERIFIED_INDEX_QUOTES",
        "market_reference":(_money(anchor,selected_currency)
                            if anchor is not None else None),
        "market_reference_provenance":("PEER_MEDIAN_SEARCH_INDEX_NOT_SELLER"
                                       if anchor is not None else "NO_PEER_ANCHOR"),
        "headline":message,
        "options":top,
        "tradeoffs":extra,
        "higher_priced_comparables":expensive_options[:4],
        "suspicious_price_quotes":anomalies[:8],
        "comparable_count":len(strong_options),
        "tradeoff_count":len(tradeoffs),
        "total_offers_seen":len(offers),
        "disclaimer":"Indexed prices and titles do not verify stock, shipping, exact variant or checkout total.",
        "payment_authorized":False,
    }
