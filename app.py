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
from decision_tree import (ReportStore, analyze, generate_question_proposals,
                           to_html_tree, MAX_DOC_BYTES)
from source_collector import collect_and_analyze, attach_collection_provenance

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
input[type=checkbox]{width:auto}details.branch{margin:8px 0;padding:10px 12px;
border:1px solid #3e5169;border-radius:8px;background:#15202f}
details.branch details.branch{margin-left:14px}details.branch .body{margin:8px 0 0 12px;
font-size:14px;overflow-wrap:anywhere;color:#cfdef2}
details.branch summary{cursor:pointer}details.branch summary em{color:#f3d09e;
font-style:normal;font-size:12px}details.branch .badge{font-size:11px;color:#61e6be}
details.branch a{color:#9ed6ff}
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
        max_size = MAX_DOC_BYTES if self.path == "/research/analyze" else 8000
        if size < 1 or size > max_size:
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
                </section><section><h2>Evidence-based decision research</h2>
                <p>Research offers and third-party reviews, run an independent critic,
                and export the full expandable decision tree with unanswered questions.</p>
                <p><a class="btn" href="/research">Open decision research lab</a></p>
                </section>""".format(self.hidden(), menu))
        elif path == "/research":
            import json
            fixture = (Path(__file__).resolve().parent / "examples" /
                       "sample_research_fixture.json").read_text(encoding="utf-8")
            sample = h(fixture)
            self.send_page("""<section><h2>Independent Evidence & Critic Lab</h2>
                <p>Import your collected offers, reviews, test excerpts and source URLs
                as JSON. This first version does <b>not</b> search the web or verify URLs
                automatically. The included input is FICTIONAL and for demonstration only.</p>
                <form action="/research/analyze" method="post">{}
                <label>Collected source data (JSON)<textarea rows="20" name="research_data"
                maxlength="60000" required>{}</textarea></label>
                <label><input type="checkbox" name="ask_ai" value="yes">
                Ask two independent local Qwen roles — RESEARCHER and CRITIC —
                for unanswered follow-up questions (no facts or answers created)</label>
                <button>Build the complete decision tree</button></form>
                <p class="muted">Everything remains local; generated reports are stored
                on this machine. Payment is disabled from research reports.</p>
                </section><section><h2>LIVE merchant source collection</h2>
                <p>Paste up to 5 actual product URLs, one per line, from the explicitly
                supported merchant <b>Adafruit</b>. The collector checks robots.txt,
                rate-limits requests and extracts Product/Offer JSON-LD with provenance.
                Only <strong>merchant assertions</strong> are available through this
                connector. It does NOT independently verify prices, collect outside
                reviews or search for other merchants yet.</p>
                <form action="/research/collect" method="post">{}
                <label>Supported live product URLs<textarea name="product_urls" rows="4"
                maxlength="1900" required>https://www.adafruit.com/product/1083
https://www.adafruit.com/product/4885
https://www.adafruit.com/product/3400</textarea></label>
                <label><input type="checkbox" name="ask_ai" value="yes">
                Ask separate local Qwen RESEARCHER and CRITIC roles to propose
                further source questions (no invented evidence; may take some time)</label>
                <button>Collect live source claims &amp; inspect critic tree</button>
                </form><p class="warning">Retail price and stock may change.
                Collector records retrieval date; sources are not independently validated.</p>
                </section>""".format(self.hidden(), sample, self.hidden()))
        elif path.startswith("/research/report/"):
            tail = path[len("/research/report/"):]
            is_json = tail.endswith(".json")
            rid = tail[:-5] if is_json else tail
            try:
                report = self.server.reports.load(rid)
            except ValueError as exc:
                self.send_page('<section class="error">{}</section>'.format(h(exc)), 404)
                return
            if is_json:
                self.send_json_report(report, rid)
            else:
                self.research_report_page(rid, report)
        elif path.startswith("/quote/"):
            qid = path[len("/quote/"):]
            try:
                row = self.server.store.read(qid)
                self.quote_page(row)
            except ValueError as exc:
                self.send_page('<section class="error">{}</section>'.format(h(exc)), 404)
        else:
            self.send_page("<section class='error'>Not found</section>", 404)

    def send_json_report(self, report, rid):
        content = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="tracecart-{}.json"'.format(rid))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def research_report_page(self, rid, report):
        summary = report["root"]
        branch_count = len(summary["children"])
        collection = report.get("source_collection")
        if collection:
            collection_html = ("""<section><h2>Live source collection provenance</h2>
                <p>Successfully retrieved merchant product pages: <strong>{}</strong>
                of {} requested. External customer reviews: <strong>{}</strong>.
                Independent product tests: <strong>{}</strong>.</p>
                <p class="warning">All collected price, stock and condition facts
                come from the merchant. They are not independently corroborated.</p>
                <p>Retrieval policy: {}</p></section>""".format(
                    h(collection["fetched_pages"]), h(collection["requested_pages"]),
                    h(collection["review_sources_collected"]),
                    h(collection["independent_product_tests_collected"]),
                    h(collection["retrieval_policy"])))
            if collection["source_failures"]:
                collection_html += '<section class="warning"><b>Failed sources:</b> {}</section>'.format(
                    h(json.dumps(collection["source_failures"], ensure_ascii=False)))
        else:
            collection_html = ""
        body = """<section><div class="tag">IMMUTABLE RESEARCH SNAPSHOT</div>
            <h2>Complete evidence and decision tree</h2>
            <p>Each branch is expandable. No sources, objections or open questions
            have been removed to shorten the summary.</p>
            <p><b>SHA-256:</b> <code>{}</code></p>
            <p><b>Research branches:</b> {} · <b>Last decision:</b> {}
            · <b>Generated:</b> {}</p>
            <p><a class="btn" href="/research/report/{}.json">Export complete JSON</a>
            <a class="btn" href="/research">Start another investigation</a></p>
            <p class="warning">Source excerpts are unverified input data.
            This is NOT authorization to make a purchase.</p></section>
            <section><h2>Every decision, objection, source and question</h2>
            {} </section>""".format(
            h(report["sha256"]), branch_count, h(summary["children"][-1]["status"]),
            h(report["generated_at"]), h(rid), to_html_tree(report))
        body = collection_html + body
        # Native <details> is interactive without JavaScript and works with CSP.
        self.send_page(body)

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
            elif self.path == "/research/collect":
                urls = [x.strip() for x in form.get("product_urls", "").splitlines()
                        if x.strip()]
                if len(urls) > 5:
                    raise ValueError("Maximum five product URLs per collection")
                report, collected = collect_and_analyze(urls,
                    category="electronic components",
                    goal="Analyze current sourced merchant product claims and independent critique")
                if form.get("ask_ai") == "yes":
                    proposals, failures = [], []
                    for role in ("researcher", "critic"):
                        try:
                            proposals.extend(generate_question_proposals(report, role))
                        except (ValueError, KeyError, TypeError, OSError, RuntimeError,
                                json.JSONDecodeError) as exc:
                            failures.append({"role": role, "error_type": type(exc).__name__})
                    input_data = {k: collected[k] for k in ("goal", "category", "offers")}
                    input_data["generated_questions"] = proposals
                    input_data["model_failures"] = failures
                    report = attach_collection_provenance(analyze(input_data), collected)
                rid = self.server.reports.save(report)
                self.research_report_page(rid, report)
            elif self.path == "/research/analyze":
                raw = form.get("research_data", "")
                if len(raw) > 60000:
                    raise ValueError("Research input too large")
                payload = json.loads(raw)
                # First run deterministic critic and *preserve* all facts as supplied.
                baseline = analyze(payload)
                if form.get("ask_ai") == "yes":
                    proposals, failures = [], []
                    for role in ("researcher", "critic"):
                        try:
                            proposals += generate_question_proposals(baseline, role)
                        except (ValueError, KeyError, TypeError, OSError, RuntimeError,
                                json.JSONDecodeError) as exc:
                            # A failed model must not prevent a complete deterministic report.
                            failures.append({"role": role, "error_type": type(exc).__name__})
                    payload["generated_questions"] = proposals
                    payload["model_failures"] = failures
                result = analyze(payload)
                rid = self.server.reports.save(result)
                self.research_report_page(rid, result)
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
    server.reports = ReportStore(server.store.db)
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
