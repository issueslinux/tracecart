"""Read-only decision UI projection from persisted TraceCart research evidence.

The legacy OPF catalog counter is NOT a Google Shopping counter. Project the
latter separately, without changing immutable saved source material. User
answers are local UI choices, NOT independent facts or purchase authorization.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from statistics import median
from urllib.parse import urlsplit
import re

from autonomous_research import build_research_path
from similar_tier import (
    category_of, read_specs, enrich_alternatives, STATUS_SIMILAR, STATUS_POSSIBLE,
)

MAX_CANDIDATES = 18
MAX_QUESTIONS = 5


def _amount(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number=Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        return None
    if not number.is_finite() or not Decimal("0.01") <= number <= Decimal("1000000"):
        return None
    return number


def _public_link(value):
    if not isinstance(value,str) or len(value) > 1400:
        return None
    try:
        p=urlsplit(value)
        if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None,443):
            return None
        if p.hostname in ("localhost","127.0.0.1") or p.hostname.endswith(".local"):
            return None
    except ValueError:
        return None
    return value


def _question(id_, title, options, detail):
    return {"id":id_, "title":title, "detail":detail,
            "choices":[{"value":key,"label":value,"hint":hint}
                       for key,value,hint in options]}


def questions_for(category):
    if category == "LAPTOP":
        return [
            _question("usage","Do czego potrzebujesz laptopa?",[
                ("office","Codzienna praca","Przeglądarka, dokumenty, spotkania."),
                ("coding","Programowanie i aplikacje","Zgodność narzędzi i środowiska ma znaczenie."),
                ("demanding","Gry lub wymagające aplikacje","Weryfikujemy GPU, wydajność i zgodność."),
            ],"Inne zastosowanie zmienia to, które cechy są najważniejsze."),
            _question("priority","Co ma największe znaczenie?",[
                ("price","Możliwie dobra cena","Szukamy wartości, odrzucając podejrzane ceny."),
                ("balanced","Rozsądny kompromis","Cena i porównywalna konfiguracja."),
                ("screen","Ekran i komfort pracy","OLED/IPS nie traktujemy jako tożsame."),
            ],"To wybór użytkownika, nie dowód jakości produktu."),
            _question("compatibility","Czy potrzebujesz programów zgodnych z x86?",[
                ("x86","Tak, zgodność x86 jest ważna","Intel/AMD zamiast niezweryfikowanej kompatybilności ARM."),
                ("arm","Nie, ARM może być OK","Można uwzględnić modele Snapdragon."),
                ("unknown","Nie wiem","Nie deklarujemy zgodności aplikacji bez sprawdzenia."),
            ],"Snapdragon X wykorzystuje ARM; nie każde narzędzie Windows x86 działa identycznie."),
            _question("verification","Czy sprawdziłeś cenę i warunki konkretnej oferty?",[
                ("yes","Tak, osobiście w sklepie","Zapisujemy Twoją deklarację, nie weryfikację TraceCart."),
                ("no","Jeszcze nie","Cena z Google Shopping może być błędna lub nieaktualna."),
                ("unavailable","Strona jest niedostępna","Nie uznajemy ceny indeksowanej za potwierdzoną."),
            ],"Bez sprawdzenia ceny, wariantu, gwarancji i dostępności nie ma pewnej decyzji zakupowej."),
        ]
    if category == "E_BIKE":
        return [
            _question("usage","Jak będziesz używać roweru?",[
                ("commute","Codzienne dojazdy","Praktyczny zasięg, niezawodność i serwis."),
                ("trails","Szutry i trasy terenowe","Hamulce, napęd i geometria mają znaczenie."),
                ("leisure","Rekreacyjnie","Komfort i rzeczywisty zasięg."),
            ],"Same deklarowane 100 km nie potwierdza osiągów."),
            _question("priority","Co jest ważniejsze?",[
                ("price","Cena","Szukanie tańszych, ale porównywalnych opcji."),
                ("balanced","Parametry i cena","Bateria, silnik, koła oraz wyposażenie."),
                ("quality","Serwis i trwałość","Gwarancja, hamulce i jakość ogniw."),
            ],"W indeksie rzadko znajdziemy wiarygodne testy komponentów."),
            _question("verification","Czy potwierdziłeś konkretną ofertę?",[
                ("yes","Tak, ręcznie","Twoja deklaracja nie jest niezależnym dowodem."),
                ("no","Nie","Wróć do strony sprzedawcy po aktualną cenę."),
                ("unavailable","Nie mogę otworzyć oferty","Cena w indeksie pozostaje niepotwierdzona."),
            ],"Wymagana także kontrola serwisu i pochodzenia akumulatora."),
        ]
    return [
        _question("usage","Jaki jest Twój cel?",[
            ("same","Szukam tańszego podobnego produktu","Inna marka/model może spełniać podobną funkcję."),
            ("quality","Szukam lepszej jakości","Potrzebne testy i dane o trwałości."),
            ("research","Chcę porównać możliwości","Pokazujemy dostępne źródła i braki dowodów."),
        ],"Nie trzeba wybierać identycznego SKU."),
        _question("priority","Jak wybierasz?",[
            ("price","Cena","Bez potwierdzenia nie uznajemy niskiego indeksu za okazję."),
            ("balanced","Cena i parametry","Porównywalne funkcje, a nie tylko numer modelu."),
            ("quality","Trwałość i gwarancja","Wymaga rzetelnych niezależnych testów."),
        ],"Nie wnioskujemy o jakości z samej ceny."),
        _question("verification","Czy sam sprawdziłeś warunki wybranej oferty?",[
            ("yes","Tak, w sklepie","Tylko deklaracja użytkownika."),
            ("no","Nie","Indeks wyszukiwarki jest wskazówką."),
            ("unavailable","Strona niedostępna","Wynik wymaga dodatkowej weryfikacji."),
        ],"TraceCart nie wykonuje zakupów ani płatności."),
    ]


def _display_title(title, category, unverified):
    """Readable URL-derived hypothesis, NEVER a verified retailer title."""
    if category != "LAPTOP" or not unverified:
        return title
    text=title.lower()
    if "lenovo" in text and "ideapad" in text and "slim" in text:
        parts=["Laptop Lenovo IdeaPad Slim"]
        m=re.search(r"\bslim[ -]?(\d+)\b",text)
        if m:
            parts[0]+=" "+m.group(1)
        if "snapdragon" in text:
            parts.append("Snapdragon")
        elif "intel" in text:
            parts.append("Intel")
        specs=read_specs(title,"LAPTOP")
        if specs.get("ram_gb"):
            parts.append("{:g} GB RAM".format(specs["ram_gb"]))
        if specs.get("capacity_gb"):
            parts.append("{:g} GB SSD (URL text only)".format(specs["capacity_gb"]))
        if specs.get("display_technology"):
            parts.append(specs["display_technology"])
        return " · ".join(parts)
    return re.sub(r"(?i)\.html?$","",re.sub(r"^\d{4,9}\s+","",title))


def build_decision_projection(record):
    """Produce bounded, explicitly sourced content for interactive navigation.

    Historical jobs are projected on access; the persisted tree and its SHA
    remain unchanged. This prevents silently rewriting an old audit.
    """
    state=record.get("state")
    if state != "READY":
        return {"state":state,"error_type":record.get("error_type"),
                "payment_authorized":False}
    report=record.get("report") or {}
    selected=record.get("item") or {}
    title=selected.get("title") or "Produkt ze wskazanego adresu"
    shopping=report.get("indexed_shopping") or {}
    source=report.get("source_intake") or {}
    catalog=(report.get("source_discovery") or {}).get("catalog") or []
    direct=shopping.get("indexed_offers") or []
    cards=shopping.get("search_result_groups") or []
    category=category_of(title)
    # Re-evaluate old historical jobs with the *current* version of
    # similarity rules, without touching original timestamp/source claims.
    tier=enrich_alternatives(selected,deepcopy(direct),deepcopy(cards))
    indexed=[]
    for kind,group in (("INDEXED_STORE_LINK",direct),
                       ("SEARCH_CARD_NO_DIRECT_SELLER_LINK",cards)):
        for entry in group[:20]:
            indexed.append((
                kind,entry,
                entry.get("current_price_indexed") if kind=="INDEXED_STORE_LINK"
                else entry.get("indexed_price"),
                entry.get("currency") if kind=="INDEXED_STORE_LINK"
                else entry.get("indexed_currency"),
            ))
    priced=[(_amount(p), unit) for _,_,p,unit in indexed if unit=="PLN"]
    priced=[p for p,unit in priced if p is not None]
    median_index=median(priced) if len(priced)>=3 else None
    suspicious_raw=0
    if median_index:
        for kind,row,price,unit in indexed:
            amount=_amount(price)
            if (unit=="PLN" and amount is not None and
                    amount < median_index*Decimal("0.40") and
                    category_of(row.get("title"))==category):
                suspicious_raw+=1
    suspicious=0
    candidates=[]
    seen=set()
    for candidate in tier["ranked_alternatives"]:
        title_candidate=candidate.get("title") or ""
        link=_public_link(candidate.get("merchant_url")) or _public_link(
            candidate.get("shopping_lookup_url"))
        comparison=candidate["comparison"]
        amount=_amount(candidate.get("indexed_price"))
        currency=candidate.get("currency")
        reasons=[]
        anomaly=candidate.get("index_price_anomaly")
        if anomaly=="SUSPICIOUS_LOW_PRICE_VS_PEER_MEDIAN_NOT_VERIFIED":
            reasons.append("Very low indexed quote relative to peers")
        if median_index and amount and currency=="PLN" and amount < median_index*Decimal("0.40"):
            reasons.append("Very low indexed quote relative to category median")
        source_name=(candidate.get("source") or "").lower()
        lowered=title_candidate.casefold()
        if ("abonament" in lowered or "abonament" in source_name
                or "miesięcznie" in lowered or "miesiecznie" in lowered):
            reasons.append("May represent installments or a subscription")
        if comparison.get("condition_difference"):
            reasons.append(comparison["condition_difference"])
        if reasons:
            suspicious+=1
        key=(candidate.get("source"),title_candidate.casefold(),candidate.get("indexed_price"))
        if key in seen:
            continue
        seen.add(key)
        specs=read_specs(title_candidate,category)
        cpu=specs.get("cpu_family")
        candidates.append({
            "id":"candidate-{}".format(len(candidates)+1),
            "source":str(candidate.get("source") or "")[:100],
            "title":title_candidate[:200],
            "price":str(amount) if amount is not None else None,
            "currency":currency if currency in ("PLN","EUR","USD") else None,
            "link":link,
            "link_kind":("seller URL (not retrieved)" if
                         candidate.get("merchant_url") else
                         "Google Shopping search (no direct seller link)"),
            "source_kind":candidate.get("source_kind"),
            "tier":comparison["status"],
            "technical_fit":comparison.get("technical_score"),
            "matched_specs":comparison.get("matched_features",[])[:6],
            "missing_specs":comparison.get("unconfirmed_features",[])[:5],
            "different_specs":comparison.get("different_features",[])[:5],
            "specs":specs,
            "cpu_architecture":("ARM" if cpu and "ARM" in cpu else
                                "x86" if cpu and "x86" in cpu else "UNKNOWN"),
            "quality_verified":False,
            "seller_price_verified":False,
            "price_warnings":reasons,
            "index_only":True,
        })
    evidence={
        "catalog_only":len(catalog),
        "google_shopping_cards":len(cards),
        "indexed_store_links":len(direct),
        "indexed_listing_records":len(direct)+len(cards),
        "unverified_similar_product_leads":len(candidates),
        "index_prices_flagged_in_alternatives":sum(bool(x["price_warnings"]) for x in candidates),
        "unusually_low_raw_index_quotes":suspicious_raw,
        "seller_confirmed_competitor_prices":shopping.get("source_qualified_seller_offers",0),
        "selected_seller_price":selected.get("price"),
        "selected_currency":selected.get("currency"),
        "input_source_status":source.get("intake_status") or "UNKNOWN",
        "input_source_problem":source.get("access_problem"),
        "shopping_status":shopping.get("status") or "NOT_RESEARCHED",
        "shopping_api_calls":shopping.get("provider_calls") or 0,
        "independent_product_tests":0,
    }
    if evidence["seller_confirmed_competitor_prices"] != 0:
        # The legacy Search-First field must never be promoted into a
        # checkout-verification claim. This projection is intentionally strict.
        evidence["seller_confirmed_competitor_prices"]=0
    reasons=[]
    if selected.get("price") is None:
        reasons.append("Selected retailer price could not be retrieved.")
    if source.get("intake_status") == "URL_ONLY_UNVERIFIED":
        reasons.append("Selected product description is inferred from URL, not fetched seller HTML.")
    if direct or cards:
        reasons.append("Google Shopping quotes are indexed observations, not verified checkout prices.")
    if not direct and not cards:
        reasons.append("No comparable indexed offers could be retrieved.")
    if suspicious or suspicious_raw:
        reasons.append(
            "{} indexed quotes are much lower than others; "
            "they may be index errors, installments or other variants. They are not "
            "verified purchase prices.".format(suspicious_raw))
    payload={
        "state":"READY",
        "title":str(title)[:200],
        "display_title":_display_title(
            title, category, source.get("intake_status")=="URL_ONLY_UNVERIFIED"),
        "selected_url":_public_link(selected.get("merchant_url")),
        "category":category,
        "selected_specs":read_specs(title,category),
        "source_provenance":"URL-derived, unverified title" if source.get("intake_status")=="URL_ONLY_UNVERIFIED"
                            else "Retailer page claims",
        "evidence":evidence,
        "questions":[],  # Deprecated buyer questionnaire; no clicks required.
        "research":build_research_path(report, selected, candidates[:MAX_CANDIDATES], evidence),
        "candidates":candidates[:MAX_CANDIDATES],
        "research_questions":[
            "Czy cena jest aktualna, bez abonamentu i dotyczy wskazanego wariantu?",
            "Czy parametry i zgodność oprogramowania są potwierdzone u producenta?"
            if category=="LAPTOP" else
            "Czy istotne parametry są potwierdzone poza tytułem oferty?",
            "Czy warunki zwrotu, gwarancja i reputacja sprzedawcy są udokumentowane?",
        ],
        "warnings":reasons,
        "decision_boundary":"NO_AUTOMATIC_PAYMENT_OR_VERIFIED_CHEAPEST_CLAIM",
        "measurement_provenance":"Read-only reinterpretation of saved research report",
        "saved_report_sha256":report.get("sha256"),
        "payment_authorized":False,
    }
    return payload
