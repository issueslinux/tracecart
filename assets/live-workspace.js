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
      let mode="QUEUED",label="WAITING",detail="Scheduled for source checking.";
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
          d.input_access_problem==="HTTP_403"?"HTTP 403 BLOCKED":
          restricted?"ACCESS RESTRICTED":
          failed?"PAGE NOT RETRIEVED":
          mismatch?"WRONG MODEL":
          capacity?"BROWSER CAPACITY":
          rendered?"NO STRUCTURED DATA":
          !direct.length?(d.url?"NO FETCH RECEIPT":"INDEX ONLY"):"NO PRODUCT FACTS";
        detail=label==="HTTP 403 BLOCKED"||label==="ACCESS RESTRICTED"?
          "Seller denied automated retrieval. Graphical mode does not bypass access restrictions.":
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
      },...selectedEvidence.slice(0,5),...selectedGaps.slice(0,9)];
    }
    const changed=Number(data.progress_revision)||0;
    const rotated=open.length?
      open.slice(changed%open.length).concat(open.slice(0,changed%open.length)):[];
    const lead=running.slice(0,1).concat(answered.slice(0,5))
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
    if(["COMPLETE","UNAVAILABLE","INTERRUPTED"].includes(verdict))
      return true;
    // Old durable jobs predate the verdict phase. Never retroactively
    // describe those saved reports as local LLM conclusions.
    return verdict==="NOT_SCHEDULED" &&
      snapshot.progress_stage==="PER_OFFER_MODEL_COMPLETE";
  }
  function renderVerdict(target,snapshot,app) {
    if(!target)return;
    const v=snapshot.final_verdict||{};
    const stats=(snapshot.graph||{}).stats||{};
    const legacy=snapshot.state==="READY" &&
      (!v.status||v.status==="NOT_SCHEDULED")&&isTerminal(snapshot);
    const ready=snapshot.state==="READY" &&
      ["COMPLETE","UNAVAILABLE","INTERRUPTED"].includes(v.status);
    target.hidden=!(ready||legacy);
    if(target.hidden)return;
    target.replaceChildren();
    const head=item("div","verdict-head");
    const title=v.status==="COMPLETE"?"Final evidence assessment":
      v.status==="UNAVAILABLE"?"Research complete · evidence-based summary":
      legacy?"Research result · earlier saved job":"Research interrupted";
    head.appendChild(item("strong","",title));
    const tag=item("span","verdict-tag"+(v.status==="UNAVAILABLE"?" unavailable":""),
      v.status==="COMPLETE"?"Local Qwen · conditional verdict":
      v.status==="UNAVAILABLE"?"Local Qwen timed out · source-based fallback":
      "Research from archived job");
    head.appendChild(tag);target.appendChild(head);
    const text=v.summary || (
      "Research finished. This saved job has no final local-LLM synthesis. "+
      (stats.documented_product_declarations||0)+" documented product declarations, "+
      (stats.independent_reference_measurements||0)+" independent measurements and "+
      (stats.verified_checkout_prices||0)+" confirmed checkout prices."
    );
    target.appendChild(item("p","verdict-summary",text));
    if(v.status==="COMPLETE")
      target.appendChild(item("p","verdict-tag",String(v.verdict||"").replace(/_/g," ")));
    const findings=(v.observations||[]).filter(x=>x&&typeof x.text==="string");
    if(findings.length){
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
      target.appendChild(item("p","verdict-next","Next step: "+v.next_step));
    target.appendChild(item("p","verdict-limits",
      "Product claims are not independent tests. Index prices are not checkout totals. "+
      "No payment or purchase was authorized."+
      (v.status==="COMPLETE" && v.coverage&&v.coverage.observations_omitted?
       " Local-model context omitted "+v.coverage.observations_omitted+
       " source observations; full audit remains available.":"")));
  }

  function boot(){
    const app=$("decision-app");
    if(!app||!window.TraceCartKnowledgeGraph)return;
    const status=$("job-state"),form=$("product-form"),button=form.querySelector("button");
    const verdictBox=$("live-verdict");
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
        (app.dataset.visibleGraphNodes||"0")+" nodes visible · "+
        Math.max(0,(graph.nodes||[]).length-
          Number(app.dataset.visibleGraphNodes||0))+" empty checks hidden · "+
        (app.dataset.visibleGraphLinks||"0")+" displayed links";
      const activity=snapshot.evidence_progress||{};
      const pendingSource=Object.values(snapshot.evidence_offers||{})
        .filter(x=>["RUNNING","QUEUED"].includes(x.status)).length;
      const workingModel=Object.values(snapshot.model_offers||{})
        .filter(x=>["RUNNING","BATCH_RUNNING"].includes(x.state)).length;
      const sources=sourceTasks(snapshot),
        questions=questionTasks(snapshot,(app._traceCartGraphView||{}).focus||
          "offer-0");
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
      setBusy(!researchDone);
      renderVerdict(verdictBox,snapshot,app);
      const finalStatus=(snapshot.final_verdict||{}).status;
      status.textContent=snapshot.state==="FAILED"?"Research failed":
        snapshot.state==="INTERRUPTED"?"Research interrupted":
        researchDone?
        ((finalStatus==="COMPLETE"?"Verdict ready":"Research finished")+
         " · "+(activity.processed||0)+"/"+
         (activity.planned||0)+" checked"):
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
          v.status==="COMPLETE"?"Verdict ready":"Research finished")+
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
      isTerminal,renderVerdict};
  if(typeof document!=="undefined"){
    if(document.readyState==="loading")
      document.addEventListener("DOMContentLoaded",boot,{once:true});
    else boot();
  }
})();