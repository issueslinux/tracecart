"""Deterministic SHT40 merchant-vs-component-manufacturer specification check.

Only two fixed, publicly accessible pages are read:
 * Adafruit breakout board Product 4885
 * Sensirion component SHT40

Comparing documents from two different publishers does NOT establish physical
test accuracy, board quality or genuinely independent laboratory validation.
"""
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlsplit
from urllib.request import Request, build_opener
from urllib.robotparser import RobotFileParser

from decision_tree import analyze
from source_collector import (ProductCollector, USER_AGENT, _NoRedirect,
                              _download, _public_addresses,
                              attach_collection_provenance)

MERCHANT_URL = "https://www.adafruit.com/product/4885"
OEM_URL = "https://sensirion.com/products/catalog/SHT40"
METRICS = (
    ("typical_humidity_accuracy", "typical relative humidity accuracy", "%RH"),
    ("typical_temperature_accuracy", "typical temperature accuracy", "°C"),
)


class VisibleText(HTMLParser):
    """Only HTML visible text. Do NOT mistake script hydration for documentation."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.segments = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ("script", "style", "noscript", "template"):
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in ("script", "style", "noscript", "template"):
            self.skip_depth = max(self.skip_depth - 1, 0)

    def handle_data(self, data):
        if not self.skip_depth:
            value = " ".join(data.split())
            if value:
                self.segments.append(value)


def parse_oem_specs(html):
    p = VisibleText()
    p.feed(html)
    if "SHT40" not in p.segments:
        raise ValueError("Manufacturer page must identify exact SHT40 model")
    labels = {
        "typical_humidity_accuracy": "Typ. relative humidity accuracy",
        "typical_temperature_accuracy": "Typ. temperature accuracy",
    }
    values = {}
    for key, label in labels.items():
        indexes = [i for i, v in enumerate(p.segments) if v == label]
        if len(indexes) != 1:
            raise ValueError("Missing or duplicate OEM specification label: " + label)
        idx = indexes[0]
        if idx + 2 >= len(p.segments):
            raise ValueError("Truncated OEM specification")
        raw = p.segments[idx + 1]
        unit = p.segments[idx + 2]
        expected_unit = "%RH" if "humidity" in key else "°C"
        if not re.fullmatch(r"[0-9]{1,2}(?:\.[0-9]{1,3})?", raw) or unit != expected_unit:
            raise ValueError("Unrecognized OEM spec value/unit")
        values[key] = (str(Decimal(raw)), raw + " " + unit)
    return values


def parse_merchant_specs(html):
    p = VisibleText()
    p.feed(html)
    if not any("SHT40 Specifications" in x for x in p.segments):
        raise ValueError("Merchant must label explicit SHT40 specs")
    labels = {
        "typical_humidity_accuracy": (
            r"Relative humidity accuracy: up to [±+/-]*\s*([0-9]+(?:\.[0-9]+)?)\s*%RH",
            "%RH"),
        "typical_temperature_accuracy": (
            r"Temperature accuracy: up to [±+/-]*\s*([0-9]+(?:\.[0-9]+)?)\s*°C",
            "°C"),
    }
    result = {}
    for key, (pattern, unit) in labels.items():
        candidates = []
        for text in p.segments:
            m = re.fullmatch(pattern, text, flags=re.IGNORECASE)
            if m:
                candidates.append((str(Decimal(m.group(1))), text))
        if len(candidates) != 1:
            raise ValueError("Expected one unambiguous merchant metric " + key)
        result[key] = candidates[0]
    return result


def _check_robots(domain, url, download_robots=None):
    robot_url = "https://" + domain + "/robots.txt"
    if download_robots:
        raw = download_robots(robot_url)
    else:
        _public_addresses(domain)
        with build_opener(_NoRedirect()).open(
                Request(robot_url, headers={"User-Agent": USER_AGENT}), timeout=12) as r:
            if r.status != 200:
                raise ValueError("robots.txt unavailable")
            raw = r.read(50001)
    if len(raw) > 50000:
        raise ValueError("robots.txt unexpectedly large")
    rules = RobotFileParser()
    rules.parse(raw.decode("utf-8", "replace").splitlines())
    if not rules.can_fetch(USER_AGENT, url):
        raise ValueError("Access disallowed by robots.txt: " + domain)
    return raw.decode("utf-8", "replace")


def collect_spec_crosscheck(fetch_html=None, download_robots=None):
    """Fetch and compare two *documents*, NOT live measurements or reviews.

    The URLs are constants: user/model cannot redirect this module to a host.
    Optional test fixtures replace transport only, never security policy.
    """
    robots = {}
    for site, url in (("www.adafruit.com", MERCHANT_URL),
                      ("sensirion.com", OEM_URL)):
        robots[site] = _check_robots(site, url, download_robots)
    fetch_html = fetch_html or (lambda url: _download(url, max_bytes=850000))
    records = {}
    for key, url in (("merchant", MERCHANT_URL), ("oem", OEM_URL)):
        raw, html = fetch_html(url)
        if not isinstance(raw, bytes) or not isinstance(html, str):
            raise ValueError("Invalid source payload")
        if len(raw) > 850000:
            raise ValueError("Source page too large")
        records[key] = {
            "url": url, "html": html, "raw": raw,
            "sha256": sha256(raw).hexdigest(),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
    merchant = parse_merchant_specs(records["merchant"]["html"])
    manufacturer = parse_oem_specs(records["oem"]["html"])
    questions = []
    comparison = []
    for criterion, label, unit in METRICS:
        left, raw_left = merchant[criterion]
        right, raw_right = manufacturer[criterion]
        agreement = (Decimal(left) == Decimal(right))
        comparison.append({
            "metric": criterion, "unit": unit,
            "merchant_value": left, "manufacturer_value": right,
            "documents_agree": agreement,
            "scope": "SHT40 sensor chip, NOT measured breakout-board performance",
        })
        evidence = []
        for index, (side, value, excerpt) in enumerate((
                ("merchant", left, raw_left), ("oem", right, raw_right))):
            row = records[side]
            evidence.append({
                "id": "sht40_{}_{}".format(criterion, side),
                "stance": "supports" if agreement or side == "merchant" else "contradicts",
                "url": row["url"], "source_type": "listing" if side == "merchant" else "manufacturer",
                "excerpt": (
                    ("Merchant documented: " if side == "merchant" else
                     "Component manufacturer documented: ") + excerpt),
                "observation": "Published nominal spec; not independent measurement",
                "retrieved_at": row["retrieved_at"],
                "sha256": row["sha256"],
                "extraction_method": "visible_text_exact_label_" + side,
            })
        questions.append({
            "id": criterion, "text": "Do merchant and manufacturer documents agree on SHT40 "
            + label + " (" + unit + ")?",
            "importance": 4, "evidence": evidence,
        })
    # Avoid treating sensor chip supply voltage as identical to the breakout
    # board operating voltage (onboard regulator changes board requirements).
    proposals = [{
        "trigger_question_id": "product_4885-typical_humidity_accuracy",
        "text": "Has an independent laboratory measured the assembled board's accuracy?",
        "origin": "external_question_proposal",
    }, {
        "trigger_question_id": "product_4885-typical_temperature_accuracy",
        "text": "Is the assembled breakout board accuracy affected by self-heating?",
        "origin": "external_question_proposal",
    }]
    # Use the REAL current seller Product JSON-LD offer for price, stock and
    # condition; the OEM page is documentation, not a competing seller offer.
    merchant_collection = ProductCollector(
        download=lambda url: (records["merchant"]["raw"], records["merchant"]["html"]),
        robots_text=robots["www.adafruit.com"]).collect(
            [MERCHANT_URL], category="electronics humidity sensor",
            goal="Compare Adafruit SHT40 board listing against OEM chip specifications")
    offer = merchant_collection["offers"][0]
    offer["questions"].extend(questions)
    source_data = {
        "goal": merchant_collection["goal"],
        "category": merchant_collection["category"],
        "offers": merchant_collection["offers"],
        "generated_questions": proposals,
    }
    report = analyze(source_data)
    source_details = {
        side: {"url": row["url"], "sha256": row["sha256"],
               "retrieved_at": row["retrieved_at"]}
        for side, row in records.items()
    }
    report["source_collection"] = {
        "collector": "merchant_vs_sensirion_sht40_visible_html",
        "fetched_pages": 2, "requested_pages": 2,
        "source_failures": [], "review_sources_collected": 0,
        "independent_product_tests_collected": 0,
        "retrieval_policy": "two fixed HTTPS URLs; robots checked; no redirects; bounded payload",
        "source_documents": source_details,
        "source_scope": "Retailer breakout board vs OEM chip nominal specs, not laboratory measurements",
        "current_merchant_listing": {
            "price_usd": offer["price"],
            "availability": next(
                (q["evidence"][0]["excerpt"] for q in offer["questions"]
                 if q["id"] == "availability"), "unknown"),
        },
    }
    report["crosscheck"] = comparison
    report["provenance"] = "Two distinct publishers of specifications; no external reviews or measurements"
    report.pop("sha256", None)
    report["sha256"] = sha256(json.dumps(
        report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return report, source_data
