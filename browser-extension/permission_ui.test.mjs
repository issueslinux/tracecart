import assert from "node:assert/strict";
import test from "node:test";
import {merchantOrigin,permissionStatus,requestMerchantPermission,
        revokeMerchantPermission} from "./permission_ui.mjs";

test("accept only explicit public https merchant origin",()=>{
  assert.equal(merchantOrigin("https://www.adafruit.com/product/1083"),
               "https://www.adafruit.com");
  assert.equal(merchantOrigin("https://shop.example.org/product?id=23"),
               "https://shop.example.org");
  for (const rejected of [
    "http://shop.example.org/product", "file:///etc/passwd",
    "https://127.0.0.1:443/item", "https://127.0.0.1/item",
    "https://localhost/item", "https://shop.local/item",
    "https://shop.example.org:8443/p",
    "https://private:secret@shop.example.org/p",
    "https://shop.internal/p", "https://foo.example/p",
    "https://[::1]/p", "https://shop..example.org/p", "invalid"
  ]) {
    assert.equal(merchantOrigin(rejected),null,rejected);
  }
});

test("request status and explicit removal of optional site permission",async()=>{
  const origins=[];
  let allowed=false, prompts=0, deletes=0;
  const api={
    contains:async ({origins:patterns})=>{
      origins.push(...patterns);return allowed;
    },
    request:async ({origins:patterns})=>{
      prompts++;origins.push(...patterns);allowed=true;return true;
    },
    remove:async ({origins:patterns})=>{
      deletes++;origins.push(...patterns);allowed=false;return true;
    }
  };
  assert.equal((await permissionStatus(api,"https://www.adafruit.com/p")).status,
               "NOT_GRANTED");
  assert.equal((await requestMerchantPermission(api,"https://www.adafruit.com/p")).status,
               "GRANTED");
  assert.equal((await permissionStatus(api,"https://www.adafruit.com/p")).status,
               "GRANTED");
  assert.equal((await revokeMerchantPermission(api,"https://www.adafruit.com/p")).status,
               "NOT_GRANTED");
  assert.equal((await permissionStatus(api,"https://www.adafruit.com/p")).status,
               "NOT_GRANTED");
  assert.equal(prompts,1);
  assert.equal(deletes,1);
  assert.ok(origins.every(x=>x==="https://www.adafruit.com/*"));
});

test("declined grant and impossible remove do not invent status",async()=>{
  const api={request:async()=>false,remove:async()=>false,contains:async()=>true};
  assert.equal((await requestMerchantPermission(api,"https://shop.example.org/p")).status,
               "DECLINED");
  assert.equal((await revokeMerchantPermission(api,"https://shop.example.org/p")).status,
               "STILL_GRANTED");
});
