#!/usr/bin/env python3
"""Populate a running local TraceCart UI with real MV3 browser observations.

The developer explicitly chooses permitted public merchants. The real
Chrome profile and repository extension permissions are never modified.
A disposable copied test extension receives an isolated test-only host grant.

Usage:
 python3 benchmarks/browser_companion_running_app_demo.py --port 8807 \
   --db /tmp/tracecart-quicktest-20261103/demo.sqlite3 --sites adafruit maxpronet
"""
import argparse
import html
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmarks.browser_companion_mv3_e2e import PUBLIC_MERCHANT_CASES, run_case
from universal_source_acquisition import acquire_public_product

JOB_REF = re.compile(r'/research/companion/([A-Za-z0-9_-]{24})[.]json')
CSRF = re.compile(r'name="csrf" value="([^"]{20,200})"')


class LiveCompanionProxy:
    def __init__(self, port, token):
        self.port = port
        self.token = token

    def _read(self, path):
        if not path.startswith("/") or ".." in path:
            raise ValueError("INVALID_LOCAL_BROKER_PATH")
        with urlopen("http://127.0.0.1:{}{}".format(self.port, path),
                     timeout=6) as response:
            return response.read().decode("utf8")

    def get_job(self, job_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]{24}", job_id):
            raise ValueError("INVALID_JOB_ID")
        return json.loads(self._read(
            "/research/companion/{}.json".format(job_id)))

    def listed(self):
        page = self._read("/research/companion")
        return [self.get_job(job_id) for job_id in JOB_REF.findall(page)]


class RunningTraceCart:
    def __init__(self, port, db):
        if not 1024 <= port <= 65535:
            raise ValueError("INVALID_LOOPBACK_PORT")
        # The developer's existing live TraceCart instance uses port 8781.
        # This demonstration must never enqueue to that service.
        if port == 8781:
            raise ValueError("PRODUCTION_PORT_FORBIDDEN")
        secret = Path(db).resolve().parent / "browser_companion.token"
        if not secret.is_file():
            raise ValueError("STAGING_TOKEN_MISSING")
        token = secret.read_text(encoding="ascii").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", token):
            raise ValueError("INVALID_STAGING_TOKEN")
        self.server_port = port
        self.companion = LiveCompanionProxy(port, token)
        page = self.companion._read("/research/companion")
        found = CSRF.findall(page)
        if not found or len(set(found)) != 1:
            raise ValueError("STAGING_CSRF_NOT_FOUND_OR_INCONSISTENT")
        self.csrf = html.unescape(found[0])
        if token not in page:
            raise ValueError("STAGING_TOKEN_MISMATCH")


def run(port, db, sites):
    stage = RunningTraceCart(port, db)
    if len(sites) != len(set(sites)):
        raise ValueError("DUPLICATE_MERCHANT_SELECTION")
    if any(job["status"] in ("QUEUED", "IN_PROGRESS")
           for job in stage.companion.listed()):
        raise ValueError("RUNNING_STAGE_HAS_PENDING_USER_TASKS")
    reports = []
    for name in sites:
        url = PUBLIC_MERCHANT_CASES[name]
        source = acquire_public_product(url)
        if (not source.get("robots_checked") or
                source["status"] !=
                "PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED"):
            raise RuntimeError("MERCHANT_PREFLIGHT_DENIED: {}".format(name))
        parent = Path.home() / "snap/chromium/common"
        folder = Path(tempfile.mkdtemp(
            prefix="tc-live-ui-demo-", dir=str(parent)))
        try:
            result = run_case(folder, stage, url, grant=True)
        finally:
            # Chromium Snap child processes may still release profile files
            # after the main browser exits. Retry bounded cleanup.
            for retry in range(12):
                try:
                    shutil.rmtree(str(folder))
                    break
                except OSError:
                    if retry == 11:
                        raise
                    time.sleep(0.5)
        good = (result["status"] ==
                "PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED" and
                result["acquisition_method"] == "USER_BROWSER" and
                result["declared_price"] == source["fields"]["price"] and
                result["currency"] == source["fields"]["currency"] and
                result["seller_verified"] is False and
                result["checkout_verified"] is False)
        reports.append({
            "merchant": name, "url": url, "status": result["status"],
            "price": result["declared_price"], "currency": result["currency"],
            "price_origin": result["browser_original_price_origin"],
            "evidence_count": result["evidence_count"],
            "static_browser_agree": good,
            "test_only_host_permission": True,
            "checkout_verified": False,
        })
        if not good:
            break
    output = {
        "demo": "RUNNING_TRACECART_MV3_BROWSER_RESEARCH",
        "ui": "http://127.0.0.1:{}/research/companion".format(port),
        "normal_browser_profile_changed": False, "results": reports,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if len(reports) != len(sites) or not all(
            item["static_browser_agree"] for item in reports):
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--sites", nargs="+", required=True,
                        choices=sorted(PUBLIC_MERCHANT_CASES))
    args = parser.parse_args()
    run(args.port, args.db, args.sites)
