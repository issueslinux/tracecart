"use strict";
const assert=require("node:assert/strict");
const test=require("node:test");
const {layoutAllNodes}=require("../assets/offer-graph.js");

test("the default layout renders every available node regardless of type",()=>{
  const nodes=[];
  for(let i=0;i<16;i++)nodes.push({id:"offer-"+i,type:"offer"});
  for(let i=0;i<80;i++)nodes.push({id:"gap-"+i,type:"verification_gap"});
  for(let i=0;i<24;i++)nodes.push({id:"dim-"+i,type:"research_gap"});
  for(let i=0;i<12;i++)nodes.push({id:"source-"+i,type:"source_declaration"});
  nodes.push({id:"decision:abstain",type:"decision_gate"});
  const {layout,bounds}=layoutAllNodes(nodes);
  assert.equal(layout.size,133);
  assert.ok(bounds.height>=880);
  assert.ok(bounds.width>=2600);
  assert.ok(layout.has("gap-79"));
  assert.ok(layout.has("dim-23"));
  assert.ok(layout.has("decision:abstain"));
  assert.equal(new Set([...layout.values()].map(p=>p.x+":"+p.y)).size,nodes.length);
});

test("all nodes are the default, selecting an offer only changes emphasis",()=>{
  const fs=require("node:fs");
  const path=require("node:path");
  const src=fs.readFileSync(path.join(__dirname,"../assets/offer-graph.js"),"utf8");
  assert.match(src,/prior.focus===undefined\?null:prior.focus/);
  assert.match(src,/const \{layout,bounds\}=layoutAllNodes\(graph.nodes\)/);
  assert.ok(!src.includes("const visibleOffers=selected?"));
  assert.ok(src.includes("autoFit=true;remember();draw();"));
});
