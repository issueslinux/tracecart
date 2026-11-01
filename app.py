"""TraceCart single-user, loopback-only web UI.

Run: python3 app.py --port 8765
This UI does not capture funds and never talks to production PayPal.
"""
from argparse import ArgumentParser
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
from urllib.parse import parse_qs, urlsplit

from core import (CATALOG, CONSENT_TEXT, CheckoutStore, SandboxPayPal,
                  ollama_suggestion)

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TraceCart · AI with a payment firewall</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{background:#10151f;color:#ecf3ff;
font:16px/1.5 system-ui,sans-serif;max-width:1040px;margin:0 auto;padding:28px}
header{border-bottom:1px solid #33435b;padding-bottom:20px;margin-bottom:28px}
h1{font-size:42px;margin:6px 0}h2{font-size:23px}
small,.muted{color:#9eb1cb}.tag{color:#61e6be;font-weight:700;letter-spacing:.1em}
section{background:#1a2433;border:1px solid #36455a;border-radius:14px;padding:24px;margin:14px 0}
input,button,textarea{font:inherit}textarea,input[type=text]{width:100%;color:white;background:#0e1623;
border:1px solid #4f6380;border-radius:7px;padding:12px}button,.btn{cursor:pointer;
display:inline-block;text-decoration:none;background:#6df3c5;color:#06111d;border:0;border-radius:7px;
padding:12px 17px;font-weight:750;margin-top:12px}
.warning{color:#ffce8c}.error{background:#402530;border:1px solid #ac6676;border-radius:8px;padding:16px}
.total{font-size:32px;font-weight:800;color:#6df3c5}code{color:#a7d8ff;overflow-wrap:anywhere}
footer{margin-top:28px;color:#9eb1cb}label{display:block;margin-top:16px}
</style></head><body><header><div class="tag">PAYPAL SANDBOX ONLY · HUMAN-IN-THE-LOOP</div>
<h1>TraceCart</h1><p>Ask an AI to pick a product. <strong>Only the fixed catalog sets the price.</strong>
Only you can approve a PayPal sandbox order. No funds are captured.</p></header>
{{body}}<footer>AI may suggest SKUs, never prices or authorizations.
All approvals and sandbox-order actions are logged in the local audit trail. No real-money mode.</footer>
</body></html>"""


def h(text):
    return escape(str(text), quote=True)


class TraceCartHandler(BaseHTTPRequestHandler):
    server_version = "TraceCart/0.1"

    def log_message(self, format_, *args):
        # Do not log form payloads or PayPal approval tokens.
        print("TraceCart:", format_ % args)

    def send_page(self, body, status=200):
        data = PAGE.replace("{{body}}", body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def trusted_host(self):
        # Reject DNS rebinding via an attacker-controlled Host value.
        host = self.headers.get("Host", "")
        expected = {
            "127.0.0.1:{}".format(self.server.server_port),
            "localhost:{}".format(self.server.server_port),
        }
        if host not in expected:
            self.send_page('<section class="error">Invalid local host</section>', 403)
            return False
        return True

    def form(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size < 1 or size > 8000:
            raise ValueError("Form too large or empty")
        if self.headers.get("Content-Type", "").split(";")[0].strip() != (
                "application/x-www-form-urlencoded"):
            raise ValueError("Unexpected form content type")
        body = self.rfile.read(size).decode("utf-8")
        params = {key: values[0] for key, values in parse_qs(body).items()}
        if params.get("csrf") != self.server.csrf:
            raise ValueError("CSRF token invalid")
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + self.headers.get("Host", ""):
            raise ValueError("Cross-origin form blocked")
        return params

    def hidden(self):
        return '<input type="hidden" name="csrf" value="{}">'.format(h(self.server.csrf))

    def do_GET(self):
        if not self.trusted_host():
            return
        path = urlsplit(self.path).path
        if path == "/":
            menu = "".join("<li><b>{}</b> — {} USD · {}</li>".format(h(name), h(value[1]), h(value[0]))
                           for name, value in CATALOG.items())
            self.send_page("""<section><h2>1 · Describe your request</h2>
                <p>Local Qwen model proposes a SKU and quantity. The fixed catalog calculates the amount.</p>
                <form method="post" action="/propose">{}
                <label>Request<textarea name="description" rows="3" required minlength="3"
                maxlength="500" placeholder="Two vintage ceramic pendants, please"></textarea></label>
                <button>Ask AI for a locked quote</button></form></section>
                <section><h2>Server-controlled catalog</h2><ul>{}</ul></section>
                <section><h2>Payment safeguards</h2>
                <p>Explicit amount confirmation · Expiring quote · One order attempt
                · No automatic retries after timeouts · Sandbox links only · No capture endpoint.</p>
                </section>""".format(self.hidden(), menu))
        elif path.startswith("/quote/"):
            qid = path[len("/quote/"):]
            try:
                row = self.server.store.read(qid)
                self.quote_page(row)
            except ValueError as exc:
                self.send_page('<section class="error">{}</section>'.format(h(exc)), 404)
        else:
            self.send_page("<section class='error'>Not found</section>", 404)

    def quote_page(self, row, error=""):
        qid = h(row["id"])
        amount = h(row["total"])
        state = row["state"]
        body = '<section><div class="tag">QUOTE {}</div><h2>{}</h2><div>Quantity: {}</div>'.format(
            qid, h(CATALOG[row["sku"]][0]), h(row["quantity"]))
        body += '<p class="total">{} {}</p><p>Status: <code>{}</code></p>'.format(amount, h("USD"), h(state))
        if error:
            body += '<div class="error">{}</div>'.format(h(error))
        if state == "QUOTED":
            body += """<h2>2 · Explicit buyer review</h2><p class="warning">This is a sandbox demo.
                AI cannot approve this action. Review the exact amount shown above.</p>
                <form method="post" action="/approve">{}<input name="quote_id" type="hidden" value="{}">
                <label>Enter the exact total (USD)<input type="text" name="expected_total" required
                placeholder="{}"></label><label>Type this exact consent phrase:
                <code>{}</code><input type="text" name="consent" required></label>
                <button>Record my approval</button></form>""".format(
                    self.hidden(), qid, amount, h(CONSENT_TEXT))
        elif state == "APPROVED":
            body += """<h2>3 · Create a PayPal SANDBOX order</h2>
                <p>No order is created before clicking this button. A real PayPal sandbox
                client ID and secret must be configured on the server.</p>
                <form method="post" action="/create">{}<input type="hidden" name="quote_id"
                value="{}"><button>Create sandbox order (no capture)</button></form>""".format(self.hidden(), qid)
        elif state == "PAYER_ACTION_REQUIRED":
            body += '<p>Sandbox order ID: <code>{}</code></p>'.format(h(row["paypal_id"]))
            body += '<p><a class="btn" rel="noreferrer" href="{}">Open PayPal sandbox payer approval</a></p>'.format(
                h(row["approval_url"]))
            body += '<p>No capture endpoint is implemented. Seller and payer must authorize separately.</p>'
        elif state == "CREATE_UNCERTAIN":
            body += """<h2>4 · Recover with a READ-ONLY lookup</h2>
                <p class="warning">The prior create call might have succeeded.
                Never repeat it blindly. Find the sandbox order ID in the PayPal
                sandbox dashboard, then verify that it matches this quote.</p>
                <form method="post" action="/reconcile">{}
                <input type="hidden" name="quote_id" value="{}">
                <label>Existing sandbox order ID<input type="text" name="order_id"
                required maxlength="64" placeholder="FAKEORDER123"></label>
                <button>Verify existing order (GET only)</button></form>""".format(
                    self.hidden(), qid)
        else:
            body += '<p class="warning">No automatic retries. Investigate the audit trail and reconcile manually.</p>'
        body += '</section><p><a class="btn" href="/">Start another request</a></p>'
        self.send_page(body)

    def do_POST(self):
        if not self.trusted_host():
            return
        try:
            form = self.form()
            if self.path == "/propose":
                sku, quantity, _ = ollama_suggestion(form.get("description", ""))
                row = self.server.store.quote(sku, quantity)
                self.quote_page(row)
            elif self.path == "/approve":
                row = self.server.store.approve(form.get("quote_id", ""),
                    form.get("consent", ""), form.get("expected_total", ""))
                self.quote_page(row)
            elif self.path == "/create":
                qid = form.get("quote_id", "")
                paypal = SandboxPayPal()
                row = self.server.store.create_sandbox_order(qid, paypal)
                self.quote_page(row)
            elif self.path == "/reconcile":
                paypal = SandboxPayPal()
                row = self.server.store.reconcile_sandbox_order(
                    form.get("quote_id", ""), form.get("order_id", ""), paypal)
                self.quote_page(row)
            else:
                self.send_page("<section class='error'>Not found</section>", 404)
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
            # Never reflect credential values, token URLs or raw payment API responses.
            print("TraceCart blocked:",type(exc).__name__,
                  str(exc) if isinstance(exc, ValueError) else "redacted",
                  file=sys.stderr,flush=True)
            message = str(exc)
            if "PayPal sandbox credentials" in message or "Quote" in message or "Unknown" in message:
                display = message
            else:
                display = "Request could not be completed. No new payment attempt will be retried."
            self.send_page('<section class="error">{}</section><p><a href="/">Home</a></p>'.format(h(display)), 400)


def run():
    parser = ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path,
                        default=Path.home() / ".tracecart" / "quotes.sqlite")
    args = parser.parse_args()
    args.db.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    server = HTTPServer(("127.0.0.1", args.port), TraceCartHandler)
    server.csrf = secrets.token_urlsafe(32)
    server.store = CheckoutStore(str(args.db))
    print("TraceCart local demo: http://127.0.0.1:{}".format(args.port))
    print("PayPal mode: sandbox only; no capture code; user approval mandatory")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.store.db.close()


if __name__ == "__main__":
    run()
