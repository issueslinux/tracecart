import {traceCartQueuedProductProjection} from "./queue_capture.mjs";

/* Disabled until paired and enabled by the user. Strictly loopback-only.
   This worker cannot read cookies or localStorage of any merchant. */
const ALARM = "tracecart-queued-research";
let busy = false;

function validConfig(c) {
  return c && c.enabled === true && /^[0-9a-f]{64}$/.test(c.token || "") &&
    Number.isInteger(c.port) && c.port >= 1024 && c.port <= 65535;
}
function endpoint(config, path) {
  return `http://127.0.0.1:${config.port}${path}`;
}
async function localFetch(config, path, options={}) {
  const signal=AbortSignal.timeout(12000);
  const response=await fetch(endpoint(config,path), {
    ...options, signal,
    headers:{"Authorization":`Bearer ${config.token}`,
             "Content-Type":"application/json"}
  });
  if (!response.ok) throw new Error("LOCAL_BROKER_HTTP_"+response.status);
  return response.json();
}
// A merchant can redirect a background tab to a security interstitial.
// Report the denial, not an ordinary product redirect. Never bypass it.
function redirectFailure(url) {
  try {
    const target=new URL(url);
    if (target.protocol==="https:" && target.hostname==="www.ebay.com" &&
        target.pathname==="/splashui/challenge") return "ACCESS_CHALLENGE";
  } catch (_) { /* Invalid final URL remains a rejected redirect. */ }
  return "REDIRECTED";
}

async function snapshotJob(job) {
  let origin;
  try {
    const parsed=new URL(job.url);
    if (parsed.protocol!=="https:" || parsed.username || parsed.password ||
        parsed.port || parsed.hash || !/^[a-z0-9.-]+$/i.test(parsed.hostname)) {
      return {error:"BROWSER_ERROR"};
    }
    origin=parsed.origin+"/*";
  } catch (_) { return {error:"BROWSER_ERROR"}; }
  if (!(await chrome.permissions.contains({origins:[origin]}))) {
    return {error:"SITE_PERMISSION_REQUIRED"};
  }
  let tabId;
  try {
    const tab=await chrome.tabs.create({url:job.url,active:false});
    tabId=tab.id;
    if (typeof tabId !== "number") return {error:"BROWSER_ERROR"};
    const deadline=Date.now()+30000;
    let ready=false, state;
    while (Date.now()<deadline) {
      await new Promise(resolve => setTimeout(resolve,600));
      try { state=await chrome.tabs.get(tabId); } catch (_) { break; }
      if (state.status==="complete") {ready=true;break;}
    }
    if (!ready) return {error:"TAB_TIMEOUT"};
    // The user may revoke a host while the background tab is loading.
    // The initial pre-navigation check alone is not sufficient.
    if (!(await chrome.permissions.contains({origins:[origin]}))) {
      return {error:"SITE_PERMISSION_REQUIRED"};
    }
    // No redirects to another offer or host: the research queue must refer
    // to exactly the requested URL, with no silent price reassignment.
    const actual=String(state.url || "");
    if (actual !== job.url) return {error:redirectFailure(actual)};
    const data=await chrome.scripting.executeScript({
      target:{tabId}, func:traceCartQueuedProductProjection
    });
    const projection=data?.[0]?.result;
    if (!projection || projection.error) {
      return {error:projection?.error || "BROWSER_ERROR"};
    }
    if (projection.url!==job.url) return {error:redirectFailure(projection.url)};
    // Do not forward already collected fields if permission was revoked
    // while the tab was being inspected.
    if (!(await chrome.permissions.contains({origins:[origin]}))) {
      return {error:"SITE_PERMISSION_REQUIRED"};
    }
    return projection;
  } catch (_) {
    return {error:"BROWSER_ERROR"};
  } finally {
    if (typeof tabId==="number") {
      try { await chrome.tabs.remove(tabId); } catch (_) {}
    }
  }
}

// Bounded parallelism: up to three real seller tabs are inspected at once.
// Every job gets its own source receipt; no headless access bypass or retry.
const MAX_BROWSER_JOBS_IN_PARALLEL = 3;
const MAX_PER_LANE_PER_POLL = 4; // 3 × 4 = max 12 explicitly queued URLs


async function processOne(config) {
  const response=await localFetch(config,"/api/browser-companion/next");
  const job=response.job;
  if (!job) return false;
  const captured=await snapshotJob(job);
  const receipt={
    job_id:job.job_id,url:job.url,
    captured_at:captured.captured_at || null,
    snapshot:captured.snapshot || null,
    price_origin:captured.price_origin || null,
    promotion:captured.promotion || null,
    error:captured.error || null
  };
  const ack=await localFetch(config,"/api/browser-companion/result", {
    method:"POST",body:JSON.stringify(receipt)
  });
  await chrome.storage.local.set({
    companionLastStatus:job.url+" → "+ack.status
  });
  return true;
}

async function poll() {
  if (busy) return;
  busy=true;
  try {
    const {companionConfig:config}=await chrome.storage.local.get("companionConfig");
    if (!validConfig(config)) return;
    let observed=0;
    await Promise.all(Array.from({length:MAX_BROWSER_JOBS_IN_PARALLEL},
      async ()=>{
        try {
          for (let i=0;i<MAX_PER_LANE_PER_POLL;i++){
            if (!(await processOne(config))) break;
            observed++;
          }
        } catch(error) {
          await chrome.storage.local.set({companionLastStatus:
            "Companion local broker unavailable: "+
            String(error?.message || "ERROR").slice(0,85)});
        }
      }));
    if (!observed) {
      await chrome.storage.local.set({companionLastStatus:"Queue empty"});
    }
  } finally {busy=false;}
}

chrome.alarms.onAlarm.addListener(alarm=>{
  if (alarm.name===ALARM) void poll();
});
chrome.runtime.onStartup.addListener(async ()=>{
  const {companionConfig:config}=await chrome.storage.local.get("companionConfig");
  if (validConfig(config)) chrome.alarms.create(ALARM,{periodInMinutes:1});
});
chrome.runtime.onInstalled.addListener(async ()=>{
  const {companionConfig:config}=await chrome.storage.local.get("companionConfig");
  if (validConfig(config)) chrome.alarms.create(ALARM,{periodInMinutes:1});
});

chrome.runtime.onMessage.addListener((msg,sender,respond)=>{
  if (sender.id !== chrome.runtime.id || msg?.action!=="configureCompanion") return false;
  void (async ()=>{
    const {companionConfig:config}=await chrome.storage.local.get("companionConfig");
    if (validConfig(config)) {
      chrome.alarms.create(ALARM,{periodInMinutes:1});
      void poll();
    } else {
      await chrome.alarms.clear(ALARM);
    }
    respond({ok:true});
  })().catch(()=>respond({ok:false}));
  return true;
});
