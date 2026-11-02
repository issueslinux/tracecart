"""Functional alternatives from shopping-index titles; NOT product identity or quality proof.

Source evidence is strictly index-only. A different model/brand may be a useful
alternative if the product category and relevant specifications are comparable.
Missing technical information is UNKNOWN, not a matching specification.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from statistics import median
import re
import unicodedata

CATEGORY_LABELS = {
    "E_BIKE": "rower elektryczny", "BICYCLE": "rower bez potwierdzonego napędu",
    "E_SCOOTER": "hulajnoga elektryczna", "SSD": "dysk SSD",
    "SMARTPHONE": "smartfon", "HEADPHONES": "słuchawki",
    "COMPRESSOR": "kompresor", "PRINTER": "drukarka",
    "SMARTWATCH": "zegarek sportowy/smartwatch",
    "ROUTER": "router", "LAPTOP": "laptop", "POWER_TOOL": "elektronarzędzie",
    "ACCESSORY": "akcesorium / część", "UNKNOWN": "kategoria nieustalona",
}

# Spec weight describes the importance of comparing the explicit title fields,
# not empirical quality, reliability, real-world range, or suitability for use.
SPEC_WEIGHT = {
    "E_BIKE": {"power_w": 30, "battery_ah": 28, "battery_wh": 28, "wheel_in": 15,
               "gears": 7, "speed_kmh": 7, "claimed_range_km": 5,
               "bike_style": 8},
    "COMPRESSOR": {"power_w": 45, "pressure_bar": 40, "tank_l": 15},
    "SSD": {"capacity_gb": 60, "ssd_form": 40},
    # Laptop model codes are not required to match. ARM/x86 differences remain
    # visible as a major compatibility difference, not a hidden disqualification.
    "LAPTOP": {"ram_gb": 25, "capacity_gb": 23,
               "cpu_family": 22, "display_technology": 15, "screen_in": 15},
    "SMARTPHONE": {"capacity_gb": 65},
    "E_SCOOTER": {"power_w": 40, "battery_ah": 40, "battery_wh": 40,
                   "speed_kmh": 20},
    "BICYCLE": {"wheel_in": 70, "bike_style": 30},
}
CORE_SPECS = {"E_BIKE": ("power_w", "battery_ah", "battery_wh"),
              "COMPRESSOR": ("power_w", "pressure_bar"),
              "SSD": ("capacity_gb", "ssd_form"),
              "SMARTPHONE": ("capacity_gb",),
              "E_SCOOTER": ("power_w", "battery_ah", "battery_wh"),
              "BICYCLE": ("wheel_in",)}
PUBLIC_SPEC_NAMES = {
    "power_w": "moc silnika", "battery_ah": "pojemność akumulatora (Ah)",
    "battery_wh": "nominalna energia akumulatora (Wh)",
    "battery_voltage_v": "napięcie akumulatora",
    "wheel_in": "rozmiar koła (cale)", "gears": "liczba przełożeń",
    "speed_kmh": "deklarowana prędkość", "claimed_range_km": "deklarowany zasięg",
    "bike_style": "typ roweru", "pressure_bar": "maksymalne ciśnienie",
    "tank_l": "zbiornik (litry)", "capacity_gb": "pojemność pamięci",
    "ssd_form": "typ/nośnik SSD",
    "ram_gb": "pamięć RAM", "cpu_family": "rodzina procesora",
    "display_technology": "typ matrycy", "screen_in": "przekątna ekranu",
}
STATUS_SIMILAR = "SIMILAR_TECHNICAL_TIER_INDEX_ONLY"
STATUS_POSSIBLE = "POSSIBLE_ALTERNATIVE_NEEDS_SPEC_CHECK"
STATUS_DIFFERENT = "DIFFERENT_TECHNICAL_TIER"
STATUS_OTHER_CATEGORY = "DIFFERENT_PRODUCT_CATEGORY"
STATUS_CATEGORY_UNKNOWN = "CATEGORY_UNKNOWN_NO_TECHNICAL_COMPARISON"
STATUS_INSUFFICIENT = "CATEGORY_MATCH_INSUFFICIENT_SPECS"
PRICE_BAND_SAME = "SIMILAR_INDEX_PRICE_BAND"
PRICE_BAND_LOWER = "LOWER_INDEX_PRICE_BAND"
PRICE_BAND_HIGHER = "HIGHER_INDEX_PRICE_BAND"
PRICE_BAND_UNKNOWN = "PRICE_BAND_UNDETERMINED"


def _normalize(value):
    value = unicodedata.normalize("NFKD", value if isinstance(value, str) else "")
    value = value.casefold().replace("ł", "l")
    return "".join(x for x in value if not unicodedata.combining(x))


def category_of(title):
    text = _normalize(title)
    # Accessory/consumable gates MUST precede main product category matches.
    if re.search(
        r"\b(?:etui|pokrowiec|ochrona|szklo ochronne|szybka|ladowarka|adapter|"
        r"uchwyt|kabel|filtr wymienny|zamiennik|akumulator do|bateria do|"
        r"opona do|klocki hamulcowe|oslona|case|cover)\b", text
    ):
        return "ACCESSORY"
    if re.search(r"\bhulajnoga\b|\be[ -]?scooter\b", text):
        return "E_SCOOTER" if re.search(r"elektryczn|e[ -]?scooter", text) else "UNKNOWN"
    is_bike = bool(re.search(r"\brower\b|\be[ -]?bike\b|\bebike\b", text))
    if is_bike:
        if re.search(r"elektryczn|\be[ -]?bike\b|\bebike\b", text):
            return "E_BIKE"
        return "BICYCLE"
    if re.search(r"\bkompresor\b|\bsprezark", text):
        return "COMPRESSOR"
    if re.search(r"\bssd\b|\bdysk nvme\b", text):
        return "SSD"
    if re.search(r"\biphone\b|\bsmartfon\b|\bsmartphone\b|\btelefon komorkowy\b", text):
        return "SMARTPHONE"
    if re.search(r"\bsluchawki\b|\bheadphones\b", text):
        return "HEADPHONES"
    if re.search(r"\bdrukarka\b|\bprinter\b", text):
        return "PRINTER"
    if re.search(r"\bgarmin forerunner\b|\bsmartwatch\b|\bzegarek sportowy\b", text):
        return "SMARTWATCH"
    if re.search(r"\brouter\b|\barcher (?:ax|be)\d+", text):
        return "ROUTER"
    if re.search(r"\blaptop\b|\bnotebook\b|\bideapad\b|\bthinkpad\b|\bvivobook\b|\bmacbook\b", text):
        return "LAPTOP"
    if re.search(r"\bwiertarka\b|\bwkretarka\b", text):
        return "POWER_TOOL"
    return "UNKNOWN"


def _first_number(text, pattern, lower, upper):
    m = re.search(pattern, text)
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    return value if lower <= value <= upper else None


def _wheel_size(text):
    # 27,5″ / 27.5"/27-5/27 5; bare 27 without units is ambiguous.
    wheel = _first_number(
        text, r"(?<![\d])((?:2[4-9]|3[0-2])(?:[,.\- ]5))\s*(?:[\"″]|cal|inch)?(?=\D|$)",
        24, 32)
    if wheel is not None:
        return wheel
    pair = re.search(r"(?<!\d)(2[4-9]|3[0-2])\s*[,\.\- ]\s*5(?:[\"″]|\b)", text)
    if pair:
        return float(pair.group(1)) + 0.5
    m = re.search(r"(?<!\d)(2[4-9]|3[0-2])\s*(?:[\"″]|cal(?:e|i)?\b|inch\b)", text)
    return float(m.group(1)) if m else None


def _capacity_gb(text):
    # Converts TB to 1000 GB only for comparing advertised packaging labels.
    values = re.findall(r"(?<!\w)(\d+(?:[.,]\d+)?)\s*(tb|gb)\b", text)
    if not values:
        return None
    number, unit = values[0]
    size = float(number.replace(",", ".")) * (1000 if unit == "tb" else 1)
    return size if 16 <= size <= 100000 else None


def read_specs(title, category=None):
    text = _normalize(title)
    cat = category or category_of(title)
    specs = {}
    if cat in ("E_BIKE", "E_SCOOTER", "COMPRESSOR"):
        w = _first_number(text, r"(?<!\w)(\d{2,4}(?:[,.]\d+)?)\s*w\b", 100, 5000)
        kw = _first_number(text, r"(?<!\w)(\d(?:[,.]\d+)?)\s*kw\b", 0.1, 5)
        if w is not None or kw is not None:
            specs["power_w"] = w if w is not None else round(kw * 1000)
    if cat in ("E_BIKE", "E_SCOOTER"):
        ah = _first_number(text, r"(?<!\w)(\d{1,3}(?:[,.]\d+)?)\s*ah\b", 2, 150)
        if ah is not None:
            specs["battery_ah"] = ah
        volts = _first_number(text, r"(?<!\w)(\d{2,3}(?:[,.]\d+)?)\s*v\b", 12, 100)
        if volts is not None:
            specs["battery_voltage_v"] = volts
        if ah is not None and volts is not None:
            specs["battery_wh"] = round(ah * volts, 2)
        wheel = _wheel_size(text)
        if wheel is not None and cat == "E_BIKE":
            specs["wheel_in"] = wheel
        speed = _first_number(text, r"(?<!\w)(\d{2,3})\s*(?:km/h|kmh)\b", 10, 100)
        if speed is not None:
            specs["speed_kmh"] = speed
        if cat == "E_BIKE":
            claimed = _first_number(text, r"(?<!\w)(\d{2,3})\s*km\b", 25, 300)
            if claimed is not None:
                specs["claimed_range_km"] = claimed
            gears = _first_number(
                text, r"(?:\bshimano\s*[- ]?\s*)?(\d{1,2})\s*(?:s\b|bieg(?:ow(?:a|y)?)?\b|przelozen)", 1, 30)
            if gears is not None:
                specs["gears"] = gears
            if re.search(r"\bmtb\b|\bgorsk", text):
                specs["bike_style"] = "mountain"
            elif re.search(r"\bmiejsk|\bc[yi]ty\b", text):
                specs["bike_style"] = "city"
            elif re.search(r"\btrekking\b|\btrekkingow", text):
                specs["bike_style"] = "trekking"
            elif re.search(r"\bskladan|\bfolding", text):
                specs["bike_style"] = "folding"
    if cat == "BICYCLE":
        wheel = _wheel_size(text)
        if wheel is not None:
            specs["wheel_in"] = wheel
    if cat == "COMPRESSOR":
        bar = _first_number(text, r"(?<!\w)(\d{1,2}(?:[,.]\d+)?)\s*bar\b", 1, 30)
        if bar is not None:
            specs["pressure_bar"] = bar
        liters = _first_number(text, r"(?<!\w)(\d{1,3})\s*l(?:itrow)?\b", 3, 200)
        if liters is not None:
            specs["tank_l"] = liters
    if cat == "LAPTOP":
        ram = _first_number(
            text, r"(?<!\d)(4|8|12|16|24|32|48|64|96|128)\s*(?:gb|g)(?:\s*ram)?\b",
            4, 128)
        if ram is not None:
            specs["ram_gb"] = ram
        # Capacity uses explicit GB/TB when available. X-kom URL slugs
        # sometimes use "16gb 512 win11" with omitted SSD units.
        storage = None
        for value, unit in re.findall(
                r"(?<!\w)(\d{3,4}(?:[.,]\d+)?)\s*(tb|gb)\b", text):
            size = float(value.replace(",", ".")) * (1000 if unit=="tb" else 1)
            if 128 <= size <= 16000:
                storage = size
                break
        if storage is None:
            raw = re.search(
                r"\b(?:ssd[- ]?)?(256|512|1024|2048)\b(?=\s*(?:ssd|win(?:dows)?"
                r"|oled|ips|w11|$))", text)
            if raw:
                storage = float(raw.group(1))
        if storage is not None:
            specs["capacity_gb"] = storage
        if re.search(r"\bsnapdragon\b|\bqualcomm\b", text):
            specs["cpu_family"] = "Snapdragon ARM"
        elif re.search(r"\b(?:intel|core i[3579]|core ultra|ultra [3579] \d{3}|i[3579][- ]?\d{4,5}[a-z]{0,3})\b", text):
            specs["cpu_family"] = "Intel x86"
        elif re.search(r"\b(?:ryzen|amd)\b", text):
            specs["cpu_family"] = "AMD x86"
        elif re.search(r"\bapple m[1-5]\b", text):
            specs["cpu_family"] = "Apple ARM"
        if re.search(r"\boled\b", text):
            specs["display_technology"] = "OLED"
        elif re.search(r"\bips\b", text):
            specs["display_technology"] = "IPS"
        elif re.search(r"\btn\b", text):
            specs["display_technology"] = "TN"
        size = _first_number(
            text, r"(?<!\d)(1[034567](?:[.,]\d)?)\s*(?:[\"″]|cal(?:e|i)?\b|inch\b)",
            10, 18)
        if size is not None:
            specs["screen_in"] = size
    if cat in ("SSD", "SMARTPHONE"):
        size = _capacity_gb(text)
        if size is not None:
            specs["capacity_gb"] = size
        if cat == "SSD":
            if re.search(r"\bportable\b|\bzewnetrzn|\bprzenosn", text):
                specs["ssd_form"] = "external"
            elif re.search(r"\bnvme\b|\bm[.]?2\b|\bwewnetrzn", text):
                specs["ssd_form"] = "internal"
    return specs


def _fit(name, baseline, candidate):
    if isinstance(baseline, str):
        return 1.0 if baseline == candidate else 0.0
    b = float(baseline)
    c = float(candidate)
    if b <= 0:
        return 0.0
    relative = abs(c - b) / b
    if name in ("power_w", "battery_ah", "battery_wh", "capacity_gb", "ram_gb"):
        return 1.0 if relative <= 0.20 else (0.45 if relative <= 0.40 else 0.0)
    if name == "screen_in":
        return 1.0 if abs(c - b) <= 0.7 else (0.45 if abs(c - b) <= 1.5 else 0.0)
    if name == "wheel_in":
        return 1.0 if abs(c - b) <= 1.5 else (0.45 if abs(c - b) <= 2.5 else 0.0)
    if name == "gears":
        return 1.0 if abs(c - b) <= 2 else (0.45 if abs(c - b) <= 6 else 0.0)
    if name == "speed_kmh":
        return 1.0 if abs(c - b) <= 5 else (0.45 if abs(c - b) <= 10 else 0.0)
    if name == "claimed_range_km":
        return 1.0 if relative <= 0.30 else (0.45 if relative <= 0.50 else 0.0)
    return 1.0 if relative <= 0.20 else (0.45 if relative <= 0.40 else 0.0)


def _display_spec(name, number):
    if isinstance(number, str):
        return number
    suffix = {"power_w": "W", "battery_ah": "Ah", "wheel_in": '"',
              "battery_wh": "Wh", "battery_voltage_v": "V", "gears": "", "speed_kmh": "km/h",
              "claimed_range_km": "km",
              "pressure_bar": "bar", "tank_l": "l", "capacity_gb": "GB",
              "ram_gb": "GB", "screen_in": '"'}
    return "{:g}{}".format(number, suffix.get(name, ""))


def evaluate_alternative(selected_title, candidate_title):
    selected_category = category_of(selected_title)
    category = category_of(candidate_title)
    base = read_specs(selected_title, selected_category)
    target = read_specs(candidate_title, category)
    result = {
        "category": category,
        "category_label": CATEGORY_LABELS[category],
        "selected_category": selected_category,
        "status": STATUS_CATEGORY_UNKNOWN,
        "technical_score": None,
        "matched_features": [],
        "different_features": [],
        "unconfirmed_features": [],
        "comparison_basis": "ONLY_PUBLIC_SEARCH_INDEX_TITLES_NOT_PRODUCT_TESTS",
        "same_model_required": False,
        "actual_quality_not_measured": True,
        "advertised_range_is_unverified": "claimed_range_km" in (base.keys() | target.keys()),
    }
    if selected_category == "UNKNOWN" or category == "UNKNOWN":
        return result
    if category != selected_category or category == "ACCESSORY":
        result["status"] = STATUS_OTHER_CATEGORY
        return result
    weights = SPEC_WEIGHT.get(category, {})
    relevant = [name for name in weights if name in base]
    # Ah is not a true energy comparison when voltages vary; compare
    # nominal Wh if the selected product declares both Ah and V.
    if "battery_wh" in relevant and "battery_ah" in relevant:
        relevant.remove("battery_ah")
    if not relevant:
        result["status"] = STATUS_INSUFFICIENT
        return result
    possible = sum(weights[name] for name in relevant)
    achieved = 0.0
    covered = 0
    matches = 0
    core_bad = False
    core_partial = False
    for name in relevant:
        a = base[name]
        b = target.get(name)
        if b is None:
            result["unconfirmed_features"].append(PUBLIC_SPEC_NAMES[name])
            continue
        covered += 1
        fit = _fit(name, a, b)
        achieved += fit * weights[name]
        caption = "{}: {} ↔ {}".format(
            PUBLIC_SPEC_NAMES[name], _display_spec(name, a),
            _display_spec(name, b))
        if fit == 1:
            result["matched_features"].append(caption)
            matches += 1
        else:
            result["different_features"].append(caption)
            if name in CORE_SPECS.get(category, ()):
                if fit == 0:
                    core_bad = True
                elif fit < 1:
                    core_partial = True
    if "battery_ah" in base and "battery_wh" not in base:
        result["unconfirmed_features"].append(
            "energia baterii (Wh) – brak napięcia w opisie produktu wejściowego")
    elif "battery_wh" in base and "battery_wh" not in target:
        result["unconfirmed_features"].append(
            "energia baterii (Wh) – brak napięcia lub Ah w opisie alternatywy")
    score = round(100 * achieved / possible) if possible else None
    result["technical_score"] = score
    result["evidence_dimensions_compared"] = covered
    result["selected_spec_dimensions"] = len(relevant)
    if core_bad:
        result["status"] = STATUS_DIFFERENT
    elif category == "E_BIKE" and not core_partial and covered >= 2 and matches >= 2 and score >= 65:
        result["status"] = STATUS_SIMILAR
    elif category in ("COMPRESSOR", "SSD", "LAPTOP", "E_SCOOTER", "BICYCLE") and not core_partial and covered >= 2 and matches >= 2 and score >= 70:
        result["status"] = STATUS_SIMILAR
    elif score >= 35 and matches:
        result["status"] = STATUS_POSSIBLE
    else:
        result["status"] = STATUS_INSUFFICIENT
    return result


def _condition(title):
    text = _normalize(title)
    if re.search(r"\buzywan[yae]\b|\bpowystawow|\bodnowion|\brefurbished\b", text):
        return "USED_OR_REFURBISHED_TITLE_CLAIM"
    if re.search(r"\bnow[yae]\b|\bbrand new\b", text):
        return "NEW_TITLE_CLAIM"
    return "NOT_STATED"


def _price(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return dec if dec.is_finite() and Decimal("0.01") <= dec <= Decimal("100000") else None


def _relative_price_band(price, reference):
    if not price or not reference:
        return PRICE_BAND_UNKNOWN
    ratio = price / reference
    if ratio < Decimal("0.65"):
        return PRICE_BAND_LOWER
    if ratio > Decimal("1.45"):
        return PRICE_BAND_HIGHER
    return PRICE_BAND_SAME


def enrich_alternatives(selected, indexed_offers, shopping_cards):
    """Add functional similarity assessments without changing exact-SKU gates.

    Price reference = input seller-listed price when available; otherwise
    median of >=3 clearly similar index observations (an *estimate*, not
    the true price of the selected item). No extra provider calls.
    """
    title = selected.get("title", "")
    selected_condition = _condition(title)
    selected_cat = category_of(title)
    all_rows = []
    for group, kind in ((indexed_offers, "INDEXED_STORE_LINK"),
                        (shopping_cards, "SEARCH_CARD_NO_DIRECT_OFFER")):
        for entry in group:
            comparison = evaluate_alternative(title, entry.get("title"))
            claimed_condition = _condition(entry.get("title"))
            comparison["selected_condition_from_title"] = selected_condition
            comparison["candidate_condition_from_title"] = claimed_condition
            if (claimed_condition != "NOT_STATED"
                    and selected_condition != "NOT_STATED"
                    and selected_condition != claimed_condition):
                comparison["condition_difference"] = (
                    "Różny deklarowany stan produktu: nowy / używany lub odnowiony")
                if comparison["status"] == STATUS_SIMILAR:
                    comparison["status"] = STATUS_POSSIBLE
            elif claimed_condition == "USED_OR_REFURBISHED_TITLE_CLAIM":
                comparison["condition_difference"] = (
                    "Produkt używany/odnowiony – nie porównuj ceny z nowym bez sprawdzenia")
            entry["functional_alternative"] = comparison
            price = _price(entry.get("current_price_indexed") if kind == "INDEXED_STORE_LINK"
                           else entry.get("indexed_price"))
            currency = entry.get("currency") if kind == "INDEXED_STORE_LINK" else entry.get("indexed_currency")
            all_rows.append((entry,kind,price,currency))
    supplied_price = _price(selected.get("price"))
    currency = selected.get("currency")
    reference = None
    origin = "UNKNOWN_NO_SELLER_PRICE_OR_SUFFICIENT_PEERS"
    if supplied_price is not None and currency in ("PLN", "EUR", "USD"):
        reference, origin = supplied_price, "INPUT_SELLER_DECLARED_NOT_CHECKOUT"
    else:
        # Restrict cohort to technically comparable results with same
        # currency, filtering anomalously low index quotes and duplicates.
        peers = {}
        for entry, kind, price, unit in all_rows:
            comparison = entry["functional_alternative"]
            if (comparison["status"] not in (STATUS_SIMILAR, STATUS_POSSIBLE)
                    or unit != "PLN" or
                    price is None or
                    entry.get("index_price_anomaly") ==
                    "SUSPICIOUS_LOW_PRICE_VS_PEER_MEDIAN_NOT_VERIFIED"):
                continue
            key = (entry.get("product_id") or entry.get("merchant_url") or
                   (entry.get("source") or entry.get("seller"),entry.get("title")))
            peers[key] = price
        if len(peers) >= 3:
            reference = median(peers.values())
            currency, origin = "PLN", "ESTIMATE_FROM_SIMILAR_INDEX_LISTINGS"
    # Search cards are indexed evidence too; compare prices against the
    # available same-category peers before allowing any "cheaper" framing.
    # This catches obvious poisoned results without declaring genuine
    # extreme discounts impossible (warning, not deletion).
    by_currency = {}
    for entry, kind, price, unit in all_rows:
        assessment = entry["functional_alternative"]
        if (assessment["status"] in (STATUS_SIMILAR, STATUS_POSSIBLE)
                and price is not None and unit in ("PLN", "EUR", "USD")):
            by_currency.setdefault(unit, []).append((entry, price))
    for cohort in by_currency.values():
        if len(cohort) < 3:
            continue
        typical = median(p for _, p in cohort)
        for entry, price in cohort:
            if price < typical * Decimal("0.40"):
                entry["index_price_anomaly"] = (
                    "SUSPICIOUS_LOW_PRICE_VS_PEER_MEDIAN_NOT_VERIFIED")
    # If a price anomaly was discovered in the same-index peer pool, do
    # not use that price as the reference median either.
    if origin == "ESTIMATE_FROM_SIMILAR_INDEX_LISTINGS":
        peers = {}
        for entry, kind, price, unit in all_rows:
            if (entry["functional_alternative"]["status"] not in
                    (STATUS_SIMILAR, STATUS_POSSIBLE)
                    or unit != "PLN" or price is None
                    or entry.get("index_price_anomaly") ==
                    "SUSPICIOUS_LOW_PRICE_VS_PEER_MEDIAN_NOT_VERIFIED"):
                continue
            key = (entry.get("product_id") or entry.get("merchant_url") or
                   (entry.get("source") or entry.get("seller"), entry.get("title")))
            peers[key] = price
        reference = median(peers.values()) if len(peers) >= 3 else None
        if reference is None:
            origin = "UNKNOWN_NO_SELLER_PRICE_OR_SUFFICIENT_PEERS"
            currency = selected.get("currency")
    ranked = []
    counts = {STATUS_SIMILAR:0, STATUS_POSSIBLE:0,
              STATUS_DIFFERENT:0, STATUS_OTHER_CATEGORY:0,
              STATUS_CATEGORY_UNKNOWN:0, STATUS_INSUFFICIENT:0}
    for entry, kind, price, unit in all_rows:
        comparison = entry["functional_alternative"]
        status = comparison["status"]
        counts[status] += 1
        band = _relative_price_band(price, reference) if unit == currency else PRICE_BAND_UNKNOWN
        comparison["price_band"] = band
        comparison["price_reference_kind"] = origin
        comparison["price_reference_value"] = str(reference) if reference is not None else None
        comparison["price_reference_currency"] = currency if reference is not None else None
        if status not in (STATUS_SIMILAR, STATUS_POSSIBLE):
            continue
        # Different models and brands are fully eligible as candidates.
        ranked.append({
            "source": entry.get("source") or entry.get("seller"),
            "title": entry["title"],
            "indexed_price": str(price) if price is not None else None,
            "currency":unit,
            "source_kind":kind,
            "merchant_url":(entry.get("merchant_url") if kind == "INDEXED_STORE_LINK"
                            else None),
            "shopping_lookup_url":entry.get("index_search_url"),
            "comparison": comparison,
            "index_price_anomaly":entry.get("index_price_anomaly", "NOT_ASSESSED_CARD"),
            "source_verified":False,
            "selected_model_identity_verified":False,
            "real_quality_test_available":False,
        })
    def order_key(row):
        cmp = row["comparison"]
        status_weight = 0 if cmp["status"] == STATUS_SIMILAR else 1
        flagged = row["index_price_anomaly"] == "SUSPICIOUS_LOW_PRICE_VS_PEER_MEDIAN_NOT_VERIFIED"
        band = cmp["price_band"]
        band_weight = 0 if band == PRICE_BAND_SAME else (1 if band == PRICE_BAND_UNKNOWN else 2)
        # Price breaks ties among close (~10pt) technical scores. This
        # favours cheaper comparable alternatives rather than different
        # models solely because one title happens to repeat more keywords.
        return (status_weight, flagged, band_weight,
                -int((cmp["technical_score"] or 0) // 10),
                _price(row["indexed_price"]) or Decimal("999999"),
                -(cmp["technical_score"] or 0))
    ranked.sort(key=order_key)
    return {
        "selected_category": selected_cat,
        "category_label": CATEGORY_LABELS[selected_cat],
        "selected_declared_specs": read_specs(title, selected_cat),
        "price_reference":(str(reference.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
                           if reference is not None else None),
        "price_reference_currency":currency if reference is not None else None,
        "price_reference_provenance":origin,
        "status_counts": counts,
        "ranked_alternatives": ranked[:12],
        "total_index_observations":len(all_rows),
        "no_independent_product_tests":True,
        "price_versus_quality_not_measured":True,
        "same_sku_not_required_for_alternatives":True,
        "payment_authorized":False,
        "limitations":[
            "Similarity is heuristic, from indexed title specifications, not independent testing.",
            "Power, battery and advertised range may be incomplete or seller-inaccurate.",
            "Price segment derived from search-index peers is not the selected item's current seller price.",
            "A related bike model may differ in brakes, battery cells, frame, warranty and safety.",
        ],
    }
