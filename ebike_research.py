"""Evidence-directed e-bike investigation, not 288 mechanically permuted questions.

Questions are tasks for source retrieval and verification, not user prompts or
LLM-written answers. Every domain dimension has a meaningful leading check.
Detailed follow-ups vary by physical measurement, part identity, safety,
service, seller or regulatory evidence; inappropriate tests are never asked.
"""
from similar_tier import read_specs

# (dimension index from AXES["E_BIKE"], investigation mode, high-impact question)
FACETS = (
 (0,"identity","What manufacturer, model, production year and frame-size variant identify this exact bicycle?"),
 (1,"component","Who manufactured the motor, what exact model is fitted, and is its claimed 250 W continuous rated rather than peak power?"),
 (2,"measurement","What torque curve and temperature-controlled sustained-load test establish actual motor torque and derating?"),
 (3,"safety","Which cell maker, battery-pack maker, BMS and independently checkable battery safety certificates apply to this pack?"),
 (4,"battery","The title claims 15 Ah. What nominal battery voltage and independently documented energy in Wh correspond to that figure?"),
 (5,"service","Can the battery pack be obtained and replaced independently of a whole-bike replacement, and at what documented cost?"),
 (6,"measurement","Is the claimed 100 km range supported by a measured test with stated rider mass, assist setting, route, weather and speed?"),
 (7,"safety","What charger model, charge current, cell protection, temperature limits and safety certifications are documented?"),
 (8,"component","What exact Shimano derailleur, cassette/freewheel and shifter models constitute the advertised 7-speed drivetrain?"),
 (9,"measurement","Which brake caliper, rotor and pad models are fitted, and are stopping-distance tests available at full load?"),
 (10,"component","Does the stated 27.5-inch wheel configuration include documented rim, tire width, suspension fork and travel?"),
 (11,"identity","Does the listing's men/women claim correspond to specified frame geometry, sizes and standover heights?"),
 (12,"safety","What maximum gross load, luggage load and fatigue-tested frame rating does the manufacturer declare?"),
 (13,"safety","Which independently documented ingress-protection or rain test applies to motor, battery and connectors?"),
 (14,"component","What controller, display and firmware versions are installed, and can the manufacturer supply supported updates?"),
 (15,"regulatory","Does electric assistance stop at the declared 25 km/h and on stopping pedalling, with continuous motor rating and throttle behavior documented?"),
 (16,"service","What authorized repairs, spare parts and service coverage are actually offered in the country of purchase?"),
 (17,"regulatory","Is this specific configuration legally classified as a pedal-assisted cycle in the intended market, with verifiable declarations and test reports?"),
 (18,"service","Can the motor, battery, display, controller, drivetrain and brake parts be repaired individually or replaced with listed spares?"),
 (19,"reliability","What independently documented long-term failure patterns occur for this exact frame, battery and motor combination?"),
 (20,"measurement","Which independent tests measured battery range, braking, power and reliability on the same precise model and battery option?"),
 (21,"seller","Who is the legal seller, what is the actual item condition, and do their photos/serial markings match the advertised model?"),
 (22,"price","What is today's complete price in the actual seller checkout, excluding installments, financing teaser rates or subscription costs?"),
 (23,"seller","What carrier, shipping restrictions, delivery fees and battery transport conditions apply to this bicycle?"),
)

# Eight further source-directed checks for each aspect; task templates are
# intentionally separated by evidence type (no "lab measured model identity").
FOLLOWUPS = {
 "identity": (
  "Which exact part numbers, serial codes or catalog revisions identify {focus}?",
  "Does the manufacturer's official catalog explicitly describe {focus} for this production year?",
  "Which retailer photographs or frame markings could corroborate {focus} without relying on the title alone?",
  "How do different sizes, revisions or model years change {focus}?",
  "Is a downloadable factory technical document available to identify {focus}?",
  "Do seller identifiers conflict with any published manufacturer identifiers for {focus}?",
  "What documentary source independent of the seller confirms {focus}?",
  "Which fields about {focus} remain unknowable without the actual serial number?",
 ),
 "component": (
  "What manufacturer's part number and data sheet identify {focus}?",
  "Does the seller's claimed component match the OEM build specification for this exact variant of {focus}?",
  "Are pictures of the actual component and nameplate available for checking {focus}?",
  "Does the claimed component rating refer to nominal, maximum or short-duration performance of {focus}?",
  "Are differently equipped versions sold under the same model title for {focus}?",
  "Which replacement part and manufacturer support documents apply to {focus}?",
  "Do independent inspections or teardowns corroborate the installed hardware for {focus}?",
  "Are there contradictory hardware identifiers or revisions across sources for {focus}?",
 ),
 "measurement": (
  "Which independent laboratory or instrumented field test has actually measured {focus}?",
  "What exact frame size, battery, rider load, ambient temperature and assistance setting were tested for {focus}?",
  "Was the claimed result for {focus} measured repeatedly, and what is its uncertainty?",
  "Which standardized protocol or disclosed equipment was used when testing {focus}?",
  "How does {focus} change under hills, sustained load or unfavorable conditions?",
  "Can a test of {focus} be linked to the same motor, battery and component revision as the advertised offer?",
  "Do two independent measured results for {focus} agree within plausible test differences?",
  "What specific source evidence would rule out transferring a different variant's result for {focus}?",
 ),
 "battery": (
  "What nominal voltage, cell arrangement and actual Wh rating are documented for {focus}?",
  "Is the {focus} figure a manufacturer specification, a seller estimate or a measured battery test?",
  "Do the cell label, pack nameplate and charger voltage agree for {focus}?",
  "Which independently published capacity or discharge test measured {focus}?",
  "What usable energy remains under cold-weather and high-current use for {focus}?",
  "Is a similar 15 Ah pack sold with a different voltage or cell capacity affecting {focus}?",
  "Which battery degradation, cycle-life and storage instructions apply to {focus}?",
  "How can a source verify {focus} without treating ampere-hours alone as watt-hours?",
 ),
 "safety": (
  "Which exact applicable product, component and battery safety standards cover {focus}?",
  "Who issued the declaration or test report supporting {focus}, and which model was tested?",
  "Does any safety certificate cover this precise hardware revision and not merely the product family for {focus}?",
  "Which documented failure hazards or recalls are associated with {focus}?",
  "What manufacturer safety instructions address {focus} under ordinary and wet-weather use?",
  "Do parts used in this particular listing have traceable makers and batch markings for {focus}?",
  "Is there a third-party safety test that corroborates or contradicts the supplier's {focus} claims?",
  "What would prevent a trustworthy safety conclusion about {focus} without a matched report?",
 ),
 "regulatory": (
  "Which specific manufacturer declaration covers {focus} for this exact EU-market variant?",
  "Are pedal activation, 25 km/h motor-assist cut-off and continuous motor rating documented for {focus}?",
  "Is the throttle or walk-assist behavior documented and compatible with the advertised classification of {focus}?",
  "Which model, jurisdiction and edition of technical standard are identified in the evidence for {focus}?",
  "Could a speed-unrestricted or high-power variant be confused with this listing for {focus}?",
  "Does the seller supply a readable declaration of conformity and user manual for {focus}?",
  "Are there any recalls, legal restrictions or missing markings connected to {focus}?",
  "Which facts remain unverified before claiming road-use compliance for {focus}?",
 ),
 "service": (
  "Which exact replacement part identifiers and prices can be verified for {focus}?",
  "Who is authorized to perform {focus}, and where is service available?",
  "What work is user-serviceable and what requires proprietary diagnostics for {focus}?",
  "What written warranty terms and exclusions apply specifically to {focus}?",
  "What is the published labor cost or replacement lead time for {focus}?",
  "Are essential parts for {focus} independently stocked beyond the seller?",
  "Which real repair reports or manufacturer bulletins corroborate the ease of {focus}?",
  "Do incompatible generations or firmware locks prevent replacement parts for {focus}?",
 ),
 "reliability": (
  "Which independent long-duration tests or service reports document {focus}?",
  "Do reported failures identify the exact model and production batch relevant to {focus}?",
  "How many tested units, months and kilometers support any assertion about {focus}?",
  "Which battery, motor, controller or frame failures are most consequential to {focus}?",
  "Could different riding conditions explain conflicting reliability reports about {focus}?",
  "Do manufacturer bulletins or recalls document a repair for {focus}?",
  "Can the results be corroborated without treating unverified buyer comments as measured reliability of {focus}?",
  "What reliability evidence is missing before ranking the offer on {focus}?",
 ),
 "seller": (
  "Does the seller explicitly identify {focus} in their own source document or current product page?",
  "Which model, serial, photographs and SKU would establish that {focus} describes this exact offer?",
  "Are the declared terms for {focus} current, complete and legally attributable to this merchant?",
  "Do customer protections or warranty documents actually cover {focus}?",
  "Which terms are excluded or conditional in the fine print relevant to {focus}?",
  "Does a trusted independent source corroborate any material seller assertion about {focus}?",
  "Do the listing and seller-issued invoice descriptions agree about {focus}?",
  "What essential fact about {focus} remains inaccessible without seller verification?",
 ),
 "price": (
  "Is {focus} an outright one-time price or only a monthly installment?",
  "What is the actual cash purchase amount shown on the seller's current product page for {focus}?",
  "Does the quoted price correspond to the exact battery, frame and motor variant for {focus}?",
  "Which delivery, oversize parcel and mandatory handling fees affect {focus}?",
  "Are discounts contingent on subscription, financing, membership or vouchers for {focus}?",
  "Is the item available now in the stated condition at the current listed price for {focus}?",
  "Do source metadata and visible seller price agree for {focus}?",
  "Can the delivered checkout total be verified without authorizing a payment for {focus}?",
 ),
}

CROSS = (
 ("What frame brand and precise product code can be independently confirmed, given that the current title lists only generic specifications?", "identity"),
 ("What voltage is missing from a title that claims 15 Ah, and why does that prevent converting Ah to Wh?", "battery"),
 ("If the battery is 15 Ah, which range test supports the seller's 100 km claim and at what assistance level?", "range"),
 ("Does the displayed 25 km/h figure denote motor-assistance cut-off or merely a claimed top speed?", "regulatory"),
 ("Does 250 W denote continuous rated power or a marketing output label?", "motor"),
 ("Which exact Shimano 7-speed parts are installed rather than a generic brand claim?", "drivetrain"),
 ("Do the brake types and rotor sizes suit the bicycle's full load and advertised performance?", "brakes"),
 ("Is the declared 27.5-inch wheel size consistent with photographed tires and original manufacturer equipment?", "wheels"),
 ("Which seller or manufacturer record establishes that any 'men/women' frame suits documented height and inseam ranges?", "fit"),
 ("Is the same 15 Ah battery pack fitted to every indexed offer, or are different voltages and capacities mixed together?", "variants"),
 ("Which seller source confirms current all-in price, delivery and return policy without financing conditions?", "seller"),
 ("Are there any independent test results of the actual advertised motor and battery, not a similarly named e-bike?", "independent_test"),
)


def _claims(title):
    specs = read_specs(title, "E_BIKE")
    claims = []
    for key, unit, label in (
        ("power_w"," W","motor label"),
        ("battery_ah"," Ah","battery capacity label"),
        ("claimed_range_km"," km","range label"),
        ("wheel_in"," in","wheel label"),
        ("gears"," speeds","gears label"),
        ("speed_kmh"," km/h","speed label"),
    ):
        if specs.get(key) is not None:
            val=specs[key]
            claims.append({"type":key,"display":"{}: {:g}{}".format(label,val,unit),
                           "status":"UNVERIFIED_LISTING_TITLE"})
    if specs.get("battery_ah") and not specs.get("battery_voltage_v"):
        claims.append({"type":"missing_voltage","display":"Battery voltage and Wh NOT known from the title",
                       "status":"NOT_DECLARED_IN_TITLE"})
    return claims


def _plan(title):
    # Put one actionable, different research problem from EACH facet first.
    # Make numeric claims conditional: other bicycles need not say 15 Ah,
    # 100 km, 25 km/h, 250 W or Shimano merely because one example does.
    specs=read_specs(title, "E_BIKE")
    priority_override={
        1: ("Who manufactured the motor, what exact model is fitted, and is "
            "the {v:g} W claim continuous rather than peak power?").format(
                v=specs["power_w"]) if specs.get("power_w") else
            "Which motor maker, exact model and continuous rated power can be confirmed?",
        4: ("The title claims {v:g} Ah. What is the nominal voltage and "
            "documented energy in Wh for this exact pack?").format(
                v=specs["battery_ah"]) if specs.get("battery_ah") else
            "What nominal battery voltage, ampere-hour capacity and watt-hour energy can be confirmed?",
        6: ("Is the claimed {v:g} km range supported by a measured test with "
            "stated rider mass, assist level, route, weather and speed?").format(
                v=specs["claimed_range_km"]) if specs.get("claimed_range_km") else
            "What independently measured range is reported, under what load and assistance settings?",
        8: ("Which exact Shimano derailleur, cassette/freewheel and shifter "
            "models constitute the advertised {v:g}-speed drivetrain?").format(
                v=specs["gears"]) if specs.get("gears") and "shimano" in title.casefold() else
            "Which drivetrain and shifter models are actually fitted, and how many ratios are supported?",
        10: ("Does the advertised {v:g}-inch wheel size correspond to original "
             "OEM rims, tires and suspension equipment?").format(
                 v=specs["wheel_in"]) if specs.get("wheel_in") else
             "What wheel, tire and fork dimensions are verified by the actual OEM build specification?",
        11: ("Does the listing's men/women claim correspond to documented frame sizes and standover heights?"
             if any(w in title.casefold() for w in ("meski","męski","damski","damsk","men/women","unisex"))
             else "Which frame sizes, standover heights and rider dimensions are documented?"),
        15: ("Does electric assistance stop at the advertised {v:g} km/h and "
             "when pedalling stops, with throttle and continuous motor power documented?").format(
                 v=specs["speed_kmh"]) if specs.get("speed_kmh") else
             "At what measured speed does pedal assistance stop, and what is the throttle behavior?",
    }
    order=(0,4,6,15,1,7,3,5,9,8,11,12,17,21,22,20,2,13,14,16,18,19,10,23)
    entries=[]
    for i in order:
        _,kind,question=FACETS[i]
        entries.append((i,"priority",priority_override.get(i,question),"P0"))
    cross_override={}
    import re
    model_token=re.search(r"(?i)\b([A-Za-z][A-Za-z0-9]{3,16})\s+([A-Za-z]{1,4}[0-9]{2,4}[A-Za-z0-9-]*)\b",title)
    if model_token:
        cross_override[0]="Does the indexed '{}' name match a real OEM model year, frame and production revision?".format(model_token.group(0))
    if not specs.get("battery_ah"):
        cross_override[1]="What battery voltage and Ah capacity are documented, and why are both needed to establish Wh?"
        cross_override[2]="What independent range test matches the actual battery energy, load and assist level?"
        cross_override[9]="Do indexed bicycle offers have a verifiably identical battery voltage and Wh, not just a matching title?"
    else:
        cross_override[1]=("What voltage is missing from a {v:g} Ah claim, "
                           "and why does that prevent converting Ah to Wh?").format(
                               v=specs["battery_ah"])
        cross_override[2]=("For {v:g} Ah, what independent test supports "
                           "the advertised range under defined conditions?").format(
                               v=specs["battery_ah"])
        cross_override[9]=("Do all indexed offers with {v:g} Ah use the "
                           "same voltage and cell pack, or different Wh?").format(
                               v=specs["battery_ah"])
    if not specs.get("claimed_range_km") and specs.get("battery_ah"):
        cross_override[2]="Which independent range test used a pack documented as {:g} Ah with confirmed Wh?".format(specs["battery_ah"])
    if specs.get("speed_kmh"):
        cross_override[3]="Does the advertised {:g} km/h mean motor assistance cutoff, or only overall speed?".format(specs["speed_kmh"])
    else:
        cross_override[3]="What motor-assist cut-off speed, not just top speed, is independently documented?"
    if specs.get("power_w"):
        cross_override[4]=("Does the {v:g} W advertised power refer to continuous "
                           "rated output or a peak marketing figure?").format(v=specs["power_w"])
    else:
        cross_override[4]="What motor continuous rated power is documented and is it a peak marketing figure?"
    if specs.get("gears") and "shimano" in title.casefold():
        cross_override[5]="Which exact Shimano component models form the advertised {:g}-speed system?".format(specs["gears"])
    elif specs.get("gears"):
        cross_override[5]="Which manufacturer and exact parts form the advertised {:g}-speed system?".format(specs["gears"])
    else:
        cross_override[5]="Which actual drivetrain maker, model and number of gears are fitted?"
    if specs.get("wheel_in"):
        cross_override[7]="Are the advertised {:g}-inch wheels consistent with the OEM rims, tire dimensions and variant?".format(specs["wheel_in"])
    else:
        cross_override[7]="What wheel and tire dimensions are verified by an OEM specification or component markings?"
    if not any(w in title.casefold() for w in ("meski","męski","damski","damsk","men/women","unisex")):
        cross_override[8]="Which size table and actual frame geometry support the rider fit claims?"
    for i,(question,focus) in enumerate(CROSS):
        entries.append((100+i,"cross",cross_override.get(i,question),"P0" if i<5 else "P1"))
    for i,(axis,kind,_) in enumerate(FACETS):
        # These are investigations of different valid evidence types, not
        # pointless 12-way permutations that include nonsensical lab tests.
        for probe,template in enumerate(FOLLOWUPS[kind]):
            entries.append((i,"source_{}".format(probe),template.format(focus=axis_name(axis)),"P1"))
    return entries


def axis_name(index):
    from offer_question_bank import AXES
    return AXES["E_BIKE"][index]


def ebike_question_count():
    return len(FACETS)+len(CROSS)+len(FACETS)*8


def questions_for_ebike(offer, offset=0, limit=24):
    total=ebike_question_count()
    if type(offset) is not int or not 0<=offset<=total:
        raise ValueError("Invalid question offset")
    if type(limit) is not int or not 1<=limit<=24:
        raise ValueError("Invalid question limit")
    items=_plan(offer.get("title",""))
    result=[]
    for index in range(offset,min(total,offset+limit)):
        dimension,probe,question,priority=items[index]
        result.append({
            "id":"{}-{}".format(offer["id"],index+1),
            "question":question,
            "dimension":axis_name(dimension) if dimension<24 else "cross-claim verification",
            "probe":probe,
            "priority":priority,
            "origin":"DOMAIN_SPECIFIC_RESEARCH_PLAN_NOT_LLM",
            "status":"PLANNED_NOT_INVESTIGATED",
            "finding":None,"evidence_ids":[],
            "addressed_to":"RESEARCH_AGENT_NOT_BUYER",
        })
    return {
        "offer_id":offer["id"],"offer_title":offer["title"],
        "total":total,"offset":offset,"limit":limit,
        "questions":result,
        "next_offset":offset+len(result) if offset+len(result)<total else None,
        "verified_answers":0,
        "important":"These are prioritized source investigations. The listing title alone does not verify bike, battery, range, legality or price.",
    }


def ebike_claims(title):
    return _claims(title)


def offer_title_diagnostics(offer):
    """Critical listing hints, not independent tests or verified seller data."""
    specs=read_specs(offer.get("title",""),"E_BIKE")
    absent=[]
    if not specs.get("battery_voltage_v"):
        absent.append("Battery voltage is absent from this title; exact Wh cannot be calculated.")
    if not specs.get("battery_wh"):
        absent.append("Battery energy in Wh is unverified. Ah alone is insufficient.")
    absent.extend([
        "Manufacturer model, frame revision and pack identity not independently verified.",
        "Assistance cutoff, throttle behavior and regulatory classification not tested.",
        "No independent range, braking or durability measurements matched to the seller SKU.",
    ])
    scenarios=[]
    ah=specs.get("battery_ah")
    km=specs.get("claimed_range_km")
    if ah and km:
        for volts in (36,48):
            wh=round(volts*ah,1)
            scenarios.append({
                "assumption":"IF the pack is {} V".format(volts),
                "energy_wh":wh,"advertised_range_km":km,
                "implied_wh_per_km":round(wh/km,2),
                "status":"HYPOTHETICAL_NOT_PRODUCT_EVIDENCE",
                "note":"Conditional arithmetic, not measured range or verified battery.",
            })
    return {"status":"UNVERIFIED_TITLE_ONLY",
            "missing_evidence":absent,"scenarios":scenarios}


def likely_index_model_hints(offers):
    """Concrete alternative model leads, NEVER exact identity of input seller."""
    import re
    if not offers:
        return []
    ref=read_specs(offers[0].get("title",""),"E_BIKE")
    found=[]
    seen=set()
    for other in offers[1:]:
        title=other.get("title","")
        spec=read_specs(title,"E_BIKE")
        if not all(ref.get(k) and spec.get(k) and
                   abs(ref[k]-spec[k])<=max(1,ref[k]*0.04)
                   for k in ("power_w","battery_ah")):
            continue
        m=re.search(r"(?i)\b([A-Za-z][A-Za-z0-9]{3,16})\s+([A-Za-z]{1,4}[0-9]{2,4}[A-Za-z0-9-]*)\b",title)
        if not m:
            continue
        label=m.group(1)+" "+m.group(2)
        if label.casefold() in seen:
            continue
        seen.add(label.casefold())
        found.append({"model_hint":label,"source_offer":other["id"],
                      "source_title":title,
                      "confidence":"RELATED_INDEX_TITLE_ONLY",
                      "exact_seller_sku_verified":False})
        if len(found)>=3:
            break
    return found
