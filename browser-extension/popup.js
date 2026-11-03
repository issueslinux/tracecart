import {traceCartCapturePage} from "./capture_core.mjs";

const captureButton = document.getElementById("capture");
const copyButton = document.getElementById("copy");
const status = document.getElementById("status");
const payload = document.getElementById("payload");

captureButton.addEventListener("click", async () => {
  copyButton.disabled = true;
  payload.value = "";
  status.textContent = "Checking current active tab...";
  try {
    const [tab] = await chrome.tabs.query({active:true, currentWindow:true});
    if (!tab || !tab.id || !tab.url?.startsWith("https://")) {
      status.textContent = "Open an HTTPS product tab first.";
      return;
    }
    const result = await chrome.scripting.executeScript({
      target:{tabId:tab.id}, func:traceCartCapturePage
    });
    const captured = result?.[0]?.result;
    if (!captured || captured.error) {
      status.textContent = captured?.error || "No product evidence found.";
      return;
    }
    payload.value = JSON.stringify(captured, null, 2);
    status.textContent = captured.price + " " + captured.currency +
      " — unverified browser observation. Paste JSON in TraceCart.";
    copyButton.disabled = false;
  } catch (_) {
    status.textContent = "Capture failed. This tab may not allow extensions.";
  }
});

copyButton.addEventListener("click", async () => {
  if (!payload.value) return;
  try {
    await navigator.clipboard.writeText(payload.value);
    status.textContent = "Copied. Paste this JSON in TraceCart's browser capture field.";
  } catch (_) {
    payload.focus();
    payload.select();
    status.textContent = "Clipboard blocked; copy the selected JSON manually.";
  }
});


/** One-time local-only pairing and per-site permission gate. */
const portInput=document.getElementById("companion-port");
const tokenInput=document.getElementById("companion-token");
const originInput=document.getElementById("companion-origin");
const enabledInput=document.getElementById("companion-enabled");
const companionStatus=document.getElementById("companion-status");

async function currentSettings() {
  return (await chrome.storage.local.get("companionConfig")).companionConfig || {};
}
function validSettings(config) {
  return Number.isInteger(config.port) && config.port>=1024 &&
         config.port<=65535 && /^[0-9a-f]{64}$/.test(config.token || "");
}
async function applyCompanion(config) {
  await chrome.storage.local.set({companionConfig:config});
  const reply=await chrome.runtime.sendMessage({action:"configureCompanion"});
  if (!reply?.ok) throw new Error("Worker did not acknowledge configuration");
}
async function initCompanion() {
  const c=await currentSettings();
  if (c.port) portInput.value=String(c.port);
  enabledInput.checked=c.enabled===true;
  const status=(await chrome.storage.local.get("companionLastStatus")).companionLastStatus;
  companionStatus.textContent=status || (c.enabled ? "Queue enabled." : "Queue disabled.");
}
document.getElementById("companion-pair").addEventListener("click",async ()=>{
  const port=Number(portInput.value);
  const token=tokenInput.value.trim();
  if (!validSettings({port,token})) {
    companionStatus.textContent="Invalid port or pairing token (64 hex chars).";
    return;
  }
  try {
    // Pairing alone does not authorize background visits.
    await applyCompanion({port,token,enabled:false});
    tokenInput.value="";
    enabledInput.checked=false;
    companionStatus.textContent="Paired locally. Grant a site, then enable the queue.";
  } catch (_) { companionStatus.textContent="Could not configure companion."; }
});
document.getElementById("companion-grant").addEventListener("click", async ()=>{
  let origin;
  try {
    const u=new URL(originInput.value);
    if (u.protocol!=="https:" || u.username || u.password || u.port ||
        !/^[a-z0-9.-]+$/i.test(u.hostname)) throw new Error("invalid");
    origin=u.origin+"/*";
  } catch (_) {
    companionStatus.textContent="Enter a public HTTPS merchant URL.";
    return;
  }
  try {
    // Must be called from this explicit user click, never the background worker.
    const granted=await chrome.permissions.request({origins:[origin]});
    companionStatus.textContent=granted
      ? "Permission granted to "+new URL(originInput.value).origin
      : "Site permission declined.";
  } catch (_) { companionStatus.textContent="Browser rejected this permission."; }
});
document.getElementById("companion-apply").addEventListener("click",async ()=>{
  const c=await currentSettings();
  if (!validSettings(c)) {
    companionStatus.textContent="Save the local pairing token first.";
    enabledInput.checked=false;
    return;
  }
  try {
    await applyCompanion({...c,enabled:enabledInput.checked});
    companionStatus.textContent=enabledInput.checked
      ? "Queue enabled. Browser will check the local broker."
      : "Queue disabled. No new tabs will open.";
  } catch (_) { companionStatus.textContent="Could not update the queue."; }
});
void initCompanion().catch(()=>{
  companionStatus.textContent="Extension storage is unavailable.";
});
