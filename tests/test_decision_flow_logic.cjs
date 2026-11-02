"use strict";
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const browserCode=require('../assets/decision-flow.js');
const raw=JSON.parse(fs.readFileSync(path.resolve(__dirname,
 '../examples/live_lenovo_ideapad_decision_projection_2026-11-02.json'),'utf8'));
const flow=()=>JSON.parse(JSON.stringify(raw));

test('historical job has real Google Shopping evidence despite zero OPF catalog',()=>{
 const data=flow();
 assert.equal(data.evidence.catalog_only,0);
 assert.equal(data.evidence.google_shopping_cards,12);
 assert.equal(data.evidence.indexed_store_links,3);
 assert.equal(data.evidence.seller_confirmed_competitor_prices,0);
 assert.equal(data.evidence.selected_seller_price,null);
});

test('x86 compatibility changes candidate and cannot imply checkout verification',()=>{
 const state=browserCode.prioritize(flow(),{
   usage:'coding',priority:'balanced',compatibility:'x86',verification:'no'});
 assert.equal(state.outcome,'HOLD_FOR_PRICE_AND_SELLER_VERIFICATION');
 assert.ok(state.candidate);
 assert.equal(state.candidate.cpu_architecture,'x86');
 assert.notEqual(state.candidate.price,'124.95');
 assert.ok(state.notes.some(x=>x.includes('ARM')));
 assert.equal(state.payment_authorized,false);
 assert.equal(state.price_check_performed_by_tracecart,false);
});

test('accepting ARM may find Snapdragon offer but cannot turn indexed quote into fact',()=>{
 const outcome=browserCode.prioritize(flow(),{
   usage:'office',priority:'balanced',compatibility:'arm',verification:'yes'});
 assert.equal(outcome.candidate.cpu_architecture,'ARM');
 assert.equal(outcome.candidate.price,'2849.00');
 assert.equal(outcome.buyer_claimed_verification,true);
 assert.equal(outcome.price_check_performed_by_tracecart,false);
 assert.equal(outcome.payment_authorized,false);
 assert.equal(outcome.outcome,'CONDITIONAL_SHORTLIST_NOT_A_PURCHASE_AUTHORIZATION');
});

test('user prioritizing screen OLED must not receive machine with unknown panel',()=>{
 const outcome=browserCode.prioritize(flow(),{
   usage:'office',priority:'screen',compatibility:'arm',verification:'no'});
 assert.equal(outcome.outcome,'INSUFFICIENT_COMPARABLE_EVIDENCE');
 assert.equal(outcome.candidate,null);
 assert.equal(outcome.payment_authorized,false);
});

test('demanding GPU use case abstains without benchmark evidence',()=>{
 const outcome=browserCode.prioritize(flow(),{
   usage:'demanding',priority:'balanced',compatibility:'x86',verification:'yes'});
 assert.equal(outcome.outcome,'HOLD_FOR_PERFORMANCE_EVIDENCE');
 assert.ok(outcome.notes.some(x=>x.includes('GPU')));
 assert.equal(outcome.payment_authorized,false);
});

test('the anomalous 124.95 indexed price never becomes a price winner',()=>{
 for(const priority of ('price','balanced')) {
   const result=browserCode.prioritize(flow(),{
      usage:'office',priority,compatibility:'arm',verification:'no'});
   assert.ok(result.candidate);
   assert.notEqual(result.candidate.price,'124.95');
   assert.ok(Number(result.candidate.price)>1000);
 }
});

test('strict link policy rejects javascript and blocks private host; audit same-origin is allowed',()=>{
 assert.equal(browserCode.safeHref('javascript:alert(1)'),null);
 assert.equal(browserCode.safeHref('http://example.com/offer'),null);
 assert.equal(browserCode.safeHref('https://localhost:8888/'),null);
 assert.equal(browserCode.safeHref('https://127.0.0.1:8080/a'),null);
 assert.equal(browserCode.safeHref('/cart/status/w8MOeW8uE7pCqDYKf48-lXxy/audit'),
              '/cart/status/w8MOeW8uE7pCqDYKf48-lXxy/audit');
 assert.ok(browserCode.safeHref('https://allegro.pl/oferta/item'));
});

test('no candidate means abstention, no fabricated winner and no payment',()=>{
 const data=flow();
 data.candidates=[];
 const outcome=browserCode.prioritize(data,{priority:'price',verification:'yes'});
 assert.equal(outcome.candidate,null);
 assert.equal(outcome.outcome,'INSUFFICIENT_COMPARABLE_EVIDENCE');
 assert.equal(outcome.payment_authorized,false);
});

test('price formatting uses Polish locale and no null-to-zero sales pitch',()=>{
 assert.equal(browserCode.money(null,'PLN'),'Brak ceny'); // regression needed
 assert.equal(browserCode.money('2849','PLN'),'2849,00 PLN');
});
