"""In-memory consent-gated queue for an optional local browser companion.

No merchant fetches, no checkout, no credentials or site cookies.
Only a strict Product/Offer projection from an opt-in browser is accepted.
"""
from datetime import datetime, timezone
import hmac
import json
import os
from pathlib import Path
import re
import secrets
from threading import Lock
import time
from urllib.parse import urlsplit

from product_intake import validate_product_url
from universal_product_extract import extract_snapshot

MAX_PENDING = 12
MAX_HISTORY = 60
MAX_CAPTURE = 12000
LEASE_SECONDS = 90
FAILURES = frozenset((
    "SITE_PERMISSION_REQUIRED", "REDIRECTED", "ACCESS_CHALLENGE",
    "NO_STRUCTURED_PRODUCT", "MULTIPLE_PRODUCTS_AMBIGUOUS",
    "CONFLICTING_PRODUCT_IDENTITY", "CONFLICTING_OFFER_EVIDENCE",
    "TAB_TIMEOUT", "BROWSER_ERROR",
))
PRICE_ORIGINS = frozenset(("DIRECT_OFFER_PRICE",
                           "EXPLICIT_SALE_PRICE_SPECIFICATION",
                           "UNTYPED_PRICE_SPECIFICATION",
                           "PRODUCT_OFFER_MICRODATA",
                           "WOOCOMMERCE_PRIMARY_PRICE"))
_ALLOWED_PRODUCT = frozenset(("@type", "name", "brand", "model", "sku",
                              "gtin", "gtin8", "gtin12", "gtin13", "gtin14",
                              "offers"))
_ALLOWED_OFFER = frozenset(("@type", "price", "priceCurrency",
                            "availability", "itemCondition", "seller"))
_ALLOWED_NAME = frozenset(("@type", "name"))


def _plain(value, size=180):
    return type(value) is str and 0 < len(value) <= size and not any(
        ord(c) < 32 for c in value)


def _validate_snapshot(value):
    """Prevent unexpected browser data (including cookies, tokens and HTML)."""
    if type(value) is not dict or set(value) - _ALLOWED_PRODUCT:
        raise ValueError("UNEXPECTED_PRODUCT_FIELDS")
    if value.get("@type") != "Product" or not _plain(value.get("name")):
        raise ValueError("INVALID_PRODUCT_IDENTITY")
    for k in ("model", "sku", "gtin", "gtin8", "gtin12", "gtin13", "gtin14"):
        if k in value and not _plain(value[k]):
            raise ValueError("INVALID_PRODUCT_FIELD")
    brand = value.get("brand")
    if brand is not None and not (_plain(brand) or (
            type(brand) is dict and set(brand) == {"name"}
            and _plain(brand["name"]))):
        raise ValueError("INVALID_BRAND")
    offer = value.get("offers")
    if type(offer) is not dict or set(offer) - _ALLOWED_OFFER:
        raise ValueError("INVALID_OFFER_FIELDS")
    if offer.get("@type") != "Offer":
        raise ValueError("NOT_AN_INDIVIDUAL_OFFER")
    price = offer.get("price")
    if not _plain(str(price), 16) or not re.fullmatch(
            r"(?:0|[1-9][0-9]{0,5})(?:[.][0-9]{1,2})?", str(price)):
        raise ValueError("INVALID_PRICE_CLAIM")
    if offer.get("priceCurrency") not in ("PLN", "EUR", "USD"):
        raise ValueError("INVALID_CURRENCY")
    for key in ("availability", "itemCondition"):
        if key in offer and not _plain(offer[key], 100):
            raise ValueError("INVALID_OFFER_FIELD")
    seller = offer.get("seller")
    if seller is not None and not (_plain(seller, 150) or (
            type(seller) is dict and set(seller) == {"name"}
            and _plain(seller["name"], 150))):
        raise ValueError("INVALID_SELLER")
    if len(json.dumps(value, ensure_ascii=False).encode("utf8")) > MAX_CAPTURE:
        raise ValueError("OVERSIZED_PRODUCT_PROJECTION")
    return value


def _validate_coupon_promotion(value, snapshot):
    """A conditional visible coupon claim, never a checkout total."""
    from decimal import Decimal
    if value is None:
        return None
    if (type(value) is not dict or set(value)!={
            "price","currency","code","valid_until","source"}):
        raise ValueError("INVALID_COUPON_PROJECTION")
    price=value["price"]
    code=value["code"]
    currency=value["currency"]
    until=value["valid_until"]
    if (type(price) is not str or not
            re.fullmatch(r"(?:0|[1-9][0-9]{0,5})[.][0-9]{2}",price) or
            type(code) is not str or not re.fullmatch(r"[A-Z0-9_-]{4,30}",code) or
            not re.search(r"[A-Z]",code) or not re.search(r"[0-9]",code) or
            currency!=snapshot["offers"]["priceCurrency"] or
            value["source"]!="VISIBLE_PRODUCT_PRICE_WITH_CODE"):
        raise ValueError("INVALID_COUPON_PROJECTION")
    if (Decimal(price)>=Decimal(str(snapshot["offers"]["price"])) or
            Decimal(price)<=Decimal("0")):
        raise ValueError("INVALID_COUPON_PRICE_RELATION")
    if until is not None:
        if type(until) is not str or not re.fullmatch(
                r"20[0-9]{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])",until):
            raise ValueError("INVALID_COUPON_EXPIRY")
        try:
            datetime.fromisoformat(until)
        except ValueError as exc:
            raise ValueError("INVALID_COUPON_EXPIRY") from exc
    return {"price":price,"currency":currency,"code":code,
            "valid_until":until,"source":value["source"],
            "condition":"CODE_REQUIRED",
            "checkout_verified":False,"code_applied":False}

def _capture_time(stamp, now=None):
    if not _plain(stamp, 45):
        raise ValueError("INVALID_CAPTURE_TIME")
    try:
        captured = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("INVALID_CAPTURE_TIME") from exc
    if captured.tzinfo is None:
        raise ValueError("INVALID_CAPTURE_TIME")
    if abs((captured - (now or datetime.now(timezone.utc))).total_seconds()) > 180:
        raise ValueError("STALE_CAPTURE")


def _load_token(path):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise ValueError("INSECURE_COMPANION_TOKEN_FILE")
        token = path.read_text(encoding="ascii").strip()
        if len(token) != 64 or not re.fullmatch(r"[0-9a-f]{64}", token):
            raise ValueError("INVALID_COMPANION_TOKEN")
        return token
    token = secrets.token_hex(32)
    # O_EXCL ensures we do not overwrite an existing file / follow symlinks.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(token + "\n")
    except Exception:
        path.unlink(missing_ok=True) if hasattr(path, "unlink") else None
        raise
    return token


class CompanionQueue:
    def __init__(self, token_path=None, token=None, clock=None):
        if token_path and token:
            raise ValueError("Provide token or token_path")
        self.token = (_load_token(token_path) if token_path else
                      token if token is not None else secrets.token_hex(32))
        self.clock = clock or time.monotonic
        self.jobs = []
        self.lock = Lock()

    def authorized(self, provided):
        return bool(type(provided) is str and hmac.compare_digest(provided, self.token))

    def _expire(self):
        now = self.clock()
        for row in self.jobs:
            if row["status"] == "IN_PROGRESS" and now - row["leased_at"] > LEASE_SECONDS:
                row["status"] = "TAB_TIMEOUT"
                row["result"] = None

    def enqueue(self, url):
        return self.enqueue_many([url])[0]

    def enqueue_many(self, urls):
        """Atomically reserve a bounded, user-submitted batch."""
        if type(urls) is not list or not 1 <= len(urls) <= MAX_PENDING:
            raise ValueError("INVALID_COMPANION_BATCH")
        safe = [validate_product_url(url) for url in urls]
        for url in safe:
            p = urlsplit(url)
            if len(url) > 900 or (p.query and len(p.query) > 180):
                raise ValueError("PRODUCT_URL_TOO_LONG")
        if len(set(safe)) != len(safe):
            raise ValueError("DUPLICATE_BATCH_PRODUCT")
        with self.lock:
            self._expire()
            pending = [r["url"] for r in self.jobs
                       if r["status"] in ("QUEUED", "IN_PROGRESS")]
            if len(pending)+len(safe) > MAX_PENDING:
                raise ValueError("COMPANION_QUEUE_FULL")
            if set(pending).intersection(safe):
                raise ValueError("DUPLICATE_PENDING_PRODUCT")
            added=[]
            for url in safe:
                row = {"id": secrets.token_urlsafe(18), "url": url,
                       "status": "QUEUED",
                       "created_at": datetime.now(timezone.utc).isoformat(),
                       "leased_at": None, "result": None}
                self.jobs.append(row)
                added.append(row["id"])
            if len(self.jobs) > MAX_HISTORY:
                self.jobs[:] = self.jobs[-MAX_HISTORY:]
            return added

    def take(self):
        with self.lock:
            self._expire()
            for row in self.jobs:
                if row["status"] == "QUEUED":
                    row["status"] = "IN_PROGRESS"
                    row["leased_at"] = self.clock()
                    return {"job_id": row["id"], "url": row["url"]}
        return None

    def report(self, payload):
        expected={"job_id", "url", "captured_at", "snapshot",
                  "price_origin", "error"}
        if type(payload) is not dict or set(payload) not in (
                expected,expected | {"promotion"}):
            raise ValueError("INVALID_CAPTURE_RECEIPT")
        job_id = payload["job_id"]
        with self.lock:
            self._expire()
            row = next((r for r in self.jobs if r["id"] == job_id), None)
            if row is None or row["status"] != "IN_PROGRESS":
                raise ValueError("JOB_NOT_LEASED")
            if payload["url"] != row["url"]:
                raise ValueError("CAPTURE_URL_MISMATCH")
            if payload["error"] is not None:
                if (payload["error"] not in FAILURES or
                        payload["snapshot"] is not None or
                        payload["price_origin"] is not None or
                        payload.get("promotion") is not None):
                    raise ValueError("INVALID_FAILURE_RECEIPT")
                row["status"] = payload["error"]
                row["result"] = None
                return {"job_id": job_id, "status": row["status"]}
            _capture_time(payload["captured_at"])
            if payload["price_origin"] not in PRICE_ORIGINS:
                raise ValueError("UNKNOWN_BROWSER_PRICE_SOURCE")
            snapshot = _validate_snapshot(payload["snapshot"])
            promotion=_validate_coupon_promotion(payload.get("promotion"),snapshot)
            raw = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf8")
            extracted = extract_snapshot(row["url"], raw, content_type="application/ld+json",
                                         acquisition_method="USER_BROWSER",
                                         acquired_at=payload["captured_at"])
            if promotion:
                extracted["browser_promotion"]=promotion
            extracted["browser_original_price_origin"] = payload["price_origin"]
            extracted["browser_projection_scope"] = "FILTERED_PRODUCT_OFFER_ONLY"
            for claim in extracted["evidence"]:
                if claim["field"] in ("price", "currency"):
                    claim["browser_original_price_origin"] = payload["price_origin"]
            row["result"] = extracted
            row["status"] = extracted["status"]
            # Strictly segregated from verified live seller/checkout flows.
            return {"job_id": job_id, "status": row["status"]}

    def get_job(self, job_id):
        if type(job_id) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{24}", job_id):
            raise ValueError("INVALID_COMPANION_JOB_ID")
        with self.lock:
            self._expire()
            row = next((r for r in self.jobs if r["id"] == job_id), None)
            if row is None:
                raise ValueError("UNKNOWN_COMPANION_JOB")
            return {
                "id": row["id"], "url": row["url"], "status": row["status"],
                "created_at": row["created_at"], "result": row["result"],
            }

    def listed(self):
        with self.lock:
            self._expire()
            return [
                {"id": r["id"], "url": r["url"], "status": r["status"],
                 "created_at": r["created_at"], "result": r["result"]}
                for r in reversed(self.jobs)
            ]
