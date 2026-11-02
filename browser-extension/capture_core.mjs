/**
 * Runs only after explicit extension popup click on an open, visible tab.
 * Self-contained so chrome.scripting.executeScript can serialize this function.
 * Never reads cookies, tokens, localStorage, other tabs, fetch() or hidden APIs.
 */
export function traceCartCapturePage() {
  const url = String(globalThis.location?.href || "");
  const title = String(globalThis.document?.title || "").trim().slice(0, 180);
  const observedAt = new Date().toISOString();
  if (!url.startsWith("https://") || title.length < 3) {
    return {error: "Open a public HTTPS product page first."};
  }

  function normalizedPrice(value) {
    if (typeof value !== "string" && typeof value !== "number") return null;
    const raw = String(value).trim().replace(/[\s\u00a0\u202f]/g, "");
    if (!/^(?:0|[1-9][0-9]{0,5})(?:[.,][0-9]{1,2})?$/.test(raw)) return null;
    const number = Number(raw.replace(",", "."));
    if (!(number > 0 && number <= 100000) || !Number.isFinite(number)) return null;
    return number.toFixed(2);
  }

  function onlyProduct(root) {
    const nodes = [];
    function visit(value) {
      if (Array.isArray(value)) {
        for (const entry of value.slice(0, 25)) visit(entry);
      } else if (value && typeof value === "object") {
        const type = value["@type"];
        const labels = Array.isArray(type) ? type : [type];
        if (labels.some(t => t === "Product" || t === "https://schema.org/Product")) {
          nodes.push(value);
        }
        if (value["@graph"]) visit(value["@graph"]);
      }
    }
    visit(root);
    return nodes;
  }

  // When the user deliberately highlights a visible price (including a
  // currency), trust that explicit selection *as a browser observation* over
  // possibly stale JSON-LD, but never as an independently verified offer.
  const selected = String(globalThis.getSelection?.()?.toString() || "").trim();
  const priceMatch = selected.match(/^\s*((?:0|[1-9][0-9]{0,5}|[1-9][0-9]{0,2}(?:[ \u00a0\u202f][0-9]{3})+)(?:[.,][0-9]{1,2})?)\s*(zł|PLN|€|EUR|\$|USD)\s*$/i);
  if (priceMatch) {
    const price = normalizedPrice(priceMatch[1]);
    if (!price) return {error:"Selected price is invalid."};
    const unit = priceMatch[2].toUpperCase();
    const currency = (unit === "ZŁ" || unit === "PLN") ? "PLN"
      : (unit === "€" || unit === "EUR") ? "EUR" : "USD";
    return {
      version:1, method:"USER_SELECTED_VISIBLE_PRICE", url, title,
      price, currency, gtin_claim:null, observed_at:observedAt,
      price_evidence:"SELECTED_VISIBLE_TEXT"
    };
  }

  // Primary path: a single explicit Product -> Offer, not AggregateOffer,
  // search results, page-level teaser prices or crossed-out list prices.
  const products = [];
  for (const node of Array.from(document.querySelectorAll('script[type="application/ld+json"]')).slice(0, 25)) {
    try {
      const parsed = JSON.parse(node.textContent || "");
      products.push(...onlyProduct(parsed));
    } catch (_) {
      // Unparseable scripts are not evidence.
    }
  }
  if (products.length === 1) {
    const product = products[0];
    const offer = Array.isArray(product.offers)
      ? (product.offers.length === 1 ? product.offers[0] : null)
      : product.offers;
    const offerType = String(offer?.["@type"] || "Offer").split("/").pop();
    const currency = offer?.priceCurrency;
    const price = (offerType === "Offer" && ["PLN","EUR","USD"].includes(currency))
      ? normalizedPrice(offer.price) : null;
    const code = [product.gtin13,product.gtin14,product.gtin12,product.gtin8,product.gtin]
      .find(v => typeof v === "string" && /^\d{8}$|^\d{12,14}$/.test(v)) || null;
    if (price) {
      return {
        version:1, method:"ACTIVE_TAB_SINGLE_PRODUCT_JSONLD", url,
        title:String(product.name || title).slice(0,180), price,
        currency, gtin_claim:code, observed_at:observedAt,
        price_evidence:"UNIQUE_PRODUCT_JSONLD"
      };
    }
  }

  return {error: "No unique Product/Offer price. Highlight exactly a visible price like 229,00 zł and try again."};
}
