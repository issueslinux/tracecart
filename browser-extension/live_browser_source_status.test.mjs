import assert from "node:assert/strict";
import test from "node:test";
import {createRequire} from "node:module";
const require=createRequire(import.meta.url);
const {sourceTasks}=require("../assets/live-workspace.js");
const url="https://www.ebay.com/itm/880062986898";
function snapshot(status){
  return {state:"READY",evidence_progress:{status:"COMPLETE"},
    offer_queue:[{id:"offer-0",kind:"INPUT_PRODUCT",title:"Unidentified product from www.ebay.com",url}],
    graph:{offer_details:{"offer-0":{input_access_problem:"HTTP_403"}},nodes:[]},
    browser_auto_batch:{status:"COMPLETE_WITH_FAILURES",queued_count:1,
      tasks:[{url,status}]}};
}
test("permission-required selected eBay browser task overrides server HTTP 403",()=>{
  const rows=sourceTasks(snapshot("SITE_PERMISSION_REQUIRED"));
  assert.equal(rows[0].key,"#1");
  assert.equal(rows[0].state,"BROWSER PERMISSION REQUIRED");
  assert.match(rows[0].detail,/grant permission/i);
  assert.equal(rows[0].mode,"BLOCKED");
});
test("access-challenged eBay is not presented as missing store price",()=>{
  const rows=sourceTasks(snapshot("ACCESS_CHALLENGE"));
  assert.equal(rows[0].state,"BROWSER ACCESS CHALLENGE");
  assert.match(rows[0].detail,/not bypass/);
  assert.doesNotMatch(rows[0].detail,/No browser price available/);
});
test("failed structured source keeps a clear browser failure",()=>{
  const rows=sourceTasks(snapshot("NO_STRUCTURED_PRODUCT"));
  assert.equal(rows[0].state,"BROWSER: NO_STRUCTURED_PRODUCT");
});
