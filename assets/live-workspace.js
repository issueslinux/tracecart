/* Live graph-only workspace. All real changes arrive from loopback SSE;
 * no fake progress timers, speculative answers or browser access to RAM/VRAM. */
(function(){
  "use strict";
  const $=id=>document.getElementById(id);
  function item(tag,className,label){
    const el=document.createElement(tag);
    if(className)el.className=className;
    if(label!==undefined&&label!==null)el.textContent=String(label);
    return el;
  }
  function renderItems(target,records){
    const hash=JSON.stringify(records.map(x=>[x.key,x.state,x.title,x.detail]));
    if(target.dataset.signature===hash)return;
    target.dataset.signature=hash;
    target.replaceChildren();
    if(!records.length){
      target.appendChild(item("p","live-empty","No active work yet."));
      return;
    }
    records.forEach(r=>{
      const card=item("article","live-task");
      card.dataset.status=r.mode;
      const top=item("div","live-task-header");
      top.appendChild(item("span","",r.key));
      top.appendChild(item("span","",r.state));
      card.appendChild(top);
      card.appendChild(item("p","live-task-title",r.title));
      if(r.detail)card.appendChild(item("small","",r.detail));
      target.appendChild(card);
    });
  }
  function sourceTasks(data){
    const g=data.graph||{},details=g.offer_details||{},result=data.evidence_offers||{};
    const offers=(data.offer_queue&&data.offer_queue.length?
      data.offer_queue.map(o=>[o.id,{title:o.title,url:o.url,kind:o.kind,
        input_access_problem:(details[o.id]||{}).input_access_problem}]):
      Object.entries(details));
    const complete=data.state==="READY" &&
      ["COMPLETE","INTERRUPTED"].includes((data.evidence_progress||{}).status);
    const rows=[],indexOnly=[],duplicates=[];
    const weight={RUNNING:0,QUEUED:1,REFERENCE:2,BLOCKED:3};
    const seenLinks=new Set();
    offers.forEach(([id,d])=>{
      const entry=result[id]||{},state=entry.status;
      const attempts=entry.attempted_sources||[];
      const direct=attempts.filter(a=>a.url);
      const restricted=direct.find(a=>
        String(a.status||"").startsWith("NOT_RETRIEVED_SourceAccessDenied"));
      const failed=direct.find(a=>String(a.status||"").startsWith("NOT_RETRIEVED_"));
      const mismatch=direct.find(a=>a.status==="SOURCE_PAGE_IDENTITY_NOT_CONFIRMED");
      const rendered=direct.find(a=>a.browser_status==="RENDERED_NO_MATCHED_PRODUCT_DATA");
      const capacity=direct.find(a=>a.browser_status==="GRAPHICAL_BROWSER_CAPACITY_LIMIT");
      const hasFacts=(entry.reference_answers||[]).length>0;
      const directUrl=direct.find(a=>a.url)?.url || d.url || null;
      // A finished research job may acquire new index offers later.
      // Those offers have NO fetch/evidence task; never show endless WAITING.
      let mode="QUEUED",label="WAITING",detail="Scheduled for source checking.";
      if(complete&&!state){
        mode="BLOCKED";
        label=d.kind==="INDEXED_SEARCH_CARD"?"INDEX ONLY":"NOT VERIFIED";
        detail=d.kind==="INDEXED_SEARCH_CARD"
          ?"Shopping search card with no direct seller URL; no page to visit."
          :"Indexed seller URL found. Browser verification has not yet been authorized.";
      }
      const offerIdx=Number(id.split("-")[1]);
      const browserCheck=(data.indexed_browser_checks||[]).find(c=>
        c.offer_idx===offerIdx && id!=="offer-0");
      if(state==="RUNNING"){
        mode="RUNNING";label="CHECKING";detail="Fetching eligible source pages.";
      }else if(state==="QUEUED"){
        mode="QUEUED";label="QUEUED";detail="Waiting for an available source worker.";
      }else if(hasFacts){
        mode="REFERENCE";label=(entry.reference_answers||[]).some(x=>
          x.source_kind==="INDEPENDENT_TEST")?"REVIEW FOUND":"SPECIFICATIONS";
        detail=label==="REVIEW FOUND"?
          "Independent measurements of the reviewed model; exact retailer variant still unproven.":
          (entry.reference_answers||[]).length+
          " sourced product specifications; not independent testing.";
      }else if(state){
        mode="BLOCKED";
        label=state.startsWith("INTERRUPTED")?"INTERRUPTED":
          d.input_access_problem==="HTTP_403"?"SERVER HTTP 403":
          restricted?"ACCESS RESTRICTED":
          failed?"PAGE NOT RETRIEVED":
          mismatch?"WRONG MODEL":
          capacity?"BROWSER CAPACITY":
          rendered?"NO STRUCTURED DATA":
          !direct.length?(d.url?"NO FETCH RECEIPT":"INDEX ONLY"):"NO PRODUCT FACTS";
        detail=label==="SERVER HTTP 403"?
          "The shop rejected TraceCart's server request, not the product. An authorized Chromium browser can still provide seller-declared data; checkout remains unverified.":
          label==="ACCESS RESTRICTED"?
          "Server retrieval was denied. This does not mean the product is unavailable to customers.":
          label==="PAGE NOT RETRIEVED"?
          "The source URL failed its network, robots or redirect check.":
          label==="WRONG MODEL"?
          "Page opened, but product identity did not match; its facts were rejected.":
          label==="BROWSER CAPACITY"?
          "No graphical renderer slot became available; evidence was not fabricated.":
          label==="NO STRUCTURED DATA"?
          "Page rendered, but no matching structured product fields were present.":
          label==="INDEX ONLY"?
          "Search index has a listing, but no usable direct product URL was supplied.":
          label==="NO FETCH RECEIPT"?
          "A product URL exists, but no HTTP or graphical fetch outcome was recorded.":
          label==="NO PRODUCT FACTS"?
          "Source was checked; no product facts matched the listed model.":
          "Source check was interrupted.";
      }
      if(browserCheck){
        const b=browserCheck.browser_claim||{};
        const amount=b.fields?.price && b.fields?.currency
          ? b.fields.price+" "+b.fields.currency : "";
        const status=browserCheck.status||"QUEUED";
        mode=["QUEUED","IN_PROGRESS"].includes(status)?"RUNNING":
          status==="PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED"?"REFERENCE":"BLOCKED";
        label=status==="PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED"
          ?"BROWSER CAPTURED":status==="IN_PROGRESS"?"CHECKING":
          status==="QUEUED"?"QUEUED":"BROWSER: "+status;
        const promotion=b.browser_promotion;
        detail=amount
          ?"Browser seller-declared price: "+amount+
            (promotion?" · with code "+promotion.code+": "+
              promotion.price+" "+promotion.currency:"")+
            ". Checkout unverified."
          :"No browser price available. "+status;
      }
      const inputBrowser=id==="offer-0"?(details[id]||{}).browser_observation:null;
      if(inputBrowser?.status==="PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED"){
        mode="REFERENCE";label="BROWSER CAPTURED";
        const listed=inputBrowser.declared_price&&inputBrowser.currency
          ?inputBrowser.declared_price+" "+inputBrowser.currency:"price unknown";
        const coupon=inputBrowser.promotion;
        detail="Browser-listed: "+listed+
          (coupon?" · with code "+coupon.code+": "+coupon.price+" "+
            coupon.currency+(coupon.valid_until?" until "+coupon.valid_until:""):"")+
          " · checkout NOT VERIFIED. An earlier HTTP 403 only blocked server access.";
      }
      const row={key:"#"+(Number(id.split("-")[1])+1),
        title:d.title||"Product",detail,mode,state:label,weight:weight[mode]};
      // An index search card is useful in the graph, but not a browser task.
      // Avoid twenty identical pseudo-failures in the left-side source rail.
      if(complete&&mode==="BLOCKED"&&label==="INDEX ONLY"&&id!=="offer-0"){
        indexOnly.push(row);return;
      }
      // A seller listing repeated under the same URL needs one visible task,
      // although each persisted offer and quote remains in the full graph.
      if(complete&&mode==="BLOCKED"&&directUrl&&id!=="offer-0" &&
         seenLinks.has(directUrl)){
        duplicates.push(row);return;
      }
      if(directUrl)seenLinks.add(directUrl);
      rows.push(row);
    });
    if(indexOnly.length){
      rows.push({key:"INDEX",title:indexOnly.length+
        " index-only cards without direct product links",
        detail:"No web page can be opened from these search cards. Their indexed prices remain visible as unverified graph observations.",
        mode:"BLOCKED",state:"INDEX LEADS",weight:weight.BLOCKED});
    }
    if(duplicates.length){
      rows.push({key:"REUSED",title:duplicates.length+
        " listings share an already checked seller URL",
        detail:"Duplicate source checks are collapsed here; the separate product and indexed-price nodes remain in the graph.",
        mode:"BLOCKED",state:"SAME URL",weight:weight.BLOCKED});
    }
    const promotions=(g.nodes||[]).filter(node=>
      node.provenance==="BROWSER_VISIBLE_CONDITIONAL_PRICE" &&
      node.parameter==="coupon_price_with_code");
    if(promotions.length){
      promotions.slice(0,4).forEach(node=>rows.unshift({
        key:"COUPON",title:"Conditional "+node.value+" "+
          (node.currency||"")+" · code "+node.promotion_code,
        detail:"Automatically observed in the authorized store browser. "+
          "The coupon must be entered and accepted in checkout; "+
          (node.valid_until?"listed expiry "+node.valid_until+". ":"")+
          "The delivered total is NOT verified.",
        mode:"REFERENCE",state:"CODE REQUIRED",weight:weight.REFERENCE
      }));
    }
    const browserPages=(g.nodes||[]).filter(node=>
      node.source_kind==="USER_BROWSER_FILTERED_PROJECTION");
    if(browserPages.length){
      rows.push({
        key:"BROWSER",title:browserPages.length+" browser-captured seller page",
        detail:"Claim from opted-in Chromium; URL matched. Exact variant and checkout price unverified.",
        mode:"REFERENCE",state:"PAGE CAPTURED",weight:weight.REFERENCE
      });
    }
    rows.sort((a,b)=>(a.key==="#1"?-1:b.key==="#1"?1:
      a.weight-b.weight||
      (Number(a.key.slice(1))||999)-(Number(b.key.slice(1))||999)));
    return rows.slice(0,20);
  }
  function questionTasks(data,selectedId="offer-0"){
    const g=data.graph||{},details=g.offer_details||{},model=data.model_offers||{};
    const complete=data.state==="READY" && isTerminal(data);
    const running=[],open=[],answered=[],proposed=[];
    let batchReported=false;
    const ordered=Object.entries(details).sort(([a],[b])=>
      a===selectedId?-1:b===selectedId?1:
      Number(a.split("-")[1])-Number(b.split("-")[1]));
    for(const [id,d] of ordered){
      const idx=Number(id.split("-")[1])+1;
      const ml=model[id]||{};
      if(["RUNNING","BATCH_RUNNING"].includes(ml.state) &&
          data.progress_stage!=="PER_OFFER_MODEL_COMPLETE"){
        if(!batchReported){
          running.push({key:"QWEN · BATCH",
            title:"One batched request for distinct product models",
            detail:"Single inference call · independent source checks run separately.",
            state:"INFERENCE",mode:"RUNNING"});
          batchReported=true;
        }
      } else if(ml.state==="OK") {
        for(const q of (ml.questions||[]).slice(0,2)){
          proposed.push({key:"#"+idx+" · QWEN",title:q.question,
            detail:"Proposed by local model · awaiting source verification.",
            state:"PROPOSED",mode:"QUEUED"});
        }
      }
      const e=(data.evidence_offers||{})[id]||{};
      for(const a of (e.reference_answers||[]).slice(0,3)){
        const independent=a.source_kind==="INDEPENDENT_TEST";
        answered.push({
          key:"#"+idx+(independent?" · TEST":" · DOCUMENT"),
          title:a.finding,
          detail:independent?
            "Independent measurement · exact retailer SKU still unknown.":
            "Fetched product specifications · publisher declaration, not a lab test.",
          state:independent?"REFERENCE":"DECLARED",mode:"REFERENCE",
        });
      }
      for(const c of (e.declared_claim_conflicts||[]).slice(0,2)){
        answered.push({key:"#"+idx+" · DISCREPANCY",
          title:(c.type==="PUBLISHED_SOURCES_DISAGREE"?
            String(c.source_a_value)+" vs "+String(c.source_b_value):
            String(c.listing_value)+" vs "+String(c.source_value)),
          detail:"Two published claims differ · variant/test conditions unresolved.",
          state:"CHECK SOURCES",mode:"BLOCKED"});
      }
      for(const q of (d.high_impact_questions||[]).slice(0,5)){
        open.push({key:"#"+idx+" · VERIFY",title:q.question,
          detail:q.reason||"A new independent source or SKU check is required.",
          state:complete?"UNRESOLVED":"OPEN",mode:"QUEUED"});
      }
    }
    const review=data.graph_question_review||{};
    const generated=[];
    const priority=[];
    for(const q of (data.instant_assessment?.priority_checks||[])){
      if(q.offer_id===selectedId)priority.push({key:"PRIORITY",title:q.question,state:"VERIFY",mode:"QUEUED"});
    }
    if(review.status==="COMPLETE")for(const q of (review.questions||[])){
      if(q.offer_id===selectedId)generated.push({key:"GRAPH QWEN",title:q.question,detail:"Unverified · source: "+q.anchor_id,state:"PROPOSED",mode:"QUEUED"});
    }
    if(review.status==="RUNNING")generated.push({key:"GRAPH MODEL",title:"New questions under review",state:"INFERENCE",mode:"RUNNING"});
    // Finished work is not a queue. The old revision-rotating generic
    // probes made completed jobs appear to be indefinitely processing.
    // Show actual documented findings and selected-offer gaps, not 18×24
    // template questions. The other offers remain navigable in the graph.
    if(complete){
      const selectedEvidence=answered.filter(row=>
        row.key.startsWith("#"+(Number(selectedId.split("-")[1])+1)+" ·"));
      const selectedGaps=open.filter(row=>
        row.key.startsWith("#"+(Number(selectedId.split("-")[1])+1)+" ·"));
      return [{
        key:"RESEARCH",title:"Source and model checks have finished",
        detail:(data.evidence_progress.processed||0)+"/"+
          (data.evidence_progress.planned||0)+
          " offers checked. Unresolved items require additional sources.",
        state:"COMPLETE",mode:"REFERENCE",
      },...priority,...generated,...selectedEvidence.slice(0,5),...selectedGaps.slice(0,9)];
    }
    const changed=Number(data.progress_revision)||0;
    const rotated=open.length?
      open.slice(changed%open.length).concat(open.slice(0,changed%open.length)):[];
    const lead=priority.slice(0,3).concat(running.slice(0,1)).concat(answered.slice(0,5))
      .concat(proposed.slice(0,2));
    return lead.concat(rotated.slice(0,Math.max(0,18-lead.length)));
  }
  function emptyGraph(){
    return {
      schema_version:"tracecart.offer-knowledge-graph.v1",
      nodes:[{id:"offer-0",type:"offer",ordinal:1,
        offer_kind:"INPUT_PRODUCT",label:"Paste a product URL"}],
      edges:[],offer_details:{"offer-0":{
        title:"Paste a product URL",
        claim_provenance:"NOT_STARTED",claims:[],
        high_impact_questions:[],planned_question_count:0,
      }},stats:{offers:0,unique_title_claim_values:0,
        independent_reference_measurements:0,verified_exact_sku_answers:0}
    };
  }
  function isTerminal(snapshot) {
    if(!snapshot||snapshot.state==="FAILED"||snapshot.state==="INTERRUPTED")
      return true;
    if(snapshot.state!=="READY")return false;
    const evidenceStatus=(snapshot.evidence_progress||{}).status;
    const verdictStatus=(snapshot.final_verdict||{}).status;
    if(evidenceStatus==="INTERRUPTED"||verdictStatus==="INTERRUPTED")
      return true;
    if(evidenceStatus!=="COMPLETE")return false;
    const verdict=(snapshot.final_verdict||{}).status||"NOT_SCHEDULED";
    if(["COMPLETE","UNAVAILABLE","INTERRUPTED",
        "STALE_AFTER_SHOPPING_REFRESH","SKIPPED_NOT_NEEDED"].includes(verdict))
      return true;
    // Old durable jobs predate the verdict phase. Never retroactively
    // describe those saved reports as local LLM conclusions.
    return verdict==="NOT_SCHEDULED" &&
      snapshot.progress_stage==="PER_OFFER_MODEL_COMPLETE";
  }
  // Technical link checks are NOT a merchant fraud clearance.
  const linkSignals={
    INVALID_OR_UNSAFE_LINK:"Unsafe or malformed URL",
    DESTINATION_NOT_PUBLIC:"DNS returned a private or non-public destination",
    DNS_LOOKUP_UNAVAILABLE:"DNS could not be verified",
    TLS_CERTIFICATE_OR_CONNECTION_NOT_VERIFIED:"TLS certificate/connection could not be verified",
    TLS_NOT_VERIFIED:"TLS certificate could not be confirmed",
    RECENTLY_REGISTERED_DOMAIN_UNDER_90_DAYS:"Domain registered less than 90 days ago",
    PUNYCODE_DOMAIN_REVIEW:"Internationalized domain requires visual review",
    BRAND_NAME_IN_THIRD_PARTY_SUBDOMAIN:"Brand name appears in a third-party subdomain",
    CHECK_NOT_COMPLETED:"Automated check was incomplete",
    HOST_LIMIT_REACHED:"Automated host-check limit reached",
  };
  const linkSafetyLabels={
    HIGH_RISK_SIGNALS:"Unsafe URL signals",
    REVIEW_REQUIRED:"Review recommended",
    BASIC_TECHNICAL_CHECKS_PASSED:"Basic network checks passed",
    INCONCLUSIVE:"Not enough information",
  };
  function renderLinkSafety(target,snapshot) {
    if(!target)return;
    const report=snapshot.link_safety||{};
    target.hidden=!report.status||report.status==="NOT_STARTED";
    if(target.hidden)return;
    target.replaceChildren();
    const head=item("div","link-safety-header");
    head.appendChild(item("strong","","Retailer link safety checks"));
    head.appendChild(item("span","link-safety-tag",
      report.status==="RUNNING"?"Checking domains…":
      report.status==="COMPLETE"?"Technical signals only":"Incomplete screening"));
    target.appendChild(head);
    if(report.status==="RUNNING"){
      target.appendChild(item("p","link-safety-disclaimer",
        "Checking HTTPS, public DNS, certificate validity and available domain registration data. This does not certify a shop."));
      return;
    }
    const links=Array.isArray(report.links)?report.links:[];
    const bad=links.filter(x=>["HIGH_RISK_SIGNALS","REVIEW_REQUIRED"].includes((x.risk||{}).status));
    const inputOnly=Number(report.index_cards_without_direct_url||0);
    target.appendChild(item("p","link-safety-summary",
      links.length+" unique links inspected · "+bad.length+
      " flagged for review · "+inputOnly+
      " search-index cards have no direct retailer URL."));
    const disclosure=document.createElement("details");
    disclosure.className="link-safety-disclosure";
    disclosure.open=bad.length>0;
    const summary=document.createElement("summary");
    summary.textContent="Inspect all "+links.length+" URL assessments";
    disclosure.appendChild(summary);
    const rows=item("div","link-safety-list");
    links.forEach(entry=>{
      const result=entry.risk||{},reg=result.registration||{};
      const row=item("div","link-safety-row");
      row.appendChild(item("span","link-safety-domain",entry.domain||
        "Invalid/unsafe URL"));
      const kind=linkSafetyLabels[result.status]||"Not assessed";
      row.appendChild(item("span","link-safety-rating",kind));
      const attrs=[];
      if(result.dns_status==="PUBLIC_ADDRESS")attrs.push("Public DNS");
      if(result.tls_status==="VALID_CERTIFICATE")attrs.push("Valid HTTPS certificate");
      if(reg.registered_at)attrs.push("Registered: "+reg.registered_at);
      else attrs.push("Registration date unavailable");
      attrs.push("Store legitimacy NOT verified");
      if((result.signals||[]).length)attrs.push(
        "Signals: "+result.signals.map(x=>linkSignals[x]||x).join("; "));
      row.appendChild(item("p","link-safety-facts",attrs.join(" · ")));
      if(entry.url_check==="PUBLIC_HTTPS_URL_SYNTAX" &&
         result.status!=="HIGH_RISK_SIGNALS"){
        const a=document.createElement("a");
        a.href=entry.url;a.rel="noopener noreferrer";a.target="_blank";
        a.textContent="Visit listing (external)";
        row.appendChild(a);
      }
      rows.appendChild(row);
    });
    disclosure.appendChild(rows);
    target.appendChild(disclosure);
    target.appendChild(item("p","link-safety-disclaimer",
      report.disclaimer||
      "HTTPS and an older domain do not prove that a merchant is legitimate. No independent fraud database has been checked."));
  }
  function offerSafetyLabel(report,offerId) {
    const entry=((report||{}).links||[]).find(x=>
      (x.offer_ids||[]).includes(offerId));
    if(!entry)return "Merchant identity not checked (no direct link or receipt)";
    const result=entry.risk||{};
    return (linkSafetyLabels[result.status]||"Link safety not confirmed")+
      " · Merchant legitimacy not verified";
  }

  function renderPurchaseAlternatives(target,snapshot,app,report){
    if(!report||typeof report!=="object")return;
    const options=Array.isArray(report.options)?report.options:[];
    const unitMode=report.pricing_basis==="INDEXED_NORMALIZED_UNIT_RATE_NOT_CHECKOUT";
    const moreExpensive=Array.isArray(report.higher_priced_comparables)?
      report.higher_priced_comparables:[];
    const tradeoffs=Array.isArray(report.tradeoffs)?report.tradeoffs:[];
    const container=item("section","purchase-insights");
    container.appendChild(item("h3","",
      unitMode?"How do comparable pack sizes and unit prices differ?":
      report.selected_price?"Do cheaper comparable alternatives exist?":
      "Are there better-value or cheaper alternatives?"));
    if(report.selected_price){
      const note=item("div","purchase-input-baseline");
      note.appendChild(item("strong","",
        "Selected seller observed price: "+report.selected_price));
      note.appendChild(item("p","",
        "Evidence: "+String(report.selected_price_source||"NOT_VERIFIED").replace(/_/g," ")+
        ". This is not a verified checkout total."));
      if(report.promotion_code){
        note.appendChild(item("p","",
          "Promo code: "+report.promotion_code+
          (report.promotion_valid_until?
            " · Listed valid until: "+report.promotion_valid_until:"")+
          " · Apply the code and check final price before purchasing."));
      }
      container.appendChild(note);
    }
    container.appendChild(item("p","purchase-market-note",
      unitMode?"Unit costs use prices and pack sizes stated only in search-index cards. "+
        "They do not confirm the actual retailer total, stock or product equivalence.":
      report.market_reference?
      "Median of comparable indexed listings: "+report.market_reference+
      " — not the selected store price or verified savings.":
      report.status==="FUNCTIONAL_INDEX_LEADS_NEED_SPEC_VERIFICATION"?
      "Offers are conditional leads; there is no reliable like-for-like peer median. "+
      "Confirm the model, performance, stock and delivered total at the retailer.":
      "No reliable price baseline; listing data is incomplete."));
    function addGroup(rows,heading){
      if(!rows.length)return;
      container.appendChild(item("h4","",heading));
      const cards=item("div","purchase-options");
      rows.forEach(row=>{
        const card=item("article","purchase-option");
        const summary=item("div","purchase-option-heading");
        summary.appendChild(item("strong","",row.title||"Listing"));
        summary.appendChild(item("span","purchase-price",
          (row.price||"Price unavailable")+" "+(row.currency||"")));
        card.appendChild(summary);
        if(row.unit_comparison_label)
          card.appendChild(item("p","purchase-relative",
            "Indexed unit quote: "+row.unit_comparison_label+
            " · derived from advertised pack size"));
        else if(row.vs_index_median)
          card.appendChild(item("p","purchase-relative",row.vs_index_median));
        if((row.matched_features||[]).length)
          card.appendChild(item("p","purchase-matches",
            "Advertised comparable specifications: "+
            row.matched_features.slice(0,4).join(" · ")));
        if((row.different_features||[]).length)
          card.appendChild(item("p","purchase-diff",
            "Differences: "+row.different_features.slice(0,3).join(" · ")));
        if((row.unconfirmed_features||[]).length)
          card.appendChild(item("p","purchase-unknown",
            "Unconfirmed: "+row.unconfirmed_features.slice(0,3).join(", ")));
        if((row.highlights||[]).length)
          card.appendChild(item("p","purchase-highlight",
            "Potential advantage: "+row.highlights.join("; ")));
        const actions=item("div","purchase-actions");
        const controller=app._traceCartGraphController;
        if(row.offer_id&&controller&&controller.graph.nodes.some(n=>n.id===row.offer_id)){
          const button=item("button","","Highlight offer in graph");
          button.type="button";
          button.addEventListener("click",()=>controller.select(row.offer_id));
          actions.appendChild(button);
        }
        if(row.source_url){
          try{
            const u=new URL(row.source_url);
            if(u.protocol==="https:"||u.protocol==="http:"){
              const a=document.createElement("a");
              a.href=u.href;a.target="_blank";a.rel="noopener noreferrer";
              a.textContent="Open indexed listing ↗";
              actions.appendChild(a);
            }
          }catch(_ignore){}
        }else {
          actions.appendChild(item("small","",
            "No direct retailer URL was provided by the search index."));
        }
        card.appendChild(actions);
        card.appendChild(item("p","purchase-link-safety",
          offerSafetyLabel(snapshot.link_safety,row.offer_id)));
        cards.appendChild(card);
      });
      container.appendChild(cards);
    }
    const functionalMode=report.status==="FUNCTIONAL_INDEX_LEADS_NEED_SPEC_VERIFICATION";
    addGroup(options,unitMode?
      "Comparable advertised packs · ranked by indexed cost per unit":
      functionalMode?"Potentially cheaper functional leads · specifications not verified":
      "Potentially cheaper, comparable configurations");
    addGroup(tradeoffs,unitMode?
      "Pack or product variant not confirmed":
      functionalMode?"Further unverified functional leads":
      "Cheaper with specification differences");
    if(unitMode&&(report.different_variant_listings||[]).length){
      container.appendChild(item("p","purchase-disclaimer",
        (report.different_variant_listings||[]).length+
        " indexed listings have a different declared variant and were not "+
        "treated as equivalent products."));
    }
    if(moreExpensive.length){
      const disclosure=document.createElement("details");
      disclosure.className="purchase-expensive";
      const label=document.createElement("summary");
      label.textContent=moreExpensive.length+
        " higher-priced comparable listings — not recommended on price";
      disclosure.appendChild(label);
      const expensive=item("div","purchase-expensive-lines");
      moreExpensive.forEach(row=>{
        expensive.appendChild(item("p","",
          row.title+": "+row.price+" "+row.currency+" ("+
          (row.vs_selected_price||"no demonstrated value improvement")+
          "). Price is only from the search index."));
      });
      disclosure.appendChild(expensive);
      container.appendChild(disclosure);
    }
    const anomalies=Array.isArray(report.suspicious_price_quotes)?
      report.suspicious_price_quotes:[];
    if(anomalies.length){
      const amounts=[...new Set(anomalies.map(x=>
        (x.indexed_price||"?")+" "+(x.currency||"")))];
      container.appendChild(item("p","purchase-anomaly",
        "Excluded "+anomalies.length+" suspiciously low indexed prices ("+
        amounts.join(", ")+"). These are not reliable purchase prices."));
    }
    container.appendChild(item("p","purchase-disclaimer",
      report.disclaimer||
      "Search titles and prices do not confirm an identical configuration or checkout total."));
    target.appendChild(container);
  }

  // Live evidence always takes precedence over a possibly stale Qwen result.
  // This is a display choice, not a modification of stored model receipts.
  function verdictForDisplay(snapshot){
    const model=snapshot.final_verdict||{};
    const instant=snapshot.instant_assessment||null;
    return {model,instant,shown:instant||model,
            live:!!instant};
  }
  function renderVerdict(target,snapshot,app) {
    if(!target)return;
    const {model,instant,shown:v,live}=verdictForDisplay(snapshot);
    const stats=(snapshot.graph||{}).stats||{};
    const legacy=snapshot.state==="READY" &&
      (!model.status||model.status==="NOT_SCHEDULED")&&isTerminal(snapshot);
    const ready=snapshot.state==="READY" &&
      ["COMPLETE","UNAVAILABLE","INTERRUPTED",
       "SKIPPED_NOT_NEEDED","STALE_AFTER_SHOPPING_REFRESH"].includes(model.status);
    target.hidden=!(live||ready||legacy);
    if(target.hidden)return;
    target.replaceChildren();
    const head=item("div","verdict-head");
    const title=live?"Current evidence-based comparison":
      model.status==="COMPLETE"?"Offer comparison results":
      model.status==="UNAVAILABLE"?"Offer comparison · model unavailable":
      legacy?"Research result · earlier saved job":"Research interrupted";
    head.appendChild(item("strong","",title));
    const tag=item("span","verdict-tag"+(!live && model.status==="UNAVAILABLE"?" unavailable":""),
      live?(instant.status==="CURRENT"?
        "Updated from current evidence · no checkout verified":
        "Preliminary · updates as sources arrive"):
      v.comparison_projection_updated?"Reassessed from saved evidence · index prices unverified":
      model.status==="COMPLETE"?"Local Qwen · conditional assessment · indexed prices":
      model.status==="UNAVAILABLE"?"Local Qwen timed out · source-based assessment":
      model.status==="SKIPPED_NOT_NEEDED"?"Model unnecessary · source-based assessment":
      "Research from archived job");
    head.appendChild(tag);target.appendChild(head);
    if(live){
      const modelNote=model.status==="RUNNING"?"Optional Qwen classification running; this assessment is available now.":
        model.status==="QUEUED"?"Optional Qwen not yet finished; this assessment does not wait.":
        model.status==="COMPLETE"?"Previous Qwen classification: "+
          String(model.verdict||"INDETERMINATE").replace(/_/g," ")+
          " · may predate newer browser observations; current source facts take precedence.":
        model.status==="UNAVAILABLE"?"Model unavailable; latest source evidence remains available.":
        model.status==="SKIPPED_NOT_NEEDED"?"No qualifying documented semantic conflict was found by current rules.":
        model.status==="STALE_AFTER_SHOPPING_REFRESH"?"Previous model classification is stale; current sources were reassessed.":
        "Assessment uses recorded evidence only; no model inference required for display.";
      target.appendChild(item("p","verdict-model-note",modelNote));
    }
    const text=v.summary || (
      "Research finished. This saved job has no final local-LLM synthesis. "+
      (stats.documented_product_declarations||0)+" documented product declarations, "+
      (stats.independent_reference_measurements||0)+" independent measurements and "+
      (stats.verified_checkout_prices||0)+" confirmed checkout prices."
    );
    target.appendChild(item("p","verdict-summary",text));
    if(live||v.status==="COMPLETE"){
      const comparisonStatus=v.purchase_insights?.status||"";
      const comparisonLabel={
        FUNCTIONAL_INDEX_LEADS_NEED_SPEC_VERIFICATION:
          "Functional alternatives found · verify technical specs and retailer total",
        UNIT_PRICE_LEADS_NOT_CHECKOUT:
          "Compare index unit costs · retailer total and variant unverified",
        SELECTED_PRICE_UNDERCUTS_AVAILABLE_INDEX_PEERS:
          "Input offer leads on observed price · verify checkout",
        CHEAPER_INDEX_COMPARABLE_LEADS:
          "Cheaper indexed comparable leads · prices and variants unverified",
        CHEAPER_BUT_DIFFERENT_INDEX_LEADS:
          "Cheaper indexed alternatives differ in specifications",
        COMPARABLE_INDEX_OFFERS_FOUND:
          "Comparable index offers found · no verified final price",
        INPUT_PRICE_UNKNOWN_NO_VALUE_RECOMMENDATION:
          "Selected seller price unknown · no reliable value ranking",
        NO_RELIABLE_COMPARABLE_INDEX_LEADS:
          "No reliable comparable index offers yet",
      }[comparisonStatus]||
        "Source-based assessment only · verify variant, retailer and checkout";
      target.appendChild(item("p","verdict-tag",comparisonLabel));
    }
    renderPurchaseAlternatives(target,snapshot,app,v.purchase_insights);
    const findings=(v.observations||[]).filter(x=>x&&typeof x.text==="string");
    if(findings.length){
      target.appendChild(item("h4","purchase-facts-title",
        "Key documented product specifications"));
      const group=item("div","verdict-findings");
      findings.forEach((finding,i)=>{
        const card=item("div","verdict-finding");
        card.appendChild(item("div","",finding.text));
        (finding.evidence_ids||[]).forEach((ref,j)=>{
          if(typeof ref!=="string"||
              !(snapshot.graph||{}).nodes?.some(n=>n.id===ref))return;
          const button=item("button","", "Evidence "+(j+1)+" ↗");
          button.type="button";
          button.addEventListener("click",()=>{
            const controller=app._traceCartGraphController;
            if(controller&&controller.graph.nodes.some(n=>n.id===ref))
              controller.select(ref);
          });
          card.appendChild(button);
        });
        group.appendChild(card);
      });
      target.appendChild(group);
    }
    if(v.next_step)
      target.appendChild(item("p","verdict-next","Next research step: "+v.next_step));
    target.appendChild(item("p","verdict-limits",
      "Search-title specifications and seller claims are not independent tests. "+
      "Index prices are not checkout totals. No purchase was authorized."+
      (!live && v.status==="COMPLETE" && v.coverage&&v.coverage.observations_omitted?
       " Local-model context omitted "+v.coverage.observations_omitted+
       " source observations; full audit remains available.":"")));
  }

  function boot(){
    const app=$("decision-app");
    if(!app||!window.TraceCartKnowledgeGraph)return;
    const status=$("job-state"),form=$("product-form"),button=form.querySelector("button");
    const verdictBox=$("live-verdict"),linkSafetyBox=$("link-safety");
    function setBusy(busy) {
      button.disabled=busy;
      button.classList.toggle("is-analyzing",busy);
      button.setAttribute("aria-busy",String(busy));
      $("analyze-label").textContent=busy?"Analyzing…":"Analyze";
    }
    let gotData=false,graphFingerprint="",source,lastEventAt=Date.now();
    let lastSnapshot=null;
    function show(snapshot,id){
      lastSnapshot=snapshot;
      if(id!==undefined)lastEventAt=Date.now();
      gotData=true;
      const graph=snapshot.graph;
      const fingerprint=JSON.stringify(graph&&[graph.nodes,graph.edges,
        graph.stats,graph.offer_details]);
      if(graph&&fingerprint!==graphFingerprint){
        graphFingerprint=fingerprint;
        window.TraceCartKnowledgeGraph.create(app,graph);
      }
      const stats=graph&&graph.stats||{};
      $("live-graph-count").textContent=
        (stats.offers||0)+" offers · "+
        (app.dataset.visibleGraphNodes||"0")+" evidence/offer cards · "+
        (stats.unverified_index_quotes||0)+" indexed prices inside offer cards · "+
        (stats.focused_verification_gaps||0)+" unresolved checks in audit";
      const activity=snapshot.evidence_progress||{};
      const pendingSource=Object.values(snapshot.evidence_offers||{})
        .filter(x=>["RUNNING","QUEUED"].includes(x.status)).length;
      const workingModel=Object.values(snapshot.model_offers||{})
        .filter(x=>["RUNNING","BATCH_RUNNING"].includes(x.state)).length;
      const sources=sourceTasks(snapshot),
        questions=questionTasks(snapshot,(app._traceCartGraphView||{}).focus||
          "offer-0");
      const auto=snapshot.browser_auto_batch||{};
      if(["QUEUED","COMPLETE","COMPLETE_WITH_FAILURES",
          "INTERRUPTED_ON_RESTART"].includes(auto.status)){
        sources.unshift({key:"AUTO BROWSER",title:
          (auto.status==="QUEUED"?"Automatic browser queue: ":
           auto.status==="COMPLETE"?"Completed browser checks: ":
           auto.status==="COMPLETE_WITH_FAILURES"?"Browser checks partly blocked: ":
           "Browser jobs interrupted on restart: ")+
          (auto.queued_count||0)+" page(s)",
          detail:"Browser checks start only for sites granted permissions "+
            "in Chromium. No CAPTCHA bypass or checkout.",
          mode:auto.status==="COMPLETE_WITH_FAILURES"?"BLOCKED":"REFERENCE",
          state:auto.status,weight:2});
      }else if(auto.status==="SKIPPED_QUEUE_FULL"){
        sources.unshift({key:"AUTO BROWSER",title:"Automatic browser queue is full",
          detail:"Some pages were not added. Review existing browser jobs "+
            "and retry only after they finish.",
          mode:"BLOCKED",state:"CAPACITY",weight:3});
      }
      const checks=snapshot.indexed_browser_checks||[];
      const eligible=(snapshot.offers||[]).filter(x=>
        x.kind==="INDEXED_SELLER_LINK"&&x.url).length;
      const verifyButton=$("verify-indexed-button");
      if(verifyButton){
        const working=checks.some(x=>["QUEUED","IN_PROGRESS"].includes(x.status));
        const failures=checks.filter(x=>x.status!=="PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED");
        verifyButton.disabled=eligible===0||working;
        verifyButton.textContent=working
          ?"Browser checks running · "+checks.length
          :checks.length
          ?(failures.length?"Retry "+failures.length+" failed browser visits":
             "Refresh "+checks.length+" browser seller prices")
          :eligible
          ?"Verify "+eligible+" indexed seller pages (3 parallel)"
          :"No direct seller URLs to verify";
      }
      if(checks.length){
        const complete=checks.filter(x=>x.status==="PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED").length;
        const errors=checks.filter(x=>!["QUEUED","IN_PROGRESS",
          "PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED"].includes(x.status)).length;
        sources.unshift({
          key:"BROWSER INDEX",title:complete+"/"+checks.length+
            " indexed store pages captured · "+errors+" inaccessible/failed",
          detail:"Three concurrent browser tabs maximum. Only separately authorized merchant origins are visited. Cards without seller URLs cannot be fetched.",
          state:complete===checks.length?"CAPTURED":"VERIFYING",mode:"REFERENCE"
        });
      }else if((snapshot.offers||[]).some(x=>x.kind==="INDEXED_SELLER_LINK")){
        sources.unshift({
          key:"BROWSER INDEX",title:"Store URLs ready for browser verification",
          detail:"Use the Verify indexed retailer offers button. Each shop needs its own Chrome permission; indexed prices are not current seller checks.",
          state:"AWAITING USER",mode:"QUEUED"
        });
      }
      const shopping=snapshot.shopping_search_status||"";
      const shoppingRefresh=(snapshot.shopping_refresh||{}).status||"NOT_STARTED";
      const shopButton=$("shopping-search-button");
      if(shopButton){
        const missing=shopping==="SKIPPED_NO_SERPAPI_API_KEY";
        const running=["QUEUED","RUNNING"].includes(shoppingRefresh);
        shopButton.disabled=missing||running;
        shopButton.textContent=running?"Searching Shopping index…"
          :missing?"Configure Shopping provider first"
          :"Search / refresh alternative offers";
      }
      if(shopping==="SKIPPED_NO_SERPAPI_API_KEY"||
         shopping==="SEARCH_NOT_STARTED"){
        sources.unshift({
          key:"SHOPPING",title:"No competitor search was performed",
          detail:"No Shopping-index provider is configured for this research. "+
            "Open Shopping discovery to enable it; zero alternatives here does "+
            "NOT mean competitors do not exist.",
          state:"NOT SEARCHED",mode:"BLOCKED"
        });
      }else if(shopping==="SKIPPED_DAILY_QUERY_BUDGET"){
        sources.unshift({
          key:"SHOPPING",title:"Shopping discovery paused: daily API cap",
          detail:"The local daily paid-provider request cap was reached. "+
            "Existing cached index evidence is retained.",
          state:"API CAP",mode:"BLOCKED"
        });
      }else if(shopping.startsWith("FAILED_")){
        sources.unshift({
          key:"SHOPPING",title:"Shopping provider search failed",
          detail:"Provider returned no usable data or an error. Do not "+
            "interpret this as no alternative offers.",
          state:"FAILED",mode:"BLOCKED"
        });
      }else if(shopping&&shopping!=="NOT_STARTED"){
        sources.unshift({
          key:"SHOPPING",title:"Shopping-index search: "+shopping,
          detail:"Search-index cards and seller URLs are only leads. "+
            "Browser checks require separate user-granted merchant permissions.",
          state:"INDEX SCANNED",mode:"REFERENCE"
        });
      }
      const search=snapshot.source_search||{};
      if(search.status==="RUNNING"){
        sources.unshift({key:"DISCOVERY",title:"Searching external sources",
          detail:"Bounded, provider-backed model discovery; not an evidence test.",
          state:"SEARCHING",mode:"RUNNING"});
      } else if((search.leads||[]).length){
        sources.unshift({key:"DISCOVERY",
          title:search.leads.length+" source URLs located",
          detail:"Unverified leads; each page requires independent fetch and SKU check.",
          state:"INDEX LEADS",mode:"QUEUED"});
      }
      $("live-source-count").textContent=pendingSource?
        pendingSource+" checking":String(sources.length);
      const checksDone=snapshot.state==="READY" && isTerminal(snapshot);
      $("live-question-count").textContent=checksDone?
        "Complete · 0 active":workingModel?
        questions.length+" · 1 model batch":String(questions.length);
      renderItems($("live-source-tasks"),sources);
      renderItems($("live-question-tasks"),questions);
      const phase=snapshot.progress_stage||snapshot.state||"STARTING";
      const researchDone=isTerminal(snapshot);
      // The usable source assessment is already available before optional
      // inference finishes. Keep the graph stream running, but unlock input.
      setBusy(!researchDone&&!snapshot.instant_assessment);
      renderVerdict(verdictBox,snapshot,app);
      renderLinkSafety(linkSafetyBox,snapshot);
      const finalStatus=(snapshot.final_verdict||{}).status;
      status.textContent=snapshot.state==="FAILED"?"Research failed":
        snapshot.state==="INTERRUPTED"?"Research interrupted":
        researchDone?
        ((snapshot.instant_assessment?"Evidence assessment ready":
          finalStatus==="COMPLETE"?"Verdict ready":
          finalStatus==="STALE_AFTER_SHOPPING_REFRESH"
          ?"Offers updated · old verdict stale":"Research finished")+
         " · "+(activity.processed||0)+"/"+
         (activity.planned||0)+" checked"):
        snapshot.instant_assessment&&finalStatus==="RUNNING"?
          "Evidence assessment ready · optional Qwen running":
        snapshot.instant_assessment?
          "Evidence assessment ready · research updating":
        finalStatus==="RUNNING"?"Qwen synthesizing evidence":
        finalStatus==="QUEUED"&&activity.status==="COMPLETE"?
          "Preparing final verdict":
        phase==="SOURCE_FETCH"?"Reading input page":
        snapshot.state==="READY"&&
        (snapshot.evidence_progress||{}).status==="RUNNING"?
          "Checking "+(snapshot.evidence_progress.processed||0)+"/"+
          (snapshot.evidence_progress.planned||0)+" offers":
        phase.replace(/_/g," ").toLowerCase();
      $("live-evidence-status").textContent=
        (researchDone?"Research finished · new evidence requires another run · ":"")+
        (stats.seller_page_declarations||0)+" seller-page declarations · "+
        (stats.browser_claims_not_checkout_verified||0)+" browser declarations (unverified) · "+
        (stats.independent_reference_measurements||0)+
        " independent test values · "+(stats.documented_product_declarations||0)+
        " sourced declarations · "+(stats.unresolved_source_discrepancies||0)+
        " source discrepancies · "+(stats.verified_exact_sku_answers||0)+
        " verified exact variants · "+
        (stats.verified_checkout_prices||0)+" verified checkout prices";
    }
    app.addEventListener("tracecart:selection-changed",()=>{
      if(!lastSnapshot)return;
      renderItems($("live-question-tasks"),questionTasks(lastSnapshot,
        (app._traceCartGraphView||{}).focus||"offer-0"));
    });
    window.TraceCartKnowledgeGraph.create(app,emptyGraph());
    $("live-graph-count").textContent="1 node · 0 links";
    status.textContent="Ready";
    setBusy(false);
    form.addEventListener("submit",()=>{
      // Native form POST, CSRF protection and PRG remain authoritative.
      setBusy(true);status.textContent="Starting";
    });
    if(!app.dataset.live){
      $("graph-export").hidden=true;
      $("audit-link").hidden=true;
      return;
    }
    status.textContent="Connecting";
    setBusy(true);
    // EventSource consumes same-origin server RAM snapshots and automatically
    // reconnects. Never exposes memory addresses or GPU buffers.
    if(typeof EventSource==="undefined"){
      status.textContent="Live stream unsupported";
      fetch(app.dataset.knowledgeGraph,{cache:"no-store"})
        .then(r=>r.json())
        .then(g=>show({graph:g,state:"READY",progress_stage:"RESEARCH_COMPLETE",
          evidence_progress:{},evidence_offers:{},model_offers:{}},0))
        .catch(()=>{status.textContent="Unavailable";});
      return;
    }
    // The source is authoritative, but a periodic same-origin snapshot
    // repairs stuck states after lost events or server restarts. Poll only
    // if no SSE update was received recently, not on every graph tick.
    const fallbackUrl=app.dataset.live+".json";
    let polling=false,unloaded=false;
    const refresh=setInterval(()=>{
      if(unloaded||polling||Date.now()-lastEventAt<6500)return;
      polling=true;
      fetch(fallbackUrl,{cache:"no-store"})
        .then(r=>{if(!r.ok)throw Error("live snapshot unavailable");
                  return r.json();})
        .then(snapshot=>{
          if(unloaded)return;
          show(snapshot);
          lastEventAt=Date.now();
        })
        .catch(()=>{})
        .finally(()=>{polling=false;});
    },3200);
    source=new EventSource(app.dataset.live,{withCredentials:false});
    source.addEventListener("graph",event=>{
      try{show(JSON.parse(event.data),event.lastEventId);}catch(_){
        status.textContent="Update invalid";
      }
    });
    source.addEventListener("settled",()=>{
      if(source)source.close();
      if(gotData){
        const e=(lastSnapshot||{}).evidence_progress||{};
        setBusy(false);
        const v=(lastSnapshot||{}).final_verdict||{};
        status.textContent=(lastSnapshot.state==="FAILED"?"Research failed":
          lastSnapshot.state==="INTERRUPTED"?"Research interrupted":
          (lastSnapshot.instant_assessment)?"Evidence assessment ready":
          v.status==="COMPLETE"?"Verdict ready":
          v.status==="STALE_AFTER_SHOPPING_REFRESH"
            ?"Offers updated · previous verdict needs refreshing"
            :"Research finished")+
          " · "+(e.processed||0)+"/"+(e.planned||0)+" checked";
      }
    });
    source.onerror=()=>{
      if(source.readyState===EventSource.CONNECTING)
        status.textContent=gotData?"Reconnecting":"Connecting";
      else if(source.readyState===EventSource.CLOSED)
        status.textContent="Stream disconnected";
    };
    window.addEventListener("pagehide",()=>{
      unloaded=true;clearInterval(refresh);
      if(source)source.close();
    });
  }
  if(typeof module!=="undefined"&&module.exports)
    module.exports={sourceTasks,questionTasks,emptyGraph,
      isTerminal,renderVerdict,renderLinkSafety,offerSafetyLabel,
      verdictForDisplay};
  if(typeof document!=="undefined"){
    if(document.readyState==="loading")
      document.addEventListener("DOMContentLoaded",boot,{once:true});
    else boot();
  }
})();