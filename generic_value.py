"""Conservative cross-category normalized value leads for measured goods.

Supports detergent/food/paint/cosmetic and other pack-based products without
requiring a category-specific LLM prompt. Uses only explicit indexed titles,
unit quantities and prices. Different variants and missing quantities cannot
be promoted to equivalent offers or advertised savings.
"""
from decimal import Decimal
import re
from title_facts import title_facts,unit_price,primary_quantity

STOP=frozenset(("do","dla","i","a","the","for","of","and","in","with",
"proszek","prania","pran","kolorowych","koloru","tkanin","ubrań","ubran",
"zestaw","xxxl","xxl","kg","ml","g","l","prań","pran","washes",
"wash","powder","washing","pack","bundle","pcs","pieces","szt",
"color","colour","kolor","white","bialych","białych",
"universal","uniwersalny","one","new","nowy","spray","lotion",
"shampoo","szampon","soap","mydlo","mydło"))


def tokens(title):
    raw=re.findall(r"[a-z0-9]+",str(title or "").casefold())
    return {word for word in raw if word not in STOP and
            not word.isdigit() and len(word)>=3 and not re.match(
                r"\d+(?:kg|ml|l|g)$",word)}


def _price(value):
    try:
        d=Decimal(str(value).replace(" ","").replace(",","."))
        return d if d.is_finite() and d>0 else None
    except Exception:return None


def generic_unit_value(projection):
    offers=projection.get("offers") or []
    selected=offers[0] if offers else {}
    base=selected.get("title") or projection.get("title") or ""
    category=projection.get("category") or "UNKNOWN"
    base_facts=title_facts(base,category)
    base_variant=next((f["value"] for f in base_facts
                       if f["key"]=="variant"),None)
    base_tokens=tokens(base)
    selected_price=projection.get("input_price") or {}
    peers=[]
    uncertain=[]
    invalid_variants=[]
    for offer in offers[1:]:
        if not isinstance(offer,dict):continue
        title=offer.get("title") or ""
        overlap=base_tokens & tokens(title)
        if len(overlap)<2:
            continue
        facts=title_facts(title,category)
        variant=next((f["value"] for f in facts if f["key"]=="variant"),None)
        price=offer.get("indexed_price")
        currency=offer.get("currency")
        quote=unit_price(price,currency,facts)
        if not quote:
            continue
        row={
            "offer_id":offer.get("id"),
            "title":title[:170],
            "price":str(price),
            "currency":currency,
            "source_url":offer.get("url"),
            "unit_quote":quote,
            "unit_comparison_label":quote["amount"]+" "+currency+
                                    "/"+quote["per"],
            "matched_features":[f["label"] for f in facts
                                if f["key"] in ("quantity_kg","quantity_L",
                                                "wash_count","count","bundle",
                                                "variant")][:5],
            "different_features":[],
            "unconfirmed_features":[],
            "price_source":"SEARCH_INDEX_QUOTE_NOT_CHECKOUT",
            "identity_verified":False,"checkout_verified":False,
            "value_status":"INDEXED_UNIT_RATE_REQUIRES_CONFIRMATION",
            "has_direct_url":bool(offer.get("url")),
            "variant":variant,
            "tier":"EXPLICIT_TITLE_UNIT_COMPARISON",
            "vs_index_median":"Unverified indexed unit quote; compare unit and pack size.",
        }
        if base_variant and variant and variant!=base_variant:
            row["different_features"]=[
                "Input variant: "+base_variant+"; listing: "+variant]
            invalid_variants.append(row)
            continue
        if base_variant and variant is None:
            row["unconfirmed_features"]=[
                "The listing does not state the "+base_variant+" variant."]
            uncertain.append(row)
            continue
        peers.append(row)
    # Only compare within the same currency *and same physical unit*.
    # An advertised washing-cycle count is never presumed from powder mass.
    by_unit={}
    for row in peers:
        key=(row["currency"],row["unit_quote"]["per"])
        by_unit.setdefault(key,[]).append(row)
    group=max(by_unit.values(),key=lambda arr:len(arr),default=[])
    group.sort(key=lambda o:(_price(o["unit_quote"]["amount"]) or Decimal("999999"),
                             _price(o["price"]) or Decimal("999999"),
                             o["offer_id"]))
    unit_label=(group[0]["unit_quote"]["per"] if group else None)
    if group:
        best=group[0]
        summary=(
            "Comparable indexed pack leads: "+best["title"]+
            " at "+best["price"]+" "+best["currency"]+
            " total, equivalent to "+best["unit_comparison_label"]+
            " calculated from an advertised quantity. "
            "A larger bundle may cost more in total while costing less per unit. "
            "The input retailer's observed price and package quantity must both "
            "be known before any saving against the selected product can be claimed."
        )
        status="UNIT_PRICE_LEADS_NOT_CHECKOUT"
    elif uncertain:
        status="VARIANT_NOT_CONFIRMED"
        summary=("Listings with measurable quantities were found, but their exact "
                 "product variant is not stated; do not assume equivalence.")
    else:
        status="NO_COMPARABLE_MEASURABLE_PACKS"
        summary=("No safely comparable unit-price leads were found in the "
                 "available indexed listing titles.")
    return {
        "status":status,
        "selected_title":base[:175],
        "category":category,
        "pricing_basis":"INDEXED_NORMALIZED_UNIT_RATE_NOT_CHECKOUT",
        "selected_price":selected_price.get("price"),
        "selected_price_source":selected_price.get("origin") or "NOT_AVAILABLE",
        "selected_price_verified":False,
        "selected_price_available_in_seller_page":False,
        "market_reference":None,
        "market_reference_provenance":"INDEXED_UNIT_RATE_NOT_SELECTED_SELLER",
        "unit_basis":unit_label,
        "headline":summary,
        "options":group[:6],
        "tradeoffs":uncertain[:3],
        "higher_priced_comparables":[],
        "different_variant_listings":invalid_variants[:5],
        "suspicious_price_quotes":[],
        "comparable_count":len(group),
        "tradeoff_count":len(uncertain)+len(invalid_variants),
        "total_offers_seen":len(offers),
        "disclaimer":(
            "All prices are from a search index. Pack quantity, product variant, "
            "stock and final delivered price remain unverified; this is not "
            "evidence of a safe or lowest-priced merchant."
        ),
        "payment_authorized":False,
    }
