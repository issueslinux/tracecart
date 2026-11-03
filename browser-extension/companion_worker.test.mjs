import assert from "node:assert/strict";
import test from "node:test";

const source="https://store.example.org/product/example";
const token="a".repeat(64);
let onAlarm, onMessage, onStartup, onInstalled;
let config={port:8765,token,enabled:true};
let permit=false;
let next={job_id:"job-1",url:source};
let receipt=null, opened=0, executed=0, closed=0, lastStatus="";
let ack;
globalThis.chrome={
  permissions:{contains:async()=>permit},
  tabs:{
    create:async()=>{opened++;return {id:123};},
    get:async()=>({id:123,status:"complete",url:source}),
    remove:async()=>{closed++;}
  },
  scripting:{executeScript:async()=>{executed++;return [{result:{
    url:source,captured_at:new Date().toISOString(),
    price_origin:"DIRECT_OFFER_PRICE", snapshot:{"@type":"Product",name:"Example",
              offers:{"@type":"Offer",price:"12.00",priceCurrency:"PLN"}}
  }}];}},
  storage:{local:{
    get:async()=>({companionConfig:config}),
    set:async value=>{if(value.companionLastStatus)lastStatus=value.companionLastStatus;}
  }},
  alarms:{
    onAlarm:{addListener:fn=>{onAlarm=fn;}},
    create:()=>{},clear:async()=>{}
  },
  runtime:{
    id:"tracecart-test", onStartup:{addListener:fn=>{onStartup=fn;}},
    onInstalled:{addListener:fn=>{onInstalled=fn;}},
    onMessage:{addListener:fn=>{onMessage=fn;}}
  }
};
globalThis.fetch=async (u,options)=>{
  assert.ok(u.startsWith("http://127.0.0.1:8765/api/browser-companion/"));
  assert.equal(options.headers.Authorization,"Bearer "+token);
  if(u.endsWith("/next")){
    const job=next;next=null;
    return {ok:true,json:async()=>({job})};
  }
  receipt=JSON.parse(options.body);
  ack?.(receipt);
  return {ok:true,json:async()=>({status:receipt.error || "EXTRACTED"})};
};
await import("./companion_worker.mjs");

function tick() {
  return new Promise((resolve,reject)=>{
    const timeout=setTimeout(()=>reject(Error("No receipt")),3000);
    ack=(payload)=>{clearTimeout(timeout);resolve(payload);};
    onAlarm({name:"tracecart-queued-research"});
  });
}

test("unapproved merchant host produces permission-required result without opening tabs",async()=>{
  permit=false; next={job_id:"job-1",url:source};
  const done=await tick();
  assert.equal(done.error,"SITE_PERMISSION_REQUIRED");
  assert.equal(opened,0);
  assert.equal(executed,0);
});
test("approved URL executes one filtered capture and closes tab",async()=>{
  permit=true; next={job_id:"job-2",url:source};
  const done=await tick();
  assert.equal(done.error,null);
  assert.equal(done.snapshot.offers.price,"12.00");
  assert.equal(opened,1);
  assert.equal(executed,1);
  assert.equal(closed,1);
});
test("disabled configuration never polls the broker",async()=>{
  config={...config,enabled:false};
  let calls=0;
  const original=globalThis.fetch;
  globalThis.fetch=async (...args)=>{calls++;return original(...args);};
  onAlarm({name:"tracecart-queued-research"});
  await new Promise(resolve=>setTimeout(resolve,20));
  assert.equal(calls,0);
  globalThis.fetch=original;
});
