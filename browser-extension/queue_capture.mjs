/**
 * Restricted, self-contained Product/Offer projection for executeScript.
 * Uses the currently rendered DOM only. No network, cookies, localStorage,
 * password inputs, full-page HTML, cross-origin frames or payment data.
 */
export function traceCartQueuedProductProjection() {
  const url = String(globalThis.location?.href || "");
  if (!url.startsWith("https://")) return {error:"BROWSER_ERROR"};
  const visible = String(globalThis.document?.body?.innerText || "").slice(0, 2000).toLowerCase();
  if (["please enable js and disable any ad blocker", "verify you are human",
       "captcha challenge", "access denied - datadome"].some(x => visible.includes(x))) {
    return {error:"ACCESS_CHALLENGE"};
  }

  function plain(value, max=180) {
    if (typeof value !== "string" || !value.trim() || value.length > max) return null;
    if (/[\x00-\x1f]/.test(value)) return null;
    return value.trim();
  }
  function priceValue(value) {
    if (!["string","number"].includes(typeof value)) return null;
    const raw = String(value).trim();
    if (!/^(?:0|[1-9][0-9]{0,5})(?:[.,][0-9]{1,2})?$/.test(raw)) return null;
    const number = Number(raw.replace(",","."));
    if (!Number.isFinite(number) || number <= 0 || number > 100000) return null;
    return number.toFixed(2);
  }
  function correctType(value, expected) {
    const types = Array.isArray(value?.["@type"]) ? value["@type"] : [value?.["@type"]];
    return types.some(x => typeof x === "string" &&
      x.split("/").pop().toLowerCase() === expected.toLowerCase());
  }
  const found=[];
  function visit(obj, depth=0) {
    if (depth > 8 || found.length > 3) return;
    if (Array.isArray(obj)) {
      for (const node of obj.slice(0,40)) visit(node,depth+1);
    } else if (obj && typeof obj === "object") {
      if (correctType(obj,"Product")) found.push(obj);
      if (obj["@graph"]) visit(obj["@graph"],depth+1);
      if (obj.mainEntity) visit(obj.mainEntity,depth+1);
    }
  }
  for (const script of Array.from(document.querySelectorAll(
       'script[type="application/ld+json"]')).slice(0,25)) {
    if (typeof script.textContent !== "string" || script.textContent.length > 150000) continue;
    try { visit(JSON.parse(script.textContent)); } catch (_) {}
  }
  if (found.length !== 1) return {error:"NO_STRUCTURED_PRODUCT"};
  const product=found[0];
  const offer=Array.isArray(product.offers)
    ? (product.offers.length===1 ? product.offers[0] : null) : product.offers;
  if (!correctType(offer,"Offer")) return {error:"NO_STRUCTURED_PRODUCT"};
  const title=plain(product.name);
  const direct=priceValue(offer.price);
  const specs=Array.isArray(offer.priceSpecification)
    ? offer.priceSpecification.slice(0,20)
    : (offer.priceSpecification ? [offer.priceSpecification] : []);
  const sale=[];
  const untyped=[];
  for (const spec of specs) {
    if (!spec || typeof spec!=="object") continue;
    const value=priceValue(spec.price);
    const currency=spec.priceCurrency || offer.priceCurrency;
    if (!value || !["PLN","EUR","USD"].includes(currency)) continue;
    const kind=String(spec.priceType || "").split("/").pop().toLowerCase();
    if (kind==="saleprice") sale.push([value,currency]);
    else if (!kind) untyped.push([value,currency]);
    // Deliberately never treat ListPrice or crossed-out reference price
    // as the current offer price.
  }
  function unique(values) {
    const different=new Set(values.map(v=>JSON.stringify(v)));
    return different.size===1 ? values[0] : null;
  }
  if (new Set(sale.map(v=>JSON.stringify(v))).size>1 ||
      new Set(untyped.map(v=>JSON.stringify(v))).size>1) {
    return {error:"NO_STRUCTURED_PRODUCT"};
  }
  const selectedSale=unique(sale);
  const selectedUntyped=unique(untyped);
  let selected=null;
  let priceOrigin="DIRECT_OFFER_PRICE";
  if (direct && ["PLN","EUR","USD"].includes(offer.priceCurrency)) {
    selected=[direct,offer.priceCurrency];
    if (selectedSale && JSON.stringify(selectedSale)!==JSON.stringify(selected)) {
      return {error:"NO_STRUCTURED_PRODUCT"};
    }
  } else {
    selected=selectedSale || selectedUntyped;
    priceOrigin=selectedSale ? "EXPLICIT_SALE_PRICE_SPECIFICATION"
                            : "UNTYPED_PRICE_SPECIFICATION";
  }
  const price=selected?.[0];
  const currency=selected?.[1];
  if (!title || !price || !currency) {
    return {error:"NO_STRUCTURED_PRODUCT"};
  }
  const projection={"@type":"Product","name":title,"offers":{
    "@type":"Offer","price":price,"priceCurrency":currency
  }};
  for (const key of ["model","sku","gtin","gtin8","gtin12","gtin13","gtin14"]) {
    const value=plain(product[key],70);
    if (value) projection[key]=value;
  }
  const brand=typeof product.brand==="object"
    ? plain(product.brand?.name,120) : plain(product.brand,120);
  if (brand) projection.brand={"name":brand};
  for (const key of ["availability","itemCondition"]) {
    const value=plain(offer[key],100);
    if (value) projection.offers[key]=value;
  }
  const seller=typeof offer.seller==="object"
    ? plain(offer.seller?.name,150) : plain(offer.seller,150);
  if (seller) projection.offers.seller={"name":seller};

  return {
    url, captured_at: new Date().toISOString(), snapshot: projection,
    price_origin: priceOrigin
  };
}
