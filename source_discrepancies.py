"""Auditable discrepancies across listing titles and source documents.

All comparisons are explicitly potential. Matching numbers are corroborating
*published claims*, not verified performance, identical SKU or lab evidence.
Reject ambiguous units/modes, comparisons without a strong model identity,
and differences within rounded marketing label tolerance.
"""
import re
from urllib.parse import urlsplit

from similar_tier import read_specs

MAX_DIFFERENCES=12
MIN_RELATIVE_DIFFERENCE=.075

def _numbers(value):
    # 50–85 km, 15.3, 100 and 15Ah; numbers are never treated as facts
    # unless a known property assigns dimensions and units.
    normalized=str(value or "").replace(",",".").replace("–","-").replace("−","-")
    return [float(s) for s in re.findall(r"(?<![a-z0-9])\d+(?:\.\d+)?",normalized.casefold())[:3]]

def source_attribute(row,category):
    key=str(row.get("source_property") or "").casefold()
    value=str(row.get("value") or "")
    numbers=_numbers(value)
    if not numbers:
        return None
    if category=="E_BIKE":
        if "range" in key or "zasięg" in key:
            if any(s in key for s in ("pure electric","throttle","only")):
                return None
            if "assist" not in key and "pedal" not in key:
                return None
            if len(numbers)>=2:
                return ("claimed_range_km",min(numbers[0],numbers[1]),
                        max(numbers[0],numbers[1]),"km")
            return ("claimed_range_km",numbers[0],numbers[0],"km")
        if any(x in key for x in ("rated power","motor power","motor rated")):
            return ("power_w",numbers[0],numbers[0],"W")
        if "battery" in key and ("capacity" in key or "nominal" in key):
            ah=re.search(r"(\d+(?:[.,]\d+)?)\s*ah\b",value,re.I)
            if ah:return ("battery_ah",float(ah.group(1).replace(",",".")),
                          float(ah.group(1).replace(",",".")),"Ah")
    if category=="LAPTOP" and any(x in key for x in ("ram","installed memory","system memory")):
        if re.search(r"\bgb\b",value,re.I):
            return ("ram_gb",numbers[0],numbers[0],"GB")
    if category in ("LAPTOP","SSD","SMARTPHONE"):
        if any(x in key for x in ("storage","ssd capacity","storage capacity","internal memory")):
            if re.search(r"\btb\b",value,re.I):
                number=numbers[0]*1000
            elif re.search(r"\bgb\b",value,re.I):
                number=numbers[0]
            else:
                return None
            return ("capacity_gb",number,number,"GB")
    if category=="COMPRESSOR":
        if any(x in key for x in ("max pressure","pressure")) and (
                "bar" in key or "bar" in value.casefold()):
            return ("pressure_bar",numbers[0],numbers[0],"bar")
        if "tank" in key and ("l" in value.casefold()):
            return ("tank_l",numbers[0],numbers[0],"L")
    return None

def _different(a,b):
    # The two tuples are parameter, low, high, unit.
    if a[0]!=b[0] or a[3]!=b[3]:
        return False
    if a[1]<=b[2] and b[1]<=a[2]:
        return False
    gap=(b[1]-a[2] if a[2]<b[1] else a[1]-b[2])
    pivot=max(1.0,abs(a[2]),abs(b[2]))
    return gap/pivot>MIN_RELATIVE_DIFFERENCE

def _title_attribute(specs,name):
    value=specs.get(name)
    if not isinstance(value,(int,float)) or isinstance(value,bool):
        return None
    return (name,float(value),float(value),
            {"claimed_range_km":"km","power_w":"W","battery_ah":"Ah",
             "ram_gb":"GB","capacity_gb":"GB","pressure_bar":"bar",
             "tank_l":"L"}.get(name,""))

def find_source_discrepancies(offer,category,rows):
    """Flag variant/condition questions, never a proved seller falsehood."""
    specs=read_specs(offer.get("title",""),category)
    parsed=[]
    for row in rows[:32]:
        if not isinstance(row,dict):
            continue
        normalized=source_attribute(row,category)
        if not normalized:
            continue
        url=row.get("source_url")
        digest=row.get("source_sha256")
        if not isinstance(url,str) or not isinstance(digest,str):
            continue
        parsed.append((normalized,row))
    results=[]
    seen=set()
    for found,row in parsed:
        claim=_title_attribute(specs,found[0])
        if not claim or not _different(claim,found):
            continue
        key=("TITLE_SOURCE",found[0],row["source_url"])
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "type":"TITLE_VS_PUBLISHED_SPECIFICATION",
            "parameter":found[0],
            "listing_value":"{} {}".format(specs[found[0]],found[3]),
            "source_value":row.get("value"),
            "source_property":row.get("source_property"),
            "source_url":row["source_url"],
            "source_sha256":row["source_sha256"],
            "status":"POTENTIAL_DIFFERENT_VARIANT_OR_TEST_CONDITIONS",
            "not_fraud_or_exact_sku_proof":True,
        })
        if len(results)>=MAX_DIFFERENCES:
            return results
    for i,(a,row_a) in enumerate(parsed):
        for b,row_b in parsed[i+1:]:
            if row_a["source_sha256"]==row_b["source_sha256"]:
                continue
            if not _different(a,b):
                continue
            host_a=urlsplit(row_a["source_url"]).hostname
            host_b=urlsplit(row_b["source_url"]).hostname
            if host_a==host_b:
                continue
            key=("PUBLISHED_SOURCE_MISMATCH",a[0],
                 tuple(sorted((row_a["source_sha256"],row_b["source_sha256"]))))
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "type":"PUBLISHED_SOURCES_DISAGREE",
                "parameter":a[0],
                "source_a_value":row_a.get("value"),
                "source_b_value":row_b.get("value"),
                "source_a_url":row_a["source_url"],
                "source_b_url":row_b["source_url"],
                "source_a_sha256":row_a["source_sha256"],
                "source_b_sha256":row_b["source_sha256"],
                "status":"UNRESOLVED_PUBLISHED_CLAIM_DISAGREEMENT",
                "not_fraud_or_exact_sku_proof":True,
            })
            if len(results)>=MAX_DIFFERENCES:
                return results
    return results
