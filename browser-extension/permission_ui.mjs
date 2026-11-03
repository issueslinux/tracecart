/**
 * Site-scoped browser permission helpers for the opt-in TraceCart companion.
 * No network calls or cookie access. Browser prompts must originate from
 * explicit popup button clicks, never from the worker or an alarm.
 */
export function merchantOrigin(input) {
  if (typeof input !== "string" || input.length > 1200) return null;
  let url;
  try { url = new URL(input.trim()); } catch (_) { return null; }
  if (url.protocol !== "https:" || url.username || url.password || url.port) return null;
  const host = url.hostname.toLowerCase();
  if (!host || host === "localhost" || host.endsWith(".localhost") ||
      host.endsWith(".local") || host.endsWith(".internal") ||
      host.endsWith(".test") || host.endsWith(".invalid") ||
      host.endsWith(".example") || host.includes(":") ||
      /^\d+(?:\.\d+){3}$/.test(host) ||
      !/^[a-z0-9.-]+$/.test(host) || !host.includes(".") ||
      host.startsWith(".") || host.endsWith(".") || host.includes("..")) return null;
  return url.origin;
}

export async function permissionStatus(api, input) {
  const origin = merchantOrigin(input);
  if (!origin) return {status:"INVALID_MERCHANT_URL",origin:null};
  const granted = await api.contains({origins:[origin+"/*"]});
  return {status:granted ? "GRANTED" : "NOT_GRANTED",origin};
}

export async function requestMerchantPermission(api, input) {
  const origin = merchantOrigin(input);
  if (!origin) return {status:"INVALID_MERCHANT_URL",origin:null};
  // This should be called exclusively from an actual user click.
  const granted = await api.request({origins:[origin+"/*"]});
  return {status:granted ? "GRANTED" : "DECLINED",origin};
}

export async function revokeMerchantPermission(api, input) {
  const origin = merchantOrigin(input);
  if (!origin) return {status:"INVALID_MERCHANT_URL",origin:null};
  // Removing a site permission stops future queued captures for that origin.
  const removed = await api.remove({origins:[origin+"/*"]});
  const remains = await api.contains({origins:[origin+"/*"]});
  return {status:remains ? "STILL_GRANTED" : "NOT_GRANTED",
          origin,removed:Boolean(removed)};
}
