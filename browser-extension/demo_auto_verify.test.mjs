import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../assets/demo-autoverify.js',import.meta.url),'utf8');

function setup({response={ok:true,text:async()=>'<h2>Order accepted in simulation</h2>'},hasForm=true}={}){
  const calls=[],timers=[],reloaded=[];
  const form={action:'http://127.0.0.1:8810/demo/order/test-123/verify',parentElement:{insertBefore(){}}};
  const context={
    URLSearchParams,FormData:class{constructor(){return [['csrf','test-csrf']]}} ,
    document:{querySelector(){return hasForm?form:null},
      createElement(){return {setAttribute(){},textContent:''}}},
    window:{location:{reload(){reloaded.push(true)}},setTimeout(fn,ms){timers.push({fn,ms})}},
    fetch:async(url,args)=>{calls.push({url,args});return response;}
  };
  vm.runInNewContext(source,context);
  return {calls,timers,reloaded};
}

test('approval verification polls read-only verification endpoint and reloads only after actual simulated acceptance',async()=>{
  const s=setup();
  assert.equal(s.timers.length,1);
  assert.equal(s.timers[0].ms,12000);
  await s.timers[0].fn();
  assert.equal(s.calls.length,1);
  assert.match(s.calls[0].url,/\/verify$/);
  assert.equal(s.calls[0].args.method,'POST');
  assert.equal(s.calls[0].args.body.get('csrf'),'test-csrf');
  assert.equal(s.reloaded.length,1);
  assert.equal(s.timers.length,1);
});

test('non-approved order schedules bounded read-only recheck, never PayPal create/capture',async()=>{
  const s=setup({response:{ok:true,text:async()=>'<p>Awaiting PayPal approval</p>'}});
  await s.timers[0].fn();
  assert.equal(s.reloaded.length,0);
  assert.equal(s.timers.length,2);
  assert.equal(s.timers[1].ms,12000);
  assert.ok(s.calls.every(c=>/\/verify$/.test(c.url)));
});

test('script does nothing without sandbox order verification form',()=>{
  const s=setup({hasForm:false});
  assert.equal(s.timers.length,0);
  assert.equal(s.calls.length,0);
});
