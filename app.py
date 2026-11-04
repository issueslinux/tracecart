"""TraceCart single-user, loopback-only web UI.

Run: python3 app.py --port 8765
This UI does not capture funds and never talks to production PayPal.
"""
from argparse import ArgumentParser
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import threading
import sys
import time
from urllib.parse import parse_qs, urlsplit, urlencode, quote

from core import (CATALOG, CONSENT_TEXT, CheckoutStore, SandboxPayPal,
                  ollama_suggestion)
from decision_tree import (ReportStore, analyze, generate_question_proposals,
                           to_html_tree, MAX_DOC_BYTES)
from source_collector import collect_and_analyze, attach_collection_provenance
from source_crosscheck import collect_spec_crosscheck
from comparison import compare
from cart_research import CartResearchJobs
from live_offer_compare import compare_live_offer
from multi_offer_compare import compare_live_offers
from browser_capture import parse_browser_capture
from browser_companion_queue import CompanionQueue
from country_suggestion import suggested_country
from guided_decision import build_decision_projection

FLOW_ASSETS = {
    "/assets/decision-flow.css": ("text/css; charset=utf-8", "decision-flow.css"),
    "/assets/decision-flow.js": ("text/javascript; charset=utf-8", "decision-flow.js"),
    "/assets/offer-graph.js": ("text/javascript; charset=utf-8", "offer-graph.js"),
    "/assets/live-workspace.js": ("text/javascript; charset=utf-8", "live-workspace.js"),
    "/assets/live-workspace.css": ("text/css; charset=utf-8", "live-workspace.css"),
}

FLOW_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; "
    "connect-src 'self'; form-action 'self'; img-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'; object-src 'none'"
)

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
table{border-collapse:collapse;width:100%;margin-top:12px}
td,th{border:1px solid #42556c;text-align:left;padding:10px;vertical-align:top}
td{overflow-wrap:anywhere}
</style></head><body><header><div class="tag">PAYPAL SANDBOX ONLY · HUMAN-IN-THE-LOOP</div>
<h1>TraceCart</h1><p>Analyze the product already in the cart before checkout.
<strong>Research never changes merchant prices or authorizes purchases.</strong>
PayPal remains consent-gated, sandbox only; no funds are captured.</p></header>
{{body}}<footer>AI may suggest SKUs, never prices or authorizations.
All approvals and sandbox-order actions are logged in the local audit trail. No real-money mode.</footer>
</body></html>"""


def h(text):
    return escape(str(text), quote=True)


def shopping_alternatives_panel(shopping):
    """Rank functional substitutes; never label index prices as verified."""
    data = shopping.get("functional_alternatives")
    if not data:
        return ""
    statuses = {
        "SIMILAR_TECHNICAL_TIER_INDEX_ONLY": "Similar advertised specifications",
        "POSSIBLE_ALTERNATIVE_NEEDS_SPEC_CHECK": "Possible alternative — check specifications",
    }
    bands = {
        "SIMILAR_INDEX_PRICE_BAND": "Similar indexed price band",
        "LOWER_INDEX_PRICE_BAND": "Lower indexed price band",
        "HIGHER_INDEX_PRICE_BAND": "Higher indexed price band",
        "PRICE_BAND_UNDETERMINED": "Price band unknown",
    }
    rows = []
    for offer in data.get("ranked_alternatives", []):
        assessment = offer["comparison"]
        link = offer.get("merchant_url") or offer.get("shopping_lookup_url")
        label = ("Open retailer listing" if offer.get("merchant_url")
                 else "Search Google Shopping")
        link_html = ('<a href="{}" target="_blank" rel="noopener noreferrer">'
                     '{}</a>'.format(h(link), h(label))) if link else "No link available"
        qualities = assessment.get("matched_features", [])
        differences = assessment.get("different_features", [])
        missing = assessment.get("unconfirmed_features", [])
        description = (
            "<b>Comparable features:</b> " +
            (", ".join(h(x) for x in qualities[:5]) or "insufficient evidence")
        )
        if differences:
            description += "<br><b>Differences:</b> " + ", ".join(
                h(x) for x in differences[:3])
        if missing:
            description += "<br><b>Unknown:</b> " + ", ".join(
                h(x) for x in missing[:4])
        if assessment.get("condition_difference"):
            description += "<br><b>Condition:</b> " + h(assessment["condition_difference"])
        anomaly = offer.get("index_price_anomaly")
        if anomaly == "SUSPICIOUS_LOW_PRICE_VS_PEER_MEDIAN_NOT_VERIFIED":
            description += "<br><strong>WARNING: suspiciously low indexed quote!</strong>"
        score = assessment.get("technical_score")
        score_text = (str(score) + "/100 — listing-title similarity only"
                      if score is not None else "not enough data")
        rows.append(
            '<tr><td><b>{}</b><br>{}<br>{}</td>'
            '<td><strong>{} {}</strong><br>{}</td>'
            '<td>{}<br>{}</td>'
            '<td>{}</td></tr>'.format(
                h(offer["source"]), h(offer["title"]), link_html,
                h(offer.get("indexed_price") or "unavailable"), h(offer.get("currency") or ""),
                h(bands.get(assessment.get("price_band"), "Unknown")),
                h(statuses.get(assessment["status"], assessment["status"])),
                h(score_text), description))
    selected_specs = data.get("selected_declared_specs", {})
    from similar_tier import PUBLIC_SPEC_NAMES, _display_spec
    basics = ", ".join("{} {}".format(PUBLIC_SPEC_NAMES.get(key, key),
                                      _display_spec(key, value))
                       for key, value in selected_specs.items()) or "insufficient data"
    price_info = (
        "Price reference: {} {} ({})".format(
            h(data["price_reference"]), h(data.get("price_reference_currency") or ""),
            "selected seller-declared price" if
            data["price_reference_provenance"] == "INPUT_SELLER_DECLARED_NOT_CHECKOUT"
            else "estimated median of comparable indexed prices")
        if data.get("price_reference") is not None
        else "No price reference: input seller price or comparable indexed quotes are unavailable")
    if not rows:
        table = ("<p>Not enough data to identify technically comparable alternatives. "
                 "All indexed results are listed below.</p>")
    else:
        table = (
            "<table><tr><th>Product and source</th><th>Indexed price and tier</th>"
            "<th>Similarity rating</th><th>Compared specifications</th></tr>{}</table>"
        ).format("".join(rows))
    counts = data.get("status_counts", {})
    return (
        '<section><div class="tag">SIMILAR SPECIFICATIONS · DIFFERENT MODELS WELCOME</div>'
        '<h2>Functional alternatives at a comparable technical tier</h2>'
        '<p>Input product: {}. Specifications extracted from the title: {}.</p>'
        '<p>{}. Technically similar: <b>{}</b>, possible alternatives '
        'with missing specifications: <b>{}</b>.</p>{}'
        '<p class="warning">These are only similarities between indexed listing titles, '
        '<strong>NOT independent quality testing</strong> and NOT verification of '
        'any retailer checkout price. Other models/brands can be functional alternatives. '
        'E-bike range and battery specifications may be marketing claims. '
        'Google Shopping price tiers are not verified checkout totals.</p></section>'
    ).format(
        h(data.get("category_label")), h(basics), price_info,
        h(counts.get("SIMILAR_TECHNICAL_TIER_INDEX_ONLY", 0)),
        h(counts.get("POSSIBLE_ALTERNATIVE_NEEDS_SPEC_CHECK", 0)),
        table)


def shopping_search_panel(report):
    """Expose indexed marketplace prices without disguising them as seller checks."""
    data = report.get("indexed_shopping")
    if not data:
        return ''
    rows = []
    for offer in data.get("indexed_offers", []):
        rows.append(
            '<tr><td><a href="{}" target="_blank" rel="noopener noreferrer">{}</a>'
            '</td><td>{}</td><td><strong>{} {}</strong></td>'
            '<td>{}</td><td>{}</td></tr>'.format(
                h(offer["merchant_url"]), h(offer["seller"]),
                h(offer["title"]),
                h(offer["current_price_indexed"]), h(offer["currency"]),
                h(offer["identity_status"]),
                h(offer.get("index_price_anomaly") or "UNKNOWN")))
    group_rows = []
    for group in data.get("search_result_groups", []):
        if not group.get("indexed_price") or not group.get("indexed_currency"):
            continue
        link = group.get("index_product_url") or group.get("index_search_url")
        source = (('{} <a href="{}" rel="noopener noreferrer" target="_blank">'
                   '(Search Google Shopping)</a>'.format(
                       h(group["source"]), h(link))) if link else
                  h(group["source"]))
        group_rows.append(
            '<tr><td>{}</td><td>{}</td><td><strong>{} {}</strong></td>'
            '<td>{}</td></tr>'.format(
                source, h(group["title"]), h(group["indexed_price"]),
                h(group["indexed_currency"]), h(group["identity_status"])))
    best = data.get("lowest_indexed_observation")
    if best:
        best_html = (
            '<p>Lowest indexed price <b>in returned candidates</b>: '
            '<strong>{} {}</strong> at {}. This is not proof of lowest market '
            'price or same product variant; buyer must verify the actual offer.</p>'
            .format(h(best["price"]), h(best["currency"]), h(best["seller"])))
    else:
        best_html = '<p>No comparable index price obtained in the selected currency.</p>'
    return (
        '<section><div class="tag">GOOGLE SHOPPING · INDEXED SELLER PRICES</div>'
        '<h2>Marketplace and store prices without fetching blocked seller pages</h2>'
        '<p>Provider: {} · status: {} · searched: {} · API calls: {}. '
        'Market: Poland. Indexed prices may be delayed or mismatched.</p>{}{}'
        '<p class="warning">A Google Shopping result is a search hint; '
        'its link may reopen Google Shopping, not the same seller offer. '
        'Product details may be inaccessible even when Shopping results exist.</p>'
        '<h3>Indexed direct-store links (Google product group)</h3>'
        '<table><tr><th>Seller/source link</th><th>Indexed listing</th>'
        '<th>Indexed price</th><th>Product identity</th><th>Price warning</th></tr>{}</table>'
        '<h3>Google Shopping search-result cards (not direct seller links)</h3>'
        '<table><tr><th>Source</th><th>Indexed product</th>'
        '<th>Indexed price</th><th>Identity</th></tr>{}</table>'
        '<p class="warning">SEARCH INDEX ONLY. No seller-page verification, '
        'availability, checkout total, universal cheapest-offer claim or '
        'purchase authorization. Exact product/GTIN may differ.</p></section>'
    ).format(h(data["provider"]), h(data["status"]), h(data["queried_at"]),
             h(data["provider_calls"]), shopping_alternatives_panel(data), best_html,
             ''.join(rows),
             ''.join(group_rows))


def automatic_discovery_panel(report):
    """Search discovery is visible independently of source-verified offers."""
    data = report.get("automatic_offer_discovery")
    if not data:
        return ''
    counts = data["counts"]
    rows = []
    for row in data["candidate_audit"]:
        link = row.get("candidate_url")
        anchor = ('<a href="{}" rel="noopener noreferrer" '
                  'target="_blank">{}</a>'.format(h(link), h(link))
                  if link else 'INVALID SOURCE URL')
        rows.append(
            '<tr><td>{}</td><td>{}</td><td>{}</td></tr>'.format(
                anchor, h(row["decision"]),
                h((row.get("source_check_status") or 'NOT CHECKED') +
                  (' / ' + row['source_http_status']
                   if row.get('source_http_status') else ''))))
    return (
        '<section><div class="tag">AUTOMATIC SOURCE DISCOVERY</div>'
        '<h2>Additional merchant links and independent page checks</h2>'
        '<p>Search hits: <b>{}</b>. Checked product pages: <b>{}</b>. '
        'Downloaded seller pages: <b>{}</b>. '
        'Qualified comparable seller-listed prices: <b>{}</b>.</p>'
        '<p>Search provider results are discovery-only. Listings blocked '
        'by robots or HTTP restrictions remain visible; no price is '
        'extracted from an unverified search snippet.</p>'
        '<table><tr><th>Candidate link</th><th>Decision</th>'
        '<th>Source status</th></tr>{}</table>'
        '<p class="warning">This is a bounded partial search, not proof of '
        'the lowest market price. No checkout, automatic purchase, '
        'independent product test or quality score.</p>'
        '</section>').format(
            h(counts["search_hits_seen"]),
            h(counts["candidates_checked"]),
            h(counts["seller_pages_retrieved"]),
            h(counts["source_qualified_competing_offers"]),
            ''.join(rows))


def marketplace_lead_panel(report):
    """Show unverified marketplace observations without a false price winner."""
    data = report.get('marketplace_leads') or {}
    if not data:
        return ''
    rows = []
    for lead in data['observations']:
        gap = lead['difference_vs_selected_listed_price']
        gap_label = (
            gap + ' ' + lead['currency'] + ' (UNVERIFIED observation gap)'
            if gap is not None else 'NOT COMPARABLE')
        rows.append(
            '<tr><td><a href="{}" target="_blank" rel="noopener noreferrer">'
            '{}</a></td><td>{} {}</td><td>{}</td><td>{}</td></tr>'.format(
                h(lead['url']), h(lead['url']),
                h(lead['observed_price']), h(lead['currency']),
                h(lead['comparison_status']), h(gap_label)))
    return (
        '<section><div class="tag">MARKETPLACE PRICE LEADS · UNVERIFIED</div>'
        '<h2>Potentially cheaper offers, including blocked marketplaces</h2>'
        '<p>These are <b>reported prices</b>, not source pages successfully '
        'retrieved and verified by TraceCart. The lead remains visible '
        'even if the marketplace refuses automated access. '
        'Stock, exact SKU, condition and current price still require verification.</p>'
        '<table><tr><th>Link</th><th>Reported price</th>'
        '<th>Evidence status</th><th>Difference vs selected listing</th>'
        '</tr>{}</table><p class="warning">Do not rank these as confirmed '
        'offers or use them for checkout claims.</p></section>'.format(
            ''.join(rows)))


def research_critic_panel(report):
    """Escaped, actionable summary for single- and multi-seller research."""
    critic = (report.get('multi_offer_research_critic') or
              report.get('single_offer_research_critic'))
    if not critic:
        return ''
    rows = []
    for question in critic.get('prioritized_questions', []):
        rows.append(
            '<tr><td><a href="{}" rel="noopener noreferrer" target="_blank">'
            '{}</a></td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(
                h(question['url']), h(question['url']), h(question['finding']),
                h(question['question']), h(question['selection'])))
    return (
        '<section><div class="tag">RESEARCH CRITIC</div>'
        '<h2>Evidence gaps and next research questions</h2>'
        '<p>{} lower seller-listed price research leads; {} open questions. '
        'No product quality or seller reliability verdict was established '
        'by these retailer pages.</p>'
        '<table><tr><th>Source</th><th>Finding</th><th>Research question</th>'
        '<th>Status</th></tr>{}</table>'
        '<p class="warning">A lower listing price is not a buying '
        'recommendation. Critic questions are unresolved hypotheses, '
        'not independently collected reviews or test results.</p>'
        '</section>'.format(
            h(critic['lower_listed_price_leads']),
            h(critic['open_question_count']), ''.join(rows)))


class StreamingHTTPServer(HTTPServer):
    """Only the SSE connection runs on a secondary thread.

    Legacy checkout and report routes retain the original serialized server
    loop and their thread-affine SQLite connection. Long-lived SSE streams
    use CartResearchJobs' per-call SQLite connections plus in-RAM cache.
    """

    def process_request(self, request, client_address):
        try:
            request.settimeout(2)
            first=request.recv(192,socket.MSG_PEEK)
            request.settimeout(None)
        except (socket.timeout,OSError):
            self.shutdown_request(request)
            return
        # A route is recognized before BaseHTTPRequestHandler reads it,
        # so a 48-second stream cannot stall normal checkout operations.
        line=first.split(b"\r\n",1)[0]
        live=(line.startswith(b"GET /cart/status/") and
              line.endswith(b"/live HTTP/1.1") or
              line.endswith(b"/live HTTP/1.0"))
        if not live:
            return super().process_request(request,client_address)
        worker=threading.Thread(
            target=self._stream_request,args=(request,client_address),
            daemon=True)
        worker.start()

    def _stream_request(self,request,client_address):
        try:
            self.finish_request(request,client_address)
        except Exception:
            self.handle_error(request,client_address)
        finally:
            self.shutdown_request(request)


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

    def send_flow_asset(self, path):
        content_type, name = FLOW_ASSETS[path]
        payload = (Path(__file__).resolve().parent / "assets" / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", FLOW_CSP)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def companion_json(self, payload, code=200):
        raw = json.dumps(payload, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def companion_authorized(self):
        auth = self.headers.get("Authorization", "")
        # Bearer token is never accepted in URL, form or cookie.
        if not auth.startswith("Bearer ") or not self.server.companion.authorized(auth[7:]):
            self.companion_json({"error":"UNAUTHORIZED_COMPANION"}, 401)
            return False
        return True

    def companion_page(self, default_url=""):
        jobs = self.server.companion.listed()
        # SQLite retains completed evidence even after an in-memory queue
        # restart; merge by capture ID without presenting duplicate jobs.
        seen={row["id"] for row in jobs}
        for receipt in self.server.cart_jobs.recent_browser_claim_receipts():
            if receipt["id"] not in seen:
                jobs.append(receipt)
        rows = []
        for row in jobs:
            fields = (row.get("result") or {}).get("fields") or {}
            price = ((str(fields.get("price")) + " " + str(fields.get("currency")))
                     if fields.get("price") and fields.get("currency") else "—")
            rows.append("<tr><td>{}</td><td>{}</td><td>{}</td>"
                        "<td>{}</td><td>{}</td><td>"
                        '<a href="/research/companion/{}.json">Evidence JSON</a>'
                        "</td></tr>".format(
                            h(row["created_at"][:19]), h(row["url"]),
                            h(row["status"]), h(fields.get("title") or "—"),
                            h(price), h(row["id"])))
        table = ("<table><thead><tr><th>Queued</th><th>Source URL</th>"
                 "<th>Status</th><th>Declared product</th><th>Unverified price</th>"
                 "<th>Evidence</th>"
                 "</tr></thead><tbody>{}</tbody></table>".format("".join(rows))
                 if rows else "<p>No research tasks queued.</p>")
        self.send_page("""<section><h2>Browser companion · opt-in research</h2>
            <p>Install the local, unpacked Chrome/Chromium extension from
            <code>browser-extension/</code>. Enter this local port and pairing
            token in its popup once, then grant access to each selected merchant
            site in the browser permission prompt. With automatic checks
            disabled, only URLs explicitly queued here are opened. When
            automatic checks are enabled below, a newly completed cart
            queues the input and discovered seller URLs; unapproved
            domains remain inaccessible. Disable the extension queue
            in its popup at any time.</p>
            <p><b>Local endpoint:</b> 127.0.0.1:{}</p>
            <label>Private pairing token (keep on this computer)
            <input type="text" readonly value="{}"></label>
            <p class="warning">This pairing secret has read/write access to the
            <b>research-only</b> queue. It does not authorize checkout and
            must never be shared with websites or stored in the repository.</p>
            <form method="post" action="/research/companion/queue">{}
              <label>Product HTTPS URLs (up to 12 explicitly selected pages,
              one per line)
              <textarea name="product_urls" rows="5" maxlength="7000" required
              placeholder="https://store.example.org/product/...">{}</textarea></label>
              <button>Queue selected research pages</button>
            </form>
            <form method="post" action="/research/companion/auto">{}
              <input type="hidden" name="operation" value="{}">
              <button type="submit">{}</button>
            </form>
            <p><b>Automatic follow-up:</b> {}. When enabled, new cart research
            queues the input product plus discovered direct seller URLs
            automatically (maximum 12 pages per batch). Only sites explicitly
            permitted in the paired Chromium extension can be inspected.
            No site permissions are silently granted, no checkout occurs.
            Unknown sites remain SITE_PERMISSION_REQUIRED until manually
            authorized in the extension. Queue capacity and errors remain
            visible; disabling this stops new automatic batches.</p>
            <p>No cookies, localStorage, authentication tokens, full page HTML
            or account information are sent. Only a bounded, sanitized
            Product/Offer projection is accepted. All prices remain
            <b>USER_BROWSER, not seller/checkout verified</b>.
            Access denied and CAPTCHA are not bypassed.</p>
            <p><a href="/research/companion">Refresh research jobs</a>
            · <a href="/research">Research lab</a></p>{}
            </section>""".format(self.server.server_port,
                                  h(self.server.companion.token),
                                  self.hidden(), h(default_url),
                                  self.hidden(),
                                  ("disable" if self.server.cart_jobs.browser_auto_enabled()
                                   else "enable"),
                                  ("Disable automatic seller checks" if
                                   self.server.cart_jobs.browser_auto_enabled()
                                   else "Enable automatic seller checks"),
                                  ("ENABLED" if self.server.cart_jobs.browser_auto_enabled()
                                   else "DISABLED"),table))

    def shopping_provider_page(self):
        """Loopback-only opt-in provider setup; API key never rendered."""
        status=self.server.cart_jobs.shopping_provider_status()
        enabled=status["configured"]
        header=("ACTIVE · "+status["configured_via"] if enabled else
                "NOT CONFIGURED — NO AUTOMATIC RETAILER SEARCH")
        self.send_page("""<section><h2>Shopping discovery provider</h2>
           <p><strong>{}</strong></p>
           <p>Google Shopping through SerpAPI supplies candidate offers
           for each newly submitted product. Without a provider key,
           TraceCart cannot automatically discover competitor stores.
           The Browser Companion verifies candidate seller URLs; it does
           not search the web for them.</p>
           <p><strong>Daily maximum:</strong> {} reserved API calls / {}.
           Each new product reserves at most two calls before searching.
           This is a paid/quotable third-party API; check your SerpAPI
           plan before enabling it. No API calls occur while unconfigured.
           The key is stored locally in a permission-0600 file and is
           not sent to seller sites, the extension or browser receipts.</p>
           <form method="post" action="/research/shopping/configure">{}
             <label>SerpAPI API key (private, only saved on this machine)
             <input type="password" name="api_key" minlength="20" maxlength="128"
               autocomplete="new-password" placeholder="Private key"></label>
             <input type="hidden" name="operation" value="enable">
             <button>Enable automatic Shopping discovery</button>
           </form>
           <form method="post" action="/research/shopping/configure">{}
             <input type="hidden" name="operation" value="disable">
             <button>Disable local Shopping key</button>
           </form>
           <p><a href="/cart">New cart analysis</a> ·
           <a href="/research/companion">Browser companion</a></p>
           </section>""".format(
             h(header),h(status["reserved_calls_today"]),
             h(status["daily_cap"]),self.hidden(),self.hidden()))

    def cart_entry_page(self):
        # One screen for both a new URL and ongoing graph research.
        tmpl=(Path(__file__).resolve().parent / "assets" /
              "decision-page.html").read_text(encoding="utf-8")
        for key,value in {
            "{{CSRF}}":self.server.csrf,
            "{{DECISION_URL}}":"","{{LIVE_URL}}":"",
            "{{KNOWLEDGE_GRAPH_URL}}":"","{{AUDIT_URL}}":"",
            "{{RAW_URL}}":"","{{PRODUCT_URL}}":"",
            "{{COMPANION_URL}}":"/research/companion",
            "{{VERIFY_INDEXED_ACTION}}":"",
            "{{SEARCH_INDEX_ACTION}}":"",
            "{{SHOPPING_PROVIDER_LABEL}}":("Shopping discovery · ACTIVE" if
              self.server.cart_jobs.shopping_provider_status()["configured"] else
              "⚠ Shopping discovery · NOT CONFIGURED"),
            "{{INPUT_PRICE_ACTION}}":"","{{INPUT_PRICE_VALUE}}":"",
            "{{INPUT_PROMOTION_CODE}}":"",
        }.items():
            tmpl=tmpl.replace(key,h(value))
        payload=tmpl.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Security-Policy",FLOW_CSP)
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","same-origin")
        self.send_header("X-Frame-Options","DENY")
        self.send_header("Content-Length",str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_flow_projection(self, record):
        output=json.dumps(build_decision_projection(record),
                          ensure_ascii=False,separators=(",",":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", FLOW_CSP)
        self.send_header("Content-Length", str(len(output)))
        self.end_headers()
        self.wfile.write(output)

    def send_knowledge_graph_projection(self, record, job_id=None):
        """Read-only graph plus saved source-anchored model questions."""
        from offer_knowledge_graph import build_offer_knowledge_graph
        projection=build_decision_projection(record)
        graph=build_offer_knowledge_graph(projection)
        if job_id is not None:
            from graph_question_review import graph_context,attach_model_questions
            digest=graph_context(projection,graph)[1]
            review=self.server.cart_jobs.graph_question_review(job_id,digest)
            graph=attach_model_questions(graph,review)
        output=json.dumps(graph,ensure_ascii=False,
                          separators=(",",":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Security-Policy",FLOW_CSP)
        self.send_header("Content-Length",str(len(output)))
        self.end_headers()
        self.wfile.write(output)

    def stream_live_graph(self, job_id):
        """Server-sent events from bounded RAM snapshots.

        Same-origin loopback only. The long-lived connection runs in its own
        HTTP thread and never blocks source extraction or model workers.
        Reconnects recover from SQLite if the server is restarted.
        """
        try:
            version,snapshot=self.server.cart_jobs.live_snapshot(job_id)
        except ValueError:
            self.send_page("<section>Unknown research job</section>",404)
            return
        self.send_response(200)
        self.send_header("Content-Type","text/event-stream; charset=utf-8")
        self.send_header("Cache-Control","no-cache, no-store")
        self.send_header("X-Accel-Buffering","no")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Security-Policy",FLOW_CSP)
        self.end_headers()
        self.close_connection=True
        expires=time.monotonic()+48
        last=-1
        try:
            while time.monotonic()<expires:
                if version!=last:
                    data=json.dumps(snapshot,ensure_ascii=False,
                                    separators=(",",":"))
                    frame=("id: {}\nevent: graph\ndata: {}\n\n".format(
                        version,data)).encode("utf-8")
                    self.wfile.write(frame)
                    self.wfile.flush()
                    last=version
                    stage=snapshot.get("progress_stage") or ""
                    evidence=(snapshot.get("evidence_progress") or {}).get(
                        "status","NOT_STARTED")
                    verdict_status=(snapshot.get("final_verdict") or {}).get("status")
                    finished=snapshot["state"] in ("FAILED","INTERRUPTED") or (
                        snapshot["state"]=="READY" and
                        evidence=="COMPLETE" and
                        ((not verdict_status or verdict_status=="NOT_SCHEDULED") and
                         stage=="PER_OFFER_MODEL_COMPLETE" or
                         verdict_status in ("COMPLETE","UNAVAILABLE","INTERRUPTED",
                                            "SKIPPED_NOT_NEEDED")))
                    if finished and (snapshot.get("graph_question_review") or
                                     {}).get("status") not in ("RUNNING","QUEUED"):
                        self.wfile.write(b"event: settled\ndata: {}\n\n")
                        self.wfile.flush()
                        return
                changed=self.server.cart_jobs.live_bus.wait_change(
                    job_id,version,timeout=7)
                if changed:
                    version,snapshot=self.server.cart_jobs.live_snapshot(job_id)
                else:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):
            return

    def cart_status_page(self, job_id, result):
        """Read-only decision explorer, also for historical persisted jobs.

        The old complete audit stays available under /cart/status/<id>/audit.
        A fresh projection is drawn in the browser; no original evidence
        or saved hash is rewritten, and user answers never leave the page.
        """
        tmpl=(Path(__file__).resolve().parent / "assets" /
              "decision-page.html").read_text(encoding="utf-8")
        substitutions={
            "{{CSRF}}":self.server.csrf,
            "{{LIVE_URL}}":"/cart/status/"+job_id+"/live",
            "{{DECISION_URL}}":"/cart/status/"+job_id+".decision.json",
            "{{KNOWLEDGE_GRAPH_URL}}":"/cart/status/"+job_id+".knowledge-graph.json",
            "{{AUDIT_URL}}":"/cart/status/"+job_id+"/audit",
            "{{RAW_URL}}":"/cart/status/"+job_id+".json",
            "{{SHORT_ID}}":job_id[:8],
            "{{PRODUCT_URL}}":(result.get("item") or {}).get("merchant_url") or "",
            "{{VERIFY_INDEXED_ACTION}}":"/cart/status/"+job_id+"/verify-indexed",
            "{{AUTO_VERIFY_ACTION}}":"/cart/status/"+job_id+"/auto-verify",
            "{{SEARCH_INDEX_ACTION}}":"/cart/status/"+job_id+"/search-index",
            "{{SHOPPING_PROVIDER_LABEL}}":("Shopping discovery · ACTIVE" if
              self.server.cart_jobs.shopping_provider_status()["configured"] else
              "⚠ Shopping discovery · NOT CONFIGURED"),
            "{{COMPANION_URL}}":"/research/companion?product_url="+quote(
                (result.get("item") or {}).get("merchant_url") or "",safe=""),
            "{{INPUT_PRICE_ACTION}}":"/cart/status/"+job_id+"/input-price",
            "{{INPUT_PRICE_VALUE}}":(result.get("input_price") or {}).get("price") or "",
            "{{INPUT_PROMOTION_CODE}}":(result.get("input_price") or {}).get("promotion_code") or "",
        }
        for key,value in substitutions.items():
            tmpl=tmpl.replace(key,h(value))
        payload=tmpl.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Security-Policy", FLOW_CSP)
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","same-origin")
        self.send_header("X-Frame-Options","DENY")
        self.send_header("Content-Length",str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

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
        max_size = MAX_DOC_BYTES if self.path in (
            "/research/analyze", "/compare/analyze") else 8000
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
        if path == "/api/browser-companion/next":
            if not self.companion_authorized():
                return
            task=self.server.companion.take()
            if task:
                self.server.cart_jobs.mark_index_browser_in_progress(task["job_id"])
            return self.companion_json({"job":task})
        if path == "/research/shopping":
            return self.shopping_provider_page()
        if path == "/research/companion":
            requested=parse_qs(urlsplit(self.path).query).get("product_url",[""])[0]
            if requested:
                from product_intake import normalized_product_url
                try:
                    requested=normalized_product_url(requested)
                except (ValueError,TypeError):
                    requested=""
            return self.companion_page(default_url=requested)
        if path.startswith("/research/companion/") and path.endswith(".json"):
            job_id = path[len("/research/companion/"):-len(".json")]
            try:
                row=self.server.companion.get_job(job_id)
            except ValueError:
                try:
                    row=self.server.cart_jobs.browser_claim_receipt(job_id)
                except ValueError:
                    return self.companion_json({"error": "UNKNOWN_RESEARCH_JOB"}, 404)
            return self.companion_json(row)
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
                <p><a class="btn" href="/cart">Try cart-triggered analysis</a>
                <a class="btn" href="/research">Research lab</a>
                <a class="btn" href="/compare">Compare offers</a>
                <a class="btn" href="/research/companion">Browser companion</a></p>
                </section>""".format(self.hidden(), menu))
        elif path == "/cart":
            self.cart_entry_page()
        elif path in FLOW_ASSETS:
            self.send_flow_asset(path)
        elif path.startswith("/cart/status/"):
            suffix = path[len("/cart/status/"):]
            if suffix.endswith("/live.json"):
                jid=suffix[:-len("/live.json")]
                try:
                    _,snapshot=self.server.cart_jobs.live_snapshot(jid)
                except ValueError:
                    return self.send_page("<section>Unknown research job</section>",404)
                payload=json.dumps(snapshot,ensure_ascii=False,
                                   separators=(",",":")).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type","application/json; charset=utf-8")
                self.send_header("Cache-Control","no-store")
                self.send_header("X-Content-Type-Options","nosniff")
                self.send_header("Content-Length",str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if suffix.endswith("/live"):
                return self.stream_live_graph(suffix[:-len("/live")])
            question_page = suffix.endswith("/questions.json")
            audit = suffix.endswith("/audit")
            projected = suffix.endswith(".decision.json")
            knowledge_graph = suffix.endswith(".knowledge-graph.json")
            raw = suffix.endswith(".json") and not (projected or knowledge_graph)
            job_id = (suffix[:-len("/questions.json")] if question_page else
                      suffix[:-len("/audit")] if audit else
                      suffix[:-len(".decision.json")] if projected else
                      suffix[:-len(".knowledge-graph.json")] if knowledge_graph else
                      suffix[:-len(".json")] if raw else suffix)
            try:
                result = self.server.cart_jobs.read(job_id)
            except ValueError as exc:
                self.send_page('<section class="error">{}</section>'.format(h(exc)), 404)
                return
            if question_page:
                from offer_question_bank import offer_summaries, questions_for_offer
                from similar_tier import category_of
                args = parse_qs(urlsplit(self.path).query)
                try:
                    number = int(args.get("offer", ["0"])[0])
                    offset = int(args.get("offset", ["0"])[0])
                    limit = int(args.get("limit", ["24"])[0])
                    item = result.get("item") or {}
                    category = category_of(item.get("title") or item.get("merchant_url") or "")
                    offers = offer_summaries({**result,
                          "report": result.get("report") or result.get("preview_report")}, category)
                    if not 0 <= number < len(offers):
                        raise ValueError("Invalid offer")
                    output = questions_for_offer(offers[number], category, offset, limit)
                    saved_evidence=(result.get("evidence_offers") or {}).get(
                        "offer-{}".format(number)) or {}
                    documented={x.get("question_id"):x for x in
                                saved_evidence.get("reference_answers",[])}
                    for question in output["questions"]:
                        observation=documented.get(question["id"])
                        if observation and observation.get("source_sha256"):
                            question["status"]=observation["status"]
                            question["finding"]=observation["finding"]
                            question["evidence"]={
                                "source_url":observation["source_url"],
                                "source_sha256":observation["source_sha256"],
                                "publisher":observation["publisher"],
                                "retrieved_at":observation["retrieved_at"],
                                "reviewed_variant":observation["reviewed_variant"],
                                "verified_for_exact_offer":False}
                    output["reference_only_answers"]=len(documented)
                    output["verified_answers"]=0  # no exact MTM match
                    payload = json.dumps(output, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Content-Security-Policy", FLOW_CSP)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except (TypeError, ValueError, IndexError):
                    self.send_page("<section class='error'>Invalid question page</section>", 400)
            elif projected:
                self.send_flow_projection(result)
            elif knowledge_graph:
                self.send_knowledge_graph_projection(result,job_id)
            elif raw:
                output = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(len(output)))
                self.end_headers()
                self.wfile.write(output)
            elif audit:
                self.legacy_cart_status_page(job_id, result)
            else:
                self.cart_status_page(job_id, result)
        elif path == "/compare":
            sample = (Path(__file__).resolve().parent / "examples" /
                      "comparison_three_laptops_FICTIONAL.json").read_text(encoding="utf-8")
            self.send_page("""<section><h2>Conditional comparison · no forced winner</h2>
                <p>Compare supplied offers, model what is cheaper or offers greater
                source-declared capacity, and list unknowns and questions to the
                SELLER for used products. No questionnaire to the buyer and no
                automatic 'best buy' verdict. Full evidence tree stays available.</p>
                <p>Optional per-offer <code>fulfillment</code> evidence can include
                <code>method</code>, <code>cost</code>, <code>currency</code>,
                <code>eta_min_days</code>, <code>eta_max_days</code>,
                <code>source_url</code> and <code>evidence_status: SELLER_DECLARED</code>.
                Transport amounts and times are source claims, not verified checkout
                totals; unknown cost is never assumed to be zero.</p>
                <p class="warning">The prefilled example is FICTIONAL, with
                example.org/com/net sources. No listings or reviews have been fetched.</p>
                <form method="post" action="/compare/analyze">{}
                <label>Offers and source-declared specifications (JSON)
                <textarea name="comparison_data" rows="21" maxlength="60000"
                required>{}</textarea></label>
                <button>Compare options with full evidence trail</button></form>
                </section>""".format(self.hidden(), h(sample)))
        elif path == "/research":
            fixture = (Path(__file__).resolve().parent / "examples" /
                       "sample_research_fixture.json").read_text(encoding="utf-8")
            sample = h(fixture)
            self.send_page("""<section><h2>Browser-based product extraction</h2>
                <p>Analyze explicitly queued, authorized merchant pages using
                the opt-in local browser companion. Observations remain unverified
                and cannot authorize checkout.</p>
                <a class="btn" href="/research/companion">Open browser research queue</a>
                </section><section><h2>Independent Evidence & Critic Lab</h2>
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
                </form>
                <h3>Manufacturer corroboration: Adafruit SHT40 board</h3>
                <p>Read actual merchant and Sensirion OEM pages and check whether the
                two documents agree on chip-level nominal humidity and temperature
                accuracy. This is NOT an independent laboratory test or evidence
                about the assembled board's measured performance.</p>
                <form action="/research/crosscheck" method="post">{}
                <button>Cross-check SHT40 against Sensirion</button></form>
                <p class="warning">Retail price and stock may change.
                Collector records retrieval date; sources are not independently validated.</p>
                </section>""".format(self.hidden(), sample, self.hidden(), self.hidden()))
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

    def legacy_cart_status_page(self, job_id, result):
        state = result["state"]
        title = result["item"].get("title", "Reading the selected product page")
        if state in ("QUEUED", "RUNNING"):
            # No active browser scripting required. Refresh only an in-progress job.
            body = ("""<section><div class="tag">CART ANALYSIS RUNNING</div>
                <h2>{}</h2><p>Research status: <b>{}</b></p>
                <p>The selected cart item is retained. TraceCart is now checking
                product catalog entries, historical crowd-sourced price records
                and (if configured) web search results. No payment is attempted.</p>
                <p><a class="btn" href="/cart/status/{}">Refresh status</a></p>
                </section>""".format(h(title), h(state), h(job_id)))
            html = PAGE.replace("{{body}}", body)
            html = html.replace("<head>", '<head><meta http-equiv="refresh" content="3">', 1)
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if state != "READY":
            problem = result.get("error_type") or "UNKNOWN"
            self.send_page('''<section class="error"><h2>Source could not be analyzed</h2>
                <p>Status: <strong>{}</strong> · Failure class: <strong>{}</strong>.</p>
                <p>TraceCart did not invent source details or bypass the retailer's
                restrictions. This URL may be unsupported or inaccessible to
                automated clients. The original product page can still be opened
                directly in your browser.</p><p><a class="btn" href="/cart">
                Analyze another product URL</a></p></section>'''.format(
                h(state), h(problem)))
            return
        report = result["report"]
        intake = report.get("source_intake", {})
        context = report["root"]["details"]
        sources = report["source_discovery"]
        candidates = sources["catalog"]
        lines = "".join(
            '<tr><td>{}</td><td>{}</td><td><a href="{}" rel="noopener noreferrer" '
            'target="_blank">Catalog record</a></td><td>NO VERIFIED STORE PRICE</td></tr>'.format(
                h(c["name"]), h(c.get("quantity", "not stated")),
                h(c["url"])) for c in candidates)
        if not lines:
            lines = "<tr><td colspan=4>No sufficiently comparable product identity found</td></tr>"
        attempt_html = "".join("<li>{}: <b>{}</b></li>".format(
            h(x["source"]), h(x["status"])) for x in sources["attempts"])
        question_nodes = next(
            (node for node in report["root"]["children"]
             if node["kind"] == "category_model"), None)
        questions = question_nodes["children"] if question_nodes else []
        economics = report.get("unit_economics", {})
        if economics.get("status") == "CALCULATED_FROM_SELLER_CLAIMS":
            econ_html = ("""<section><h2>Selected product: cost per wash</h2>
                <p><strong>{} {} / wash</strong>, using seller-listed price
                {} {} and {} washes declared in the product name.</p>
                <p class="warning">This is an arithmetic conversion of the
                selected seller's claims, not a verified checkout price or
                independently tested optimal dosage. Delivery and discounts
                are excluded. Other products cannot be compared without
                their own verified cost and pack information.</p>
                </section>""".format(
                    h(economics["cost_per_wash"]), h(economics["currency"]),
                    h(economics["seller_listed_price"]), h(economics["currency"]),
                    h(economics["washes_declared_in_title"])))
        else:
            econ_html = ("""<section><h2>Selected product: cost per wash</h2>
                <p>Cannot calculate from existing evidence ({}).
                Need a numeric seller price and one unambiguous declared
                number of washes. Do not guess from package weight alone.</p>
                </section>""".format(h(economics.get("status", "NOT_AVAILABLE"))))
        question_summary = "".join("<li>{}</li>".format(h(q["title"]))
                                   for q in questions[:8])
        source_details = ""
        if intake:
            limited = intake.get("intake_status") == "URL_ONLY_UNVERIFIED"
            source_details = ("""<section><h2>{}</h2>
                <p>Page: <a href="{}" target="_blank" rel="noopener noreferrer">{}</a></p>
                <p>Method: {} · Retrieved: {}</p>
                <p>Price extraction: <strong>{}</strong>. EAN: <strong>{}</strong>.
                Seller availability statement: {}.</p>
                <p>Current price metadata: {}. Reference/list price:
                {} (NOT the active offer price).</p>
                <p>Page SHA-256: <code>{}</code></p>
                <p class="warning">{}</p>
                {}
                </section>""".format(
                    ("Limited URL-only identification — product page unavailable"
                     if limited else "Original product page — extracted facts"),
                    h(intake["source_url"]), h(intake["source_url"]),
                    h(intake["extraction_method"]),
                    h(intake.get("retrieved_at") or "NOT DOWNLOADED"),
                    h(intake["price_status"]), h(intake["barcode_status"]),
                    h(intake.get("availability_claim") or "NOT VERIFIED"),
                    h(intake.get("price_evidence_method") or "NOT PROVIDED"),
                    h(intake.get("reference_list_price") or "NOT PROVIDED"),
                    h(intake.get("page_sha256") or "NOT AVAILABLE"),
                    ("This retailer did not provide usable product page content "
                     "({}). The displayed product label was inferred ONLY from "
                     "the URL you supplied, not verified against the store. "
                     "Actual product identity, price, pack contents, stock, "
                     "EAN and seller details remain unverified. No access "
                     "restrictions were bypassed.".format(
                         h(intake.get("access_problem", "SOURCE_BLOCKED")))
                     if limited else
                     "These are claims on the seller page, not independently "
                     "verified tests or the final checkout price."),
                    ("<p>Identifiers found in supplied URL: <code>{}</code>. "
                     "Offer ID, if present: <code>{}</code>. "
                     "These are NOT EAN codes and do not verify the actual offer. "
                     "Current prices and stock require an authorized source.</p>".format(
                        h(", ".join(intake.get("product_url_identifiers", [])) or
                          intake.get("allegro_product_id") or "not found"),
                        h(intake.get("allegro_offer_id") or "not supplied"))
                     if limited else "")))

        displayed_price = (str(result["item"]["price"]) + " " +
                           str(result["item"]["currency"])
                           if result["item"]["price"] is not None
                           else "not disclosed by the source")
        body = """<section><div class="tag">PRE-CHECKOUT INSIGHT · NOT A PAYMENT ACTION</div>
            <h2>Automatic analysis of selected cart item</h2>
            <p><strong>{}</strong> · source-listed price {} (not independently verified)</p>
            <p>Product category: <b>{}</b>. Model/source questions: <b>{}</b>.
            AI enrichment: <b>{}</b>.</p>
            <p class="warning">No current competing retailer prices were verified.
            A catalog product is NOT a store offer. TraceCart will not invent
            "10% cheaper" or imply these catalog entries are immediately available.</p>
            <p><a class="btn" href="/cart/status/{}.json">Export complete audit JSON</a>
            <a class="btn" href="/cart">Analyze another cart item</a></p></section>
            <section><h2>Other matching product identities found online</h2>
            <table><thead><tr><th>Product</th><th>Pack/quantity</th>
            <th>Source</th><th>Verified retail price</th></tr></thead>
            <tbody>{}</tbody></table>
            <p>These are searchable alternatives, not competing checkout offers.</p></section>
            <section><h2>Relevant questions for listings, reviews and tests</h2>
            <ul>{}</ul></section>
            <section><h2>Search outcomes and limitations</h2><ul>{}</ul>
            <p>Review evidence: 0 independent tests confirmed. Payment remains
            a separate, buyer-authorized step.</p></section>
            <section><h2>Complete expandable research &amp; critic tree</h2>{}</section>""".format(
            h(title), h(displayed_price), h(context["category"]),
            h(len(questions)), h(context["local_ai_question_generation"]),
            h(job_id), lines, question_summary, attempt_html, to_html_tree(report))
        search_url = "https://www.google.com/search?" + urlencode({
            "tbm": "shop", "q": result["item"]["title"][:140]})
        country_hint = suggested_country(self.headers.get("Accept-Language", "")) or ""
        competitor_form = ("""<section><h2>Compare up to four other stores</h2>
            <p>Paste 1–4 public HTTPS product-page URLs, one per line, from
            different retailers. TraceCart checks robots.txt and independently
            retrieves each source, preserving failures, stock, price and
            GTIN evidence in the complete tree. Search snippets never become
            verified prices. Product-plus-shipping subtotals require explicit buyer country and seller shipping evidence; payment fees and checkout totals remain unverified.</p>
            <p><a href="{}" target="_blank" rel="noopener noreferrer">
            Search shopping listings (external)</a></p>
            <form method="post" action="/cart/compare-live">{}
            <input type="hidden" name="job_id" value="{}">
            <label>Alternative retailer product URLs (one per line)
            <textarea name="competitor_urls" rows="4" maxlength="4800"
            placeholder="https://other-store.example/product/..."></textarea></label>
            <label>Destination country (editable, ISO two-letter code)
            <input name="buyer_country" maxlength="2" pattern="[A-Za-z]{{2}}"
            value="{}" placeholder="e.g. PL" autocomplete="country"></label>
            <p>Country suggested from browser language-region settings, not verified location.
            Check or change it before comparing delivery costs. If blank, delivery costs stay unknown.</p>
            <p><b>Browser-based marketplace capture (feasibility prototype)</b>.
            Open the product in your ordinary browser, click the TraceCart
            Capture extension, and paste its JSON here. This is a user-initiated,
            still UNVERIFIED DOM observation; it cannot establish the market's
            lowest price or do unattended marketplace research.</p>
            <label>Browser capture JSON (optional, one product)
            <textarea name="browser_capture_json" rows="6" maxlength="3800"
            placeholder='{{"version":1,"method":"USER_SELECTED_VISIBLE_PRICE",...}}'></textarea></label>
            <p><b>Optional cheaper marketplace lead</b> (e.g. a listing your browser
            can display but TraceCart cannot fetch). This stays an UNVERIFIED
            observation: neither product identity nor price is confirmed here.</p>
            <label>Marketplace listing URL
            <input type="text" name="marketplace_url" maxlength="1200"
            placeholder="https://marketplace.example/product/..."></label>
            <label>Price seen in browser (product price only)
            <input type="text" name="marketplace_price" maxlength="16"
            placeholder="265.00"></label>
            <label>Observed price currency
            <select name="marketplace_currency"><option>PLN</option>
            <option>EUR</option><option>USD</option></select></label>
            <button>Audit competing sources and compare seller claims</button>
            </form></section>""".format(
                h(search_url), self.hidden(), h(job_id), h(country_hint)))
        discovery_panel = (shopping_search_panel(report) +
                           automatic_discovery_panel(report))
        indexed=report.get("indexed_shopping") or {}
        note=(
            '<section><h2>Important: evidence sources have separate counts</h2>'
            '<p><strong>catalog_alternatives_found</strong> counts only records '
            'from the OPF catalog: <b>{}</b>. Google Shopping '
            'returned <b>{}</b> product cards and <b>{}</b> indexed '
            'retailer links. None of these links establishes '
            'a final checkout total or independently measured product quality.</p>'
            '<p><a class="btn" href="/cart/status/{}">'
            'Open interactive product decision graph</a></p></section>'
        ).format(h(len(sources.get("catalog") or [])),
                 h(len(indexed.get("search_result_groups") or [])),
                 h(len(indexed.get("indexed_offers") or [])),h(job_id))
        self.send_page(note + source_details + econ_html + discovery_panel
                       + competitor_form + body)

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
                <p class="warning">{}</p>
                <p>Retrieval policy: {}</p></section>""".format(
                    h(collection["fetched_pages"]), h(collection["requested_pages"]),
                    h(collection["review_sources_collected"]),
                    h(collection["independent_product_tests_collected"]),
                    h("Two source publishers: retailer declares board price/availability; "
                      "Sensirion declares chip nominal accuracy. No independent "
                      "measurements, test reports or reviews."
                      if collection.get("collector") ==
                      "merchant_vs_sensirion_sht40_visible_html"
                      else "All collected price, stock and condition facts come from "
                           "the merchant and are not independently corroborated."),
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
            <p><b>Research branches:</b> {} · <b>Research state:</b> {}
            · <b>Generated:</b> {}</p>
            <p><a class="btn" href="/research/report/{}.json">Export complete JSON</a>
            <a class="btn" href="/research">Start another investigation</a></p>
            <p class="warning">Source excerpts are unverified input data.
            This is NOT authorization to make a purchase.</p></section>
            <section><h2>Every decision, objection, source and question</h2>
            {} </section>""".format(
            h(report["sha256"]), branch_count, h(summary["children"][-1]["status"]),
            h(report["generated_at"]), h(rid), to_html_tree(report))
        crosscheck = report.get("crosscheck", [])
        if crosscheck:
            stats = "".join(
                "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                    h(row["metric"]), h(row["merchant_value"]),
                    h(row["manufacturer_value"]), h("AGREE" if row["documents_agree"]
                                                   else "CONFLICT"))
                for row in crosscheck)
            table = ("""<section><h2>Two-publisher SHT40 documentation cross-check</h2>
               <p><strong>Scope:</strong> nominal SHT40 chip specifications only.
               Agreement of documents does not establish independently tested
               sensor performance or the quality of the assembled breakout.</p>
               <table><thead><tr><th>Metric</th><th>Merchant</th>
               <th>Component manufacturer</th><th>Documents</th></tr></thead>
               <tbody>{}</tbody></table></section>""".format(stats))
            body = table + body
        live = report.get("live_competitor_comparison")
        if live:
            other = live.get("alternative") or {}
            source = live.get("alternative_source") or {}
            selected = live["selected"]
            def shown(item):
                return ("{} {}".format(item["price"], item["currency"])
                        if item.get("price") is not None else "UNKNOWN")
            delta = live.get("seller_listed_price_delta_pct_vs_selected")
            delivery = live.get("delivery_break_even")
            if delivery:
                if delivery["lower_listed_price_offer"] == "neither":
                    delivery_note = ("""<p><strong>Delivery sensitivity (one pack):
                        listed prices tie.</strong> Whichever seller has lower
                        delivery and fees may be cheaper; both amounts are
                        unknown.</p>""")
                else:
                    delivery_note = ("""<p><strong>Delivery break-even (one pack):
                        {} {}.</strong> The {} listing is cheaper before
                        delivery. It remains cheaper only if its additional
                        delivery and fees relative to the other listing are
                        <strong>less than {} {}</strong>. At that difference,
                        total prices tie. Actual delivery, discount eligibility
                        and checkout totals are UNKNOWN.</p>""".format(
                            h(delivery["one_pack_listed_price_advantage"]),
                            h(delivery["currency"]),
                            h(delivery["lower_listed_price_offer"]),
                            h(delivery["max_extra_shipping_and_fees_for_lower_listed_price_offer"]),
                            h(delivery["currency"])))
            else:
                delivery_note = ("""<p class="warning">No shipping break-even:
                    product identity, seller-declared stock, price or currency
                    is not sufficiently established. Delivery costs remain
                    unknown; no savings are claimed.</p>""")
            table = ("""<section><div class="tag">SECOND LIVE MERCHANT SOURCE</div>
                <h2>Second-offer evidence · {}</h2>
                <table><tr><th>Selected</th><th>Second seller</th></tr>
                <tr><td>{}<br>Seller-listed price: {}<br>
                Cost/wash: {}</td><td>{}<br>Seller-listed price: {}<br>
                Cost/wash: {}</td></tr></table>
                <p>Second source: <a href="{}" target="_blank"
                rel="noopener noreferrer">{}</a></p>
                <p>Retrieved: {} · Page SHA-256: <code>{}</code></p>
                <p>Second seller current price evidence: {}.
                Reference/list price (NOT payable price): {}.</p>
                <p>GTIN equality claimed: {} · Listed price change vs selected: {}.</p>
                <p>Stock evidence: selected {} · second {}.</p>
                {}
                <p class="warning">Seller assertions only, not verified
                checkout totals. No automatic purchase. Missing or conflicting
                identity, price or currency prevents a cheaper-equivalent claim.
                Shipping, discounts, actual dose and product performance remain
                unknown. The complete source/critic tree is below.</p></section>""".format(
                    h(live["status"]), h(selected["title"]), h(shown(selected)),
                    h(live["selected_cost_per_wash"].get("cost_per_wash") or "UNKNOWN"),
                    h(other.get("title") or "NOT RETRIEVED"), h(shown(other)),
                    h(live["alternative_cost_per_wash"].get("cost_per_wash") or "UNKNOWN"),
                    h(live["alternative_requested_url"]), h(live["alternative_requested_url"]),
                    h(source.get("retrieved_at") or "NOT DOWNLOADED"),
                    h(source.get("page_sha256") or "NOT AVAILABLE"),
                    h(source.get("price_evidence_method") or "NOT PROVIDED"),
                    h(source.get("reference_list_price") or "NOT PROVIDED"),
                    h(live["same_gtin_claimed"]),
                    h(delta + "%" if delta is not None else "NOT COMPARABLE"),
                    h(live.get("selected_stock_evidence") or "UNKNOWN"),
                    h(live.get("alternative_stock_evidence") or "UNKNOWN"),
                    delivery_note))
            body = table + body
        multi = report.get("live_competitor_comparisons")
        if multi:
            rows = []
            for entry in multi:
                other = entry.get("alternative") or {}
                source = entry.get("alternative_source") or {}
                cost = entry.get("alternative_cost_per_wash") or {}
                rows.append(
                    '<tr><td><a href="{}" target="_blank" '
                    'rel="noopener noreferrer">{}</a></td>'
                    '<td>{}</td><td>{}</td><td>{}</td>'
                    '<td>{}</td><td>{}</td><td>{}</td></tr>'.format(
                        h(entry["alternative_requested_url"]),
                        h(entry["alternative_requested_url"]),
                        h(entry["status"]),
                        h("{} {}".format(other.get("price"), other.get("currency"))
                          if other.get("price") is not None else "UNKNOWN"),
                        h(cost.get("cost_per_wash") or "UNKNOWN"),
                        h(entry.get("alternative_stock_evidence") or "UNKNOWN"),
                        h(source.get("retrieved_at") or "NOT DOWNLOADED"),
                        h(source.get("page_sha256") or "NOT AVAILABLE")))
            info = report["multi_offer_summary"]
            body = ("""<section><div class="tag">BOUNDED MULTI-STORE EVIDENCE</div>
                <h2>Independent source audit: {} of {} pages retrieved</h2>
                <p>{} other seller pages passed the identity, stock, price
                and currency gates against the original selected product.
                These are seller claims, not independently verified stock or
                checkout totals. Distinct domains may belong to one company.</p>
                <table><tr><th>Source</th><th>Evidence status</th>
                <th>Listed price</th><th>Cost per wash</th><th>Stock</th>
                <th>Retrieved</th><th>SHA-256</th></tr>{}</table>
                <p class="warning">No delivered-price winner. Shipping,
                fees, discount eligibility, destination and actual product
                performance remain unknown. All unsuccessful source checks
                and critic objections are retained in the full tree.</p>
                </section>""".format(
                    h(info["pages_retrieved"]), h(info["requested"]),
                    h(info["source_qualified_comparisons"]), "".join(rows))) + body
        if (report.get('multi_offer_research_critic') or
                report.get('single_offer_research_critic')):
            body = research_critic_panel(report) + body
        if report.get('marketplace_leads'):
            body = marketplace_lead_panel(report) + body
        if report.get("automatic_offer_discovery"):
            body = automatic_discovery_panel(report) + body
        if report.get("indexed_shopping"):
            body = shopping_search_panel(report) + body
        comparison = report.get("comparison_summary")
        if comparison:
            rows = []
            for opt in comparison["options"]:
                questions = ("<br>".join("• " + h(q) for q in opt["seller_questions"])
                             if opt["seller_questions"] else "None automatically required")
                shipping = opt["fulfillment"]
                if shipping["product_plus_shipping"] is not None:
                    transport = ("{} {} (product + seller-declared shipping); ETA {}–{} days. "
                                 "Fees and final checkout unknown.".format(
                                     h(shipping["product_plus_shipping"]), h(opt["currency"]),
                                     h(shipping["eta_min_days"]) if shipping["eta_min_days"] is not None else "?",
                                     h(shipping["eta_max_days"]) if shipping["eta_max_days"] is not None else "?"))
                else:
                    transport = "Transport cost unknown (pickup travel cost not assumed zero)."
                rows.append("<tr><td>{}</td><td><strong>{} {}</strong></td>"
                            "<td>{}</td><td>{}</td><td>{}</td></tr>".format(
                                h(opt["title"]), h(opt["price"]), h(opt["currency"]),
                                h(opt["condition"]), transport, questions))
            pairs = []
            for pair in comparison["pairwise"]:
                change = pair["right_vs_left_pct"]
                if change is None:
                    description = "Percentage unavailable (zero baseline price)."
                elif change.startswith("-"):
                    description = ("{} is {} cheaper than {}, using {} as baseline."
                                   .format(h(pair["right_offer"]), h(change[1:]),
                                           h(pair["left_offer"]), h(pair["left_offer"])))
                elif change.startswith("0"):
                    description = "Both offers display the same listed price."
                else:
                    description = ("{} is {} more expensive than {}, using {} as baseline."
                                   .format(h(pair["right_offer"]), h(change),
                                           h(pair["left_offer"]), h(pair["left_offer"])))
                metrics = []
                for m in pair["metric_differences"]:
                    if m["status"] != "LISTING_DECLARED_COMPARISON":
                        metrics.append("{}: missing/incompatible comparable data".format(
                            h(m["metric"])))
                    else:
                        metrics.append("{}: {} {} versus {} {} ({} on second offer; "
                                       "real benefit depends on use).".format(
                                           h(m["label"]), h(m["left_value"]),
                                           h(m["unit"]), h(m["right_value"]),
                                           h(m["unit"]), h(m["right_vs_left"])))
                shipping_diff = pair["right_minus_left_product_plus_shipping"]
                if shipping_diff is not None:
                    description += (" Seller-declared product + shipping difference "
                                    "(right minus left): {} {}. Checkout fees unknown."
                                    .format(h(shipping_diff), h(comparison["currency"])))
                pairs.append("<li>{}<br><span class='muted'>{}</span></li>".format(
                    description, "<br>".join(metrics)))
            comparison_html = ("""<section><div class="tag">COMPARATIVE ANALYSIS · NO VERDICT</div>
                <h2>Prices, capabilities and unknowns</h2>
                <p>Price differences are calculated against an explicit reference
                price. Technical values are seller-declared, not verified benchmarks.
                Greater capacity may not be useful for the intended workload.</p>
                <table><thead><tr><th>Offer</th><th>Listed price</th>
                <th>Condition</th><th>Transport and timing</th>
                <th>Questions to seller / listing</th></tr></thead>
                <tbody>{}</tbody></table>
                <h3>Direct comparisons</h3><ul>{}</ul>
                <p class="warning">Research does not pick a winner.
                The full tree below records the source links, evidence objections
                and all open questions. Payment authorization is a separate step.</p>
                </section>""".format("".join(rows), "".join(pairs)))
            body = comparison_html + body
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

    def cart_event_api(self):
        # Server-to-server integration for an authorized checkout application.
        # This local demo does not automatically install a WooCommerce webhook.
        configured = os.environ.get("TRACECART_CART_WEBHOOK_TOKEN", "")
        token = self.headers.get("X-TraceCart-Event-Token", "")
        if not configured:
            self.send_page('<section class="error">Cart API disabled</section>', 503)
            return
        if not token or not hmac.compare_digest(configured, token):
            self.send_page('<section class="error">Unauthorized cart event</section>', 403)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 1 <= size <= 4096:
                raise ValueError("Invalid cart event size")
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                raise ValueError("Cart API accepts JSON only")
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
            if type(payload) is dict and set(payload) == {"product_url"}:
                job_id = self.server.cart_jobs.submit_url(payload["product_url"])
            else:
                job_id = self.server.cart_jobs.submit(payload)
            body = json.dumps({
                "accepted": True, "job_id": job_id, "state": "QUEUED",
                "status_path": "/cart/status/" + job_id,
            }).encode("utf-8")
            self.send_response(202)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ValueError, TypeError, UnicodeError):
            self.send_page('<section class="error">Invalid cart event</section>', 400)

    def do_POST(self):
        if not self.trusted_host():
            return
        if self.path == "/api/cart/added":
            return self.cart_event_api()
        if self.path == "/api/browser-companion/result":
            if not self.companion_authorized():
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 2 <= size <= 16000 or (
                        self.headers.get("Content-Type", "").split(";", 1)[0].strip()
                        != "application/json"):
                    raise ValueError("INVALID_COMPANION_CONTENT_TYPE_OR_SIZE")
                payload = json.loads(self.rfile.read(size).decode("utf8"))
                ack=self.server.companion.report(payload)
                if ack["status"]=="PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED":
                    # Persist the filtered claim before notifying the live
                    # graph; otherwise SSE might cache a missing result.
                    row=self.server.companion.get_job(ack["job_id"])
                    self.server.cart_jobs.store_browser_claim(row)
                self.server.cart_jobs.finish_index_browser_task(
                    ack["job_id"], ack["status"])
                self.server.cart_jobs.finish_browser_auto_task(
                    ack["job_id"], ack["status"])
                return self.companion_json(ack)
            except (ValueError, UnicodeError, TypeError, KeyError):
                return self.companion_json({"error": "INVALID_COMPANION_RECEIPT"}, 400)
        try:
            form = self.form()
            if (self.path.startswith("/cart/status/") and
                    self.path.endswith("/search-index")):
                cart_job_id=self.path[len("/cart/status/"):-len("/search-index")]
                self.server.cart_jobs.request_shopping_refresh(cart_job_id)
                self.send_response(303)
                self.send_header("Location","/cart/status/"+cart_job_id)
                self.send_header("Cache-Control","no-store")
                self.send_header("Content-Length","0")
                self.end_headers()
                return
            if (self.path.startswith("/cart/status/") and
                    self.path.endswith("/auto-verify")):
                cart_job_id=self.path[len("/cart/status/"):-len("/auto-verify")]
                from automatic_browser_verification import enqueue_for_completed_cart
                result=enqueue_for_completed_cart(self.server,cart_job_id)
                if result["status"] not in ("QUEUED","ALREADY_QUEUED"):
                    raise ValueError("AUTOMATIC_BROWSER_NOT_ENABLED_OR_NOT_AVAILABLE")
                self.send_response(303)
                self.send_header("Location","/cart/status/"+cart_job_id)
                self.send_header("Cache-Control","no-store")
                self.send_header("Content-Length","0")
                self.end_headers()
                return
            if (self.path.startswith("/cart/status/") and
                    self.path.endswith("/verify-indexed")):
                cart_job_id=self.path[len("/cart/status/"):-len("/verify-indexed")]
                targets=self.server.cart_jobs.indexed_browser_targets(cart_job_id)
                if not targets:
                    raise ValueError("NO_DIRECT_SELLER_URLS_TO_VERIFY")
                # Requires a direct, CSRF-protected user POST. No background
                # search result ever grants browser-site permission itself.
                existing=self.server.cart_jobs.index_browser_checks(cart_job_id)
                if any(x["status"] in ("QUEUED","IN_PROGRESS") for x in existing):
                    raise ValueError("INDEX_VERIFICATION_ALREADY_RUNNING")
                # Retrying inaccessible sites requires another explicit
                # human click, not a hidden browser loop.
                if existing:
                    failed={x["offer_idx"] for x in existing
                            if x["status"]!="PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED"}
                    targets=[x for x in targets if x["offer_idx"] in failed] or targets
                queued=self.server.companion.enqueue_many(
                    [row["url"] for row in targets],hold=True)
                try:
                    self.server.cart_jobs.register_index_browser_batch(
                        cart_job_id,targets,queued)
                except Exception:
                    self.server.companion.cancel_held(queued)
                    raise
                self.server.companion.release_many(queued)
                self.send_response(303)
                self.send_header("Location","/cart/status/"+cart_job_id)
                self.send_header("Cache-Control","no-store")
                self.send_header("Content-Length","0")
                self.end_headers()
                return
            if self.path == "/research/shopping/configure":
                if form.get("operation")=="enable":
                    self.server.cart_jobs.configure_shopping_provider(
                        form.get("api_key",""))
                elif form.get("operation")=="disable":
                    self.server.cart_jobs.disable_shopping_provider()
                else:
                    raise ValueError("INVALID_PROVIDER_ACTION")
                self.send_response(303)
                self.send_header("Location","/research/shopping")
                self.send_header("Cache-Control","no-store")
                self.send_header("Content-Length","0")
                self.end_headers()
                return
            if self.path == "/research/companion/auto":
                action=form.get("operation")
                if action not in ("enable","disable"):
                    raise ValueError("INVALID_AUTOMATIC_BROWSER_SETTING")
                self.server.cart_jobs.set_browser_auto_enabled(action=="enable")
                self.send_response(303)
                self.send_header("Location","/research/companion")
                self.send_header("Cache-Control","no-store")
                self.send_header("Content-Length","0")
                self.end_headers()
                return
            if self.path == "/research/companion/queue":
                urls = [v.strip() for v in form.get("product_urls", "").splitlines()
                        if v.strip()]
                self.server.companion.enqueue_many(urls)
                self.send_response(303)
                self.send_header("Location", "/research/companion")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if self.path.startswith("/cart/status/") and self.path.endswith("/input-price"):
                job_id=self.path[len("/cart/status/"):-len("/input-price")]
                # Input only; never claim a user-visible price was fetched.
                self.server.cart_jobs.set_input_price(
                    job_id,form.get("observed_price",""),
                    form.get("observed_currency","PLN"),
                    promotion_code=form.get("promotion_code") or None)
                self.server.cart_jobs.refresh_price_comparison(job_id)
                self.send_response(303)
                self.send_header("Location","/cart/status/"+job_id)
                self.send_header("Cache-Control","no-store")
                self.send_header("Content-Length","0")
                self.end_headers()
            elif self.path == "/cart/add":
                if form.get("product_url"):
                    job_id = self.server.cart_jobs.submit_url(
                        form["product_url"],form.get("observed_price") or None,
                        form.get("observed_currency","PLN"),
                        form.get("promotion_code") or None)
                else:
                    # Historical JSON demo path kept for existing integration tests.
                    item = {k: form.get(k, "") for k in (
                        "title", "price", "currency", "barcode", "merchant_url")}
                    job_id = self.server.cart_jobs.submit(item)
                # Post/Redirect/Get: render the interactive tree immediately
                # after the click, without a second link or duplicate POST on refresh.
                self.send_response(303)
                self.send_header("Location","/cart/status/"+job_id)
                self.send_header("Cache-Control","no-store")
                self.send_header("X-Content-Type-Options","nosniff")
                self.send_header("Content-Length","0")
                self.end_headers()
            elif self.path == "/cart/compare-live":
                job = self.server.cart_jobs.read(form.get("job_id", ""))
                if job["state"] != "READY" or not job.get("report"):
                    raise ValueError("Original cart research must be READY")
                raw_urls = form.get("competitor_urls", "")
                urls = [line.strip() for line in raw_urls.splitlines()
                        if line.strip()]
                if not urls and form.get("competitor_url"):
                    urls = [form["competitor_url"]]  # legacy clients
                marketplace_url = form.get("marketplace_url", "").strip()
                marketplace_price = form.get("marketplace_price", "").strip()
                browser_json = form.get("browser_capture_json", "").strip()
                if browser_json and (marketplace_url or marketplace_price):
                    raise ValueError("Choose browser capture OR typed marketplace lead")
                if bool(marketplace_url) != bool(marketplace_price):
                    raise ValueError("Marketplace lead URL and observed price must both be supplied")
                market_leads = None
                if browser_json:
                    market_leads = [parse_browser_capture(browser_json)]
                    if not urls:
                        urls = [market_leads[0]["url"]]
                if marketplace_url:
                    market_leads = [{
                        "url": marketplace_url,
                        "price": marketplace_price,
                        "currency": form.get("marketplace_currency", "PLN"),
                        "origin": "USER_REPORTED_NOT_FETCHED",
                    }]
                    # When only a marketplace listing was supplied, attempt
                    # ordinary robots-aware retrieval too, retaining denial.
                    if not urls:
                        urls = [marketplace_url]
                buyer_country = form.get("buyer_country", "").strip().upper() or None
                if buyer_country is not None and (len(buyer_country) != 2 or
                        not buyer_country.isascii() or not buyer_country.isalpha()):
                    raise ValueError("Destination country must be two ASCII letters")
                report = compare_live_offers(
                    job["report"], job["item"], urls, buyer_country=buyer_country,
                    marketplace_observations=market_leads)
                rid = self.server.reports.save(report)
                self.research_report_page(rid, report)
            elif self.path == "/propose":
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
            elif self.path == "/research/crosscheck":
                report, sourced = collect_spec_crosscheck()
                rid = self.server.reports.save(report)
                self.research_report_page(rid, report)
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
            elif self.path == "/compare/analyze":
                raw = form.get("comparison_data", "")
                if len(raw) > 60000:
                    raise ValueError("Comparison input too large")
                report = compare(json.loads(raw))
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
    server = StreamingHTTPServer(("127.0.0.1", args.port), TraceCartHandler)
    server.csrf = secrets.token_urlsafe(32)
    server.store = CheckoutStore(str(args.db))
    server.reports = ReportStore(server.store.db)
    server.cart_jobs = CartResearchJobs(args.db)
    server.companion = CompanionQueue(token_path=args.db.parent /
                                      "browser_companion.token")
    from automatic_browser_verification import enqueue_for_completed_cart
    server.cart_jobs.on_research_ready=lambda jid:enqueue_for_completed_cart(
        server,jid)
    # Submitting a product URL is enough to authorize automated, bounded
    # research of eligible public merchant pages. Preserve an explicit opt-out.
    with server.cart_jobs._db() as db:
        db.execute("""INSERT OR IGNORE INTO cart_browser_auto_settings
            (id,enabled) VALUES (1,1)""")
    from managed_browser_verification import ManagedBrowserWorker
    browser_worker = ManagedBrowserWorker(server)
    server.managed_browser = browser_worker
    browser_worker.start()
    print("TraceCart local demo: http://127.0.0.1:{}".format(args.port))
    print("PayPal mode: sandbox only; no capture code; user approval mandatory")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        browser_worker.close()
        server.server_close()
        server.cart_jobs.close()
        server.store.db.close()


if __name__ == "__main__":
    run()
