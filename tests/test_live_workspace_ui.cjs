"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const test=require("node:test");
const live=require("../assets/live-workspace.js");

const example={
  graph:{offer_details:{
    "offer-0":{title:"Electric bike 250W 15Ah",high_impact_questions:[
      {question:"Which OEM frame is fitted?"},
      {question:"Which test establishes range?"}]},
    "offer-1":{title:"Electric bike 500W 12Ah",high_impact_questions:[
      {question:"Which battery pack is fitted?"}]}
  }},
  evidence_offers:{"offer-0":{status:"RUNNING",reference_answers:[]},
    "offer-1":{status:"NO_MATCHED_INDEPENDENT_EBIKE_REVIEW",reference_answers:[]}},
  model_offers:{"offer-0":{state:"RUNNING",questions:[]}},
  progress_revision:3
};
test("source rail reflects actual persisted worker statuses, not made-up verified tests",()=>{
  const rows=live.sourceTasks(example);
  assert.equal(rows.length,2);
  assert.equal(rows[0].mode,"RUNNING");
  assert.equal(rows[0].state,"CHECKING");
  assert.equal(rows[1].mode,"BLOCKED");
  assert.equal(rows[1].state,"INDEX ONLY");
  assert.match(rows[1].detail,/no usable direct product URL/);
  const withUrl={...example,offer_queue:[
    {id:"offer-0",title:"Input",url:"https://manufacturer.example/a"},
    {id:"offer-1",title:"Indexed",url:"https://seller.example/b"}]};
  const oldJob=live.sourceTasks(withUrl).find(x=>x.key==="#2");
  assert.equal(oldJob.state,"NO FETCH RECEIPT");
  assert.match(oldJob.detail,/no HTTP or graphical fetch outcome/);
});
test("blocked primary HTTP 403 is explained instead of NO MATCHED SOURCE",()=>{
  const input={...example,offer_queue:[
    {id:"offer-0",title:"Laptop Dell",url:"https://shop.example.org/laptop"}],
    graph:{offer_details:{"offer-0":{title:"Laptop Dell",
      input_access_problem:"HTTP_403"}}},
    evidence_offers:{"offer-0":{status:"NO_MATCHED_INDEPENDENT_SOURCE",
      reference_answers:[]}}};
  const row=live.sourceTasks(input)[0];
  assert.equal(row.state,"SERVER HTTP 403");
  assert.match(row.detail,/not the product/);
});
test("index-only cards are grouped instead of 12 meaningless NO SOURCE URL tasks",()=>{
  const data={
    state:"READY",evidence_progress:{status:"COMPLETE"},
    graph:{offer_details:{}},offer_queue:[
      {id:"offer-0",title:"Selected laptop",url:"https://seller.example/one"},
      {id:"offer-1",title:"Indexed laptop",url:null},
      {id:"offer-2",title:"Indexed laptop v2",url:null},
      {id:"offer-3",title:"Indexed laptop v3",url:null},
      {id:"offer-4",title:"Real seller laptop",url:"https://seller.example/two"},
    ],
    evidence_offers:{
      "offer-0":{status:"NO_MATCHED_INDEPENDENT_SOURCE",
        attempted_sources:[{url:"https://seller.example/one",
          status:"NOT_RETRIEVED_SourceAccessDenied"}]},
      "offer-1":{status:"NO_MATCHED_INDEPENDENT_SOURCE",
        attempted_sources:[{discovery:"BRAND_SITE_CANDIDATE",
          status:"NO_MATCHED_BRAND_DOCUMENT_SourceRedirect"}]},
      "offer-2":{status:"NO_MATCHED_INDEPENDENT_SOURCE",attempted_sources:[]},
      "offer-3":{status:"NO_MATCHED_INDEPENDENT_SOURCE",attempted_sources:[]},
      "offer-4":{status:"GENERAL_DOCUMENT_DECLARATIONS_FETCHED_SKU_UNVERIFIED",
        reference_answers:[{finding:"Documented 16GB RAM"}]},
    }
  };
  const rows=live.sourceTasks(data);
  assert.equal(rows.length,3);
  assert.ok(rows.some(r=>r.title.includes("3 index-only cards")));
  assert.ok(rows.some(r=>r.state==="ACCESS RESTRICTED"));
  assert.ok(rows.some(r=>r.state==="SPECIFICATIONS"));
  assert.ok(!rows.some(r=>["NO MATCHED DATA","NO SOURCE URL"].includes(r.state)));
});
test("spinner lasts through the persisted final Qwen verdict stage",()=>{
  const template=fs.readFileSync(path.join(__dirname,"../assets/decision-page.html"),"utf8");
  const css=fs.readFileSync(path.join(__dirname,"../assets/live-workspace.css"),"utf8");
  assert.ok(template.includes('id="analyze-button"'));
  assert.ok(template.includes('class="analyze-spin"'));
  assert.ok(template.includes('id="live-verdict"'));
  assert.ok(css.includes("@keyframes tracecart-spin"));
  const base={state:"READY",
    evidence_progress:{status:"COMPLETE",processed:16,planned:16}};
  for(const v of ["QUEUED","RUNNING"]){
    assert.equal(live.isTerminal({...base,
      progress_stage:"FINAL_VERDICT_RUNNING",
      final_verdict:{status:v}}),false);
  }
  assert.equal(live.isTerminal({...base,
    progress_stage:"PER_OFFER_MODEL_COMPLETE",
    final_verdict:{status:"QUEUED"}}),false);
  assert.equal(live.isTerminal({...base,
    progress_stage:"FINAL_VERDICT_COMPLETE",
    final_verdict:{status:"COMPLETE"}}),true);
  assert.equal(live.isTerminal({...base,
    progress_stage:"FINAL_VERDICT_UNAVAILABLE",
    final_verdict:{status:"UNAVAILABLE"}}),true);
  assert.equal(live.isTerminal({...base,
    progress_stage:"PER_OFFER_MODEL_COMPLETE",
    final_verdict:{status:"NOT_SCHEDULED"}}),true);
  assert.equal(live.isTerminal({...base,
    evidence_progress:{status:"RUNNING",processed:15,planned:16},
    final_verdict:{status:"COMPLETE"}}),false);
});
test("right rail cycles unresolved checks when workers update, never converts them to answers",()=>{
  const list=live.questionTasks(example);
  assert.equal(list[0].state,"INFERENCE");
  assert.ok(list.some(x=>x.state==="OPEN"));
  assert.ok(!list.some(x=>x.state==="VERIFIED"));
  const more=live.questionTasks({...example,progress_revision:4});
  assert.notDeepEqual(list.slice(1),more.slice(1));
});
test("placeholder opens before any backend request; no invented evidence",()=>{
  const graph=live.emptyGraph();
  assert.equal(graph.nodes.length,1);
  assert.equal(graph.edges.length,0);
  assert.equal(graph.stats.verified_exact_sku_answers,0);
  const template=fs.readFileSync(path.join(__dirname,"../assets/decision-page.html"),"utf8");
  assert.ok(template.includes('action="/cart/add"'));
  assert.ok(template.includes('data-live="{{LIVE_URL}}"'));
  assert.ok(template.includes('id="kg-svg"'));
  assert.ok(!template.includes("From a product"));
  assert.ok(!template.includes("PER-OFFER RESEARCH BACKLOG"));
  const frontend=fs.readFileSync(path.join(__dirname,"../assets/live-workspace.js"),"utf8");
  assert.ok(frontend.includes("new EventSource("));
  assert.ok(frontend.includes('source.addEventListener("graph"'));
  assert.ok(frontend.includes("A new independent source or SKU check is required."));
  assert.ok(!frontend.includes("innerHTML"));
});


test("source discrepancies and search leads are shown as unresolved research, not verified",()=>{
  const data={
    ...example,
    source_search:{status:"COMPLETE",queries_used:2,
      leads:[{url:"https://review.example.org/test",status:"UNVERIFIED_UNFETCHED"}]},
    evidence_offers:{
      "offer-0":{status:"GENERAL_DOCUMENT_DECLARATIONS_FETCHED_SKU_UNVERIFIED",
        reference_answers:[{
          source_kind:"BRAND_SITE_DECLARATIONS_NOT_INDEPENDENT_TESTS",
          finding:"Published assist range: 50-85 km",
        }],
        declared_claim_conflicts:[{
          type:"TITLE_VS_PUBLISHED_SPECIFICATION",
          listing_value:"100 km",source_value:"50-85 km",
          status:"POTENTIAL_DIFFERENT_VARIANT_OR_TEST_CONDITIONS",
        }]},
      "offer-1":{status:"NO_MATCHED_GENERAL_PRODUCT_SOURCE",
        reference_answers:[]},
    },
  };
  const questions=live.questionTasks(data);
  const issue=questions.find(x=>x.state==="CHECK SOURCES");
  assert.ok(issue);
  assert.ok(issue.title.includes("100 km"));
  assert.ok(!questions.some(x=>x.state==="VERIFIED"));
  const sources=live.sourceTasks(data);
  assert.ok(sources.some(x=>x.state==="SPECIFICATIONS"));
  assert.ok(!sources.some(x=>x.state==="INDEPENDENT TEST VERIFIED"));
  const css=fs.readFileSync(path.join(__dirname,"../assets/decision-flow.css"),"utf8");
  assert.ok(css.includes("kg-type-source_disagreement"));
  assert.ok(css.includes("kg-type-source_lead"));
});


test("source rail uses discovered work queue while graph shows first input offer",()=>{
  const partial={...example,
    graph:{offer_details:{"offer-0":example.graph.offer_details["offer-0"]}},
    offer_queue:[
      {id:"offer-0",title:"Original RYOBI RPI18"},
      {id:"offer-1",title:"Alternative RYOBI R18PI"},
      {id:"offer-2",title:"Other compressor"},
    ],
    evidence_offers:{
      "offer-0":{status:"GENERAL_DOCUMENT_DECLARATIONS_FETCHED_SKU_UNVERIFIED",
                 reference_answers:[{finding:"Declared max pressure"}]},
      "offer-1":{status:"RUNNING",reference_answers:[]},
      "offer-2":{status:"QUEUED",reference_answers:[]},
    },
    model_offers:{"offer-0":{state:"BATCH_RUNNING",questions:[]},
                  "offer-1":{state:"BATCH_RUNNING",questions:[]}},
  };
  const src=live.sourceTasks(partial);
  assert.equal(src.length,3);
  assert.equal(src[0].key,"#1");
  assert.equal(src[0].state,"SPECIFICATIONS");
  assert.ok(src.some(x=>x.key==="#2" && x.state==="CHECKING"));
  const qs=live.questionTasks(partial);
  assert.equal(qs.filter(x=>x.state==="INFERENCE").length,1);
  const code=fs.readFileSync(path.join(__dirname,"../assets/live-workspace.js"),"utf8");
  assert.ok(code.includes("lastEventAt"));
  assert.ok(code.includes("fallbackUrl=app.dataset.live"));
});


test("completed research shows evidence-specific unresolved checks, not rotating generic 24-question backlogs",()=>{
  const data={...example,
    state:"READY",progress_stage:"PER_OFFER_MODEL_COMPLETE",
    evidence_progress:{status:"COMPLETE",processed:18,planned:18},
    graph:{offer_details:{
      "offer-0":{high_impact_questions:[
        {question:"Independent instrumented performance test for model RPI18-0?",
         reason:"No laboratory measurement found."},
        {question:"Current all-in checkout total?",reason:"Seller quote only."}
      ]},
      "offer-1":{high_impact_questions:[
        {question:"Check another manufacturer manual?",reason:"Missing source."}
      ]},
    }},
    model_offers:{"offer-0":{state:"OK",questions:[]}},
    evidence_offers:{"offer-0":{status:"GENERAL_DOCUMENT_DECLARATIONS_FETCHED_SKU_UNVERIFIED",
      reference_answers:[{finding:"Declared voltage 18V",
        source_kind:"SELLER_PRODUCT_PAGE_DECLARATIONS"}]}}
  };
  const selected=live.questionTasks(data,"offer-0");
  assert.equal(selected[0].state,"COMPLETE");
  assert.equal(selected.filter(x=>x.state==="UNRESOLVED").length,2);
  assert.ok(selected.some(x=>x.title.includes("Independent instrumented")));
  assert.ok(!selected.some(x=>x.title.includes("another manufacturer manual")));
  const other=live.questionTasks(data,"offer-1");
  assert.equal(other.filter(x=>x.state==="UNRESOLVED").length,1);
  assert.ok(other.some(x=>x.title.includes("another manufacturer manual")));
});

test("current source assessment takes priority over completed, stale, or running model",()=>{
  const fresh={status:"PRELIMINARY",origin:"DETERMINISTIC_CURRENT_EVIDENCE_NOT_LLM",
    summary:"Browser coupon available, not checkout-verified",
    purchase_insights:{selected_price:"2799.00 PLN"}};
  for(const state of ["QUEUED","RUNNING","COMPLETE",
      "UNAVAILABLE","STALE_AFTER_SHOPPING_REFRESH","SKIPPED_NOT_NEEDED"]){
    const snapshot={final_verdict:{status:state,summary:"old 3499.99 PLN",
        purchase_insights:{selected_price:"3499.99 PLN"}},
      instant_assessment:fresh};
    const chosen=live.verdictForDisplay(snapshot);
    assert.equal(chosen.shown,fresh);
    assert.equal(chosen.model.status,state);
    assert.equal(chosen.live,true);
    assert.equal(chosen.shown.purchase_insights.selected_price,"2799.00 PLN");
  }
  const legacy=live.verdictForDisplay({final_verdict:{status:"COMPLETE",
    summary:"old archived"}});
  assert.equal(legacy.live,false);
  assert.equal(legacy.shown.summary,"old archived");
});

test("optional local-model skip is a terminal state but evidence remains visible",()=>{
  const base={state:"READY",progress_stage:"FINAL_VERDICT_SKIPPED_NOT_NEEDED",
    evidence_progress:{status:"COMPLETE",processed:2,planned:2},
    final_verdict:{status:"SKIPPED_NOT_NEEDED"},
    instant_assessment:{status:"CURRENT",summary:"Published evidence comparison"}};
  assert.equal(live.isTerminal(base),true);
  const src=fs.readFileSync(path.join(__dirname,"../assets/live-workspace.js"),"utf8");
  assert.ok(src.includes("setBusy(!researchDone&&!snapshot.instant_assessment)"));
  assert.ok(src.includes("renderPurchaseAlternatives(target,snapshot,app,v.purchase_insights)"));
});


test("changed graph Qwen proposals are shown only as unresolved questions",()=>{
  const base={
    state:"READY",evidence_progress:{status:"COMPLETE",processed:2,planned:2},
    progress_stage:"FINAL_VERDICT_SKIPPED_NOT_NEEDED",
    final_verdict:{status:"SKIPPED_NOT_NEEDED"},
    graph:{offer_details:{"offer-0":{high_impact_questions:[]}}},
    model_offers:{},evidence_offers:{},
    graph_question_review:{status:"COMPLETE",runs:1,
      questions:[{offer_id:"offer-0",anchor_id:"seller:abc",
        question:"Which independent test validates this seller claim?",
        origin:"LOCAL_LLM_QUESTION_NOT_EVIDENCE",
        evidence_confirmed:false}]}
  };
  const rows=live.questionTasks(base,"offer-0");
  assert.ok(rows.some(q=>q.state==="PROPOSED"&&
    q.title.includes("independent test")));
  assert.ok(!rows.some(q=>q.state==="VERIFIED"));
  const stale=live.questionTasks({...base,graph_question_review:{
    status:"STALE_AFTER_GRAPH_CHANGE",questions:base.graph_question_review.questions
  }},"offer-0");
  assert.ok(!stale.some(q=>q.title.includes("independent test")));
});
