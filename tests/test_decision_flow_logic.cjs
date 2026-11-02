"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const ui=require("../assets/decision-flow.js");
const historical=JSON.parse(fs.readFileSync(path.resolve(__dirname,
  "../examples/live_lenovo_ideapad_decision_projection_2026-11-02.json"),"utf8"));
const report=()=>JSON.parse(JSON.stringify(historical));

test("independent recorded counts do not become verified prices",()=>{
 const d=report();
 assert.equal(d.evidence.catalog_only,0);
 assert.equal(d.evidence.google_shopping_cards,12);
 assert.equal(d.evidence.indexed_store_links,3);
 assert.equal(d.evidence.seller_confirmed_competitor_prices,0);
});
test("fully autonomous conclusion does not require buyer answers",()=>{
 const d=report();
 const v=ui.automaticVerdict(d);
 assert.equal(v.status,"ABSTAIN_UNVERIFIED_PRICE_AND_VARIANT");
 assert.equal(v.payment_authorized,false);
 assert.equal(v.price_check_performed_by_tracecart,false);
 assert.equal(v.shortlist.length,2);
 assert.equal(v.shortlist[0].cpu_architecture,"ARM");
 assert.equal(v.shortlist[1].cpu_architecture,"x86");
});
test("ARM and x86 appear together without invented user requirements",()=>{
 const v=ui.automaticVerdict(report());
 assert.equal(v.shortlist[0].price,"2849.00");
 assert.equal(v.shortlist[1].price,"3167.00");
});
test("extreme price anomalies cannot win shortlist",()=>{
 const candidates=ui.validCandidates(report());
 assert.ok(candidates.length);
 assert.ok(candidates.every(x=>!x.price_warnings.length));
 assert.ok(candidates.every(x=>x.price!=="124.95"));
});
test("missing candidates or no evidence forces abstention",()=>{
 const d=report();
 d.candidates=[];
 const v=ui.automaticVerdict(d);
 assert.deepEqual(v.shortlist,[]);
 assert.equal(v.payment_authorized,false);
});
test("source links are HTTPS, not local or script URLs",()=>{
 assert.equal(ui.safeHref("javascript:alert(1)"),null);
 assert.equal(ui.safeHref("http://example.com/"),null);
 assert.equal(ui.safeHref("https://localhost:9999/"),null);
 assert.equal(ui.safeHref("https://127.0.0.1:8080/"),null);
 assert.ok(ui.safeHref("https://psref.lenovo.com/Product/IdeaPad/IdeaPad_Slim_3_15Q8X10"));
 assert.equal(ui.safeHref("/cart/status/w8MOeW8uE7pCqDYKf48-lXxy/audit"),
 "/cart/status/w8MOeW8uE7pCqDYKf48-lXxy/audit");
});
test("unknown price is not zero and public display uses English locale",()=>{
 assert.equal(ui.money(null,"PLN"),"Price unavailable");
 assert.equal(ui.money("2849","PLN"),"2,849.00 PLN");
});
test("front-end does not contain buyer-question choice controls",()=>{
 const source=fs.readFileSync(path.resolve(__dirname,"../assets/decision-flow.js"),"utf8");
 assert.ok(source.includes("autonomous"));
 assert.equal(source.includes("choice-btn"),false);
 assert.equal(source.includes("renderQuestion("),false);
});


test("no-click rendering supports immediate pre-result stage and paginated offer plans",()=>{
 const source=fs.readFileSync(path.resolve(__dirname,"../assets/decision-flow.js"),"utf8");
 assert.ok(source.includes("renderStaged({"));
 assert.ok(source.includes("renderOfferQueue(data"));
 assert.ok(source.includes("IntersectionObserver"));
 assert.ok(source.includes("PLANNED"));
 assert.ok(source.includes('polls<12?450:POLL_MS'));
 assert.equal(source.includes("choice-btn"),false);
});
