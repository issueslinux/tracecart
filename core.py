"""TraceCart: consent-gated, SANDBOX-ONLY PayPal order preparation.

Model output may suggest a catalog SKU and quantity, but cannot set prices,
approve an order, select hosts, or capture money. No live PayPal API is used.
"""
import base64
from decimal import Decimal
import json
import os
import re
import secrets
import sqlite3
import time
from urllib.parse import urlsplit, parse_qs
from urllib.request import Request, build_opener, HTTPRedirectHandler

CATALOG = {
    "ceramic-pendant": ("Vintage ceramic pendant", Decimal("29.00")),
    "restoration-kit": ("Small ceramic restoration kit", Decimal("39.00")),
    "archive-consult": ("Archive consultation", Decimal("75.00")),
}
CURRENCY = "USD"
SANDBOX_API = "https://api-m.sandbox.paypal.com"
CONSENT_TEXT = "I APPROVE SANDBOX CHECKOUT"
QUOTE_TTL_S = 900


def money(v):
    return str(Decimal(v).quantize(Decimal("0.01")))


def validate_selection(sku, quantity):
    if type(sku) is not str or sku not in CATALOG:
        raise ValueError("Unknown catalog SKU; no arbitrary products allowed")
    if type(quantity) is not int or not (1 <= quantity <= 3):
        raise ValueError("Quantity must be integer 1..3")
    total = CATALOG[sku][1] * quantity
    if total > Decimal("200.00"):
        raise ValueError("Transaction amount exceeds demo policy")
    return money(total)


def parse_model_selection(answer):
    """Only SKU and bounded quantity survive the untrusted model output."""
    if not isinstance(answer, str) or len(answer) > 4096:
        raise ValueError("Invalid AI response")
    try:
        obj = json.loads(answer)
    except (TypeError, ValueError):
        raise ValueError("Model returned invalid JSON")
    if type(obj) is not dict or set(obj) != {"sku", "quantity"}:
        raise ValueError("Model response must contain only sku and quantity")
    total = validate_selection(obj["sku"], obj["quantity"])
    return obj["sku"], obj["quantity"], total


def ollama_suggestion(prompt, url="http://127.0.0.1:11435", model="qwen2.5:1.5b-instruct"):
    if not isinstance(prompt, str) or not 3 <= len(prompt) <= 500:
        raise ValueError("Describe the desired product in 3..500 characters")
    if url not in ("http://127.0.0.1:11435", "http://127.0.0.1:11434"):
        raise ValueError("Only known local Ollama endpoints are allowed")
    menu = ", ".join("{}: {}".format(k, v[0]) for k, v in CATALOG.items())
    msg = ("Map the user's request to one available catalog SKU and quantity. "
           "Respond ONLY with a JSON object with exactly two keys: sku and quantity. "
           "Never add prices, amounts, merchant IDs or approval decisions. "
           "Available SKUs: {}. Return {{\"sku\":\"unknown\",\"quantity\":0}} "
           "if you are unsure.").format(menu)
    body = json.dumps({
        "model": model, "stream": False, "format": "json",
        "options": {"temperature": 0},
        "messages": [{"role": "system", "content": msg},
                     {"role": "user", "content": prompt}],
    }).encode("utf-8")
    response = _request_json(url + "/api/chat", "POST", body,
                             {"Content-Type": "application/json"}, timeout=55)
    return parse_model_selection(response["message"]["content"])


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # Authentication and payment credentials must never follow a redirect.
        raise ValueError("Unexpected redirect from trusted API")


def _request_json(url, method, body, headers, timeout=15):
    req = Request(url, data=body, method=method, headers=headers)
    with build_opener(_NoRedirect()).open(req, timeout=timeout) as reply:
        return json.loads(reply.read(200000).decode("utf-8"))


class SandboxPayPal:
    def __init__(self, client_id=None, client_secret=None):
        self.client_id = client_id or os.environ.get("PAYPAL_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("PAYPAL_CLIENT_SECRET")
        if not self.client_id or not self.client_secret:
            raise RuntimeError("PayPal sandbox credentials missing; no order sent")
        # Endpoint is fixed: no live-mode toggle or caller-supplied host.
        self.base = SANDBOX_API

    def preflight(self):
        # Check sandbox credentials before reserving the one-shot create attempt.
        # Auth failure cannot have created an order, so the quote stays APPROVED.
        self._prepared_token = self._token()

    def _token(self):
        if getattr(self, "_prepared_token", None):
            return self._prepared_token
        auth = base64.b64encode(
            (self.client_id + ":" + self.client_secret).encode("utf-8")
        ).decode("ascii")
        response = _request_json(
            self.base + "/v1/oauth2/token", "POST", b"grant_type=client_credentials",
            {"Authorization": "Basic " + auth,
             "Content-Type": "application/x-www-form-urlencoded"},
        )
        if (type(response) is not dict or
                type(response.get("access_token")) is not str or
                not response["access_token"] or
                response.get("token_type", "Bearer").lower() != "bearer"):
            raise ValueError("Invalid PayPal sandbox token response")
        return response["access_token"]

    def create_order(self, record):
        # Only purchase_units from the trusted, already-approved quote.
        body = json.dumps({
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": record["id"],
                "description": CATALOG[record["sku"]][0],
                "amount": {"currency_code": CURRENCY, "value": record["total"]},
            }],
        }).encode("utf-8")
        token = self._token()
        return _request_json(
            self.base + "/v2/checkout/orders", "POST", body,
            {"Authorization": "Bearer " + token,
             "PayPal-Request-Id": record["request_id"],
             "Content-Type": "application/json",
             "Prefer": "return=representation"},
        )

    def get_order(self, order_id):
        # Safe read-only recovery path; no retry of POST and no payment capture.
        if not isinstance(order_id, str) or not re.fullmatch(
                r"[A-Za-z0-9-]{6,64}", order_id):
            raise ValueError("Invalid PayPal sandbox order id")
        return _request_json(
            self.base + "/v2/checkout/orders/" + order_id, "GET", None,
            {"Authorization": "Bearer " + self._token(),
             "Accept": "application/json"},
        )


def validate_paypal_result(result, expected_record=None):
    if type(result) is not dict:
        raise ValueError("Unexpected PayPal response")
    order_id = result.get("id")
    if type(order_id) is not str or not re.fullmatch(r"[A-Za-z0-9-]{6,64}", order_id):
        raise ValueError("Missing or invalid PayPal order ID")
    if result.get("status") not in ("CREATED", "PAYER_ACTION_REQUIRED", "SAVED", "APPROVED"):
        raise ValueError("Unexpected PayPal order status")
    if expected_record is not None:
        # PayPal must echo the exact amount and our unique purchase reference.
        # Missing purchase units are NOT silently accepted (even on 201).
        units = result.get("purchase_units")
        if type(units) is not list or len(units) != 1 or type(units[0]) is not dict:
            raise ValueError("Missing or ambiguous PayPal purchase units")
        unit = units[0]
        amount = unit.get("amount")
        if (unit.get("reference_id") != expected_record["id"] or
                type(amount) is not dict or
                amount.get("currency_code") != CURRENCY or
                amount.get("value") != expected_record["total"]):
            raise ValueError("PayPal purchase reference, currency or amount mismatch")
    links = result.get("links", [])
    if type(links) is not list:
        raise ValueError("Invalid PayPal links")
    approval = next((x.get("href") for x in links if
                     type(x) is dict and x.get("rel") in ("approve", "payer-action")), None)
    if type(approval) is not str:
        raise ValueError("No payer approval link returned")
    p = urlsplit(approval)
    if (p.scheme != "https" or p.hostname != "www.sandbox.paypal.com" or
            p.username or p.password or p.port not in (None, 443) or
            not p.path.startswith("/checkoutnow")):
        raise ValueError("Non-sandbox PayPal redirect blocked")
    # A link to a DIFFERENT sandbox order is also unsafe.
    tokens = parse_qs(p.query).get("token", [])
    if len(tokens) != 1 or tokens[0] != order_id:
        raise ValueError("PayPal approval link does not match order")
    return order_id, approval


class CheckoutStore:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.execute("CREATE TABLE IF NOT EXISTS quotes ("
                        "id TEXT PRIMARY KEY, sku TEXT NOT NULL, quantity INTEGER NOT NULL,"
                        "total TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL,"
                        "approved REAL, request_id TEXT NOT NULL UNIQUE,"
                        "paypal_id TEXT, approval_url TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS events ("
                        "id INTEGER PRIMARY KEY AUTOINCREMENT, quote_id TEXT NOT NULL,"
                        "event TEXT NOT NULL, time REAL NOT NULL)")

    def _audit(self, qid, name):
        self.db.execute("INSERT INTO events(quote_id,event,time) VALUES(?,?,?)",
                        (qid, name, time.time()))

    def quote(self, sku, quantity):
        total = validate_selection(sku, quantity)
        quote_id, rid = secrets.token_urlsafe(18), secrets.token_hex(16)
        self.db.execute(
            "INSERT INTO quotes(id,sku,quantity,total,state,created,request_id)"
            " VALUES(?,?,?,?,?,?,?)",
            (quote_id, sku, quantity, total, "QUOTED", time.time(), rid),
        )
        self._audit(quote_id, "QUOTE_CREATED")
        return self.read(quote_id)

    def read(self, quote_id):
        row = self.db.execute("SELECT * FROM quotes WHERE id=?", (quote_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown quote")
        result = dict(row)
        result.pop("request_id")
        return result

    def _internal_read(self, qid):
        row = self.db.execute("SELECT * FROM quotes WHERE id=?", (qid,)).fetchone()
        if row is None:
            raise ValueError("Unknown quote")
        return dict(row)

    def approve(self, quote_id, confirmation, expected_total):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self._internal_read(quote_id)
            if row["state"] != "QUOTED":
                raise ValueError("Quote is not awaiting approval")
            if time.time() - row["created"] > QUOTE_TTL_S:
                raise ValueError("Quote expired: request a fresh quote")
            if confirmation != CONSENT_TEXT or expected_total != row["total"]:
                raise ValueError("Human approval and exact amount are required")
            self.db.execute("UPDATE quotes SET state='APPROVED',approved=? WHERE id=?",
                            (time.time(), quote_id))
            self._audit(quote_id, "HUMAN_APPROVED")
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return self.read(quote_id)

    def create_sandbox_order(self, quote_id, paypal):
        # Validate all inputs and credentials BEFORE making an irreversible state change.
        if paypal is None or not callable(getattr(paypal, "create_order", None)):
            raise ValueError("A configured PayPal sandbox client is required")
        # Check quote before touching external authentication; check it again
        # in the transaction after authentication because it could have changed.
        precheck = self._internal_read(quote_id)
        if precheck["state"] != "APPROVED":
            raise ValueError("Order requires approval; repeats are blocked")
        if precheck["approved"] is None or time.time() - precheck["approved"] > QUOTE_TTL_S:
            raise ValueError("Approval expired: manual intervention required")
        if callable(getattr(paypal, "preflight", None)):
            paypal.preflight()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self._internal_read(quote_id)
            if row["state"] != "APPROVED":
                raise ValueError("Order requires approval; repeats are blocked")
            if row["approved"] is None or time.time() - row["approved"] > QUOTE_TTL_S:
                raise ValueError("Approval expired: manual intervention required")
            # A crash or HTTP timeout must NOT trigger a blind payment replay.
            self.db.execute("UPDATE quotes SET state='CREATE_UNCERTAIN' WHERE id=?",
                            (quote_id,))
            self._audit(quote_id, "CREATE_REQUEST_STARTED")
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        try:
            order_id, approval_url = validate_paypal_result(paypal.create_order(row), row)
        except Exception:
            self._audit(quote_id, "CREATE_UNCERTAIN_NEEDS_RECONCILIATION")
            raise
        self.db.execute(
            "UPDATE quotes SET state='PAYER_ACTION_REQUIRED',paypal_id=?,approval_url=?"
            " WHERE id=? AND state='CREATE_UNCERTAIN'",
            (order_id, approval_url, quote_id))
        self._audit(quote_id, "PAYPAL_SANDBOX_ORDER_CREATED")
        return self.read(quote_id)

    def reconcile_sandbox_order(self, quote_id, order_id, paypal):
        """Manual READ-ONLY recovery after timeout. Never reissue order POST."""
        if paypal is None or not callable(getattr(paypal, "get_order", None)):
            raise ValueError("A PayPal sandbox order lookup is required")
        row = self._internal_read(quote_id)
        if row["state"] != "CREATE_UNCERTAIN":
            raise ValueError("Only uncertain orders can be reconciled")
        # API GET is explicitly read-only and cannot charge the buyer.
        order_id_received, approval_url = validate_paypal_result(
            paypal.get_order(order_id), row)
        if order_id_received != order_id:
            raise ValueError("PayPal returned a different order id")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row_now = self._internal_read(quote_id)
            if row_now["state"] != "CREATE_UNCERTAIN":
                raise ValueError("Order state changed during reconciliation")
            self.db.execute(
                "UPDATE quotes SET state='PAYER_ACTION_REQUIRED', "
                "paypal_id=?, approval_url=? WHERE id=?",
                (order_id, approval_url, quote_id))
            self._audit(quote_id, "MANUAL_READ_ONLY_ORDER_RECONCILIATION")
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return self.read(quote_id)

    def events(self, quote_id):
        self.read(quote_id)
        return [dict(row) for row in self.db.execute(
            "SELECT event,time FROM events WHERE quote_id=? ORDER BY id", (quote_id,))]


if __name__ == "__main__":
    raise SystemExit("Use TraceCart's CLI or tests; importing this module is safe.")
