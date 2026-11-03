"""Product-agnostic title facts for readable offer/value graphs.

Conservative declared-title extraction only. Values are NOT seller-verified,
and do not establish SKU identity. Works for mass/volume/count goods,
electronics, tools, groceries, cosmetics and arbitrary catalog titles.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

MAX_FACTS=8
NUM=r"(?<![A-Za-z0-9])([1-9]\d{0,3}(?:[.,]\d{1,3})?)"


def _number(raw):
    try:
        value=Decimal(str(raw).replace(",","."))
    except (InvalidOperation,TypeError,ValueError):
        return None
    return value if value.is_finite() and value>0 else None


def _show(value):
    return format(value.normalize(),"f")


def title_facts(title, category=None):
    """Extract explicit pack/size/quantity facts with no external requests."""
    s=str(title or "")[:240].casefold().replace("\u00a0"," ").replace("\u202f"," ")
    facts=[]
    bundle=1
    prefix=re.search(r"(?:^|\s)([2-9])\s*[x×]\s*(?=[a-ząćęłńóśźż])",s)
    explicit=re.search(r"(?:^|\s)([2-9])\s*[x×]\s*(?=\d)",s)
    if explicit:bundle=int(explicit.group(1))
    elif prefix:bundle=int(prefix.group(1))
    unit_pattern=re.compile(
        r"(?<![a-z0-9])(?:[2-9]\s*[x×]\s*)?([1-9]\d{0,3}(?:[.,]\d{1,3})?)"
        r"\s*(kg|g|ml|l)\b")
    units=[]
    for match in unit_pattern.finditer(s):
        # Slug "8 45 kg" is not a trustworthy decimal measurement;
        # do not incorrectly transform it into a 45 kg pack.
        if re.search(r"\b\d{1,2}\s+$",s[:match.start()]):
            continue
        num=_number(match.group(1))
        if num is None:continue
        u=match.group(2)
        if u=="g":amount=num/Decimal("1000");base="kg"
        elif u=="ml":amount=num/Decimal("1000");base="L"
        elif u=="l":amount=num;base="L"
        else:amount=num;base="kg"
        if amount>Decimal("10000"):continue
        units.append((match.start(),amount,base))
    # Only one unambiguous physical pack size becomes the price unit.
    measures={(str(a),b) for _,a,b in units}
    if len(measures)==1:
        amount,unit=units[0][1:]
        total=amount*bundle
        facts.append({"key":"quantity_"+unit,"value":_show(total),
                      "label":_show(total)+" "+unit,
                      "origin":"TITLE_ONLY",
                      "unit":unit,
                      "unit_amount":str(total),
                      "bundle_multiplier":bundle})
    if bundle>1:
        facts.append({"key":"bundle","value":str(bundle),
                      "label":"Pack ×"+str(bundle),"origin":"TITLE_ONLY"})
    # Washes are meaningful only when explicitly stated, never inferred
    # from mass; 8.45 kg powder may or may not yield 130 cycles.
    wash=re.search(NUM+r"\s*(?:prań|pran|washes|wash(?:ing)?\s*loads|pr)\b",s)
    if wash:
        qty=_number(wash.group(1))
        if qty and qty<=10000:
            facts.append({"key":"wash_count","value":_show(qty),
                          "label":_show(qty)+" washes (claimed)",
                          "origin":"TITLE_ONLY","unit":"wash",
                          "unit_amount":str(qty)})
    count=re.search(NUM+r"\s*(?:szt\.?|pcs\.?|pieces|tablets|capsules|caps)\b",s)
    if count:
        qty=_number(count.group(1))
        if qty and qty<=20000:
            facts.append({"key":"count","value":_show(qty),
                          "label":_show(qty)+" pieces (claimed)",
                          "origin":"TITLE_ONLY","unit":"piece",
                          "unit_amount":str(qty)})
    detergent=bool(re.search(
        r"\b(?:proszek\s+do\s+prania|laundry|washing\s+powder|"
        r"detergent|capsules\s+for\s+laundry)\b",s))
    # Functional variants matter across detergents, paint, cosmetics and
    # other product families. Do not silently equate WHITE and COLOR labels.
    if detergent or re.search(r"\b(?:white|color|colour|kolor)\b",s):
        if re.search(r"\b(?:color|colour|kolor|kolorowych|koloru)\b",s):
            variant="COLOR"
        elif re.search(r"\b(?:white|białych|bialych)\b",s):
            variant="WHITE"
        elif re.search(r"\b(?:universal|uniwersalny)\b",s):
            variant="UNIVERSAL"
        else:variant=None
        if variant:
            facts.append({"key":"variant","value":variant,
                          "label":variant.title()+" variant (claimed)",
                          "origin":"TITLE_ONLY"})
    # Generic laptop and tool attributes still come from the same shared
    # parser, not from bespoke visual graph logic.
    if category and category not in ("UNKNOWN","ACCESSORY"):
        from similar_tier import read_specs, PUBLIC_SPEC_NAMES
        for key,value in read_specs(title,category).items():
            label=PUBLIC_SPEC_NAMES.get(key,key.replace("_"," ").capitalize())
            facts.append({"key":"spec_"+key,"value":str(value),
                          "label":str(label)+": "+str(value),
                          "origin":"TITLE_ONLY"})
    # Generic physical specifications for otherwise unclassified goods.
    # Not a laptop-specific model: usable for appliances, pumps, tools,
    # lamps, electronic accessories, furniture and household equipment.
    if category in (None,"UNKNOWN","OTHER","ACCESSORY"):
        for key,unit,label in (
            ("power_w","w","Power"),("voltage_v","v","Voltage"),
            ("pressure_bar","bar","Pressure"),
            ("refresh_hz","hz","Frequency"),
            ("length_cm","cm","Dimension"),
            ("length_mm","mm","Dimension"),
        ):
            match=re.search(NUM+r"\s*"+unit+r"\b",s)
            if not match:continue
            raw=_number(match.group(1))
            if raw is None or raw>Decimal("1000000"):continue
            facts.append({"key":key,"value":_show(raw),
                          "label":label+": "+_show(raw)+" "+unit,
                          "origin":"TITLE_ONLY"})
    seen=set()
    unique=[]
    for fact in facts:
        if fact["key"] in seen:continue
        seen.add(fact["key"])
        unique.append(fact)
    return unique[:MAX_FACTS]


def primary_quantity(facts):
    lookup={f["key"]:f for f in facts}
    for key in ("quantity_kg","quantity_L","wash_count","count"):
        if key in lookup:return lookup[key]
    return None


def unit_price(indexed_price,currency,facts):
    """Price normalization solely from *indexed* price and title-declared qty."""
    try:
        price=_number(str(indexed_price).strip().replace(" ",""))
    except (ValueError,TypeError):
        price=None
    quantity=primary_quantity(facts)
    if (price is None or not quantity or
        currency not in ("PLN","USD","EUR")):
        return None
    value=_number(quantity.get("unit_amount"))
    if value is None:return None
    return {
        "amount":str((price/value).quantize(
            Decimal("0.01"),rounding=ROUND_HALF_UP)),
        "currency":currency,"per":quantity["unit"],
        "source":"INDEX_PRICE_DIVIDED_BY_TITLE_CLAIM_NOT_CHECKOUT",
    }
