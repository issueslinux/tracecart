"""Bounded read-only retailer-link safety signals; never a scam certification.

Checks ALL available merchant/source URLs without interacting with checkout,
defeating bot protections, fetching untrusted HTML, or sending credentials.
HTTPS/DNS + official registry age are necessary context, NOT evidence a store
is honest. No fraud database is queried unless an approved provider exists.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import ipaddress
import json
import re
import socket
import ssl
from urllib.parse import urlsplit

from product_intake import validate_product_url, _public_ip, _read

MAX_LINKS=60
MAX_HOSTS=25
MAX_WORKERS=6
COMMON_SUFFIXES={"co.uk","org.uk","com.pl","net.pl","org.pl","gov.pl",
                 "co.jp","com.au","co.nz","com.br"}
COMMON_BRANDS={"allegro","amazon","mediaexpert","mediamarkt","paypal",
               "ebay","xkom","morele"}


def root_domain(hostname):
    parts=str(hostname).lower().split(".")
    if len(parts)<2:return None
    suffix=".".join(parts[-2:])
    if suffix in COMMON_SUFFIXES and len(parts)>=3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def rdap_registration(host,reader=None):
    """Official NASK and Verisign RDAP, never arbitrary registry URLs."""
    root=root_domain(host)
    if not root:return {"status":"NO_REGISTRABLE_DOMAIN"}
    if root.endswith(".pl"):
        uri="https://rdap.dns.pl/domain/"+root
    elif root.endswith(".com"):
        uri="https://rdap.verisign.com/com/v1/domain/"+root
    else:
        return {"status":"REGISTRY_NOT_CONFIGURED"}
    try:
        getter=reader or (lambda url: _read(
            url,100000,("application/rdap+json","application/json"),timeout=3))
        raw=getter(uri)
        data=json.loads(raw)
        if not isinstance(data,dict) or str(data.get("ldhName") or "").lower()!=root:
            return {"status":"REGISTRY_RESPONSE_INVALID"}
        dates=[]
        for event in data.get("events") or []:
            if not isinstance(event,dict) or event.get("eventAction")!="registration":
                continue
            try:
                stamp=datetime.fromisoformat(str(event.get("eventDate")).replace("Z","+00:00"))
                if stamp.tzinfo and stamp<=datetime.now(timezone.utc):
                    dates.append(stamp)
            except ValueError:
                pass
        registered=min(dates) if dates else None
        return {"status":"REGISTRY_DATA_FOUND",
                "registered_at":registered.date().isoformat() if registered else None,
                "age_days":(datetime.now(timezone.utc)-registered).days
                           if registered else None,
                "registration_source":uri}
    except (OSError,ValueError,TypeError,KeyError,RuntimeError,
            TimeoutError,ssl.SSLError,ConnectionError):
        return {"status":"REGISTRY_UNAVAILABLE"}


def _tls_check(host,timeout=3):
    address=_public_ip(host)
    with socket.create_connection((address,443),timeout=timeout) as sock:
        with ssl.create_default_context().wrap_socket(sock,server_hostname=host) as tls:
            cert=tls.getpeercert()
            return {"valid":bool(cert),"tls_version":str(tls.version() or "")[:20]}


def _host_report(host,dns=None,tls=None,rdap=None):
    signals=[]
    resolver=dns or _public_ip
    checker=tls or _tls_check
    try:
        ip=resolver(host)
        # Even injected DNS results must be validated: never connect to
        # loopback, private, multicast, link-local or reserved networks.
        if not ipaddress.ip_address(ip).is_global:
            return {"status":"HIGH_RISK_SIGNALS",
                    "signals":["DESTINATION_NOT_PUBLIC"],
                    "dns_status":"NON_PUBLIC_ADDRESS",
                    "tls_status":"NOT_PROBED",
                    "registration":{"status":"NOT_CHECKED"},
                    "legitimacy_verified":False}
        dns_status="PUBLIC_ADDRESS"
    except (OSError,ValueError,TypeError,RuntimeError,TimeoutError):
        return {"status":"INCONCLUSIVE",
                "signals":["DNS_LOOKUP_UNAVAILABLE"],
                "dns_status":"UNAVAILABLE","tls_status":"NOT_PROBED",
                "registration":{"status":"NOT_CHECKED"},
                "legitimacy_verified":False}
    try:
        result=checker(host)
        tls_status="VALID_CERTIFICATE" if result.get("valid") else "NO_VERIFIED_CERTIFICATE"
        if tls_status!="VALID_CERTIFICATE":signals.append("TLS_NOT_VERIFIED")
    except (OSError,ValueError,TypeError,RuntimeError,
            TimeoutError,ssl.SSLError,ConnectionError):
        tls_status="TLS_CHECK_FAILED"
        signals.append("TLS_CERTIFICATE_OR_CONNECTION_NOT_VERIFIED")
    registration=(rdap or rdap_registration)(host)
    if not isinstance(registration,dict):
        registration={"status":"REGISTRY_UNAVAILABLE"}
    age=registration.get("age_days")
    if isinstance(age,int) and 0<=age<90:
        signals.append("RECENTLY_REGISTERED_DOMAIN_UNDER_90_DAYS")
    status=("REVIEW_REQUIRED" if signals else
            "BASIC_TECHNICAL_CHECKS_PASSED" if
            tls_status=="VALID_CERTIFICATE" else "INCONCLUSIVE")
    return {"status":status,"signals":signals,
            "dns_status":dns_status,"tls_status":tls_status,
            "registration":registration,
            "legitimacy_verified":False,
            "fraud_database_screened":False}


def assess_links(offers,source_urls=(),dns=None,tls=None,rdap=None,
                 max_links=MAX_LINKS,workers=MAX_WORKERS):
    """Assess unique links per URL and cache DNS/TLS/RDAP by full hostname.

    Offers without URLs are counted but cannot be security-scanned.
    No links are opened in a browser, no bot challenge is bypassed.
    """
    entries=[]
    no_url=0
    used=set()
    for o in list(offers or [])[:MAX_LINKS]:
        if not isinstance(o,dict):continue
        url=o.get("url")
        if not url:
            no_url+=1
            continue
        key=str(url)
        if key in used:
            for item in entries:
                if item["url"]==key:
                    item["offer_ids"].append(o.get("id"))
                    break
            continue
        used.add(key)
        entries.append({"url":key,"offer_ids":[o.get("id")],"kind":"SELLER_LISTING"})
    for record in list(source_urls or [])[:MAX_LINKS]:
        url=record.get("url") if isinstance(record,dict) else record
        if not isinstance(url,str) or url in used:continue
        used.add(url)
        entries.append({"url":url,"offer_ids":[],"kind":"RESEARCH_SOURCE"})
    entries=entries[:max(1,min(max_links,MAX_LINKS))]
    validated=[]
    hosts=[]
    for entry in entries:
        try:
            safe=validate_product_url(entry["url"])
            host=urlsplit(safe).hostname
            entry["domain"]=host
            entry["url_check"]="PUBLIC_HTTPS_URL_SYNTAX"
            if host not in hosts:hosts.append(host)
        except (ValueError,TypeError):
            entry["domain"]=None
            entry["url_check"]="INVALID_OR_UNSAFE_URL"
            entry["risk"]={"status":"HIGH_RISK_SIGNALS",
                           "signals":["INVALID_OR_UNSAFE_LINK"],
                           "legitimacy_verified":False,
                           "fraud_database_screened":False}
        validated.append(entry)
    hosts=hosts[:MAX_HOSTS]
    host_results={}
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS,max(1,workers),
                                             max(1,len(hosts)))) as pool:
        futures={pool.submit(_host_report,host,dns,tls,rdap):host
                 for host in hosts}
        for future in as_completed(futures):
            host=futures[future]
            try:host_results[host]=future.result()
            except Exception:host_results[host]={
                "status":"INCONCLUSIVE","signals":["CHECK_NOT_COMPLETED"],
                "legitimacy_verified":False,"fraud_database_screened":False}
    for entry in validated:
        host=entry.get("domain")
        if not host:continue
        risk=dict(host_results.get(host,{"status":"INCONCLUSIVE",
                                        "signals":["HOST_LIMIT_REACHED"]}))
        if host.startswith("xn--") or ".xn--" in host:
            risk["signals"]=list(risk.get("signals",[]))+["PUNYCODE_DOMAIN_REVIEW"]
            risk["status"]="REVIEW_REQUIRED"
        # Flag common brand names in a third-party host/subdomain, but
        # NEVER label such a signal as a verified impersonation attempt.
        root=root_domain(host)
        for label in host.split(".")[:-2]:
            if label in COMMON_BRANDS and not root.startswith(label+"."):
                risk["signals"]=list(risk.get("signals",[]))+[
                    "BRAND_NAME_IN_THIRD_PARTY_SUBDOMAIN"]
                risk["status"]="REVIEW_REQUIRED"
                break
        entry["risk"]=risk
    return {
        "status":"COMPLETE",
        "links":validated,
        "total_offer_records":len(list(offers or [])),
        "unique_links_checked":len(validated),
        "hosts_checked":len(host_results),
        "index_cards_without_direct_url":no_url,
        "limits":{"max_links":MAX_LINKS,"max_hosts":MAX_HOSTS},
        "scope":"URL_SYNTAX_PUBLIC_DNS_TLS_CERT_AND_AVAILABLE_RDAP_ONLY",
        "merchant_legitimacy_verified":False,
        "independent_fraud_reputation_checked":False,
        "disclaimer":(
            "Valid HTTPS or an old registered domain does NOT prove that a shop is "
            "legitimate. A risk signal is NOT proof of fraud. This assessment does "
            "not check national business registers, chargebacks, customer complaints "
            "or an independent phishing/malware reputation database."),
    }
