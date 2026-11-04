/* Runs only on the same-origin return page after PayPal Sandbox approval
   was independently verified server-side. No payment APIs are called here. */
(function(){
  "use strict";
  const match=location.pathname.match(/^\/cart\/sandbox\/([A-Za-z0-9_-]{20,50})$/);
  const token=new URL(location.href).searchParams.get("token");
  if(!match||!token||!window.opener||window.opener===window)return;
  try{
    window.opener.postMessage(
      {type:"tracecart:sandbox:return",quote_id:match[1]},
      location.origin);
    // A popup may be isolated by the payment provider; if closing is blocked,
    // the verified receipt remains visible in this same-origin page.
    window.setTimeout(()=>window.close(),700);
  }catch(_ignore){}
})();