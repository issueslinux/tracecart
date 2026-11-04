"use strict";
/* Non-financial, read-only PayPal Sandbox order-status polling.
 * Invokes ONLY the CSRF-protected verification route (PayPal Orders GET).
 * It does not create, retry or capture PayPal transactions. Stops after
 * a bounded number of checks or any error; manual verification remains.
 */
(function(){
  const form=document.querySelector('form[action$="/verify"]');
  if(!form)return;
  const status=document.createElement('p');
  status.setAttribute('role','status');
  status.textContent='Waiting for PayPal Sandbox buyer approval; status checks are automatic.';
  form.parentElement.insertBefore(status,form);
  let attempts=0,finished=false;
  async function inspect(){
    if(finished||attempts>=15)return;
    attempts+=1;
    try{
      const result=await fetch(form.action,{
        method:'POST',
        headers:{'Content-Type':'application/x-www-form-urlencoded'},
        body:new URLSearchParams(new FormData(form)),
        credentials:'same-origin',redirect:'follow',cache:'no-store'
      });
      if(!result.ok){
        finished=true;
        status.textContent='Sandbox order-status check unavailable. Manual verification is still possible.';
        return;
      }
      const html=await result.text();
      if(html.includes('Order accepted in simulation')){
        finished=true;
        window.location.reload();
      }else if(attempts<15){
        window.setTimeout(inspect,12000);
      }else{
        status.textContent='Automatic checking ended. You can verify again manually.';
      }
    }catch(_){
      finished=true;
      status.textContent='Order-status check failed. No payment was initiated.';
    }
  }
  window.setTimeout(inspect,12000);
})();
