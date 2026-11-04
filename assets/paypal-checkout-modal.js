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
  let pollCount=0,creating=false,generation=0;
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
    catch(_ignore){throw Error("Nie udało się odczytać odpowiedzi TraceCart.");}
    if(!response.ok){
      const ex=Error("Operacja nie została potwierdzona przez serwer.");
      ex.code=data.error||"SERVER_ERROR";
      ex.quote=data.quote||null;
      throw ex;
    }
    if(!data.quote||typeof data.quote.id!=="string"){
      throw Error("Brakuje potwierdzonej wyceny.");
    }
    return data.quote;
  }
  function quotePath(){return "/cart/sandbox/"+encodeURIComponent(quote.id);}
  function progress(state){
    const current=state==="LOADING"?1:state==="QUOTED"?2:
      state==="APPROVED"||state==="CREATE_UNCERTAIN"?3:
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
      "Weryfikuję dane bez zmiany ceny ani sprzedawcy."));
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
      if(button)button.textContent="✓ PayPal — zatwierdzono";
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
      CONSENT_OR_AMOUNT_MISMATCH:"Kwota lub formuła zgody jest niepoprawna. Porównaj je z wyceną.",
      QUOTE_EXPIRED:"Wycena wygasła. Wybierz produkt ponownie z listy propozycji.",
      SANDBOX_CONSENT_EXPIRED:"Zgoda wygasła. Nie utworzono nowego zamówienia.",
      SANDBOX_ORDER_ALREADY_STARTED_OR_NOT_APPROVED:
        "Ta próba była już rozpoczęta. Nie ponawiam tworzenia zamówienia.",
      QUOTE_NOT_AWAITING_APPROVAL:"Ta wycena nie oczekuje już na zgodę.",
      SANDBOX_REQUEST_UNAVAILABLE:
        "Nie udało się zakończyć żądania. Jeśli dotarło do PayPal, nie wolno go ponawiać.",
      SANDBOX_STATUS_UNAVAILABLE:
        "Nie udało się odczytać statusu PayPal. Nie ponawiam zamówienia.",
      UNKNOWN_SANDBOX_QUOTE:"Nie znaleziono zapisanej wyceny.",
    };
    return codes[ex.code]||ex.message||"Nie udało się ukończyć operacji.";
  }
  function render(){
    if(!quote)return;
    const state=quote.state;
    progress(state);
    product.textContent=quote.title||"Wybrany produkt";
    amount.textContent=quote.amount+" "+quote.currency;
    content.replaceChildren();
    fallback.hidden=false;
    fallback.href=quotePath();
    if(state==="QUOTED"){
      setStatus("Etap 2 / 4 · Potwierdź wybraną kwotę testową","normal");
      const intro=node("div","tc-paypal-instruction");
      intro.appendChild(node("h3","","Kontrola przed przejściem do PayPal"));
      intro.appendChild(node("p","",
        "Sprawdź wskazany produkt, wpisz dokładną kwotę i potwierdź świadomą zgodę. "+
        "System nie może zatwierdzić tej czynności za Ciebie."));
      const form=document.createElement("form");
      form.className="tc-paypal-review-form";
      const amountLabel=node("label","tc-paypal-field","Kwota w "+quote.currency);
      const total=document.createElement("input");
      total.type="text";total.required=true;total.autocomplete="off";
      total.inputMode="decimal";total.placeholder=quote.amount;
      total.name="expected_total";
      total.setAttribute("aria-label","Wpisz dokładną kwotę: "+quote.amount);
      amountLabel.appendChild(total);
      const consentLabel=node("label","tc-paypal-field","Potwierdzenie zgody");
      const consent=document.createElement("input");
      consent.type="text";consent.required=true;consent.autocomplete="off";
      consent.name="consent";consent.placeholder=quote.consent_text;
      consent.setAttribute("aria-label","Przepisz wymaganą formułę zgody");
      consentLabel.appendChild(consent);
      form.append(intro,amountLabel,
        node("p","tc-paypal-consent-hint","Wymagany tekst: "+quote.consent_text),
        consentLabel);
      const submit=node("button","tc-paypal-button tc-paypal-primary",
        "Potwierdzam kwotę testową →");
      submit.type="submit";form.appendChild(submit);
      form.addEventListener("submit",async ev=>{
        ev.preventDefault();
        if(creating)return;
        const generationAtStart=generation;
        creating=true;submit.disabled=true;clearWarning();
        setStatus("Zapisuję Twoją zgodę…","busy");
        try{
          const value=await request(quotePath()+"/approve",
            {expected_total:total.value,consent:consent.value});
          if(generationAtStart!==generation)return;
          quote=value;saveQuote();render();
        }catch(ex){
          if(generationAtStart!==generation)return;
          if(ex.quote){quote=ex.quote;saveQuote();}
          render();
          warning(explain(ex));
        }finally{creating=false;}
      });
      content.appendChild(form);
      return;
    }
    if(state==="APPROVED"){
      setStatus("Etap 3 / 4 · Twoja zgoda została zapisana","ready");
      content.append(
        node("h3","","Gotowe do bezpiecznego przekierowania"),
        node("p","tc-paypal-instruction",
          "Następny krok utworzy jedno zamówienie testowe w PayPal Sandbox. "+
          "Strona płatności otworzy się w osobnym, bezpiecznym oknie PayPal."),
        action("Otwórz PayPal Sandbox ↗",createPayPal,"paypal"));
      return;
    }
    if(state==="PAYER_ACTION_REQUIRED"){
      setStatus("Etap 3 / 4 · Oczekiwanie na zatwierdzenie u PayPal","busy");
      const wait=node("div","tc-paypal-pending");
      wait.appendChild(node("div","tc-paypal-pulse","●"));
      wait.appendChild(node("h3","","Czekam na potwierdzenie…"));
      wait.appendChild(node("p","",
        "Zaloguj się na konto Sandbox Personal w otwartym oknie PayPal. "+
        "TraceCart sprawdza status w trybie tylko do odczytu."));
      const ref=node("p","tc-paypal-order-ref",
        "Zamówienie Sandbox: "+(quote.paypal_order_id||""));
      wait.appendChild(ref);
      const controls=node("div","tc-paypal-controls");
      const link=paymentLink();
      if(link){
        const a=node("a","tc-paypal-button tc-paypal-paypal-outline",
          "Otwórz ponownie PayPal ↗");
        a.href=link;a.rel="noopener noreferrer";a.target="_blank";
        controls.appendChild(a);
      }
      controls.appendChild(action("Sprawdź status teraz",()=>{
        refreshStatus(true);
      },"secondary"));
      wait.appendChild(controls);
      content.appendChild(wait);
      startPolling();
      return;
    }
    stopPoll();
    if(state==="VERIFIED_APPROVED"){
      setStatus("Etap 4 / 4 · Zatwierdzenie Sandbox zweryfikowane","success");
      const box=node("section","tc-paypal-success");
      box.appendChild(node("div","tc-paypal-success-check","✓"));
      box.appendChild(node("h3","","PayPal potwierdził zgodę"));
      box.appendChild(node("p","",
        "Status: APPROVED. Zamówienie testowe zostało zweryfikowane po stronie serwera. "+
        "Nie pobrano pieniędzy i nie dokonano zakupu u sprzedawcy."));
      box.appendChild(node("p","tc-paypal-order-ref",
        "ID zamówienia: "+(quote.paypal_order_id||"")));
      box.appendChild(action("Wróć do propozycji produktów",()=>modal.close()));
      content.appendChild(box);
      updateVerifiedCard();
      return;
    }
    setStatus("Transakcja wymaga wyjaśnienia · bez ponawiania płatności","alert");
    const block=node("div","tc-paypal-uncertain");
    block.appendChild(node("h3","","Nie tworzę kolejnego zamówienia"));
    block.appendChild(node("p","",
      "Wynik żądania tworzenia nie jest pewny. Bezpieczna procedura wymaga "+
      "sprawdzenia istniejącego zamówienia w PayPal, a nie ponownego wysyłania POST."));
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
        setStatus("Oczekiwanie na zatwierdzenie w PayPal Sandbox…","busy");
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
        warning("Automatyczna kontrola została wstrzymana po 2,5 minuty. "+
          "Możesz sprawdzić stan ręcznie — nie utworzy to nowego zamówienia.");
        return;
      }
      refreshStatus(true);
    },5000);
  }
  async function createPayPal(){
    if(creating||!quote||quote.state!=="APPROVED")return;
    const round=generation;
    creating=true;clearWarning();
    setStatus("Przekazuję pojedyncze zamówienie do PayPal Sandbox…","busy");
    content.replaceChildren(node("div","tc-paypal-wait",
      "Tworzenie zamówienia tylko raz. Nie ponawiaj żądania ani nie odświeżaj strony."));
    // A new window must be opened synchronously from this click to avoid popup
    // blockers. The only real navigation is the server-approved Sandbox link.
    try{
      popup=window.open("about:blank","tcSandboxPayPal_"+quote.id,
        "width=560,height=760,scrollbars=yes,resizable=yes");
      if(popup&&!popup.closed){
        popup.document.title="TraceCart · łączenie z PayPal Sandbox";
        popup.document.body.textContent="Łączenie z PayPal Sandbox…";
      }
    }catch(_ignore){popup=null;}
    try{
      const value=await request(quotePath()+"/create",{});
      if(round!==generation)return;
      quote=value;saveQuote();render();
      const link=paymentLink();
      if(link&&popup&&!popup.closed)popup.location.assign(link);
      else if(popup&&!popup.closed)popup.close();
      if(!link)warning("Zamówienie mogło zostać utworzone, ale link PayPal "+
                       "nie jest dostępny. Nie ponawiaj tworzenia zamówienia.");
    }catch(ex){
      if(round!==generation)return;
      if(popup&&!popup.closed)popup.close();
      popup=null;
      if(ex.quote){quote=ex.quote;saveQuote();render();}
      else{
        setStatus("Nie udało się potwierdzić wyniku żądania","alert");
        content.replaceChildren(node("p","","Nie wykonuję ponownej próby."));
      }
      warning(explain(ex));
    }finally{creating=false;}
  }
  async function openFromCard(id){
    if(creating)return;
    offerId=id;quote=null;stopPoll();clearWarning();
    const round=++generation;
    if(!modal.open)modal.showModal();
    product.textContent="Weryfikuję proponowany produkt…";
    amount.textContent="";fallback.hidden=true;
    loading("Etap 1 / 4 · Sprawdzam propozycję");
    try{
      let value=null;
      const previous=rememberedId(id);
      if(previous&&/^[A-Za-z0-9_-]{20,50}$/.test(previous)){
        try{
          const old=await request("/cart/sandbox/"+encodeURIComponent(previous)+".json");
          if(old.offer_id===id&&old.research_id===
                 app.dataset.sandboxAction.split("/")[3]&&
             !(old.expires_at&&Date.now()>old.expires_at*1000)){
            value=old;
          }else forgetId(id);
        }catch(_ignore){forgetId(id);}
      }
      if(!value)value=await request(app.dataset.sandboxAction,{offer_id:id});
      if(round!==generation)return;
      quote=value;saveQuote();render();
    }catch(ex){
      if(round!==generation)return;
      if(ex.quote){quote=ex.quote;saveQuote();render();}
      else{
        progress("LOADING");
        setStatus("Wybór propozycji nie powiódł się","alert");
        content.replaceChildren(node("p","",
          "Wróć do grafu i wybierz produkt ponownie."));
      }
      warning(explain(ex));
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