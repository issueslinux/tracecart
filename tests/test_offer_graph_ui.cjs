"use strict";
const assert=require("node:assert/strict");
const test=require("node:test");
const path=require("node:path");
const fs=require("node:fs");
const graph=require("../assets/offer-graph.js");

test("client graph source links disallow unsafe local and non-HTTPS targets",()=>{
  assert.equal(graph.safeUrl("https://www.notebookcheck.net/review"),"https://www.notebookcheck.net/review");
  for(const url of ["http://example.org","https://127.0.0.1/private",
                    "https://localhost/","https://169.254.169.254/",
                    "https://user:password@example.org/",
                    "file:///etc/passwd","javascript:alert(1)"]) {
    assert.equal(graph.safeUrl(url),null);
  }
});
test("network labels are shortened but never embedded as HTML",()=>{
  assert.equal(graph.clip("123456",4),"123…");
  assert.equal(graph.clip("<img onerror=alert(1)>",100),
               "<img onerror=alert(1)>");
  const src=fs.readFileSync(path.join(__dirname,"../assets/offer-graph.js"),"utf8");
  assert.ok(src.includes(".textContent="));
  assert.ok(!src.includes(".innerHTML"));
  assert.ok(src.includes("OPEN · no verified exact-variant answer"));
});
test("the page initializes graph after research READY without replacing saved audit",()=>{
 const app=fs.readFileSync(path.join(__dirname,"../assets/decision-flow.js"),"utf8");
 assert.ok(app.includes("renderKnowledgeGraph(app)"));
 assert.ok(app.includes("data-knowledge-graph") || app.includes("dataset.knowledgeGraph"));
 assert.ok(app.includes('card.id="offer-research-"+(index+1)'));
 const template=fs.readFileSync(path.join(__dirname,"../assets/decision-page.html"),"utf8");
 assert.ok(template.includes('id="knowledge-graph-region"'));
 assert.ok(template.includes('id="kg-svg"'));
 assert.ok(template.includes("{{KNOWLEDGE_GRAPH_URL}}"));
});


test("global graph keeps source contradictions visible without focusing a seller offer",()=>{
  const src=fs.readFileSync(path.join(__dirname,"../assets/offer-graph.js"),"utf8");
  assert.ok(src.includes('observations.filter(n=>n.type==="source_disagreement").slice(0,4)'));
  assert.ok(src.includes('"DISCREPANCY_REQUIRES_SOURCE_REVIEW"'));
  assert.ok(src.includes('"UNRESOLVED PUBLISHED CLAIM"'));
  assert.ok(src.includes("Downloaded source SHA256: "));
  assert.ok(src.includes("NOT an independent measurement or proof"));
});
