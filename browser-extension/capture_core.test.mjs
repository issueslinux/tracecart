import assert from "node:assert/strict";
import test from "node:test";
import {traceCartCapturePage} from "./capture_core.mjs";

const allegro = "https://allegro.pl/oferta/kompresor-stanley-air-kit-18637535530";

function mockPage(products = [], selected = "", title = "STANLEY AIR KIT OL195") {
  const nodes = products.map(p => ({textContent: JSON.stringify(p)}));
  globalThis.location = {href:allegro};
  globalThis.document = {title, querySelectorAll: selector => (
    selector === 'script[type="application/ld+json"]' ? nodes : [])};
  globalThis.getSelection = () => ({toString:() => selected});
}

function product(price="229.00") {
  return {"@context":"https://schema.org", "@type":"Product",
    name:"STANLEY AIR KIT OL195", gtin13:"8016738753899",
    offers:{"@type":"Offer", price, priceCurrency:"PLN",
      priceSpecification:{"@type":"UnitPriceSpecification",
        price:"265.00", priceCurrency:"PLN",priceType:"ListPrice"}}};
}

test("a unique current Product Offer price is not list/reference price", () => {
  mockPage([product()]);
  const result = traceCartCapturePage();
  assert.equal(result.price, "229.00");
  assert.equal(result.gtin_claim, "8016738753899");
  assert.equal(result.price_evidence, "UNIQUE_PRODUCT_JSONLD");
  assert.equal(result.method, "ACTIVE_TAB_SINGLE_PRODUCT_JSONLD");
  assert.equal(result.url, allegro);
});

test("explicitly selected visible price beats possibly stale JSON-LD", () => {
  mockPage([product()], "199,99 zł");
  const result = traceCartCapturePage();
  assert.equal(result.price, "199.99");
  assert.equal(result.method, "USER_SELECTED_VISIBLE_PRICE");
  assert.equal(result.gtin_claim, null);
});

test("selected price supports Polish grouped thousands", () => {
  mockPage([], "1 299,00 zł");
  const result = traceCartCapturePage();
  assert.equal(result.price, "1299.00");
  assert.equal(result.currency, "PLN");
});

test("multiple products are not mistaken for a unique seller offer", () => {
  mockPage([product("229.00"), product("299.00")]);
  assert.ok(traceCartCapturePage().error);
});

test("search text with several prices cannot become a product price", () => {
  mockPage([], "229 zł – 265 zł");
  assert.ok(traceCartCapturePage().error);
});

test("aggregate lowPrice is not individual offer price", () => {
  const offer=product();
  offer.offers={"@type":"AggregateOffer",lowPrice:"9.99",priceCurrency:"PLN"};
  mockPage([offer]);
  assert.ok(traceCartCapturePage().error);
});

test("user must be on https product page", () => {
  mockPage([], "229,00 zł");
  globalThis.location.href = "http://localhost:8000/test";
  assert.ok(traceCartCapturePage().error);
});

test("unparseable schema snippets do not cause invented price", () => {
  mockPage([]);
  globalThis.document.querySelectorAll = () => [{textContent:"{not-json"}];
  assert.ok(traceCartCapturePage().error);
});
