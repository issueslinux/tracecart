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
