"""Bounded execution of high-value source checks, distinct from planning.

Fetches ONLY independently reviewed, exact family-scoped documentary URLs
known to the source registry; robots.txt + pinned public-IP TLS, no redirects,
no search API fees. Findings require actual HTML markers + page hash.
They are NOT proof of the SKU on a seller page or verified checkout prices.
"""
from datetime import datetime, timezone
from hashlib import sha256
from html import unescape
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
import re

from autonomous_research import ARM_REVIEW
from product_intake import _read, USER_AGENT, validate_product_url

MAX_SOURCE_BYTES = 2500000
MAX_ROBOTS_BYTES = 80000
REVIEW_SOURCES = {
    "15Q8X10": {
        "url": ARM_REVIEW,
        "publisher": "Notebookcheck",
        "model": "15Q8X10",
        "variant": "15.3-inch IPS; battery configuration must not be inferred from any seller listing",
        "method": "Notebookcheck WiFi Websurfing (Edge 138) and Cinebench 2024 CPU Multi Core",
    },
}
# Higher-impact checks first. Unavailable exact SKU and unverified seller price
# remain top-priority unanswered tasks, not grounds for a recommendation.
TRIAGE = (
    {"dimension":"exact OEM machine type and SKU","probe":"oem",
     "importance":100,"why":"Variant mismatch invalidates performance comparison"},
    {"dimension":"measured battery life under comparable workload","probe":"lab",
     "importance":96,"why":"Battery tests require the same panel and battery"},
    {"dimension":"CPU sustained performance","probe":"lab",
     "importance":90,"why":"Hardware architecture and tested processor differ"},
    {"dimension":"actual seller price and installment exclusions","probe":"retailer",
     "importance":89,"why":"Index quotes are not checkout totals"},
    {"dimension":"screen panel identity and gamut","probe":"variant",
     "importance":86,"why":"OLED and IPS cannot inherit each other's results"},
)


def model_family(title):
    """Never infer a model ID from a brand or generic 'Slim 3' title."""
    found = re.findall(r"(?<![a-z0-9])(?:15q8x10|16iph11|15irh10r)(?![a-z0-9])",
                       str(title or "").casefold())
    return found[0].upper() if len(set(found)) == 1 else None


def _robot_checked_read(url, fetch=None, mimes=None):
    """Robot policy must be obtainable and permissive, never default-allow."""
    validate_product_url(url)
    host = urlsplit(url).hostname
    getter = fetch or _read
    robots_url = "https://" + host + "/robots.txt"
    rules = getter(robots_url, MAX_ROBOTS_BYTES, ("text/plain", "text/html"), timeout=9)
    rp = RobotFileParser()
    rp.parse(rules.decode("utf-8", "replace").splitlines())
    if not rp.can_fetch(USER_AGENT, url):
        raise ValueError("ROBOTS_DISALLOW")
    return getter(url, MAX_SOURCE_BYTES,
                  mimes or ("text/html", "application/xhtml+xml"),timeout=10)


def _parse_review(raw, source):
    """All values below must appear in independently fetched HTML (not a stored snippet)."""
    if type(raw) is not bytes or len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("INVALID_SOURCE_BODY")
    text=raw.decode("utf-8","replace")
    model=source["model"]
    # The entire page can list 'similar' products. The exact reviewed model
    # must occur in the article's own header, not only in a sidebar/footer.
    header=unescape(re.sub(r"<[^>]*>", " ",text[:12000]))
    if not re.search(r"(?<![A-Za-z0-9])"+model+r"(?![A-Za-z0-9])",header,re.I):
        raise ValueError("REVIEW_IDENTITY_NOT_IN_HEADER")
    if model=="15Q8X10" and not re.search(r"IPS display",text,re.I):
        raise ValueError("REVIEWED_PANEL_NOT_CONFIRMED")
    result=[]
    multi=re.findall(
        r"Cinebench 2024 CPU Multi Core</div>\s*"
        r"<div class=[\"']cb_bench_value[\"']>\s*([0-9]{2,5}) Points",text,re.I)
    if len(set(multi))==1 and multi:
        result.append({
            "dimension":"CPU sustained performance","probe":"lab",
            "value":"{} points".format(multi[0]),
            "finding":"Cinebench 2024 CPU Multi Core: {} points (published independent review of its tested configuration).".format(multi[0]),
            "method":"Cinebench 2024 CPU Multi Core",
            "reviewed_model":model,
        })
    # Do not pick the largest figure on the page, which contains charts for
    # other laptops. Require Websurfing caption in the immediately preceding
    # row of the test machine's own runtime table.
    matches=re.findall(
        r'<td class="caption">\s*WiFi Websurfing \(Edge 138\)\s*</td>'
        r'(?:(?!</tr>).){0,16000}?<td class="runtime">'
        r'\s*<span[^>]*>\s*([0-9]{1,2})h(?:&nbsp;|\s)*([0-9]{1,2})min',
        text,re.I|re.S)
    if len(set(matches))==1 and matches:
        hh,mm=matches[0]
        if 0<=int(hh)<=72 and 0<=int(mm)<60:
            result.append({
                "dimension":"measured battery life under comparable workload",
                "probe":"lab",
                "value":"{:02d}h{:02d}m".format(int(hh),int(mm)),
                "finding":"Notebookcheck WiFi Websurfing (Edge 138): {} h {} min, measured on the reviewed configuration, NOT an unconfirmed seller panel/battery.".format(int(hh),int(mm)),
                "method":"WiFi Websurfing (Edge 138)",
                "reviewed_model":model,
            })
    if not result:
        raise ValueError("NO_VERIFIABLE_REVIEW_MEASUREMENTS")
    return result


def execute_reference_checks(offer, category, fetch=None):
    """Execute at most one permitted source per supported model family.

    The returned entries are REFERENCE_ONLY, never exact-SKU performance
    results or automatic purchasing recommendations.
    """
    model=model_family(offer.get("title"))
    # General-purpose page research runs before category-specific fallbacks.
    # Known independently instrumented laptop review remains the preferred
    # source for its EXACT reviewed family (the prior adapter is preserved).
    if not (category=="LAPTOP" and model in REVIEW_SOURCES):
        from generic_source_research import execute_generic_sources
        general=execute_generic_sources(offer,category,fetch=fetch)
        if general["reference_answers"]:
            return general
    else:
        general={"attempted_sources":[]}
    if category=="E_BIKE":
        from ebike_research import offer_title_diagnostics
        # Never pretend the URL-derived title, indexed price or a similarly
        # named alternative has established the precise e-bike variant.
        diagnostic=offer_title_diagnostics(offer)
        return {
            "status":"NO_MATCHED_INDEPENDENT_EBIKE_REVIEW",
            "model_family":None,"sources_checked":0,
            "reference_answers":[],"verified_for_exact_offer":0,
            "listing_diagnostics":diagnostic,
            "attempted_sources":general.get("attempted_sources",[]),
            "pending_high_impact":[
                "Exact OEM brand, model, and frame variant",
                "Battery nominal voltage, manufacturer, Wh and BMS",
                "Measured assistance-only range, rider mass and terrain",
                "Motor rated continuous power, cutoff and throttle behavior",
                "Brakes, warranty, spare parts, real current seller price",
            ],
        }
    if category!="LAPTOP" or model not in REVIEW_SOURCES:
        return {"status":"NO_MATCHED_INDEPENDENT_SOURCE",
                "model_family":model,"sources_checked":0,
                "reference_answers":[],"verified_for_exact_offer":0,
                "pending_high_impact":[x["dimension"] for x in TRIAGE]}
    source=REVIEW_SOURCES[model]
    listing_title=str(offer.get("title") or "").casefold()
    if "oled" in listing_title and "ips" not in listing_title:
        variant_match="MISMATCH_LISTED_OLED_REVIEWED_IPS"
    elif "ips" in listing_title and "oled" not in listing_title:
        variant_match="IPS_PANEL_FAMILY_ONLY_EXACT_MTM_UNKNOWN"
    elif "oled" in listing_title and "ips" in listing_title:
        variant_match="AMBIGUOUS_LISTING_MENTIONS_BOTH_PANEL_TYPES"
    else:
        variant_match="LISTED_PANEL_UNCONFIRMED"
    try:
        raw=_robot_checked_read(source["url"],fetch=fetch)
        findings=_parse_review(raw,source)
        timestamp=datetime.now(timezone.utc).isoformat()
        digest=sha256(raw).hexdigest()
        answer_rows=[]
        from offer_question_bank import AXES,PROBES
        for finding in findings:
            dimension=AXES[category].index(finding["dimension"])
            probe=[x[0] for x in PROBES].index(finding["probe"])
            qid=offer["id"]+"-"+str(dimension*len(PROBES)+probe+1)
            answer_rows.append({
                "question_id":qid,
                "dimension":finding["dimension"],
                 "status":"REFERENCE_EVIDENCE_ONLY_EXACT_SKU_UNVERIFIED",
                "finding":finding["finding"],
                "value":finding["value"],
                "source_url":source["url"],
                "publisher":source["publisher"],
                "source_kind":"INDEPENDENT_TEST",
                "source_method":finding["method"],
                "source_sha256":digest,
                "retrieved_at":timestamp,
                "reviewed_model":model,
                "reviewed_variant":source["variant"],
                "variant_match":variant_match,
                "verified_for_exact_offer":False,
                "requires_exact_MTM_panel_battery_match":True,
            })
        return {
            "status":"INDEPENDENT_REFERENCE_FETCHED_VARIANT_UNVERIFIED",
            "model_family":model,"sources_checked":1,
            "variant_match":variant_match,
            "reference_answers":answer_rows,
            "verified_for_exact_offer":0,
            "pending_high_impact":[x["dimension"] for x in TRIAGE],
            "source_url":source["url"],
            "source_sha256":digest,"retrieved_at":timestamp,
        }
    except (OSError,ValueError,TypeError,KeyError) as exc:
        return {
            "status":"SOURCE_NOT_VERIFIED_"+type(exc).__name__,
            "model_family":model,"sources_checked":0,
            "reference_answers":[],"verified_for_exact_offer":0,
            "pending_high_impact":[x["dimension"] for x in TRIAGE],
            # Do not return untrusted exception text or arbitrary response.
        }
