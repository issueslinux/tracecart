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
    return types.some(x => {
      if (typeof x !== "string") return false;
      const normalized=x.replace(/\/$/,"").toLowerCase();
      return normalized===expected.toLowerCase() ||
        normalized==="https://schema.org/"+expected.toLowerCase() ||
        normalized==="http://schema.org/"+expected.toLowerCase();
    });
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
  /* DOM fallback is deliberately limited to standard schema.org product
     microdata or the MAIN WooCommerce single-product price widget.
     Never scan arbitrary text, shopping carts, recommendations, search results. */
  function one(nodes) {
    return nodes && nodes.length === 1 ? nodes[0] : null;
  }
  function microvalue(node) {
    if (!node) return null;
    return plain(node.getAttribute?.("content") || node.getAttribute?.("value") ||
                 node.textContent,180);
  }
  function domPrice(text) {
    const match=String(text || "").trim().match(
      /^([0-9][0-9 \u00a0\u202f]{0,10}(?:[.,][0-9]{1,2})?)\s*(zł|PLN|EUR|€|USD|\$)$/i);
    if (!match) return null;
    const value=priceValue(match[1].replace(/[ \u00a0\u202f]/g,""));
    const unit=match[2].toUpperCase();
    const currency=(unit==="ZŁ" || unit==="PLN") ? "PLN"
      : (unit==="€" || unit==="EUR") ? "EUR" : "USD";
    return value ? [value,currency] : null;
  }
  function domProductOffer() {
    const productNodes=Array.from(document.querySelectorAll(
      '[itemscope][itemtype]')).filter(node=>
        ["https://schema.org/product","http://schema.org/product"].includes(
          String(node.getAttribute?.("itemtype") || "").replace(/\/$/,"").toLowerCase()));
    if (productNodes.length > 1) return {error:"MULTIPLE_PRODUCTS_AMBIGUOUS"};
    if (productNodes.length === 1) {
      const root=productNodes[0];
      const nestedOffers=Array.from(root.querySelectorAll(
        '[itemprop="offers"][itemscope][itemtype]')).filter(node=>
          ["https://schema.org/offer","http://schema.org/offer"].includes(
            String(node.getAttribute?.("itemtype") || "").replace(/\/$/,"").toLowerCase()));
      if (nestedOffers.length !== 1) return {error:"NO_STRUCTURED_PRODUCT"};
      const offer=nestedOffers[0];
      const title=microvalue(one(Array.from(root.querySelectorAll('[itemprop="name"]'))
        .filter(el=>!el.closest?.('[itemprop="offers"]'))));
      const price=priceValue(microvalue(one(offer.querySelectorAll('[itemprop="price"]'))));
      const currency=microvalue(one(offer.querySelectorAll('[itemprop="priceCurrency"]')));
      if (!title || !price || !["PLN","EUR","USD"].includes(currency)) {
        return {error:"NO_STRUCTURED_PRODUCT"};
      }
      const projection={"@type":"Product",name:title,
        offers:{"@type":"Offer",price,priceCurrency:currency}};
      const brand=microvalue(one(root.querySelectorAll('[itemprop="brand"]')));
      if (brand) projection.brand={name:brand};
      for (const key of ["model","sku","gtin","gtin8","gtin12","gtin13","gtin14"]) {
        const node=one(root.querySelectorAll('[itemprop="'+key+'"]'));
        const value=microvalue(node);
        if (value && value.length<=70) projection[key]=value;
      }
      const availability=microvalue(one(offer.querySelectorAll(
        '[itemprop="availability"]')));
      if (availability && availability.length<=100) {
        projection.offers.availability=availability;
      }
      const seller=microvalue(one(offer.querySelectorAll('[itemprop="seller"]')));
      if (seller && seller.length<=150) projection.offers.seller={name:seller};
      return {snapshot:projection,price_origin:"PRODUCT_OFFER_MICRODATA"};
    }

    // WooCommerce fallback requires explicit single-product context, one
    // product heading, one primary price container, and one current amount.
    if (!document.body?.classList?.contains("single-product")) return null;
    const heading=one(document.querySelectorAll('h1.product_title, h1.entry-title'));
    const title=plain(heading?.textContent);
    if (!title) return null;
    let blocks=document.querySelectorAll('.elementor-widget-woocommerce-product-price');
    if (blocks.length===0) blocks=document.querySelectorAll('.summary.entry-summary');
    const block=one(blocks);
    if (!block) return {error:"NO_STRUCTURED_PRODUCT"};
    const priceBlock=one(block.querySelectorAll('.price'));
    if (!priceBlock) return {error:"NO_STRUCTURED_PRODUCT"};
    const ins=Array.from(priceBlock.querySelectorAll('ins bdi'));
    const del=Array.from(priceBlock.querySelectorAll('del bdi'));
    let prices=[];
    if (ins.length) {
      prices=ins.map(node=>domPrice(node.textContent));
    } else {
      const current=Array.from(priceBlock.querySelectorAll('bdi'))
        .filter(el=>!el.closest?.('del'));
      prices=current.length ? current.map(node=>domPrice(node.textContent))
        : (!del.length ? [domPrice(priceBlock.textContent)] : []);
    }
    if (prices.length!==1 || !prices[0]) return {error:"NO_STRUCTURED_PRODUCT"};
    const [price,currency]=prices[0];
    return {snapshot:{"@type":"Product",name:title,
      offers:{"@type":"Offer",price,priceCurrency:currency}},
      price_origin:"WOOCOMMERCE_PRIMARY_PRICE"};
  }

  // A coupon is separate from the schema.org sale price. Inspect only
  // bounded, visible product-price/promotion widgets; never arbitrary body
  // text, recommendations, checkout controls, cookies or full-page HTML.
  function visibleCodePromotion(listedPrice, currency) {
    if (currency!=="PLN") return null;
    const selectors=[
      'main [class*="price"]','main [class*="promo"]',
      'main [class*="discount"]','main [data-testid*="price"]',
      '[class*="product-price"]','[class*="productPrice"]',
      '[class*="product-promo"]','[data-testid*="product-price"]'
    ];
    const elements=new Set();
    for (const selector of selectors) {
      for (const node of Array.from(document.querySelectorAll(selector)).slice(0,35)) {
        elements.add(node);
        if (elements.size>=85) break;
      }
    }
    // Modern stores often render the discount in dedicated components
    // with generated class names, not in conventional .price/.promo nodes.
    // Find visible *text nodes* saying "Cena z kodem" and inspect only their
    // small, local product-page ancestors; never ship or parse full page HTML.
    if (typeof document.createTreeWalker==="function") {
      const scopes=[
        typeof document.querySelector==="function"
          ? document.querySelector("main") : null,
        document.body
      ];
      const inspected=new Set();
      for (const scope of scopes) {
        if (!scope || inspected.has(scope)) continue;
        inspected.add(scope);
        const walker=document.createTreeWalker(
          scope,globalThis.NodeFilter?.SHOW_TEXT || 4);
        let node,seen=0,anchors=0;
        while ((node=walker.nextNode()) && seen++<9000 && anchors<18) {
          const value=String(node.nodeValue || "");
          if (!/(?:cena\s+z\s+kodem|z\s+kodem\s+rabatowym)/i.test(value)) continue;
          anchors++;
          let parent=node.parentElement;
          for (let depth=0;parent && depth<7;depth++,parent=parent.parentElement) {
            if (parent.closest?.("footer,header,nav,aside,[aria-hidden=true]")) break;
            if (typeof parent.getClientRects==="function" &&
                !parent.getClientRects().length) break;
            const txt=String(parent.innerText ?? parent.textContent ?? "");
            if (txt.length>1100) break;
            if (/\b[A-Z0-9][A-Z0-9_-]{3,29}\b/.test(txt) &&
                /(?:zł|PLN)/i.test(txt) && /cena\s+z\s+kodem/i.test(txt)) {
              elements.add(parent);
              break;
            }
          }
        }
      }
    }
    const matches=[];
    for (const element of elements) {
      if (element.closest?.('footer,header,nav,aside,[aria-hidden="true"]')) continue;
      if (typeof element.getClientRects==="function" &&
          element.getClientRects().length===0) continue;
      const raw=String(element.innerText ?? element.textContent ?? "");
      if (!raw || raw.length>1100) continue;
      const text=raw.replace(/[  \s]+/g," ").trim();
      // Must explicitly state the code and the discounted amount nearby.
      const codes=Array.from(text.matchAll(
        /(?:cena\s+z\s+kodem|z\s+kodem(?:\s+rabatowym)?|kod\s+rabatowy|kod\s+promocyjny)\s*:?\s*([A-Z0-9][A-Z0-9_-]{3,29})(?=\s|$|[.,;:])/gi));
      if (codes.length!==1) continue;
      const code=codes[0][1].toUpperCase();
      if (!/[A-Z]/.test(code) || !/[0-9]/.test(code)) continue;
      const prices=Array.from(text.matchAll(
        /\b((?:[0-9]{1,3}(?: [0-9]{3})+(?: [0-9]{2})?|[0-9]{2,6})(?:[,.][0-9]{2})?)\s*(?:zł|PLN)(?=\s|$|[.,;])/gi));
      function codeAdjacentPrice(raw) {
        // Retailers sometimes render grosze in a separate raised <sup>
        // resulting in "2 799 00 zł" instead of "2 799,00 zł".
        if (/^[0-9]{1,3}(?: [0-9]{3})+ [0-9]{2}$/.test(raw)) {
          const tokens=raw.split(" ");
          const cents=tokens.pop();
          return priceValue(tokens.join("")+"."+cents);
        }
        return priceValue(raw.replace(/ /g,""));
      }
      const codeEnd=(codes[0].index||0)+codes[0][0].length;
      // Prefer the amount *after* the coupon code. An earlier "Taniej o
      // 700,99 zł" is the saving, not the 2 799,00 zł product price.
      const follows=prices.filter(p=>(p.index||0)>=codeEnd &&
         (p.index||0)-codeEnd<115);
      const candidates=follows.length?follows:prices.filter(p=>
         Math.abs((p.index||0)-(codes[0].index||0))<95);
      const near=candidates.filter(p=>
          !/(?:rata|raty|miesi[eę]cznie|taniej\s+o)/i.test(
             text.slice(Math.max(0,(p.index||0)-20),(p.index||0))))
        .map(p=>codeAdjacentPrice(p[1]))
        .filter(p=>p!==null && Number(p)<Number(listedPrice));
      const different=[...new Set(near)];
      if (different.length!==1) continue;
      const valid=text.match(/(?:ważn[yae]?\s+do|promocja\s+do|do)\s+(\d{1,2})[.](\d{1,2})[.](20\d{2})/i);
      let validUntil=null;
      if (valid) {
        const iso=valid[3]+"-"+valid[2].padStart(2,"0")+"-"+valid[1].padStart(2,"0");
        if (!Number.isNaN(Date.parse(iso+"T00:00:00Z"))) validUntil=iso;
      }
      matches.push({price:different[0],currency,code,valid_until:validUntil,
                    source:"VISIBLE_PRODUCT_PRICE_WITH_CODE"});
    }
    // Two distinct promotions visible concurrently are ambiguous. Identical
    // DOM parent/child copies of the same coupon are safe to deduplicate.
    const ids=[...new Set(matches.map(x=>x.price+"|"+x.currency+"|"+x.code))];
    const dates=[...new Set(matches.map(x=>x.valid_until).filter(Boolean))];
    if (ids.length!==1 || dates.length>1) return null;
    const candidate=matches[0];
    candidate.valid_until=dates[0] || null;
    return candidate;
  }
  const dom=domProductOffer();
  if (found.length > 1) return {error:"MULTIPLE_PRODUCTS_AMBIGUOUS"};
  if (found.length === 0) {
    if (!dom) return {error:"NO_STRUCTURED_PRODUCT"};
    if (dom.error) return dom;
    const result={url,captured_at:new Date().toISOString(),...dom};
    const offer=dom.snapshot?.offers;
    const promo=visibleCodePromotion(offer?.price,offer?.priceCurrency);
    if (promo) result.promotion=promo;
    return result;
  }
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
  if (dom && dom.error==="MULTIPLE_PRODUCTS_AMBIGUOUS") {
    return {error:"MULTIPLE_PRODUCTS_AMBIGUOUS"};
  }
  if (dom?.snapshot) {
    const a=dom.snapshot;
    if (a.name.trim().toLowerCase() !== title.trim().toLowerCase()) {
      return {error:"CONFLICTING_PRODUCT_IDENTITY"};
    }
    if (a.offers.price!==price || a.offers.priceCurrency!==currency) {
      return {error:"CONFLICTING_OFFER_EVIDENCE"};
    }
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

  const result={
    url, captured_at: new Date().toISOString(), snapshot: projection,
    price_origin: priceOrigin
  };
  const promo=visibleCodePromotion(price,currency);
  if (promo) result.promotion=promo;
  return result;
}
