#!/usr/bin/env python3
"""Read-only real Chromium check for an already running TraceCart cart graph.

Never starts or mutates production. A pre-existing test port and cart job
must be explicitly provided; this tool makes only loopback HTTP requests.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
import websocket

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benchmarks.browser_companion_mv3_e2e import cdp, evaluate, get_json


def run(port, job):
    if not 1024<=port<=65535 or port==8781:
        raise ValueError("PRODUCTION_OR_INVALID_PORT")
    if not re.fullmatch(r"[A-Za-z0-9_-]{18,40}",job):
        raise ValueError("INVALID_RESEARCH_ID")
    url="http://127.0.0.1:{}/cart/status/{}".format(port,job)
    with urlopen(url+".knowledge-graph.json",timeout=8) as response:
        expected=json.load(response)
    browser=[x for x in expected["nodes"] if
             x.get("source_kind")=="USER_BROWSER_FILTERED_PROJECTION"]
    if not browser:
        raise RuntimeError("NO_PERSISTED_BROWSER_GRAPH_SOURCE")
    parent=Path.home()/"snap/chromium/common"
    with tempfile.TemporaryDirectory(dir=str(parent),prefix="tc-graph-ui-") as folder:
        profile=Path(folder)/"profile"
        proc=subprocess.Popen([
            "chromium","--headless=new","--no-sandbox",
            "--disable-gpu","--disable-dev-shm-usage",
            "--disable-extensions","--no-first-run",
            "--remote-debugging-port=0","--remote-allow-origins=*",
            "--user-data-dir="+str(profile),"about:blank"
        ],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        ws=None
        try:
            debug=profile/"DevToolsActivePort"
            for _ in range(50):
                if debug.is_file():break
                if proc.poll() is not None:
                    raise RuntimeError("CHROMIUM_STOPPED")
                time.sleep(.2)
            if not debug.is_file():
                raise RuntimeError("CHROMIUM_CDP_NOT_READY")
            port_cdp=int(debug.read_text().splitlines()[0])
            pages=get_json("http://127.0.0.1:{}/json".format(port_cdp))
            page=next(x for x in pages if x.get("type")=="page")
            ws=websocket.create_connection(page["webSocketDebuggerUrl"],
                                           timeout=12,suppress_origin=True)
            cdp(ws,"Page.enable")
            cdp(ws,"Page.navigate",{"url":url})
            info={}
            for _ in range(65):
                time.sleep(.22)
                info=evaluate(ws,"""(()=>{
                  const root=document.getElementById("decision-app");
                  return {
                    loaded:document.readyState==="complete",
                    visible_nodes:Number(root?.dataset.visibleGraphNodes||0),
                    visible_edges:Number(root?.dataset.visibleGraphLinks||0),
                    graph_label:document.getElementById("live-graph-count")?.textContent,
                    evidence_text:document.getElementById("live-evidence-status")?.textContent,
                    browser_visible:!![...document.querySelectorAll(".kg-node text")].find(
                        n=>n.textContent.includes("Browser")),
                    companion_link:document.getElementById("companion-research-link")?.getAttribute("href")
                  };
                })()""")
                if info.get("visible_nodes",0)>3 and (
                        "browser declarations" in (info.get("evidence_text") or "")):
                    break
            return {"url":url,"browser_source_count":len(browser),
                    "chromium_ui":info,
                    "passed":bool(info.get("visible_nodes",0)>3 and
                                  info.get("visible_edges",0)>0 and
                                  info.get("browser_visible") and
                                  "browser declarations" in
                                  (info.get("evidence_text") or "") and
                                  (info.get("companion_link") or "").startswith(
                                  "/research/companion?product_url="))}
        finally:
            if ws:ws.close()
            proc.terminate()
            try:proc.wait(timeout=4)
            except subprocess.TimeoutExpired:proc.kill()


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port",required=True,type=int)
    p.add_argument("--cart-job",required=True)
    args=p.parse_args()
    result=run(args.port,args.cart_job)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["passed"]:raise SystemExit(1)
