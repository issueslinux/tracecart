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
    const job=Array.isArray(next) ? (next.shift() || null) : next;
    if (!Array.isArray(next)) next=null;
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
    ack=(payload)=>{clearTimeout(timeout);setTimeout(()=>resolve(payload),45);};
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
test("eBay security redirect is an access challenge, not a product redirect",async()=>{
  config={...config,enabled:true};
  permit=true;
  next={job_id:"job-ebay-challenge",url:"https://www.ebay.com/itm/880062986898"};
  const old=chrome.tabs.get;
  const before=executed;
  chrome.tabs.get=async()=>({id:123,status:"complete",
    url:"https://www.ebay.com/splashui/challenge?ru=https%3A%2F%2Fwww.ebay.com%2Fitm%2F880062986898"});
  try {
    const done=await tick();
    assert.equal(done.error,"ACCESS_CHALLENGE");
    assert.equal(done.snapshot,null);
    assert.equal(executed,before);
  } finally {chrome.tabs.get=old;}
});
test("an unrelated eBay destination stays rejected as redirected",async()=>{
  permit=true;next={job_id:"job-ebay-wrong-item",url:"https://www.ebay.com/itm/880062986898"};
  const old=chrome.tabs.get;const before=executed;
  chrome.tabs.get=async()=>({id:123,status:"complete",
    url:"https://www.ebay.com/itm/OTHER_ITEM"});
  try{
    const done=await tick();assert.equal(done.error,"REDIRECTED");
    assert.equal(executed,before);
  }finally{chrome.tabs.get=old;}
});
test("permission revoked after loading prevents executeScript",async()=>{
  config={...config,enabled:true};
  permit=true; next={job_id:"job-revoked-after-open",url:source};
  const prev=chrome.permissions.contains;
  let checks=0;
  chrome.permissions.contains=async()=>{
    checks++;
    return checks===1;
  };
  const executedBefore=executed;
  try {
    const done=await tick();
    assert.equal(done.error,"SITE_PERMISSION_REQUIRED");
    assert.equal(executed,executedBefore);
  } finally {chrome.permissions.contains=prev;}
});
test("permission revoked during capture discards extracted fields",async()=>{
  config={...config,enabled:true};
  permit=true; next={job_id:"job-revoked-during-capture",url:source};
  const prev=chrome.permissions.contains;
  let checks=0;
  chrome.permissions.contains=async()=>{
    checks++;
    return checks<=2;
  };
  const executedBefore=executed;
  try {
    const done=await tick();
    assert.equal(done.error,"SITE_PERMISSION_REQUIRED");
    assert.equal(done.snapshot,null);
    assert.equal(executed,executedBefore+1);
  } finally {chrome.permissions.contains=prev;}
});
test("three different sellers run truly concurrently, never more than three",async()=>{
  config={...config,enabled:true};
  permit=true;
  const urls=[
    "https://store.example.org/product/parallel-1",
    "https://store.example.org/product/parallel-2",
    "https://store.example.org/product/parallel-3",
    "https://store.example.org/product/parallel-4"
  ];
  // The browser worker sees a bounded, four-URL user submission.
  next=urls.map((url,i)=>({job_id:"parallel-job-"+i,url}));
  const savedGet=chrome.tabs.get,savedCreate=chrome.tabs.create;
  const savedExecute=chrome.scripting.executeScript;
  const savedFetch=globalThis.fetch;
  const savedRemove=chrome.tabs.remove;
  let open=0,maxOpen=0,concurrentReached;
  const reached=new Promise(resolve=>{concurrentReached=resolve;});
  let unblock;
  const gate=new Promise(resolve=>{unblock=resolve;});
  const receipts=[];
  chrome.tabs.create=async ({url})=>{
    open++;maxOpen=Math.max(maxOpen,open);
    if(maxOpen===3) concurrentReached();
    await gate;
    return {id:100+open,url};
  };
  chrome.tabs.get=async ()=>({status:"complete",url:source});
  chrome.tabs.remove=async ()=>{open--;};
  chrome.scripting.executeScript=async()=>[{result:{
    url:source,captured_at:new Date().toISOString(),
    price_origin:"DIRECT_OFFER_PRICE",snapshot:{
      "@type":"Product",name:"Example",
      offers:{"@type":"Offer",price:"12.00",priceCurrency:"PLN"}
    }
  }}];
  // This test isolates queue concurrency; set each selected URL's browser
  // page URL to the exact URL of that job through a tab-id map.
  const tabURLs=new Map();
  let tabID=200;
  chrome.tabs.create=async({url})=>{
    const id=++tabID;
    tabURLs.set(id,url);
    open++;maxOpen=Math.max(maxOpen,open);
    if(maxOpen===3) concurrentReached();
    await gate;
    return{id,url};
  };
  chrome.tabs.get=async id=>({status:"complete",url:tabURLs.get(id)});
  chrome.scripting.executeScript=async({target:{tabId}})=>[{result:{
    url:tabURLs.get(tabId),captured_at:new Date().toISOString(),
    price_origin:"DIRECT_OFFER_PRICE",snapshot:{
      "@type":"Product",name:"Example",
      offers:{"@type":"Offer",price:"12.00",priceCurrency:"PLN"}
    }
  }}];
  globalThis.fetch=async(u,options)=>{
    assert.ok(u.startsWith("http://127.0.0.1:8765/api/browser-companion/"));
    assert.equal(options.headers.Authorization,"Bearer "+token);
    if(u.endsWith("/next"))return{ok:true,json:async()=>({job:next.shift()||null})};
    const value=JSON.parse(options.body);receipts.push(value);
    return{ok:true,json:async()=>({status:"EXTRACTED"})};
  };
  chrome.tabs.remove=async(id)=>{tabURLs.delete(id);open--;};
  try {
    onAlarm({name:"tracecart-queued-research"});
    await Promise.race([reached,new Promise((_,reject)=>
      setTimeout(()=>reject(Error("Three tab overlap not reached")),3000))]);
    assert.equal(open,3);
    assert.equal(maxOpen,3);
    unblock();
    for(let i=0;i<30&&receipts.length<4;i++)
      await new Promise(resolve=>setTimeout(resolve,100));
    assert.equal(receipts.length,4);
    assert.equal(new Set(receipts.map(x=>x.url)).size,4);
    assert.ok(maxOpen<=3);
    assert.equal(open,0);
    assert.ok(receipts.every(x=>x.error===null && x.snapshot.offers.price==="12.00"));
  } finally {
    unblock();next=null;
    chrome.tabs.create=savedCreate;chrome.tabs.get=savedGet;
    chrome.scripting.executeScript=savedExecute;
    chrome.tabs.remove=savedRemove;globalThis.fetch=savedFetch;
    await new Promise(resolve=>setTimeout(resolve,60));
  }
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
