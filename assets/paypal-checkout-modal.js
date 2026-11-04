/* TraceCart: browser-owned PayPal SANDBOX checkout overlay.
   Never choose the value, gateway, payee or state client-side.
   The server owns quotes and verifies Sandbox order status read-only. */
(function(){
  "use strict";
  const app=document.getElementById("decision-app");
  const modal=document.getElementById("tc-paypal-modal");
  if(!app||!modal||typeof modal.showModal!=="function")return;
  const $=id=>document.getElementById(id);
  const product=$("tc-paypal-product"),amount=$("tc-paypal-amount");
  const status=$("tc-paypal-status"),content=$("tc-paypal-content");
  const error=$("tc-paypal-error"),fallback=$("tc-paypal-fallback");
  const steps=[...$("tc-paypal-steps").querySelectorAll("li")];
  let quote=null,offerId=null,popup=null,pollTimer=null,pollBusy=false;
  let pollCount=0,creating=false,opening=false,generation=0;
  let paymentOpened=false;
  let openerButton=null;

  function node(tag,className,text){
    const n=document.createElement(tag);
    if(className)n.className=className;
    if(text!==undefined)n.textContent=String(text);
    return n;
  }
  function action(text,handler,kind="primary"){
    const b=node("button","tc-paypal-button tc-paypal-"+kind,text);
    b.type="button";b.addEventListener("click",handler);
    return b;
  }
  function stopPoll(){
    if(pollTimer!==null){clearInterval(pollTimer);pollTimer=null;}
    pollBusy=false;pollCount=0;
  }
  function saveQuote(){
    if(!quote||!offerId)return;
    try{
      sessionStorage.setItem("tc:paypal:"+app.dataset.sandboxAction+":"+offerId,quote.id);
    }catch(_ignore){}
  }
  function rememberedId(id){
    try{return sessionStorage.getItem("tc:paypal:"+app.dataset.sandboxAction+":"+id);}
    catch(_ignore){return null;}
  }
  function forgetId(id){
    try{sessionStorage.removeItem("tc:paypal:"+app.dataset.sandboxAction+":"+id);}
    catch(_ignore){}
  }
  function warning(message){
    error.hidden=false;
    error.textContent=message;
  }
  function clearWarning(){error.hidden=true;error.textContent="";}
  async function request(path,fields){
    const options={
      method:fields?"POST":"GET",
      cache:"no-store",
      credentials:"same-origin",
      headers:{"Accept":"application/json"},
    };
    if(fields){
      options.headers["Content-Type"]="application/x-www-form-urlencoded";
      options.body=new URLSearchParams({csrf:app.dataset.csrf,...fields}).toString();
    }
    const response=await fetch(path,options);
    let data;
    try{data=await response.json();}
    catch(_ignore){throw Error("TraceCart returned an unreadable response.");}
    if(!response.ok){
      const ex=Error("The server could not complete the request.");
      ex.code=data.error||"SERVER_ERROR";
      ex.quote=data.quote||null;
      throw ex;
    }
    if(!data.quote||typeof data.quote.id!=="string"){
      throw Error("Missing the server-validated Sandbox quote.");
    }
    return data.quote;
  }
  function quotePath(){return "/cart/sandbox/"+encodeURIComponent(quote.id);}
  function progress(state){
    const current=state==="LOADING"?1:
      state==="QUOTED"||state==="APPROVED"||state==="CREATE_UNCERTAIN"?2:
      state==="PAYER_ACTION_REQUIRED"?3:4;
    steps.forEach((li,i)=>{
      const step=i+1;
      li.classList.toggle("tc-is-current",step===current);
      li.classList.toggle("tc-is-complete",step<current||
        (state==="VERIFIED_APPROVED"&&step===4));
      if(step===current)li.setAttribute("aria-current","step");
      else li.removeAttribute("aria-current");
    });
  }
  function loading(label){
    progress("LOADING");
    status.className="tc-paypal-status tc-status-busy";
    status.textContent=label;
    content.replaceChildren(node("div","tc-paypal-wait",
      "Reading the selected product and price from saved evidence."));
  }
  function setStatus(label,kind="normal"){
    status.className="tc-paypal-status tc-status-"+kind;
    status.textContent=label;
  }
  function updateVerifiedCard(){
    if(!quote||quote.state!=="VERIFIED_APPROVED")return;
    app.querySelectorAll(".purchase-option").forEach(card=>{
      if(card.dataset.offerId!==quote.offer_id)return;
      card.classList.add("tc-paypal-verified-card");
      const button=card.querySelector(".tc-paypal-open");
      if(button)button.textContent="✓ PayPal approved";
    });
  }
  function paymentLink(){
    if(!quote||!quote.approval_url||!quote.paypal_order_id)return null;
    try{
      const u=new URL(quote.approval_url);
      if(u.origin!=="https://www.sandbox.paypal.com"||
         u.pathname!=="/checkoutnow"||
         u.searchParams.get("token")!==quote.paypal_order_id)return null;
      return u.href;
    }catch(_ignore){return null;}
  }
  function explain(ex){
    const codes={
      CONSENT_OR_AMOUNT_MISMATCH:"The amount or consent text did not match this quote.",
      QUOTE_EXPIRED:"This quote expired. Select the product again.",
      SANDBOX_CONSENT_EXPIRED:"The quote expired before the Sandbox order started.",
      SANDBOX_ORDER_ALREADY_STARTED_OR_NOT_APPROVED:
        "An order was already started. TraceCart will not create another.",
      QUOTE_NOT_AWAITING_APPROVAL:"This quote is no longer awaiting approval.",
      SANDBOX_REQUEST_UNAVAILABLE:
        "The request's outcome is uncertain. No automatic payment retry is allowed.",
      SANDBOX_REQUEST_REJECTED:"The server rejected the Sandbox checkout request.",
      SANDBOX_STATUS_UNAVAILABLE:
        "PayPal status is temporarily unavailable. No new order was created.",
      UNKNOWN_SANDBOX_QUOTE:"The saved quote could not be found.",
    };
    return codes[ex.code]||ex.message||"Checkout could not be completed.";
  }
  function render(){
    if(!quote)return;
    const state=quote.state;
    progress(state);
    product.textContent=quote.title||"Selected product";
    amount.textContent=quote.amount+" "+quote.currency;
    content.replaceChildren();
    fallback.hidden=false;
    fallback.href=quotePath();
    if(state==="QUOTED"){
      setStatus("Step 2 of 4 · Previous quote awaiting manual review","alert");
      content.append(
        node("h3","","This quote was created by the previous checkout flow"),
        node("p","tc-paypal-instruction",
          "The updated one-click checkout uses the amount stored on the server. "+
          "Select the product again to begin a new Sandbox-only checkout."),
        action("Restart one-click checkout",()=>{
          forgetId(offerId);
          modal.close();
          window.setTimeout(()=>openerButton&&openerButton.click(),0);
        },"secondary"));
      return;
    }
    if(state==="APPROVED"){
      setStatus("Step 2 of 4 · Preparing your PayPal Sandbox order","busy");
      content.replaceChildren(node("div","tc-paypal-wait",
        "Your selected offer and amount are locked. "+
        "Opening the PayPal Sandbox checkout without any extra confirmation."));
      return;
    }
    if(state==="PAYER_ACTION_REQUIRED"){
      setStatus("Step 3 of 4 · Waiting for PayPal approval","busy");
      const wait=node("div","tc-paypal-pending");
      wait.appendChild(node("div","tc-paypal-pulse","●"));
      wait.appendChild(node("h3","","Waiting for PayPal confirmation…"));
      wait.appendChild(node("p","",
        "Approve the test order in the secure PayPal Sandbox window. "+
        "TraceCart checks this order using read-only requests."));
      const ref=node("p","tc-paypal-order-ref",
        "Sandbox order: "+(quote.paypal_order_id||""));
      wait.appendChild(ref);
      const controls=node("div","tc-paypal-controls");
      const link=paymentLink();
      if(link){
        const a=node("a","tc-paypal-button tc-paypal-paypal-outline",
          "Open PayPal again ↗");
        a.href=link;a.rel="noopener noreferrer";a.target="_blank";
        controls.appendChild(a);
      }
      controls.appendChild(action("Check status now",()=>{
        refreshStatus(true);
      },"secondary"));
      wait.appendChild(controls);
      content.appendChild(wait);
      startPolling();
      return;
    }
    stopPoll();
    if(state==="VERIFIED_APPROVED"){
      setStatus("Step 4 of 4 · Sandbox approval verified","success");
      const box=node("section","tc-paypal-success");
      box.appendChild(node("div","tc-paypal-success-check","✓"));
      box.appendChild(node("h3","","PayPal approval verified"));
      box.appendChild(node("p","",
        "Status: APPROVED. The test order was verified by the server. "+
        "No real funds were captured and no retailer purchase occurred."));
      box.appendChild(node("p","tc-paypal-order-ref",
        "Order ID: "+(quote.paypal_order_id||"")));
      box.appendChild(action("Back to product recommendations",()=>modal.close()));
      content.appendChild(box);
      updateVerifiedCard();
      return;
    }
    setStatus("Order status uncertain · No payment retry","alert");
    const block=node("div","tc-paypal-uncertain");
    block.appendChild(node("h3","","No new order will be created"));
    block.appendChild(node("p","",
      "The order creation response is uncertain. Check the existing PayPal order; "+
      "do not submit another create request."));
    content.appendChild(block);
  }

  async function refreshStatus(verify){
    if(!quote||pollBusy||!modal.open)return;
    const localId=quote.id,round=generation;
    pollBusy=true;
    try{
      const value=await request(quotePath()+".json"+(verify?"?verify=1":""));
      if(round!==generation||!quote||quote.id!==localId)return;
      const was=quote.state;
      quote=value;saveQuote();
      if(value.state!==was){clearWarning();render();}
      else if(verify&&value.state==="PAYER_ACTION_REQUIRED")
        setStatus("Waiting for approval in PayPal Sandbox…","busy");
    }catch(ex){
      if(round!==generation)return;
      if(ex.quote){
        const changed=quote&&quote.state!==ex.quote.state;
        quote=ex.quote;
        if(changed)render();
      }
      if(verify&&pollCount%4===0)warning(explain(ex));
    }finally{pollBusy=false;}
  }
  function startPolling(){
    if(pollTimer!==null)return;
    pollCount=0;
    pollTimer=window.setInterval(()=>{
      if(!quote||quote.state!=="PAYER_ACTION_REQUIRED"||!modal.open){
        stopPoll();return;
      }
      pollCount++;
      if(pollCount>30){
        stopPoll();
        warning("Automatic polling paused after 2½ minutes. "+
          "You can check status manually without creating a new order.");
        return;
      }
      refreshStatus(true);
    },5000);
  }
  async function createPayPal(){
    if(creating||!quote||quote.state!=="APPROVED")return;
    const round=generation;
    creating=true;clearWarning();
    setStatus("Creating one PayPal Sandbox order…","busy");
    content.replaceChildren(node("div","tc-paypal-wait",
      "Only one Sandbox order is being created. Do not retry or refresh the page."));
    // The PayPal window was already opened synchronously by the
    // original Pay with PayPal click, before any asynchronous work.
    try{
      const value=await request(quotePath()+"/create",{});
      if(round!==generation)return;
      quote=value;saveQuote();render();
      const link=paymentLink();
      if(link&&popup&&!popup.closed){
        popup.location.assign(link);
        paymentOpened=true;
      }else if(popup&&!popup.closed)popup.close();
      if(!link)warning("The Sandbox order may exist, but its PayPal link "+
                       "is unavailable. Do not create another order.");
    }catch(ex){
      if(round!==generation)return;
      if(popup&&!popup.closed)popup.close();
      popup=null;
      if(ex.quote){quote=ex.quote;saveQuote();render();}
      else{
        setStatus("Could not confirm the request outcome","alert");
        content.replaceChildren(node("p","","No automatic retry will be attempted."));
      }
      warning(explain(ex));
    }finally{creating=false;}
  }
  async function openFromCard(id){
    if(creating||opening)return;
    opening=true;
    offerId=id;quote=null;stopPoll();clearWarning();
    const round=++generation;
    paymentOpened=false;
    if(!modal.open)modal.showModal();
    // Reserve a popup as a direct consequence of this ONE user click.
    // Navigating after the async server response would be popup-blocked.
    try{
      popup=window.open("about:blank","tcSandboxPayPal_"+id,
        "width=560,height=760,scrollbars=yes,resizable=yes");
      if(popup&&!popup.closed){
        popup.document.title="TraceCart · Connecting to PayPal Sandbox";
        popup.document.body.textContent="Connecting to PayPal Sandbox…";
      }
    }catch(_ignore){popup=null;}
    product.textContent="Checking the recommended product…";
    amount.textContent="";fallback.hidden=true;
    loading("Step 1 of 4 · Checking the selected offer");
    try{
      let value=null;
      const previous=rememberedId(id);
      if(previous&&/^[A-Za-z0-9_-]{20,50}$/.test(previous)){
        try{
          const old=await request("/cart/sandbox/"+encodeURIComponent(previous)+".json");
          if(old.offer_id===id&&old.research_id===
                 app.dataset.sandboxAction.split("/")[3]&&
             old.state!=="QUOTED"&&
             !(old.expires_at&&Date.now()>old.expires_at*1000)){
            value=old;
          }else forgetId(id);
        }catch(_ignore){forgetId(id);}
      }
      if(!value)value=await request(app.dataset.sandboxStart,{offer_id:id});
      if(round!==generation)return;
      quote=value;saveQuote();render();
      if(value.state==="APPROVED"){
        opening=false;
        await createPayPal();
      }else if(value.state==="PAYER_ACTION_REQUIRED"){
        const link=paymentLink();
        if(link&&popup&&!popup.closed){
          popup.location.assign(link);
          paymentOpened=true;
        }else if(popup&&!popup.closed)popup.close();
      }else if(popup&&!popup.closed){
        popup.close();
      }
    }catch(ex){
      if(round!==generation)return;
      if(popup&&!popup.closed&&!paymentOpened)popup.close();
      if(ex.quote){quote=ex.quote;saveQuote();render();}
      else{
        progress("LOADING");
        setStatus("Could not select the offer","alert");
        content.replaceChildren(node("p","",
          "Return to the evidence graph and select a product again."));
      }
      warning(explain(ex));
    }finally{
      opening=false;
    }
  }
  app.addEventListener("submit",event=>{
    const form=event.target.closest("form.purchase-paypal-form");
    if(!form||!app.contains(form))return;
    event.preventDefault();
    const input=form.querySelector('input[name="offer_id"]');
    if(!input||!/^(offer-[0-9]{1,4})$/.test(input.value))return;
    openerButton=form.querySelector("button");
    openFromCard(input.value);
  });
  $("tc-paypal-close").addEventListener("click",()=>modal.close());
  modal.addEventListener("close",()=>{
    stopPoll();generation++;
    if(!paymentOpened){
      try{if(popup&&!popup.closed)popup.close();}catch(_ignore){}
    }
    if(openerButton&&openerButton.isConnected)openerButton.focus();
  });
  // Same-origin PayPal redirect helper. Never trust a postMessage from
  // the hosted PayPal domain or an unrelated window.
  window.addEventListener("message",event=>{
    if(event.origin!==location.origin||event.source!==popup||
       !event.data||event.data.type!=="tracecart:sandbox:return"||
       !quote||event.data.quote_id!==quote.id)return;
    refreshStatus(true);
    try{if(popup&&!popup.closed)popup.close();}catch(_ignore){}
  });
})();