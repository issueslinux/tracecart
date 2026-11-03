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
      data.offer_queue.map(o=>[o.id,{title:o.title}]):Object.entries(details));
    const rows=[];
    const weight={RUNNING:0,QUEUED:1,REFERENCE:2,BLOCKED:3};
    offers.forEach(([id,d])=>{
      const entry=result[id]||{},state=entry.status;
      let mode="QUEUED",label="WAITING";
      if(state==="RUNNING"){mode="RUNNING";label="CHECKING";}
      else if(state==="QUEUED"){mode="QUEUED";label="QUEUED";}
      else if((entry.reference_answers||[]).length){
        mode="REFERENCE";label=(entry.reference_answers||[]).some(x=>
          x.source_kind==="INDEPENDENT_TEST")?"REVIEW FOUND":"SPECIFICATIONS";
      }
      else if(state){
        mode="BLOCKED";
        label=state.startsWith("INTERRUPTED")?"INTERRUPTED":"NO MATCHED SOURCE";
      }
      rows.push({
        key:"#"+(Number(id.split("-")[1])+1),
        title:d.title||"Product",
        detail:mode==="REFERENCE"?
          (label==="REVIEW FOUND"?
           "Independent review · exact retailer variant still unproven.":
           "Real product page checked · declared specifications, not tests."):
          mode==="BLOCKED"?"This exact variant still needs a source.":
          mode==="RUNNING"?"Independent source check in progress.":
          "Scheduled for source identification and checking.",
        mode,state:label,weight:weight[mode],
      });
    });
    rows.sort((a,b)=>(a.key==="#1"?-1:b.key==="#1"?1:
        a.weight-b.weight||Number(a.key.slice(1))-Number(b.key.slice(1))));
    return rows.slice(0,20);
  }
  function questionTasks(data){
    const g=data.graph||{},details=g.offer_details||{},model=data.model_offers||{};
    const running=[],open=[],answered=[],proposed=[];
    let batchReported=false;
    for(const [id,d] of Object.entries(details)){
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
        open.push({key:"#"+idx+" · P0",title:q.question,
          detail:"Source evidence required; not answered.",
          state:"OPEN",mode:"QUEUED"});
      }
    }
    // The visible queue is bounded. New offer arrivals, actual source
    // results and model updates replace old cards instead of appending
    // hundreds of formulaic questions to the page.
    const changed=Number(data.progress_revision)||0;
    const offset=open.length?changed%Math.max(1,open.length):0;
    const rotated=open.slice(offset).concat(open.slice(0,offset));
    const lead=running.slice(0,4).concat(answered.slice(0,3))
      .concat(proposed.slice(0,5));
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
  function boot(){
    const app=$("decision-app");
    if(!app||!window.TraceCartKnowledgeGraph)return;
    const status=$("job-state"),form=$("product-form"),button=form.querySelector("button");
    let gotData=false,graphFingerprint="",source,lastEventAt=Date.now();
    function show(snapshot,id){
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
        (stats.offers||0)+"/"+(stats.total_discovered_offers||stats.offers||0)+
        " offers · "+(graph.nodes||[]).length+" nodes · "+
        (graph.edges||[]).length+" links";
      const activity=snapshot.evidence_progress||{};
      const pendingSource=Object.values(snapshot.evidence_offers||{})
        .filter(x=>["RUNNING","QUEUED"].includes(x.status)).length;
      const workingModel=Object.values(snapshot.model_offers||{})
        .filter(x=>["RUNNING","BATCH_RUNNING"].includes(x.state)).length;
      const sources=sourceTasks(snapshot),questions=questionTasks(snapshot);
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
      $("live-question-count").textContent=workingModel?
        questions.length+" · 1 model batch":String(questions.length);
      renderItems($("live-source-tasks"),sources);
      renderItems($("live-question-tasks"),questions);
      const phase=snapshot.progress_stage||snapshot.state||"STARTING";
      const researchDone=snapshot.state==="READY" &&
        (snapshot.evidence_progress||{}).status==="COMPLETE" &&
        phase==="PER_OFFER_MODEL_COMPLETE";
      status.textContent=researchDone?"Ready":
        phase==="SOURCE_FETCH"?"Reading input page":
        snapshot.state==="READY"&&
        (snapshot.evidence_progress||{}).status==="RUNNING"?
          "Checking "+(snapshot.evidence_progress.processed||0)+"/"+
          (snapshot.evidence_progress.planned||0)+" offers":
        phase.replace(/_/g," ").toLowerCase();
      $("live-evidence-status").textContent=
        (stats.independent_reference_measurements||0)+
        " independent test values · "+(stats.documented_product_declarations||0)+
        " sourced declarations · "+(stats.unresolved_source_discrepancies||0)+
        " source discrepancies · "+(stats.verified_exact_sku_answers||0)+
        " verified exact variants · "+
        (stats.verified_checkout_prices||0)+" verified checkout prices";
    }
    window.TraceCartKnowledgeGraph.create(app,emptyGraph());
    $("live-graph-count").textContent="1 node · 0 links";
    status.textContent="Ready";
    form.addEventListener("submit",()=>{
      // Native form POST, CSRF protection and PRG remain authoritative.
      button.disabled=true;status.textContent="Starting";
    });
    if(!app.dataset.live){
      $("graph-export").hidden=true;
      $("audit-link").hidden=true;
      return;
    }
    status.textContent="Connecting";
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
      if(gotData)status.textContent="Ready";
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
    module.exports={sourceTasks,questionTasks,emptyGraph};
  if(typeof document!=="undefined"){
    if(document.readyState==="loading")
      document.addEventListener("DOMContentLoaded",boot,{once:true});
    else boot();
  }
})();
