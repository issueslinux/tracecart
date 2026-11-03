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
  assert.equal(rows[1].state,"NO MATCHED SOURCE");
});
test("right rail cycles unresolved checks when workers update, never converts them to answers",()=>{
  const list=live.questionTasks(example);
  assert.equal(list[0].state,"WRITING");
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
  assert.ok(frontend.includes("Source evidence required"));
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
