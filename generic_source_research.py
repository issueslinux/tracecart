"""General source research for any product category.

No domain-specific product facts or fabricated shopping prices. Sources come
from the saved report, a model-specific link ON a candidate brand website,
or an explicitly configured provider. Every external page is fetched through
the existing pinned public-IP HTTPS + robots gate before parsing.
"""
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
from html import unescape
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree
import json
import re
import unicodedata

from evidence_execution import _robot_checked_read
from product_intake import validate_product_url

MAX_DIRECT_SOURCES=2
MAX_LINKS=600
MAX_CLAIMS=12
MAX_BYTES=2500000
GENERIC_PRODUCT_WORDS={
    "rower","elektryczny","meski","damski","ebike","bike","electric",
    "laptop","notebook","komputer","telefon","smartphone","smartfon",
    "drukarka","printer","dysk","ssd","tablet","monitor","telewizor",
    "kompresor","power","tool","wiertarka","wkretarka","zestaw","set",
    "nowy","nowa","moc","bateria","battery","szybki","wireless",
    "bluetooth","ultrabook","slim","karta","ram","gb","tb","wifi",
    "pro","plus","ultra","max","home","led","lcd","oled","ips",
}
_SPEC_SUFFIXES=("w","kw","v","ah","mah","wh","km","kmh","gb",
                "tb","mm","cm","hz","rpm","bar","kg","mp","mb")
REJECT_BRAND_DOMAINS={"allegro","amazon","ceneo","mediaexpert","ebay"}
PROPERTY_KEYS=(
    ("battery",("battery","akumulator","bateria","accu")),
    ("motor",("motor","silnik","engine","rated power")),
    ("range",("range","zasięg","zasieg")),
    ("screen",("screen","display","matryca","rozdzielczość")),
    ("memory",("ram","memory","pamięć","pamiec")),
    ("storage",("ssd","storage","capacity","pojemność")),
    ("power",("power","watt","moc")),
    ("speed",("speed","prędkość","predkosc")),
    ("weight",("weight","waga","masa")),
    ("size",("size","dimension","rozmiar","wymiary")),
    ("frame",("frame","rama","material","materiał")),
    ("brakes",("brake","hamulc")),
    ("warranty",("warranty","gwaranc")),
    ("model",("model","mpn","sku")),
    ("cpu",("cpu","processor","procesor","chipset")),
    ("gpu",("gpu","graphics","grafik","vram")),
    ("network",("connectivity","network","wifi","wi-fi","bluetooth")),
    ("energy",("energy","electricity","consumption","zużycie","zuzycie")),
    ("voltage",("voltage","napięcie","napiecie")),
    ("current",("current","amperage","natężenie","natezenie")),
    ("volume",("volume","objętość","objetosc","litre","liter","ml","pojemnosc")),
    ("ingredients",("ingredients","skład","sklad","composition")),
    ("materials",("material","fabric","materiał","materialy","tkanina")),
    ("resolution",("resolution","rozdzielczość","rozdzielczosc","dpi")),
    ("durability",("durability","ip rating","waterproof","water resistance")),
    ("noise",("noise","sound level","hałas","halas","db")),
    ("consumables",("cartridge","toner","ink","filter","filtr","tusz")),
    ("lifetime",("lifetime","battery life","runtime","trwałość","trwalosc")),
    ("color",("color","colour","kolor")),
    ("frequency",("frequency","refresh rate","odświeżanie","odswiezanie")),
    ("pressure",("pressure","ciśnienie","cisnienie")),
)
SOURCE_LABELS={
    "DIRECT_SELLER_LINK":"SELLER_PRODUCT_PAGE_DECLARATIONS",
    "PUBLISHED_DISCOVERY_HIT":"THIRD_PARTY_PAGE_UNVERIFIED_PUBLISHER",
    "BRAND_HOME_PRODUCT_LINK":"BRAND_SITE_DECLARATIONS_NOT_INDEPENDENT_TESTS",
}

def _words(text):
    normalized=unicodedata.normalize("NFKD",str(text or "").casefold())
    normalized="".join(c for c in normalized if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+",normalized)

def _is_model(token):
    value=token.casefold()
    if len(value)<3 or len(value)>19:
        return False
    if not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value):
        return False
    if any(value.endswith(sfx) and value[:-len(sfx)].replace(".","").isdigit()
           for sfx in _SPEC_SUFFIXES):
        return False
    if value in GENERIC_PRODUCT_WORDS:
        return False
    return True

def product_identity(title):
    """Conservative lexical brand+model lead, not proof of manufacture.

    Manufacturer URL discovery may use the domain only as a hypothesis.
    Publication identity must be confirmed from the fetched product page.
    """
    words=_words(title)
    candidates=[]
    for i,t in enumerate(words):
        numeric_candidate=(t.isdigit() and 3<=len(t)<=6
            and not (1990<=int(t)<=2040)
            and not (i+1<len(words) and words[i+1] in (
               "w","kw","v","mah","ah","wh","km","kmh","mm","cm",
               "gb","tb","kg","bar","hz","rpm")))
        if not (_is_model(t) or numeric_candidate):
            continue
        for pos in range(max(0,i-6),i):
            brand=words[pos]
            if (not 2<=len(brand)<=19 or not brand.isalpha()
                or brand in GENERIC_PRODUCT_WORDS
                or brand in REJECT_BRAND_DOMAINS):
                continue
            # The brand closest to product-series words is preferable; but
            # suppress arbitrary "Intel", "Snapdragon" etc CPU brand matches.
            if brand in ("intel","amd","qualcomm","snapdragon","ryzen","core","windows"):
                continue
            candidates.append((i-pos,brand,t))
            break
    if not candidates:return None
    candidates.sort(key=lambda row:(row[0],len(row[2])* -1))
    _,brand,model=candidates[0]
    return {"brand":brand,"model":model,
            "identity_status":"TITLE_MODEL_TOKEN_LEAD_NOT_VERIFIED"}

class _HTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip=0
        self.stack=[]
        self.buffer=[]
        self.h1=[]
        self.title=[]
        self.links=[]
        self.ldjson=[]
        self.current_script=False
        self.current_script_type=None
        self.script_content=[]
        self.properties=[]
        self.meta={}
        self.tuple_keys=[]
        self.table_values=[]
        self.current_row=[]
        self.cell=None
        self.cell_buffer=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=="script":
            self.current_script=True
            self.current_script_type=attrs.get("type")
            self.script_content=[]
            self.skip+=1
            return
        if tag in ("style","noscript","svg","template"):
            self.skip+=1
            return
        if self.skip:return
        self.stack.append(tag)
        if tag=="a" and len(self.links)<MAX_LINKS:
            href=attrs.get("href")
            if isinstance(href,str):self.links.append(href[:900])
        if tag=="meta":
            key=attrs.get("property") or attrs.get("name")
            val=attrs.get("content")
            if isinstance(key,str) and isinstance(val,str):
                self.meta[key[:60].casefold()]=val[:320]
        if tag=="tr":
            self.current_row=[]
        if tag in ("th","td","dt","dd"):
            self.cell=tag
            self.cell_buffer=[]
    def handle_endtag(self,tag):
        if tag=="script":
            if self.current_script and self.current_script_type=="application/ld+json":
                self.ldjson.append("".join(self.script_content)[:300000])
            self.current_script=False
            self.current_script_type=None
            self.script_content=[]
            self.skip=max(0,self.skip-1)
            return
        if tag in ("style","noscript","svg","template"):
            self.skip=max(0,self.skip-1)
            return
        if self.skip:return
        if tag in ("th","td","dt","dd") and self.cell==tag:
            value=" ".join("".join(self.cell_buffer).split())
            if value:self.current_row.append((tag,value[:230]))
            if tag=="dd" and len(self.current_row)>1:
                self.table_values.append(self.current_row[-2:])
                self.current_row=[]
            self.cell=None
        if tag=="tr" and len(self.current_row)>=2:
            self.table_values.append(self.current_row[:3])
        if tag in self.stack:
            # Malformed product HTML still allows a bounded text extraction.
            while self.stack:
                last=self.stack.pop()
                if last==tag:break
    def handle_data(self,raw):
        if self.current_script:
            if self.current_script_type=="application/ld+json":
                self.script_content.append(raw[:300000])
            return
        if self.skip:return
        value=" ".join(unescape(raw).split())
        if not value:return
        if self.cell:self.cell_buffer.append(value)
        if "h1" in self.stack:self.h1.append(value[:150])
        if "title" in self.stack:self.title.append(value[:150])
        if len(value)>5 and len(value)<200 and len(self.buffer)<1700:
            self.buffer.append(value)

def parse_html_document(raw):
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_BYTES:
        raise ValueError("INVALID_DOCUMENT")
    doc=_HTML()
    doc.feed(raw.decode("utf-8","replace"))
    return doc

def _products(doc):
    records=[]
    def walk(obj,depth=0):
        if depth>6 or len(records)>=30:return
        if isinstance(obj,list):
            for x in obj[:25]:walk(x,depth+1)
        elif isinstance(obj,dict):
            kind=obj.get("@type",[])
            kinds=kind if isinstance(kind,list) else [kind]
            if any(str(k).casefold() in ("product","productmodel","individualproduct")
                   for k in kinds):
                records.append(obj)
            if "@graph" in obj:walk(obj["@graph"],depth+1)
            if "mainEntity" in obj:walk(obj["mainEntity"],depth+1)
            if "itemListElement" in obj:walk(obj["itemListElement"],depth+1)
    for raw in doc.ldjson[:8]:
        try:walk(json.loads(raw))
        except (ValueError,TypeError):pass
    return records

def _text(value):
    if isinstance(value,str):return " ".join(value.split())[:190]
    if isinstance(value,(int,float)) and not isinstance(value,bool):
        return str(value)[:35]
    return ""

def _properties(doc,product=None):
    """Read explicit label/value facts, not arbitrary numbers in prose."""
    props=[]
    if product:
        for key in ("sku","mpn","model","color","material","size","weight",
                    "height","width","depth","gtin13","gtin","brand"):
            val=product.get(key)
            if key=="brand" and isinstance(val,dict):val=val.get("name")
            if _text(val):props.append((key,_text(val)))
        additional=product.get("additionalProperty",[])
        if isinstance(additional,dict):additional=[additional]
        if isinstance(additional,list):
            for item in additional[:45]:
                if isinstance(item,dict):
                    key=_text(item.get("name") or item.get("propertyID"))
                    val=_text(item.get("value"))
                    if key and val:props.append((key,val))
    for row in doc.table_values[:95]:
        if len(row)>=2 and len(row[0][1])<=75 and len(row[1][1])<=160:
            props.append((row[0][1],row[1][1]))
    # Common generic "Key: value" product feature lines.
    for line in doc.buffer[:500]:
        if ":" not in line:continue
        key,value=line.split(":",1)
        if 3<=len(key)<=60 and 1<=len(value)<=120:
            props.append((key.strip(),value.strip()))
    seen=set()
    unique=[]
    for key,value in props:
        key=_text(key)
        value=_text(value)
        if not key or not value or len(key)>70 or len(value)>160:
            continue
        pair=(key.casefold(),value.casefold())
        if pair in seen:continue
        seen.add(pair)
        unique.append((key,value))
        if len(unique)>=80:break
    return unique

def _field_family(name):
    normal=" ".join(_words(name))
    for group,tokens in PROPERTY_KEYS:
        if any(re.search(r"\b"+re.escape(token)+r"\b",normal) for token in tokens):
            return group
    return None

def _document_identity(doc,offer,product=None):
    listing=product_identity(offer.get("title"))
    header=" ".join(doc.h1[:8])
    if product:
        heading=" ".join([_text(product.get("name")),_text(product.get("model"))])
        if heading.strip():header=heading
    if listing:
        hwords=_words(header)
        if listing["model"] in hwords:
            return "EXACT_MODEL_TOKEN_IN_PRODUCT_HEADER_RETAIL_SKU_UNVERIFIED"
        return "DOCUMENT_MODEL_NOT_IN_PRODUCT_HEADER"
    title_tokens=set(_words(offer.get("title")))
    headers=set(_words(header))
    significant=[x for x in title_tokens if len(x)>3 and
                 x not in GENERIC_PRODUCT_WORDS]
    if len(significant)>=2 and len(set(significant)&headers)>=2:
        return "TITLE_TEXT_OVERLAP_NO_EXACT_SKU_ID"
    return "PRODUCT_IDENTITY_NOT_ESTABLISHED"

def parse_source_claims(raw,offer,category,source_url,source_kind):
    """Produce source-linked *declarations*, never independent measurement."""
    doc=parse_html_document(raw)
    products=_products(doc)
    # A page may contain multiple unrelated Product schema blocks. Never
    # assume the first model is the offered product.
    scored=[]
    for product in products:
        status=_document_identity(doc,offer,product)
        if status.startswith("EXACT_MODEL") or status.startswith("TITLE_TEXT"):
            scored.append((0 if status.startswith("EXACT_MODEL") else 1,product,status))
    scored.sort(key=lambda row:row[0])
    product=scored[0][1] if scored else None
    identity=scored[0][2] if scored else _document_identity(doc,offer)
    if identity in ("DOCUMENT_MODEL_NOT_IN_PRODUCT_HEADER",
                    "PRODUCT_IDENTITY_NOT_ESTABLISHED"):
        return {"status":"SOURCE_PAGE_IDENTITY_NOT_CONFIRMED",
                "claims":[],"identity":identity}
    props=_properties(doc,product)
    picked=[]
    for key,val in props:
        group=_field_family(key)
        if group is None:continue
        picked.append((group,key,val))
        if len(picked)>=MAX_CLAIMS:break
    if not picked:
        return {"status":"SOURCE_NO_STRUCTURED_PRODUCT_PROPERTIES",
                "claims":[],"identity":identity}
    timestamp=datetime.now(timezone.utc).isoformat()
    digest=sha256(raw).hexdigest()
    rows=[]
    for group,key,value in picked:
        rows.append({
            "dimension":None,
            "question_id":None,
            "status":"DOCUMENT_DECLARATION_EXACT_SKU_UNVERIFIED",
            "finding":"{}: {} (source page declaration, not independently measured).".format(key,value),
            "value":value,
            "source_property":key,"property_family":group,
            "source_kind":SOURCE_LABELS[source_kind],
            "source_method":"JSON_LD_OR_VISIBLE_SPECIFICATION",
            "source_url":source_url,
            "publisher":urlsplit(source_url).hostname,
            "source_sha256":digest,"retrieved_at":timestamp,
            "reviewed_model":(product or {}).get("model") if product else None,
            "reviewed_variant":identity,
            "variant_match":"SAME_MODEL_TOKEN_NOT_EXACT_SKU_OR_HARDWARE",
            "verified_for_exact_offer":False,
            "is_independent_lab_test":False,
        })
    return {
        "status":"STRUCTURED_PRODUCT_DECLARATIONS_NOT_INDEPENDENTLY_TESTED",
        "claims":rows,"identity":identity,
        "source_sha256":digest,
        "retrieved_at":timestamp,
    }

def _https_public(url):
    try:
        candidate=validate_product_url(url)
        p=urlsplit(candidate)
        return p.scheme=="https" and p.hostname is not None
    except (ValueError,TypeError):
        return False

def candidate_urls(offer):
    """Only real provided indexed/direct URLs; no invented review URLs."""
    options=[]
    url=offer.get("url")
    if isinstance(url,str) and _https_public(url):
        # Skip shopping index pseudo links (e.g. SerpApi) with no seller page.
        p=urlsplit(url)
        if p.hostname not in ("www.google.com","google.com","serpapi.com"):
            options.append({"url":url,"scope":"DIRECT_SELLER_LINK"})
    for row in offer.get("discovered_source_urls") or []:
        if not isinstance(row,dict) or not _https_public(row.get("url")):
            continue
        url=row["url"]
        if any(c["url"]==url for c in options):continue
        options.append({"url":url,"scope":"PUBLISHED_DISCOVERY_HIT"})
        if len(options)>=MAX_DIRECT_SOURCES:break
    return options[:MAX_DIRECT_SOURCES]

def _sitemap_model_links(home,model,fetch=None):
    """One public sitemap, up to two product sitemap children. No broad crawl."""
    urls=[]
    seen=set()
    targets=[urljoin(home,"/sitemap.xml")]
    origin=urlsplit(home).hostname
    while targets and len(seen)<3:
        url=targets.pop(0)
        if url in seen:continue
        seen.add(url)
        try:
            raw=_robot_checked_read(url,fetch=fetch,
                        mimes=("application/xml","text/xml",
                               "text/plain","application/xhtml+xml"))
            if len(raw)>2_000_000:continue
            root=ElementTree.fromstring(raw)
        except (ValueError,OSError,TypeError,ElementTree.ParseError):
            continue
        for tag in list(root)[:4500]:
            raw_link=next((child.text for child in tag
                           if child.tag.split("}")[-1].lower()=="loc"),None)
            if not isinstance(raw_link,str):continue
            pp=urlsplit(raw_link.strip())
            if pp.scheme!="https" or pp.hostname!=origin or (
                    pp.port not in (None,443)):
                continue
            if pp.path.endswith(".xml") and len(targets)<2 and (
                "product" in pp.path.casefold()):
                targets.append(raw_link)
                continue
            if (model in _words(pp.path) and len(pp.path)>12 and
                _https_public(raw_link)):
                urls.append(raw_link.split("#",1)[0])
                if len(urls)>5:break
        if len(urls)>5:break
    return list(dict.fromkeys(urls))


def execute_generic_sources(offer,category,fetch=None,enable_brand_discovery=True):
    """Three documented attempts maximum: seller/direct and one brand page.

    Each URL is individually validated, robots checked and fetched with
    pinned public-IP TLS. A 403 is preserved and never followed by a stealth
    browser. In absence of a matched URL, returns no verified source.
    """
    candidates=candidate_urls(offer)
    attempted=[]
    if enable_brand_discovery:
        identity=product_identity(offer.get("title"))
        if identity and identity["brand"] not in REJECT_BRAND_DOMAINS:
            # A candidate brand domain is a discovery hypothesis ONLY.
            # No maker authority or URL is inferred from a DNS response.
            hostname=identity["brand"]+".com"
            home="https://"+hostname+"/"
            try:
                doc=_robot_checked_read(home,fetch=fetch)
                parsed=parse_html_document(doc)
                # Home must actually identify the brand, and must contain
                # an explicit SAME-ORIGIN product link with exact model.
                home_title=" ".join(parsed.h1+parsed.title+parsed.buffer[:35])
                if identity["brand"] not in _words(home_title):
                    raise ValueError("BRAND_HOME_IDENTITY_NOT_CONFIRMED")
                found=[]
                for href in parsed.links:
                    if len(found)>5:break
                    u=urljoin(home,href)
                    pp=urlsplit(u)
                    if (pp.scheme!="https" or pp.hostname!=hostname or
                        pp.port not in (None,443) or
                        pp.path.count("/")<2):continue
                    if identity["model"] not in _words(pp.path):continue
                    if _https_public(u):found.append(u.split("#",1)[0])
                unique=list(dict.fromkeys(found))
                if not unique:
                    # General sitemap discovery for manufacturers whose home
                    # page does not directly link to the specific model.
                    unique=_sitemap_model_links(
                        home,identity["model"],fetch=fetch)
                if len(unique)==1 and not any(
                        x["url"]==unique[0] for x in candidates):
                    candidates.append({"url":unique[0],
                        "scope":"BRAND_HOME_PRODUCT_LINK"})
            except (ValueError,OSError,TypeError,KeyError) as e:
                attempted.append({
                    "discovery":"BRAND_SITE_CANDIDATE",
                    "status":"NO_MATCHED_BRAND_DOCUMENT_"+type(e).__name__,
                    "brand_domain_hypothesis":hostname,
                })
    docs=[]
    seen=set()
    for row in candidates[:3]:
        url=row["url"]
        if url in seen:continue
        seen.add(url)
        try:
            raw=_robot_checked_read(url,fetch=fetch)
            parsed=parse_source_claims(raw,offer,category,url,row["scope"])
            method="SAFE_STATIC_HTTPS"
            # Browser is a REAL graphical Chromium on a disposable Xvfb
            # display, never an antibot bypass. Only run if static GET was
            # allowed, returned HTTP 200, and lacked usable product details.
            if not parsed["claims"]:
                from browser_render import rendered_browser_document
                try:
                    rendered=rendered_browser_document(url,raw)
                    improved=parse_source_claims(
                        rendered,offer,category,url,row["scope"])
                    if improved["claims"]:
                        parsed=improved
                        method="ISOLATED_XVFB_CHROMIUM"
                except (ValueError,OSError) as exc:
                    # The original HTTP attempt remains auditable; no browser
                    # result or invented source if rendering was not permitted.
                    method="SAFE_STATIC_HTTPS"
            attempted.append({"url":url,"scope":row["scope"],
                "status":parsed["status"],"method":method,
                "properties":len(parsed["claims"])})
            if parsed["claims"]:
                docs.append({"url":url,"scope":row["scope"],"result":parsed})
        except (ValueError,OSError,TypeError,KeyError) as exc:
            attempted.append({"url":url,"scope":row["scope"],
                "status":"NOT_RETRIEVED_"+type(exc).__name__})
    rows=[]
    for d in docs:
        rows.extend(d["result"]["claims"])
    if not rows:
        return {"status":"NO_MATCHED_GENERAL_PRODUCT_SOURCE",
                "reference_answers":[],"verified_for_exact_offer":0,
                "sources_checked":0,"attempted_sources":attempted}
    return {"status":"GENERAL_DOCUMENT_DECLARATIONS_FETCHED_SKU_UNVERIFIED",
            "reference_answers":rows[:18],"verified_for_exact_offer":0,
            "sources_checked":len(docs),
            "attempted_sources":attempted,
            "independent_tests":0,
            "documented_declarations":len(rows)}
