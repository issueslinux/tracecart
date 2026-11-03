"use strict";
const assert=require("node:assert/strict");
const test=require("node:test");
const {layoutAllNodes}=require("../assets/offer-graph.js");

test("the default layout hides empty research nodes but keeps all observed data",()=>{
  const nodes=[];
  for(let i=0;i<16;i++)nodes.push({id:"offer-"+i,type:"offer"});
  for(let i=0;i<80;i++)nodes.push({id:"gap-"+i,type:"verification_gap"});
  for(let i=0;i<24;i++)nodes.push({id:"dim-"+i,type:"research_gap"});
  for(let i=0;i<12;i++)nodes.push({id:"source-"+i,type:"source_declaration"});
  nodes.push({id:"decision:abstain",type:"decision_gate"});
  const {layout,bounds}=layoutAllNodes(nodes);
  assert.equal(layout.size,28);
  assert.ok(bounds.height>=880);
  assert.ok(bounds.width>=740);
  assert.equal(layout.has("gap-79"),false);
  assert.equal(layout.has("dim-23"),false);
  assert.equal(layout.has("decision:abstain"),false);
  assert.ok(layout.has("source-11"));
  assert.ok(layout.has("offer-15"));
  assert.equal(new Set([...layout.values()].map(p=>p.x+":"+p.y)).size,layout.size);
});

test("all informational nodes are visible without selecting an offer",()=>{
  const fs=require("node:fs");
  const path=require("node:path");
  const src=fs.readFileSync(path.join(__dirname,"../assets/offer-graph.js"),"utf8");
  assert.match(src,/prior.focus===undefined\?null:prior.focus/);
  assert.match(src,/const box=layoutAllNodes\(graph.nodes,\{singleColumn\}\)/);
  assert.ok(!src.includes("const visibleOffers=selected?"));
  assert.ok(src.includes("autoFit=true;remember();draw();"));
});
