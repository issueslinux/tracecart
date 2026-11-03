"""Evidence-limited purchase alternatives: different models ARE allowed.

Always distinguish advertised/indexed specifications and prices from fetched
seller prices, independent lab results, and checkout totals. Never manufacture
exact-model equivalence or a checkout recommendation.
"""
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
            (r"\b120\s*hz\b","matryca 120 Hz (deklaracja w tytule)"),
            (r"\bips\b","matryca IPS (deklaracja w tytule)"),
            (r"\b(?:dotyk|touchscreen|touch)\b","ekran dotykowy (deklaracja w tytule)"),
            (r"\b(?:win(?:dows)?\s*11\s*pro|w11\s*pro)\b",
             "Windows 11 Pro (deklaracja w tytule)"),
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
                "poniżej mediany ofert indeksowych o "+_money(delta,selected_currency)
                if delta>0 else
                "powyżej mediany ofert indeksowych o "+_money(-delta,selected_currency)
                if delta<0 else "na poziomie mediany cen indeksowych")
        else:
            row["market_reference_kind"]="NO_VALID_COMPARABLE_PRICE_MEDIAN"
            row["market_reference_price"]=None
            row["vs_index_median"]="brak wiarygodnego punktu odniesienia"
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
    input_price=_number(selected.get("indexed_price"))
    # The submitted seller page may be HTTP 403. Even if its listing title
    # and an indexed price happen to match, no checkout has been verified.
    if top:
        first=top[0]
        message=(
            "Warto sprawdzić ofertę "+first["title"]+" — "+
            _money(_number(first["price"]),first["currency"])+
            " w indeksie wyszukiwania. Z tytułu wynika podobna konfiguracja: "+
            ", ".join(first["matched_features"][:3])+". "
            "Cena NIE jest potwierdzoną kwotą zakupu. "
        )
        if not input_price:
            message+=(
                "Cena produktu wejściowego nie została pobrana ze sklepu, "
                "więc nie da się uczciwie stwierdzić, że ta oferta jest od niego tańsza."
            )
        else:
            message+=(
                "Cena oferty wejściowej także wymaga weryfikacji w koszyku, "
                "zanim można ogłosić oszczędność."
            )
        status="COMPARABLE_INDEX_OFFERS_FOUND"
    elif extra:
        message=(
            "Znaleziono oferty o częściowo podobnych parametrach, "
            "ale różnice w specyfikacji nie pozwalają traktować ich jako "
            "równoważnych produktów. Ceny są jedynie z indeksu wyszukiwania."
        )
        status="TRADEOFF_ONLY"
    else:
        message=(
            "Wśród dostępnych wyników nie znaleziono ofert z wystarczającą "
            "liczbą wspólnych parametrów, aby porównać stosunek ceny do "
            "specyfikacji. To nie oznacza, że tańsze zamienniki nie istnieją."
        )
        status="NO_RELIABLE_COMPARABLE_INDEX_LEADS"
    return {
        "status":status,"selected_title":_text(title,175),
        "category":cat,
        "selected_price_verified":False,
        "selected_price_available_in_seller_page":False,
        "pricing_basis":"UNVERIFIED_SEARCH_INDEX_ONLY",
        "market_reference":(_money(anchor,selected_currency)
                            if anchor is not None else None),
        "market_reference_provenance":("PEER_MEDIAN_SEARCH_INDEX_NOT_SELLER"
                                       if anchor is not None else "NO_PEER_ANCHOR"),
        "headline":message,
        "options":top,
        "tradeoffs":extra,
        "suspicious_price_quotes":anomalies[:8],
        "comparable_count":len(strong_options),
        "tradeoff_count":len(tradeoffs),
        "total_offers_seen":len(offers),
        "disclaimer":"Indeksowe ceny i tytuły nie potwierdzają dostępności, wysyłki, wariantu ani zakupu.",
        "payment_authorized":False,
    }
