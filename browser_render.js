#!/usr/bin/env node
/* Isolated, offscreen GRAPHICAL Chromium fallback for JS-rendered public pages.
 * A private Xvfb display supplies a real GUI renderer; no user profile,
 * cookies, CAPTCHA handling, stealth plugins or unauthorized HTTP access.
 * Every request (including subresources and redirects) is intercepted and
 * denied unless it stays on the exact prevalidated public HTTPS hostname.
 * DNS for that hostname is pinned to the caller's verified public IP.
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
    if(u.protocol!=="https:"||u.hostname!==host||u.username||
       u.password||(u.port&&u.port!=="443"))return false;
    if(!/^[a-z0-9.-]{4,180}$/.test(host))return false;
    return true;
  }catch(_){return false;}
}
if(!valid()){process.stderr.write("INVALID_RENDER_SOURCE\n");process.exit(2);}
const base=process.env.TRACECART_BROWSER_PROFILE_ROOT||
   path.join(os.homedir(),"snap/chromium/common");
const profile=fs.mkdtempSync(path.join(base,"tracecart-isolated-"+process.pid+"-"));
const binary=process.env.TRACECART_CHROMIUM||"/snap/bin/chromium";
const args=[
  "-a",binary,
  "--no-first-run","--no-default-browser-check","--disable-extensions",
  "--disable-sync","--disable-default-apps","--disable-background-networking",
  "--disable-gpu","--disable-dev-shm-usage","--no-proxy-server",
  "--disable-features=MediaRouter,OptimizationHints",
  "--remote-debugging-port=0","--remote-allow-origins=*",
  "--user-data-dir="+profile,
  "--host-resolver-rules=MAP "+host+" "+pin+", MAP * ~NOTFOUND",
  "about:blank",
];
let proc=null,ws=null,finished=false;
const pending=new Map();
let seq=0;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function stop(){
  if(finished)return;finished=true;
  try{if(ws&&ws.readyState===WebSocket.OPEN)ws.close();}catch(_){}
  if(proc&&proc.pid){
    try{process.kill(-proc.pid,"SIGTERM");}catch(_){}
    setTimeout(()=>{try{process.kill(-proc.pid,"SIGKILL");}catch(_){}},650).unref();
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
async function main(){
  proc=cp.spawn("xvfb-run",args,{detached:true,
    stdio:["ignore","ignore","ignore"],env:{...process.env,DISPLAY:""}});
  const active=path.join(profile,"DevToolsActivePort");
  let port=null;
  for(let i=0;i<90;i++){
    if(proc.exitCode!==null)throw Error("CHROMIUM_EXITED");
    try{
      const first=fs.readFileSync(active,"utf8").split("\n")[0];
      if(/^\d{4,5}$/.test(first)){port=Number(first);break;}
    }catch(_){}
    await sleep(100);
  }
  if(!port)throw Error("BROWSER_START_TIMEOUT");
  const targets=await(await fetch("http://127.0.0.1:"+port+"/json/list")).json();
  const tab=targets.find(t=>t.type==="page"&&t.url==="about:blank")||
            targets.find(t=>t.type==="page");
  if(!tab)throw Error("NO_BROWSER_PAGE");
  ws=new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{
    ws.addEventListener("open",resolve,{once:true});
    ws.addEventListener("error",reject,{once:true});
  });
  ws.addEventListener("message",event=>{
    const msg=JSON.parse(event.data);
    if(msg.method==="Fetch.requestPaused"){
      const item=msg.params;
      let approve=false;
      try {
        const u=new URL(item.request.url);
        approve=(u.protocol==="https:"&&u.hostname===host&&
                 !u.username&&!u.password&&
                 (!u.port||u.port==="443"));
      }catch(_){}
      const method=approve?"Fetch.continueRequest":"Fetch.failRequest";
      call(method,{requestId:item.requestId,
        ...(!approve?{errorReason:"BlockedByClient"}:{})}).catch(()=>{});
    }
    if(!msg.id)return;
    const wait=pending.get(msg.id);
    if(wait){
      pending.delete(msg.id);
      if(msg.error)wait.reject(Error(msg.error.message));
      else wait.resolve(msg.result);
    }
  });
  await call("Page.enable");
  await call("Runtime.enable");
  await call("Network.setCacheDisabled",{cacheDisabled:true});
  await call("Fetch.enable",{patterns:[{urlPattern:"*",requestStage:"Request"}]});
  await call("Page.navigate",{url});
  await sleep(2200);
  const response=await call("Runtime.evaluate",{
    expression:"JSON.stringify({url:location.href,html:document.documentElement.outerHTML})",
    returnByValue:true,awaitPromise:false});
  const packed=JSON.parse(response.result.value||"null");
  if(!packed||packed.url!==url||typeof packed.html!=="string"||
     packed.html.length>MAX_HTML||packed.html.length<50)
    throw Error("RENDERED_PAGE_INVALID_OR_REDIRECTED");
  process.stdout.write(JSON.stringify({
    source_url:url,html:packed.html,render_method:"ISOLATED_XVFB_CHROMIUM",
    browser_request_scope:"SAME_ORIGIN_HTTPS_ONLY_PINNED_PUBLIC_IP"}));
}
const MAX_HTML=1800000;
const timer=setTimeout(()=>{process.stderr.write("BROWSER_BUDGET_EXCEEDED\n");
  stop();process.exit(3);},14000);
main().then(()=>{
  clearTimeout(timer);stop();
}).catch(err=>{
  clearTimeout(timer);
  process.stderr.write(String(err.message||"BROWSER_FAILURE").slice(0,120)+"\n");
  stop();process.exitCode=4;
});
