#!/usr/bin/env python3
"""Opt-in real MV3 worker + local TraceCart broker test in disposable Chromium.

Never use a logged-in browser profile. Uses an isolated Xvfb display,
an ephemeral Chrome profile and copied test extension; does not deploy.
The explicitly selected PUBLIC Adafruit product is robots-checked first.
The permitted-origin stage has a TEST-ONLY pre-granted host permission:
it does NOT verify the browser's permission prompt UI.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

import websocket

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))
from app import StreamingHTTPServer, TraceCartHandler
from browser_companion_queue import CompanionQueue
from universal_source_acquisition import acquire_public_product

PUBLIC_MERCHANT_CASES = {
    "adafruit": "https://www.adafruit.com/product/1083",
    "maxpronet": ("https://maxpronet.pl/"
                  "product-pol-84304-Proszek-do-prania-Persil-Color-75-pran-4-5-kg.html"),
}


def cdp(ws, method, params=None):
    cdp.seq += 1
    index = cdp.seq
    ws.send(json.dumps({"id": index, "method": method, "params": params or {}}))
    until = time.monotonic() + 15
    while time.monotonic() < until:
        data = json.loads(ws.recv())
        if data.get("id") == index:
            if data.get("error"):
                raise RuntimeError("CDP {}: {}".format(method, data["error"]))
            return data.get("result", {})
    raise TimeoutError("CDP " + method)


cdp.seq = 0


def evaluate(ws, expression):
    result = cdp(ws, "Runtime.evaluate", {
        "expression": expression, "returnByValue": True,
        "awaitPromise": True
    })
    if result.get("exceptionDetails"):
        raise RuntimeError("Extension JS exception: " +
                           str(result["exceptionDetails"]))
    return result.get("result", {}).get("value")


def get_json(url):
    with urlopen(url, timeout=4) as r:
        return json.load(r)


@contextmanager
def local_broker():
    broker = StreamingHTTPServer(("127.0.0.1", 0), TraceCartHandler)
    broker.companion = CompanionQueue(token=secrets.token_hex(32))
    broker.csrf = secrets.token_urlsafe(24)
    thread = threading.Thread(target=broker.serve_forever, daemon=True)
    thread.start()
    try:
        yield broker
    finally:
        broker.shutdown()
        thread.join(timeout=4)
        broker.server_close()


def enqueue_http(broker, url):
    # Same CSRF-checked user-facing form as /research/companion.
    body = urlencode({"csrf": broker.csrf, "product_urls": url}).encode()
    req = Request("http://127.0.0.1:{}/research/companion/queue".format(
        broker.server_port), data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Origin": "http://127.0.0.1:{}".format(broker.server_port)})
    with urlopen(req, timeout=5) as response:
        if response.status != 200 or "Browser companion" not in (
                response.read().decode("utf8", "replace")):
            raise RuntimeError("BROKER_QUEUE_UI_FAILED")
    jobs = broker.companion.listed()
    if not jobs:
        raise RuntimeError("BROKER_QUEUE_EMPTY_AFTER_FORM")
    return jobs[0]["id"]


def wait_job(broker, job_id, seconds=42):
    terminal = {"SITE_PERMISSION_REQUIRED", "PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED",
                "NO_STRUCTURED_PRODUCT", "ACCESS_CHALLENGE",
                "TAB_TIMEOUT", "REDIRECTED", "BROWSER_ERROR",
                "CONFLICTING_PRODUCT_IDENTITY", "CONFLICTING_OFFER_EVIDENCE",
                "MULTIPLE_PRODUCTS_AMBIGUOUS", "INVALID_JSON",
                "IDENTITY_CONFLICT", "PRICE_CONFLICT"}
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        row = broker.companion.get_job(job_id)
        if row["status"] in terminal:
            return row
        time.sleep(.45)
    raise TimeoutError("BROWSER_COMPANION_QUEUE_NO_RECEIPT")


def run_case(root, broker, product_url, grant=False):
    ext = root / ("extension-approved" if grant else "extension-denied")
    site = urlsplit(product_url).scheme + "://" + urlsplit(product_url).netloc
    shutil.copytree(ROOT / "browser-extension", ext)
    manifest = ext / "manifest.json"
    parsed = json.loads(manifest.read_text(encoding="utf8"))
    if grant:
        # TEST FIXTURE ONLY: explicit, single public merchant host. In a real
        # user profile, the optional permission MUST be granted by user action.
        parsed["host_permissions"].append(site + "/*")
    manifest.write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf8")

    profile = root / ("profile-approved" if grant else "profile-denied")
    logs = root / ("chrome-approved.log" if grant else "chrome-denied.log")
    cmd = [
        "xvfb-run", "-a", "-s", "-screen 0 1080x768x24",
        "chromium", "--no-sandbox", "--disable-gpu",
        "--disable-dev-shm-usage", "--no-first-run", "--no-default-browser-check",
        "--remote-debugging-port=0", "--remote-allow-origins=*",
        "--user-data-dir=" + str(profile),
        "--disable-extensions-except=" + str(ext),
        "--load-extension=" + str(ext),
        "about:blank"
    ]
    with logs.open("wb") as output:
        proc = subprocess.Popen(cmd, stdout=output, stderr=output,
                                preexec_fn=os.setsid)
    ws = None
    try:
        debug = profile / "DevToolsActivePort"
        for _ in range(65):
            if debug.is_file():
                break
            if proc.poll() is not None:
                break
            time.sleep(.2)
        if not debug.is_file():
            raise RuntimeError("MV3_CHROMIUM_DEBUG_PORT_MISSING")
        port = int(debug.read_text(encoding="utf8").splitlines()[0])
        ext_id = None
        extension_target = None
        page_target = None
        for _ in range(60):
            targets = get_json("http://127.0.0.1:{}/json".format(port))
            workers = [t for t in targets
                       if t.get("type") == "service_worker" and
                       t.get("url", "").endswith("/companion_worker.mjs")]
            pages = [t for t in targets if t.get("type") == "page"]
            if workers and pages:
                extension_target = workers[0]
                page_target = pages[0]
                ext_id = urlsplit(workers[0]["url"]).hostname
                break
            time.sleep(.2)
        if not ext_id:
            raise RuntimeError("COMPANION_MV3_WORKER_NOT_REGISTERED")
        ws = websocket.create_connection(page_target["webSocketDebuggerUrl"],
                                         timeout=15, suppress_origin=True)
        cdp(ws, "Page.enable")
        # A regular tab pointing at the copied unpacked extension popup;
        # no real user browser state is accessed.
        cdp(ws, "Page.navigate", {
            "url": "chrome-extension://{}/popup.html".format(ext_id)})
        for _ in range(45):
            try:
                ready = evaluate(ws, 'document.readyState==="complete" &&'
                                ' typeof chrome!=="undefined" &&'
                                ' typeof chrome.storage!=="undefined"')
                if ready:
                    break
            except RuntimeError:
                pass
            time.sleep(.2)
        if not ready:
            raise RuntimeError("EXTENSION_POPUP_NOT_READY")

        job_id = enqueue_http(broker, product_url)
        settings = {"port": broker.server_port, "token": broker.companion.token,
                    "enabled": True}
        response = evaluate(ws, """(async()=> {
            await chrome.storage.local.set({companionConfig: SETTINGS});
            return await chrome.runtime.sendMessage({action:"configureCompanion"});
        })()""".replace("SETTINGS", json.dumps(settings)))
        if response != {"ok": True}:
            raise RuntimeError("COMPANION_WORKER_DID_NOT_ACKNOWLEDGE")
        row = wait_job(broker, job_id)
        result = row.get("result") or {}
        fields = result.get("fields") or {}
        return {
            "status": row["status"],
            "worker_registered": bool(extension_target),
            "popup_paired": response == {"ok": True},
            "test_origin_pregranted": grant,
            "product_title": fields.get("title"),
            "declared_price": fields.get("price"),
            "currency": fields.get("currency"),
            "acquisition_method": result.get("acquisition_method"),
            "evidence_count": len(result.get("evidence") or []),
            "seller_verified": result.get("seller_verified"),
            "checkout_verified": result.get("checkout_verified"),
            "research_job_readable": bool(broker.companion.get_job(job_id)),
            "browser_original_price_origin": result.get("browser_original_price_origin"),
        }
    finally:
        if ws:
            ws.close()
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    site = parser.add_mutually_exclusive_group(required=True)
    site.add_argument("--public-adafruit", action="store_true",
                      help="Explicit public Adafruit product (robots preflight)")
    site.add_argument("--public-maxpronet", action="store_true",
                      help="Explicit public Maxpronet product (robots preflight)")
    args = parser.parse_args()
    product_url = PUBLIC_MERCHANT_CASES[
        "adafruit" if args.public_adafruit else "maxpronet"]
    preliminary = acquire_public_product(product_url)
    if preliminary["status"] != "PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED" or (
            not preliminary.get("robots_checked")):
        raise RuntimeError("MERCHANT_ACCESS_NOT_APPROVED_BY_ROBOTS_CHECK")
    path = Path.home() / "snap/chromium/common"
    with tempfile.TemporaryDirectory(prefix="tc-mv3-e2e-", dir=str(path)) as temp:
        with local_broker() as broker:
            denied = run_case(Path(temp), broker, product_url, grant=False)
            approved = run_case(Path(temp), broker, product_url, grant=True)
    outcome = {
        "test": "REAL_CHROMIUM_MV3_WORKER_QUEUE_BROWSER_LOOPBACK",
        "merchant_url": product_url,
        "merchant_robots_checked": True,
        "manual_permission_dialog_tested": False,
        "test_only_manifest_grant": True,
        "denied_without_permission": denied,
        "approved_origin": approved,
        "expected_static_declared_price": preliminary["fields"].get("price"),
    }
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    success = (denied["status"] == "SITE_PERMISSION_REQUIRED" and
               approved["status"] == "PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED" and
               approved["declared_price"] == preliminary["fields"].get("price") and
               approved["currency"] == preliminary["fields"].get("currency") and
               approved["acquisition_method"] == "USER_BROWSER" and
               approved["seller_verified"] is False and
               approved["checkout_verified"] is False)
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
