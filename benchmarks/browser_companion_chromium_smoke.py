#!/usr/bin/env python3
"""Run the actual browser extraction function in isolated Chromium DOM.

Only locally generated HTTPS pages are visited. No external shops, credentials,
merchant scraping, extension pairing or checkout. Requires Chromium, openssl,
and websocket-client; runs on hexagony-01, not in automated CI.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen

import websocket

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FUNC = (ROOT / "browser-extension/queue_capture.mjs").read_text(encoding="utf8")
FUNC = FUNC.replace("export function traceCartQueuedProductProjection",
                    "function traceCartQueuedProductProjection", 1)
SAMPLE = {"@type": "Product", "name": "Drill Sample Model-X",
          "offers": {"@type": "Offer", "price": "49.90", "priceCurrency": "PLN"}}
DIFFERENT = {"@type": "Product", "name": "Drill Sample Model-X",
             "offers": {"@type": "Offer", "price": "199.00", "priceCurrency": "PLN"}}


def page(inner, body_class=""):
    return ('<!doctype html><html><head><title>Sample Product</title></head><body class="'
            + body_class + '">' + inner + '</body></html>')


def ld(record):
    return ("<script type='application/ld+json'>" + json.dumps(record) +
            "</script>")


def fixtures():
    micro = ("""<div itemscope itemtype="https://schema.org/Product">
         <h1 itemprop="name">Drill Sample Microdata</h1>
         <div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
           <meta itemprop="price" content="70.50">
           <meta itemprop="priceCurrency" content="EUR">
         </div></div>""")
    woo = ("""<h1 class="product_title">Drill Sample Model-X</h1>
      <div class="summary entry-summary"><p class="price">
      <del><span><bdi>199,00 zł</bdi></span></del>
      <ins><span><bdi>119,00 zł</bdi></span></ins>
      </p></div>""")
    dynamic = ("""<div id="root">Loading...</div>
      <script>document.addEventListener('DOMContentLoaded',()=>{
        const el=document.createElement('script');
        el.type='application/ld+json';
        el.textContent=JSON.stringify(""" + json.dumps(SAMPLE) + """);
        document.body.appendChild(el);
      });</script>""")
    return {
        "/ld": (page(ld(SAMPLE)), "49.90", "DIRECT_OFFER_PRICE"),
        "/js": (page(dynamic), "49.90", "DIRECT_OFFER_PRICE"),
        "/micro": (page(micro), "70.50", "PRODUCT_OFFER_MICRODATA"),
        "/woo": (page(woo, "single-product"), "119.00",
                 "WOOCOMMERCE_PRIMARY_PRICE"),
        "/conflict": (page(ld(DIFFERENT) + woo, "single-product"),
                      "CONFLICTING_OFFER_EVIDENCE", None),
        "/unrelated": (page("<p>We also sell products for 12 zł</p>"),
                       "NO_STRUCTURED_PRODUCT", None),
        "/micro-many": (page(micro+micro),
                        "MULTIPLE_PRODUCTS_AMBIGUOUS", None),
        "/micro-multiple-offers": (page("""
          <div itemscope itemtype="https://schema.org/Product">
           <h1 itemprop="name">Two sizes of one product</h1>
           <div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
            <meta itemprop="price" content="20.00">
            <meta itemprop="priceCurrency" content="PLN"></div>
           <div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
            <meta itemprop="price" content="30.00">
            <meta itemprop="priceCurrency" content="PLN"></div>
          </div>"""), "NO_STRUCTURED_PRODUCT", None),
        "/woo-related": (page(woo+"""
            <div class="related"><div class="price"><bdi>1,00 zł</bdi></div></div>
            """, "single-product"), "119.00", "WOOCOMMERCE_PRIMARY_PRICE"),
        "/woo-list-only": (page("""
           <h1 class="product_title">Drill Sample Model-X</h1>
           <div class="summary entry-summary"><p class="price">
           <del><bdi>200,00 zł</bdi></del></p></div>
           """, "single-product"), "NO_STRUCTURED_PRODUCT", None),
        "/conflicting-title": (page(
            ld({"@type":"Product","name":"Completely Different Item",
                "offers":{"@type":"Offer","price":"119.00",
                          "priceCurrency":"PLN"}})+woo, "single-product"),
            "CONFLICTING_PRODUCT_IDENTITY", None),
    }


class Handler(BaseHTTPRequestHandler):
    records = fixtures()

    def do_GET(self):
        item = self.records.get(self.path)
        if item is None:
            self.send_error(404)
            return
        body = item[0].encode("utf8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *unused):
        pass


def cdp_call(ws, method, params=None):
    counter = getattr(cdp_call, "counter", 0) + 1
    cdp_call.counter = counter
    ws.send(json.dumps({"id": counter, "method": method, "params": params or {}}))
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        message = json.loads(ws.recv())
        if message.get("id") == counter:
            if message.get("error"):
                raise RuntimeError("CDP error " + str(message["error"]))
            return message.get("result", {})
    raise RuntimeError("CDP timeout for " + method)


def evaluate(ws, expression):
    response = cdp_call(ws, "Runtime.evaluate", {
        "expression": expression, "returnByValue": True,
        "awaitPromise": False, "timeout": 8000
    })
    if response.get("exceptionDetails"):
        raise RuntimeError("DOM JS exception " + str(response["exceptionDetails"]))
    return response.get("result", {}).get("value")


def smoke(public_adafruit=False):
    shared = Path.home() / "snap/chromium/common"
    if not shared.is_dir():
        raise RuntimeError("SNAP_CHROMIUM_COMMON_MISSING")
    chromium = shutil.which("chromium")
    if not chromium:
        raise RuntimeError("CHROMIUM_MISSING")
    with tempfile.TemporaryDirectory(prefix="tracecart-dom-smoke-",
                                     dir=str(shared)) as folder:
        root = Path(folder)
        cert = root / "cert.pem"
        key = root / "key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048",
                        "-nodes", "-days", "1", "-subj", "/CN=127.0.0.1",
                        "-keyout", str(key), "-out", str(cert)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=12, check=True)
        httpd = HTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert), str(key))
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        proc = None
        ws = None
        try:
            profile = root / "profile"
            proc = subprocess.Popen([
                chromium, "--headless=new", "--no-sandbox", "--disable-gpu",
                "--disable-dev-shm-usage", "--disable-extensions",
                "--no-first-run", "--no-default-browser-check",
                "--allow-insecure-localhost", "--remote-debugging-port=0",
                "--remote-allow-origins=*",
                "--user-data-dir=" + str(profile), "about:blank"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            debug = profile / "DevToolsActivePort"
            for _ in range(40):
                if debug.is_file():
                    break
                if proc.poll() is not None:
                    raise RuntimeError("CHROMIUM_FAILED_TO_START")
                time.sleep(0.25)
            if not debug.is_file():
                raise RuntimeError("CHROMIUM_DEBUG_PORT_MISSING")
            port = int(debug.read_text().splitlines()[0])
            pages = json.load(urlopen("http://127.0.0.1:{}/json".format(port),
                                      timeout=4))
            targets = [x for x in pages if x.get("type") == "page"]
            if not targets:
                raise RuntimeError("CHROMIUM_PAGE_TARGET_MISSING")
            ws = websocket.create_connection(targets[0]["webSocketDebuggerUrl"],
                                             timeout=12, suppress_origin=True)
            cdp_call(ws, "Page.enable")
            results = []
            for path, (_, expected, method) in Handler.records.items():
                url = "https://127.0.0.1:{}{}".format(httpd.server_port, path)
                cdp_call(ws, "Page.navigate", {"url": url})
                for _ in range(30):
                    ready = evaluate(ws, 'location.href === ' +
                                     json.dumps(url) +
                                     ' && document.readyState === "complete"')
                    if ready:
                        break
                    time.sleep(0.15)
                if not ready:
                    raise RuntimeError("DOM_NOT_READY " + path)
                result = evaluate(ws, FUNC + "\ntraceCartQueuedProductProjection()")
                actual = (result.get("error") if "error" in result else
                          result.get("snapshot", {}).get("offers", {}).get("price"))
                origin = result.get("price_origin")
                row = {"case": path, "expected": expected, "actual": actual,
                       "expected_method": method, "actual_method": origin,
                       "pass": actual == expected and origin == method}
                results.append(row)
            report = {"suite": "ISOLATED_CHROMIUM_LOCAL_HTTPS_DOM",
                      "real_merchant_requests": 0,
                      "passed": sum(x["pass"] for x in results),
                      "total": len(results), "cases": results}
            if public_adafruit:
                # Explicit opt-in, one specific public merchant page. Existing
                # robots/DNS-pinned transport must first allow reading it.
                from universal_source_acquisition import acquire_public_product
                target = "https://www.adafruit.com/product/1083"
                check = acquire_public_product(target)
                public = {"url": target, "static_status": check["status"],
                          "robots_checked": check.get("robots_checked", False),
                          "static_declared_price": check["fields"].get("price"),
                          "static_declared_currency": check["fields"].get("currency"),
                          "browser_observation": None,
                          "live_checkout_verified": False}
                if check["status"] == "PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED":
                    cdp_call(ws, "Page.navigate", {"url": target})
                    for _ in range(55):
                        state = evaluate(ws, "document.readyState")
                        if state == "complete":
                            break
                        time.sleep(0.2)
                    result = evaluate(ws, FUNC + "\ntraceCartQueuedProductProjection()")
                    public["browser_observation"] = {
                        "url": result.get("url"),
                        "error": result.get("error"),
                        "declared_title": (result.get("snapshot") or {}).get("name"),
                        "declared_price": ((result.get("snapshot") or {})
                                           .get("offers") or {}).get("price"),
                        "declared_currency": ((result.get("snapshot") or {})
                                              .get("offers") or {}).get("priceCurrency"),
                        "price_origin": result.get("price_origin"),
                        "checkout_verified": False,
                    }
                    observed = public["browser_observation"]
                    if observed.get("declared_price") is None or (
                            public["static_declared_price"] is None):
                        public["static_browser_price_crosscheck"] = "INCOMPLETE"
                    elif ((observed["declared_price"], observed["declared_currency"]) ==
                          (public["static_declared_price"],
                           public["static_declared_currency"])):
                        public["static_browser_price_crosscheck"] = "AGREE"
                    else:
                        public["static_browser_price_crosscheck"] = "CONFLICT"
                report["public_merchant_probe"] = public
                report["real_merchant_requests"] = 1 if (
                    public["browser_observation"] is not None) else 0
            return report
        finally:
            if ws:
                ws.close()
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    proc.kill()
            httpd.shutdown()
            worker.join(timeout=3)
            httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-adafruit", action="store_true",
                        help="Optional single permitted public Adafruit URL probe")
    args = parser.parse_args()
    report = smoke(public_adafruit=args.public_adafruit)
    print(json.dumps(report, indent=2))
    if report["passed"] != report["total"]:
        raise SystemExit(1)
