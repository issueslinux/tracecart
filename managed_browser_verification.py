"""Self-managed, isolated Chromium seller-page verification.

No browser extension, per-merchant Chrome grant or human-interactive session.
Every URL is HTTPS validated, robots-checked, and DNS pinned to a public IPv4
address; Chromium blocks cross-origin subresources and redirects. No payment,
authentication, CAPTCHA or anti-bot bypass; failure is explicit and terminal.
"""
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from product_intake import _read, MAX_ROBOTS_BYTES, USER_AGENT, validate_product_url

MAX_PARALLEL_MANAGED_BROWSERS = 3
MAX_CAPTURE_OUTPUT_BYTES = 18000
_CAPTURABLE = "PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED"
_FAILURES = frozenset((
    "ACCESS_CHALLENGE", "REDIRECTED", "NO_STRUCTURED_PRODUCT",
    "MULTIPLE_PRODUCTS_AMBIGUOUS", "CONFLICTING_PRODUCT_IDENTITY",
    "CONFLICTING_OFFER_EVIDENCE", "BROWSER_ERROR", "TAB_TIMEOUT",
    "ROBOTS_DISALLOWED", "ROBOTS_UNAVAILABLE", "UNSAFE_BROWSER_DESTINATION",
))


def _public_ipv4(host):
    for info in socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM):
        ip = info[4][0]
        if ipaddress.ip_address(ip).is_global:
            return ip
    raise ValueError("NO_PUBLIC_BROWSER_IP")


def capture_public_product(url, runner=None, robots_getter=None,
                           resolver=None):
    """Return a narrow browser receipt; no full HTML, cookies, or session state."""
    try:
        safe = validate_product_url(url)
        host = urlsplit(safe).hostname
        if not host or urlsplit(safe).port not in (None, 443):
            return {"status": "UNSAFE_BROWSER_DESTINATION"}
    except (ValueError, TypeError):
        return {"status": "UNSAFE_BROWSER_DESTINATION"}
    try:
        getter = robots_getter or _read
        raw = getter("https://" + host + "/robots.txt", MAX_ROBOTS_BYTES,
                     ("text/plain", "text/html"))
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_ROBOTS_BYTES:
            raise ValueError("INVALID_ROBOTS")
        rules = RobotFileParser()
        rules.parse(raw.decode("utf-8", "replace").splitlines())
        if not rules.can_fetch(USER_AGENT, safe):
            return {"status": "ROBOTS_DISALLOWED"}
        ip = (resolver or _public_ipv4)(host)
        if not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).version != 4:
            return {"status": "UNSAFE_BROWSER_DESTINATION"}
    except (ValueError, OSError, TimeoutError, UnicodeError):
        return {"status": "ROBOTS_UNAVAILABLE"}
    root = Path(__file__).resolve().parent
    # No secrets (PayPal, shopping provider keys, companion token) in Chromium's
    # environment; do not inherit the application's session environment.
    env = {k: os.environ[k] for k in (
        "PATH", "HOME", "LANG", "LC_ALL", "TRACECART_BROWSER_PROFILE_ROOT",
        "TRACECART_CHROMIUM") if k in os.environ}
    try:
        proc = (runner or subprocess.run)(
            ["node", str(root / "managed_browser_capture.js"), safe, host, ip],
            capture_output=True, timeout=23, check=False, env=env)
        if (proc.returncode != 0 or not proc.stdout or
                len(proc.stdout) > MAX_CAPTURE_OUTPUT_BYTES):
            return {"status": "BROWSER_ERROR"}
        output = json.loads(proc.stdout)
        if (type(output) is not dict or output.get("source_url") != safe or
                output.get("browser_request_scope") !=
                    "SAME_ORIGIN_HTTPS_ONLY_PINNED_PUBLIC_IP" or
                output.get("render_method") !=
                    "ISOLATED_MANAGED_CHROMIUM_NO_EXTENSION"):
            return {"status": "BROWSER_ERROR"}
        status = output.get("status")
        if status in _FAILURES and output.get("capture") is None:
            return {"status": status}
        if status != _CAPTURABLE:
            return {"status": "BROWSER_ERROR"}
        capture = output.get("capture")
        if (type(capture) is not dict or capture.get("url") != safe or
                type(capture.get("snapshot")) is not dict or
                not capture.get("price_origin") or
                not capture.get("captured_at")):
            return {"status": "BROWSER_ERROR"}
        return {"status": status, "capture": capture}
    except (OSError, TimeoutError, subprocess.TimeoutExpired,
            UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        return {"status": "BROWSER_ERROR"}


class ManagedBrowserWorker:
    """Daemon workers consuming the existing bounded Browser Companion queue.

    The source and graph receipts use the established trusted validation code;
    this worker never updates a price or verdict directly.
    """
    def __init__(self, server, capture=capture_public_product,
                 concurrency=MAX_PARALLEL_MANAGED_BROWSERS):
        if not 1 <= concurrency <= MAX_PARALLEL_MANAGED_BROWSERS:
            raise ValueError("INVALID_MANAGED_BROWSER_CONCURRENCY")
        self.server = server
        self.capture = capture
        self.concurrency = concurrency
        self.stop_event = threading.Event()
        self.threads = []

    def start(self):
        for idx in range(self.concurrency):
            worker = threading.Thread(target=self._loop,
                name="TraceCartManagedChromium%d" % idx, daemon=True)
            worker.start()
            self.threads.append(worker)

    def close(self):
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=0.2)

    def _loop(self):
        while not self.stop_event.is_set():
            job = self.server.companion.take()
            if job is None:
                self.stop_event.wait(0.35)
                continue
            self._process(job)

    def _process(self, job):
        ident = job["job_id"]
        self.server.cart_jobs.mark_index_browser_in_progress(ident)
        try:
            response = self.capture(job["url"])
            status = response["status"]
            if status == _CAPTURABLE:
                claim = response["capture"]
                payload = {"job_id": ident, "url": job["url"],
                           "captured_at": claim["captured_at"],
                           "snapshot": claim["snapshot"],
                           "price_origin": claim["price_origin"],
                           "promotion": claim.get("promotion"),
                           "browser_mode": "ISOLATED_MANAGED_CHROMIUM",
                           "error": None}
            else:
                payload = {"job_id": ident, "url": job["url"],
                           "captured_at": None, "snapshot": None,
                           "price_origin": None, "error": status,
                           "browser_mode": "ISOLATED_MANAGED_CHROMIUM"}
            ack = self.server.companion.report(payload)
            status = ack["status"]
            if status == _CAPTURABLE:
                self.server.cart_jobs.store_browser_claim(
                    self.server.companion.get_job(ident))
        except (ValueError, KeyError, TypeError, RuntimeError, OSError):
            status = "BROWSER_ERROR"
            try:
                self.server.companion.report({
                    "job_id": ident, "url": job["url"],
                    "captured_at": None, "snapshot": None,
                    "price_origin": None, "error": status})
            except (ValueError, KeyError, TypeError):
                pass
        self.server.cart_jobs.finish_index_browser_task(ident, status)
        self.server.cart_jobs.finish_browser_auto_task(ident, status)
