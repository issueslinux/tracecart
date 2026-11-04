#!/usr/bin/env node
/* Local managed Chromium for public, robots-approved merchant product pages.
 * No extension, no user browser profile, no per-host grants, no stealth,
 * no challenge solving. Each DNS-pinned, same-host navigation is isolated.
 * Only a filtered Product/Offer projection leaves the browser process.
 */
"use strict";
const fs=require("node:fs");
const os=require("node:os");
const path=require("node:path");
const cp=require("node:child_process");
const net=require("node:net");
const [url,host,pin]=process.argv.slice(2);
function valid(){
  if(!url||!host||!pin||net.isIP(pin)!==4)return false;
  try{
    const u=new URL(url);
    return u.protocol==="https:"&&u.hostname===host&&
      !u.username&&!u.password&&(!u.port||u.port==="443")&&
      /^[a-z0-9.-]{4,180}$/.test(host);
  }catch(_){return false;}
}
if(!valid()) {process.stderr.write("INVALID_MANAGED_BROWSER_SOURCE\n");process.exit(2);}
const base=process.env.TRACECART_BROWSER_PROFILE_ROOT||
  path.join(os.homedir(),"snap/chromium/common");
fs.mkdirSync(base,{recursive:true});
const profile=fs.mkdtempSync(path.join(base,"tracecart-managed-"));
const binary=process.env.TRACECART_CHROMIUM||"/snap/bin/chromium";
const arguments_=["-a",binary,"--no-first-run","--no-default-browser-check",
  "--disable-extensions","--disable-sync","--disable-default-apps",
  "--disable-background-networking","--disable-gpu","--disable-dev-shm-usage",
  "--no-proxy-server","--disable-features=MediaRouter,OptimizationHints",
  "--remote-debugging-port=0","--remote-allow-origins=*",
  "--user-data-dir="+profile,
  "--host-resolver-rules=MAP "+host+" "+pin+", MAP * ~NOTFOUND",
  "about:blank"];
let proc=null,ws=null,stopped=false,seq=0;
const pending=new Map();
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function stop(){
  if(stopped)return;stopped=true;
  try{if(ws&&ws.readyState===WebSocket.OPEN)ws.close();}catch(_){}
  if(proc&&proc.pid){
    try{process.kill(-proc.pid,"SIGTERM");}catch(_){}
    // Delay profile deletion until Chromium exits; never reuse persisted state.
    setTimeout(()=>{try{process.kill(-proc.pid,"SIGKILL");}catch(_){}} ,750).unref();
  }
  try{fs.rmSync(profile,{recursive:true,force:true});}catch(_){}
}
function call(method,params={}){
  return new Promise((resolve,reject)=>{
    const id=++seq;
    pending.set(id,{resolve,reject});
    ws.send(JSON.stringify({id,method,params}));
  });
}
function outcome(status,capture=null){
  process.stdout.write(JSON.stringify({
    source_url:url,status,capture,
    browser_request_scope:"SAME_ORIGIN_HTTPS_ONLY_PINNED_PUBLIC_IP",
    render_method:"ISOLATED_MANAGED_CHROMIUM_NO_EXTENSION"
  }));
}
async function main(){
  proc=cp.spawn("xvfb-run",arguments_,{detached:true,
    stdio:["ignore","ignore","ignore"],env:{...process.env,DISPLAY:""}});
  const active=path.join(profile,"DevToolsActivePort");
  let port=null;
  for(let i=0;i<95;i++){
    if(proc.exitCode!==null)throw Error("CHROMIUM_EXITED");
    try{
      const first=fs.readFileSync(active,"utf8").split("\n")[0];
      if(/^\d{4,5}$/.test(first)){port=Number(first);break;}
    }catch(_){}
    await sleep(100);
  }
  if(!port)throw Error("BROWSER_START_TIMEOUT");
  const targets=await (await fetch("http://127.0.0.1:"+port+"/json/list")).json();
  const tab=targets.find(x=>x.type==="page"&&x.url==="about:blank")||
    targets.find(x=>x.type==="page");
  if(!tab)throw Error("BROWSER_TAB_UNAVAILABLE");
  ws=new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{
    ws.addEventListener("open",resolve,{once:true});
    ws.addEventListener("error",reject,{once:true});
  });
  ws.addEventListener("message",event=>{
    const msg=JSON.parse(event.data);
    if(msg.method==="Fetch.requestPaused"){
      const item=msg.params;
      let allow=false;
      try{
        const target=new URL(item.request.url);
        allow=target.protocol==="https:"&&target.hostname===host&&
          !target.username&&!target.password&&(!target.port||target.port==="443");
      }catch(_){}
      call(allow?"Fetch.continueRequest":"Fetch.failRequest",{
        requestId:item.requestId,...(!allow?{errorReason:"BlockedByClient"}:{})
      }).catch(()=>{});
    }
    if(!msg.id)return;
    const waiter=pending.get(msg.id);
    if(waiter){
      pending.delete(msg.id);
      if(msg.error)waiter.reject(Error(msg.error.message));
      else waiter.resolve(msg.result);
    }
  });
  await call("Page.enable");
  await call("Runtime.enable");
  await call("Network.setCacheDisabled",{cacheDisabled:true});
  await call("Fetch.enable",{patterns:[{urlPattern:"*",requestStage:"Request"}]});
  await call("Page.navigate",{url});
  await sleep(2800);
  const source=fs.readFileSync(path.join(__dirname,"browser-extension","queue_capture.mjs"),"utf8")
    .replace("export function traceCartQueuedProductProjection", "function traceCartQueuedProductProjection");
  const script="(function(){"+source+"\nreturn JSON.stringify({url:location.href,capture:traceCartQueuedProductProjection()});})()";
  const response=await call("Runtime.evaluate",{expression:script,returnByValue:true});
  if(response.exceptionDetails)throw Error("BROWSER_CAPTURE_EXECUTION_ERROR");
  const packed=JSON.parse(response.result.value||"null");
  if(!packed||typeof packed.url!=="string")throw Error("BROWSER_CAPTURE_INVALID");
  if(packed.url!==url){
    const target=new URL(packed.url);
    if(target.hostname==="www.ebay.com"&&target.pathname==="/splashui/challenge"){
      outcome("ACCESS_CHALLENGE");return;
    }
    outcome("REDIRECTED");return;
  }
  const capture=packed.capture;
  if(!capture||typeof capture!=="object")throw Error("BROWSER_CAPTURE_EMPTY");
  if(capture.error){
    const known=new Set(["ACCESS_CHALLENGE","NO_STRUCTURED_PRODUCT",
      "MULTIPLE_PRODUCTS_AMBIGUOUS","CONFLICTING_PRODUCT_IDENTITY",
      "CONFLICTING_OFFER_EVIDENCE","BROWSER_ERROR"]);
    outcome(known.has(capture.error)?capture.error:"BROWSER_ERROR");return;
  }
  if(capture.url!==url||!capture.snapshot||typeof capture.snapshot!=="object"||
     !capture.price_origin||!capture.captured_at){
    outcome("BROWSER_ERROR");return;
  }
  outcome("PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED",capture);
}
const timer=setTimeout(()=>{
  process.stderr.write("MANAGED_BROWSER_TIME_BUDGET_EXCEEDED\n");
  stop();process.exit(3);
},17000);
main().then(()=>{clearTimeout(timer);stop();}).catch(err=>{
  clearTimeout(timer);
  process.stderr.write(String(err.message||"MANAGED_BROWSER_FAILED").slice(0,120)+"\n");
  stop();process.exitCode=4;
});
