"""Bounded PayPal Sandbox-only approval for recommended research offers.

Never purchases at a third-party shop, captures money or treats indexed
prices as verified checkout totals. The user explicitly confirms the
illustrative listed value before a one-shot PayPal sandbox order.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import re
import secrets
import sqlite3
import time
from urllib.parse import urlsplit, parse_qs
from core import SANDBOX_API, _request_json, SandboxPayPal

CONSENT = "I APPROVE SANDBOX DEMO"
QUOTE_SECONDS = 900
CURRENCIES = frozenset(("PLN", "USD", "EUR"))


def valid_amount(value, currency):
    if type(value) is not str or not re.fullmatch(r"[0-9]{1,7}\.[0-9]{2}", value):
        raise ValueError("INVALID_INDEXED_AMOUNT")
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ValueError("INVALID_INDEXED_AMOUNT")
    if currency not in CURRENCIES or amount <= 0 or amount > Decimal("50000.00"):
        raise ValueError("INVALID_INDEXED_AMOUNT")
    return value


def recommended_offer(jobs, job_id, offer_id):
    """Only server-recomputed actual recommended offers, not arbitrary SKU/price."""
    if type(offer_id) is not str or not re.fullmatch(r"offer-[0-9]{1,4}", offer_id):
        raise ValueError("INVALID_RECOMMENDATION_ID")
    record = jobs.read(job_id)
    if record["state"] != "READY":
        raise ValueError("RESEARCH_NOT_READY")
    _, snapshot = jobs.live_snapshot(job_id)
    # The live evidence assessment is preferred. Historical finished jobs
    # may only have the stored final model result.
    assessment = snapshot.get("instant_assessment") or {}
    reports = [assessment.get("purchase_insights") or {},
               (snapshot.get("final_verdict") or {}).get("purchase_insights") or {}]
    for report in reports:
        for group in ("options", "tradeoffs"):
            for offer in (report.get(group) or []):
                if offer.get("offer_id") != offer_id:
                    continue
                title = offer.get("title")
                currency = offer.get("currency")
                price = valid_amount(offer.get("price"), currency)
                graph = snapshot.get("graph") or {}
                nodes = graph.get("nodes") or []
                if not any(n.get("id") == offer_id and n.get("type") == "offer"
                           for n in nodes):
                    raise ValueError("RECOMMENDATION_GRAPH_MISMATCH")
                if type(title) is not str or not 1 <= len(title) <= 400:
                    raise ValueError("INVALID_RECOMMENDATION_TITLE")
                return {"offer_id": offer_id, "title": title, "total": price,
                        "currency": currency,
                        "source_url": offer.get("source_url") or "",
                        "price_status": "INDEXED_LISTING_NOT_CHECKOUT_VERIFIED"}
    raise ValueError("RECOMMENDATION_NOT_FOUND")


def check_paypal_reply(response, row, require_approval_link):
    if type(response) is not dict:
        raise ValueError("PAYPAL_INVALID_RESPONSE")
    order_id = response.get("id")
    if type(order_id) is not str or not re.fullmatch(r"[A-Za-z0-9-]{6,64}", order_id):
        raise ValueError("PAYPAL_ID_INVALID")
    units = response.get("purchase_units")
    if type(units) is not list or len(units) != 1 or type(units[0]) is not dict:
        raise ValueError("PAYPAL_PURCHASE_UNITS_MISSING")
    unit = units[0]
    amount = unit.get("amount")
    if (unit.get("reference_id") != row["id"] or
            type(amount) is not dict or
            amount.get("value") != row["total"] or
            amount.get("currency_code") != row["currency"]):
        raise ValueError("PAYPAL_QUOTE_MISMATCH")
    if not require_approval_link:
        return order_id, None
    status = response.get("status")
    if status not in ("CREATED", "PAYER_ACTION_REQUIRED", "SAVED", "APPROVED"):
        raise ValueError("PAYPAL_INVALID_INITIAL_STATUS")
    links = response.get("links")
    if type(links) is not list:
        raise ValueError("PAYPAL_APPROVAL_LINK_MISSING")
    for link in links:
        if type(link) is not dict or link.get("rel") not in ("approve", "payer-action"):
            continue
        uri = link.get("href")
        if type(uri) is not str:
            continue
        u = urlsplit(uri)
        if (u.scheme == "https" and u.hostname == "www.sandbox.paypal.com"
                and u.username is None and u.password is None and
                u.port in (None,443) and u.path.startswith("/checkoutnow")
                and parse_qs(u.query).get("token") == [order_id]):
            return order_id, uri
    raise ValueError("PAYPAL_APPROVAL_LINK_INVALID")


class OfferSandboxOrders:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS offer_sandbox_orders(
              id TEXT PRIMARY KEY, research_id TEXT NOT NULL, offer_id TEXT NOT NULL,
              title TEXT NOT NULL, source_url TEXT NOT NULL,
              total TEXT NOT NULL, currency TEXT NOT NULL,
              state TEXT NOT NULL, created REAL NOT NULL,
              approved REAL, request_id TEXT NOT NULL UNIQUE,
              paypal_id TEXT, approval_url TEXT)""")
            db.execute("""CREATE INDEX IF NOT EXISTS offer_sandbox_research_idx
                ON offer_sandbox_orders(research_id)""")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=5000")
        return db

    def select(self, jobs, job_id, offer_id):
        candidate = recommended_offer(jobs, job_id, offer_id)
        quote_id, request_id = secrets.token_urlsafe(22), secrets.token_hex(18)
        with self.connect() as db:
            db.execute("""INSERT INTO offer_sandbox_orders
               (id,research_id,offer_id,title,source_url,total,currency,
                state,created,request_id) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (quote_id,job_id,offer_id,candidate["title"],
                 candidate["source_url"],candidate["total"],
                 candidate["currency"],"QUOTED",time.time(),request_id))
        return quote_id

    def start(self, jobs, job_id, offer_id):
        """A single explicit Pay with PayPal click starts a Sandbox-only
        quote. Its price comes from persisted evidence, never the browser.

        This records the user's *click intent*, NOT a fabricated typed
        consent phrase. The buyer still approves at PayPal's own checkout.
        """
        quote_id=self.select(jobs,job_id,offer_id)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor=db.execute(
                """UPDATE offer_sandbox_orders
                   SET state='APPROVED', approved=?
                   WHERE id=? AND state='QUOTED'""",
                (time.time(),quote_id))
            if cursor.rowcount!=1:
                raise ValueError("SANDBOX_START_FAILED")
        return self.read(quote_id)

    def read(self, quote_id, internal=False):
        if type(quote_id) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{20,50}",quote_id):
            raise ValueError("INVALID_QUOTE")
        with self.connect() as db:
            row = db.execute("SELECT * FROM offer_sandbox_orders WHERE id=?", (quote_id,)).fetchone()
        if row is None:
            raise ValueError("UNKNOWN_SANDBOX_QUOTE")
        data = dict(row)
        if not internal:
            data.pop("request_id")
        return data

    def approve(self, quote_id, consent, amount):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM offer_sandbox_orders WHERE id=?", (quote_id,)).fetchone()
            if row is None or row["state"] != "QUOTED":
                raise ValueError("QUOTE_NOT_AWAITING_APPROVAL")
            if time.time()-row["created"] > QUOTE_SECONDS:
                raise ValueError("QUOTE_EXPIRED")
            if consent != CONSENT or amount != row["total"]:
                raise ValueError("CONSENT_OR_AMOUNT_MISMATCH")
            db.execute("UPDATE offer_sandbox_orders SET state='APPROVED',approved=? WHERE id=?",
                       (time.time(),quote_id))
        return self.read(quote_id)

    def create(self, quote_id, gateway=None, return_port=8810):
        if type(return_port) is not int or not 1 <= return_port <= 65535:
            raise ValueError("INVALID_SANDBOX_RETURN_PORT")
        gateway = gateway or SandboxPayPal()
        initial = self.read(quote_id, internal=True)
        if initial["state"] != "APPROVED":
            raise ValueError("SANDBOX_ORDER_ALREADY_STARTED_OR_NOT_APPROVED")
        if time.time()-initial["approved"] > QUOTE_SECONDS:
            raise ValueError("SANDBOX_CONSENT_EXPIRED")
        gateway.preflight()  # OAuth failure cannot have created an order.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM offer_sandbox_orders WHERE id=?", (quote_id,)).fetchone()
            if row is None or row["state"] != "APPROVED":
                raise ValueError("SANDBOX_ORDER_ALREADY_STARTED_OR_NOT_APPROVED")
            if time.time()-row["approved"] > QUOTE_SECONDS:
                raise ValueError("SANDBOX_CONSENT_EXPIRED")
            db.execute("UPDATE offer_sandbox_orders SET state='CREATE_UNCERTAIN' WHERE id=?",(quote_id,))
            record = dict(row)
        # After this point we NEVER automatically repeat a create POST.
        token = gateway._token()
        # Local browser returns to the same explicit review page after the
        # hosted Sandbox approval (or cancellation). This URL is built from
        # the listening server port, never a caller-supplied Host or AI value.
        return_url="http://127.0.0.1:{}/cart/sandbox/{}".format(
            return_port,record["id"])
        payload = json.dumps({
            "intent": "CAPTURE",
            "payment_source": {"paypal": {"experience_context": {
                "return_url": return_url,
                "cancel_url": return_url,
                "shipping_preference": "NO_SHIPPING",
                "user_action": "CONTINUE",
            }}},
            "purchase_units": [{
                "reference_id":record["id"],
                "description": "TraceCart test intermediary (fictional offer; no fulfillment)",
                "amount": {"currency_code":record["currency"], "value":record["total"]},
            }]
        }).encode("utf-8")
        result = _request_json(
            SANDBOX_API+"/v2/checkout/orders", "POST", payload,
            {"Authorization":"Bearer "+token,"PayPal-Request-Id":record["request_id"],
             "Content-Type":"application/json","Prefer":"return=representation"},
        )
        order_id,approval_url=check_paypal_reply(result,record,True)
        with self.connect() as db:
            db.execute("""UPDATE offer_sandbox_orders SET state='PAYER_ACTION_REQUIRED',
                       paypal_id=?,approval_url=? WHERE id=? AND state='CREATE_UNCERTAIN'""",
                       (order_id,approval_url,quote_id))
        return self.read(quote_id)

    def verify(self, quote_id, gateway=None):
        quote = self.read(quote_id)
        if quote["state"] not in ("PAYER_ACTION_REQUIRED", "VERIFIED_APPROVED"):
            raise ValueError("PAYPAL_ORDER_NOT_READY")
        if quote["state"] == "VERIFIED_APPROVED":
            return quote
        gateway = gateway or SandboxPayPal()
        response = gateway.get_order(quote["paypal_id"])  # strictly read-only
        order_id,_=check_paypal_reply(response,quote,False)
        if order_id != quote["paypal_id"]:
            raise ValueError("PAYPAL_ORDER_ID_MISMATCH")
        if response.get("status") == "APPROVED":
            with self.connect() as db:
                db.execute("""UPDATE offer_sandbox_orders SET state='VERIFIED_APPROVED'
                   WHERE id=? AND state='PAYER_ACTION_REQUIRED'""",(quote_id,))
        return self.read(quote_id)
