import assert from "node:assert/strict";
import test from "node:test";
import {traceCartQueuedProductProjection} from "./queue_capture.mjs";

const url="https://store.example.org/item/sku-7";
function page(documents=[], visible="Product details", location=url) {
  globalThis.location={href:location};
  globalThis.document={
    title:"Example product",body:{innerText:visible},
    querySelectorAll:()=>documents.map(data=>({textContent:JSON.stringify(data)}))
  };
}
function product(amount="34.90") {
  return {"@type":"Product",name:"Example Item 7",
    brand:{name:"Sample Brand",extra:"not a product field"},
    model:"X7",sku:"X7-new",gtin13:"8712561344494",
    unrelated:"not a product field",
    offers:{"@type":"Offer",price:amount,priceCurrency:"PLN",
      itemCondition:"https://schema.org/NewCondition",
      seller:{name:"Sample Merchant",extra:"not an offer field"},
      priceSpecification:{price:"99.00",priceType:"ListPrice"}
    }};
}
test("structured Product/Offer is projected with a field whitelist",()=>{
  page([product()]);
  const output=traceCartQueuedProductProjection();
  assert.equal(output.url,url);
  assert.equal(output.snapshot.offers.price,"34.90");
  assert.equal(output.price_origin,"DIRECT_OFFER_PRICE");
  assert.equal(output.snapshot.brand.name,"Sample Brand");
  assert.equal(output.snapshot.offers.seller.name,"Sample Merchant");
  assert.equal(output.snapshot.gtin13,"8712561344494");
  assert.equal(output.snapshot.model,"X7");
  const serialized=JSON.stringify(output);
  for (const notIncluded of ["unrelated","not a product field","99.00",
    "priceSpecification","extra"]) {
    assert.equal(serialized.includes(notIncluded),false);
  }
});
test("one graph product with an unrelated organization is accepted",()=>{
  page([{"@graph":[{"@type":"Organization",name:"Vendor"},product("47,50")]}]);
  assert.equal(traceCartQueuedProductProjection().snapshot.offers.price,"47.50");
});
test("multiple Product objects are ambiguous",()=>{
  page([product(),product("11.00")]);
  assert.equal(traceCartQueuedProductProjection().error,"MULTIPLE_PRODUCTS_AMBIGUOUS");
});
test("multiple offers are ambiguous",()=>{
  const entry=product();
  entry.offers=[entry.offers,{...entry.offers,price:"1.00"}];
  page([entry]);
  assert.equal(traceCartQueuedProductProjection().error,"NO_STRUCTURED_PRODUCT");
});
test("aggregate offer and invalid value are rejected",()=>{
  const entry=product();
  entry.offers["@type"]="AggregateOffer";
  page([entry]);
  assert.equal(traceCartQueuedProductProjection().error,"NO_STRUCTURED_PRODUCT");
  page([product("1 499,00")]);
  assert.equal(traceCartQueuedProductProjection().error,"NO_STRUCTURED_PRODUCT");
});
test("challenge content is reported without claiming product data",()=>{
  page([product()],"Please enable JS and disable any ad blocker");
  assert.deepEqual(traceCartQueuedProductProjection(),{error:"ACCESS_CHALLENGE"});
});
test("non HTTPS page and missing Product are rejected",()=>{
  page([product()],"", "http://store.example.org/item");
  assert.equal(traceCartQueuedProductProjection().error,"BROWSER_ERROR");
  page([]);
  assert.equal(traceCartQueuedProductProjection().error,"NO_STRUCTURED_PRODUCT");
});


test("sale specification accepted; list price alone never considered current",()=>{
  const entry=product();
  delete entry.offers.price;
  entry.offers.priceSpecification=[
    {price:"119.00",priceCurrency:"PLN",priceType:"https://schema.org/SalePrice"},
    {price:"199.00",priceCurrency:"PLN",priceType:"https://schema.org/ListPrice"}
  ];
  page([entry]);
  const selected=traceCartQueuedProductProjection();
  assert.equal(selected.snapshot.offers.price,"119.00");
  assert.equal(selected.price_origin,"EXPLICIT_SALE_PRICE_SPECIFICATION");
  entry.offers.priceSpecification=entry.offers.priceSpecification.slice(1);
  page([entry]);
  assert.equal(traceCartQueuedProductProjection().error,"NO_STRUCTURED_PRODUCT");
});
test("contradictory current direct and sale prices fail closed",()=>{
  const entry=product();
  entry.offers.priceSpecification={
    price:"29.00",priceCurrency:"PLN",priceType:"https://schema.org/SalePrice"
  };
  page([entry]);
  assert.equal(traceCartQueuedProductProjection().error,"NO_STRUCTURED_PRODUCT");
});

test("generic visible code promotion is captured separately from standard offer price",()=>{
  page([product("3499.99")]);
  const original=globalThis.document.querySelectorAll;
  globalThis.document.querySelectorAll=selector=>
    selector.startsWith('script[') ? original(selector) :
    selector==='main [class*="price"]'
      ? [{innerText:"Cena standardowa 3 499,99 zł. 2\u202f799,00 zł z kodem BW1610-0112 do 01.12.2026"}] : [];
  const result=traceCartQueuedProductProjection();
  assert.equal(result.snapshot.offers.price,"3499.99");
  assert.deepEqual(result.promotion,{
    price:"2799.00",currency:"PLN",code:"BW1610-0112",
    valid_until:"2026-12-01",source:"VISIBLE_PRODUCT_PRICE_WITH_CODE"
  });
});

test("separately rendered cents in discount widget are normalized",()=>{
  page([product("3499.99")]);
  const scripts=globalThis.document.querySelectorAll;
  globalThis.document.querySelectorAll=selector=>
    selector.startsWith('script[') ? scripts(selector) :
    selector==='main [class*="price"]'
      ? [{innerText:"2 799 00 zł z kodem BW1610-0112"}] : [];
  const result=traceCartQueuedProductProjection();
  assert.equal(result.promotion.price,"2799.00");
  assert.equal(result.promotion.code,"BW1610-0112");
});

test("coupon-shaped text without nearby product price is not fabricated",()=>{
  page([product("3499.99")]);
  const original=globalThis.document.querySelectorAll;
  globalThis.document.querySelectorAll=selector=>
    selector.startsWith('script[') ? original(selector) :
    selector==='main [class*="promo"]'
      ? [{innerText:"Z kodem SAVE2026 na akcesoria, oferta nie dotyczy tego produktu"}] : [];
  assert.equal(traceCartQueuedProductProjection().promotion,undefined);
});

test("unrelated hidden or ambiguous promotion widgets cannot become sale price",()=>{
  page([product("3499.99")]);
  const original=globalThis.document.querySelectorAll;
  const a={innerText:"2 799,00 zł z kodem BW1610-0112",getClientRects:()=>[]};
  const b={innerText:"1 799,00 zł z kodem SAVE2026",getClientRects:()=>[{x:0}]};
  globalThis.document.querySelectorAll=selector=>
    selector.startsWith('script[') ? original(selector) :
    selector==='main [class*="price"]' ? [a,b] : [];
  const result=traceCartQueuedProductProjection();
  assert.equal(result.promotion.price,"1799.00");
  globalThis.document.querySelectorAll=selector=>
    selector.startsWith('script[') ? original(selector) :
    selector==='main [class*="price"]'
      ? [{...b,innerText:"2 799,00 zł z kodem BW1610-0112"},b] : [];
  assert.equal(traceCartQueuedProductProjection().promotion,undefined);
});

test("visible DOM text near conditional checkout price is found without standard price CSS classes",()=>{
  page([product("3499.99")]);
  const phrase="Taniej o 700,99 zł Cena z kodem: BW1610-0112 2\u202f799 00 zł Cena z kodem obowiązuje do 01.12.2026 r. 3 499,99 zł Cena przed kodem";
  const candidate={
    innerText:phrase,textContent:phrase,
    getClientRects:()=>[{width:250}],
    closest:()=>null,parentElement:null
  };
  const node={nodeValue:"Cena z kodem:",parentElement:candidate};
  let used=false;
  globalThis.document.querySelector=selector=>
    selector==="main"?{tagName:"MAIN"}:null;
  globalThis.document.createTreeWalker=()=>({
    nextNode:()=>used?null:(used=true,node)
  });
  const result=traceCartQueuedProductProjection();
  assert.equal(result.snapshot.offers.price,"3499.99");
  assert.deepEqual(result.promotion,{
    price:"2799.00",currency:"PLN",code:"BW1610-0112",
    valid_until:"2026-12-01",source:"VISIBLE_PRODUCT_PRICE_WITH_CODE"
  });
});

test("a saving amount ahead of a code must not become product price",()=>{
  page([product("3499.99")]);
  const phrase="Taniej o 700,99 zł. Cena z kodem: BW1610-0112 2 799 00 zł";
  const candidate={innerText:phrase,getClientRects:()=>[{}],closest:()=>null};
  const node={nodeValue:"Cena z kodem:",parentElement:candidate};
  let used=false;
  globalThis.document.createTreeWalker=()=>({
    nextNode:()=>used?null:(used=true,node)
  });
  const result=traceCartQueuedProductProjection();
  assert.equal(result.promotion?.price,"2799.00");
});
