#!/usr/bin/env python3
"""Local, read-only TraceCart decision-model benchmark.

Five saved carts and six synthetic counterfactuals. Human truth labels are NOT
available: benchmark measures compliance with a specified triage policy, not
real-world best-buy prediction. No store visits, billing APIs or cart writes.
"""
import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import statistics
import time
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

CARTS = {
    "dell": "cjtm3DYQ4GpB_RlYosSQyaRG",
    "ryobi": "JaG4WH8LPnEyDMIrNg7Et48Z",
    "lenovo": "w8MOeW8uE7pCqDYKf48-lXxy",
    "bike": "IBL_Y9R9Q3oTfGK7ksQ5-pPt",
    "detergent": "uZlRD09K7Y_T1F6kcdX4PnT6",
}
ACTIONS = {
    "VERIFY_VARIANT": "SKU/GTIN or exact product variant conflicts; check identity.",
    "RECHECK_INDEX": "Same-seller indexed quote is implausibly lower than browser-list price.",
    "VERIFY_COUPON": "Visible cheaper conditional coupon needs checkout application.",
    "VERIFY_SELLER": "No confirmed delivered total; verify seller's actual price.",
    "ACCEPT_RECEIPT": "An exact variant delivered checkout total was verified.",
}
POLICY = (
    "Use this strict safety-first order. If exact_variant_conflict is true, "
    "VERIFY_VARIANT. Else if price_index_suspect is true, RECHECK_INDEX. "
    "Else if conditional_coupon_price > 0 and coupon_code_present is true and "
    "coupon_applied is false, VERIFY_COUPON. Else if checkout_verified and "
    "exact_variant_verified are both true, ACCEPT_RECEIPT. "
    "Otherwise VERIFY_SELLER. Never treat index quotes or store declarations "
    "as verified checkout totals."
)


def local_endpoint(url):
    u = urlsplit(url)
    if u.scheme != "http" or u.hostname not in ("127.0.0.1", "localhost") \
            or u.username or u.password:
        raise ValueError("LOOPBACK_ENDPOINT_REQUIRED")
    return url.rstrip("/")


def request_json(base, path, data=None, timeout=70):
    url = local_endpoint(base) + path
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode() \
        if data is not None else None
    req = Request(url, data=payload, headers={"Content-Type":"application/json"},
                  method="POST" if payload is not None else "GET")
    with urlopen(req, timeout=timeout) as response:
        return json.load(response)


def amount(value):
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
        return round(f,2) if math.isfinite(f) and f>0 else None
    except (ValueError,TypeError,OverflowError):
        return None


def evidence_state(base, name, job_id):
    path = "/cart/status/" + job_id
    cart = request_json(base,path+".json",timeout=9)
    graph = request_json(base,path+".knowledge-graph.json",timeout=9)
    selected = cart.get("item") or {}
    observation = (graph.get("offer_details") or {}).get("offer-0",{}).get("browser_observation") or {}
    promo = observation.get("promotion") or {}
    quote_rows = (cart.get("report") or {}).get("indexed_shopping",{}).get("indexed_offers") or []
    same_seller = [amount(x.get("current_price_indexed")) for x in quote_rows
                   if x.get("merchant_url") == selected.get("merchant_url")]
    same_seller = [x for x in same_seller if x is not None]
    return name, {
        "product": str(selected.get("title") or "")[:85],
        "seller_index_quotes_count": len(quote_rows),
        "browser_listed_price": amount(observation.get("declared_price")) or amount(selected.get("price")),
        "same_seller_index_quote": min(same_seller) if same_seller else None,
        "conditional_coupon_price": amount(promo.get("price")),
        "coupon_code_present": bool(promo.get("code")),
        "coupon_applied": bool(promo.get("code_applied")),
        "checkout_verified": bool(observation.get("checkout_verified")),
        "exact_variant_verified": bool(observation.get("exact_variant_verified")),
        "exact_variant_conflict": False,
        "source_kind": "saved_browser_observation" if observation else "saved_index_only",
    }


def index_suspect(state):
    listed=amount(state.get("browser_listed_price"))
    indexed=amount(state.get("same_seller_index_quote"))
    return bool(listed and indexed and indexed < .25*listed)


def policy_action(state):
    if state["exact_variant_conflict"]: return "VERIFY_VARIANT"
    if index_suspect(state): return "RECHECK_INDEX"
    if state["conditional_coupon_price"] and state["coupon_code_present"] \
            and not state["coupon_applied"]: return "VERIFY_COUPON"
    if state["checkout_verified"] and state["exact_variant_verified"]:
        return "ACCEPT_RECEIPT"
    return "VERIFY_SELLER"


def cases_from_archive(states):
    cases=[]
    def add(name,state,kind):
        state=deepcopy(state)
        state["price_index_suspect"]=index_suspect(state)
        cases.append({"id":name,"kind":kind,"state":state,
                      "expected":policy_action(state)})
    for name,state in states:
        add(name+"_saved",state,"archived")
        if name=="dell":
            baseline=deepcopy(state)
            baseline["same_seller_index_quote"]=3499.99
            add("dell_index_fixed",baseline,"counterfactual")
            contrast=deepcopy(baseline);contrast["exact_variant_conflict"]=True
            add("dell_sku_conflict",contrast,"counterfactual")
            contrast=deepcopy(baseline);contrast["conditional_coupon_price"]=None
            contrast["coupon_code_present"]=False
            add("dell_no_coupon",contrast,"counterfactual")
            contrast=deepcopy(baseline);contrast.update({
                "coupon_applied":True,"checkout_verified":True,
                "exact_variant_verified":True})
            add("dell_checkout_verified_simulated",contrast,"counterfactual")
        if name=="ryobi":
            contrast=deepcopy(state);contrast.update({
                "checkout_verified":True,"exact_variant_verified":True})
            add("ryobi_receipt_simulated",contrast,"counterfactual")
        if name=="lenovo":
            contrast=deepcopy(state);contrast["exact_variant_conflict"]=True
            add("lenovo_wrong_model_simulated",contrast,"counterfactual")
    return cases


def query_model(model, case, base, timeout):
    start=time.perf_counter()
    if model.startswith("tev1:"):
        result=request_json(base,"/v1/systemone",{
            "model":model,"state":case["state"],"keep_alive":"3m",
            "questions":{"action":{"type":"choice","instructions":POLICY,
                                   "criteria":ACTIONS}}
        },timeout=timeout)
        answer=(result.get("answers") or {}).get("action") or {}
        choice=answer.get("choice")
        probs=answer.get("probabilities") or {}
        if set(probs)!=set(ACTIONS) or abs(sum(probs.values())-1)>.03:
            raise ValueError("INVALID_DECISION_PROBABILITIES")
    elif model=="qwen2.5:1.5b-instruct":
        result=request_json(base,"/api/chat",{
            "model":model,"stream":False,"keep_alive":"3m",
            "format":{"type":"object","additionalProperties":False,
                      "required":["choice"],"properties":{
                      "choice":{"type":"string","enum":list(ACTIONS)}}},
            "options":{"temperature":0,"num_ctx":1024,"num_predict":40},
            "messages":[
                {"role":"system","content":"Classify a purchase evidence state. Follow the supplied policy exactly. Output only JSON."},
                {"role":"user","content":POLICY+"\nOptions: "+json.dumps(ACTIONS)+
                 "\nState: "+json.dumps(case["state"],ensure_ascii=False)}
            ]
        },timeout=timeout)
        choice=json.loads((result.get("message") or {}).get("content") or "{}").get("choice")
        probs={}
    else:
        raise ValueError("MODEL_NOT_IN_BENCHMARK")
    if choice not in ACTIONS:
        raise ValueError("INVALID_CLASSIFICATION")
    return {"choice":choice,"correct_policy":choice==case["expected"],
            "seconds":round(time.perf_counter()-start,3),
            "selected_probability":round(probs.get(choice,0),4) if probs else None}


def summary(rows):
    results={}
    for model, data in rows.items():
        valid=[x for x in data if "choice" in x]
        times=sorted(x["seconds"] for x in valid)
        n=len(data)
        results[model]={
            "cases":n,"valid":len(valid),
            "correct_policy":sum(x["correct_policy"] for x in valid),
            "accuracy_on_policy_controls":round(sum(x["correct_policy"] for x in valid)/n,3),
            "median_seconds":round(statistics.median(times),3) if times else None,
            "p95_seconds":times[max(0,math.ceil(.95*len(times))-1)] if times else None,
            "failed_or_timed_out":n-len(valid)}
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cart-server",default="http://127.0.0.1:8810")
    parser.add_argument("--ollama",default="http://127.0.0.1:11435")
    parser.add_argument("--models",nargs="+",default=[
        "tev1:0.8b","tev1:4b","qwen2.5:1.5b-instruct"])
    parser.add_argument("--timeout",type=float,default=70)
    parser.add_argument("--output",type=Path,
                        default=Path("/tmp/tracecart-local-decision-benchmark.json"))
    args=parser.parse_args()
    names=list(CARTS)
    archive=[evidence_state(args.cart_server,k,CARTS[k]) for k in names]
    tests=cases_from_archive(archive)
    report={"method":"POLICY_REPRODUCTION_WITH_SYNTHETIC_CONTROLS",
            "not_human_labelled_accuracy":True,
            "no_external_search_or_merchant_requests":True,
            "source_carts":names,"n_saved":len(archive),
            "n_counterfactual":len(tests)-len(archive),
            "case_ids":[t["id"] for t in tests],
            "models":{"deterministic":[{"choice":policy_action(t["state"]),
                     "correct_policy":True,"seconds":0.0,
                     "selected_probability":None} for t in tests]},"summary":{}}
    print("CASES",len(tests),"ARCHIVED",len(archive),flush=True)
    for model in args.models:
        results=[]
        for case in tests:
            try: r=query_model(model,case,args.ollama,args.timeout)
            except (ValueError,TypeError,OSError,KeyError,TimeoutError) as e:
                r={"error_type":type(e).__name__,"correct_policy":False}
            results.append(r)
            print("CASE",model,case["id"],"expected",case["expected"],
                  "actual",r.get("choice") or r.get("error_type"),
                  "seconds",r.get("seconds"),flush=True)
        report["models"][model]=results
        report["summary"]=summary(report["models"])
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print("SUMMARY",json.dumps(report["summary"],ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
