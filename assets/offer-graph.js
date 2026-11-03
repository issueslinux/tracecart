/* TraceCart read-only offer knowledge graph. No external framework/dependency.
 * Every edge carries a provenance type. Similar titles/values NEVER imply SKU identity.
 * The SVG draws a bounded neighborhood, while the JSON endpoint preserves ALL
 * offers, source-linked observations and their unanswered research dimensions.
 */
(function () {
  "use strict";
  const NS="http://www.w3.org/2000/svg";
  const WIDTH=1120,HEIGHT=670;
  function el(tag,cls,label) {
    const n=document.createElement(tag);
    if(cls)n.className=cls;
    if(label!==undefined&&label!==null)n.textContent=String(label);
    return n;
  }
  function svg(tag,attrs) {
    const n=document.createElementNS(NS,tag);
    Object.keys(attrs||{}).forEach(key=>n.setAttribute(key,String(attrs[key])));
    return n;
  }
  function clip(text,max) {
    const x=String(text||"");
    return x.length>max?x.slice(0,max-1)+"…":x;
  }
  function safeUrl(raw) {
    if(typeof raw!=="string"||raw.length>1400)return null;
    try {
      const u=new URL(raw);
      if(u.protocol!=="https:"||u.username||u.password||
         u.port&&u.port!=="443"||!u.hostname||
         u.hostname.includes(":")||/^(localhost|127\.|10\.|192\.168\.|169\.254\.|0\.)/i.test(u.hostname)||
         u.hostname.endsWith(".local"))return null;
      return u.href;
    }catch(_){return null;}
  }
  function external(label,url) {
    const href=safeUrl(url);
    if(!href)return el("span","kg-no-link","External source unavailable");
    const a=el("a","kg-source-link",label);
    a.href=href;a.target="_blank";a.rel="noopener noreferrer";
    return a;
  }
  function groupCounts(graph) {
    const types={};
    (graph.nodes||[]).forEach(n=>{types[n.type]=(types[n.type]||0)+1;});
    return types;
  }
  function create(root,graph) {
    if(!graph||graph.schema_version!=="tracecart.offer-knowledge-graph.v1")
      throw Error("Unsupported knowledge graph");
    const region=root.querySelector("#knowledge-graph-region"),
          canvas=root.querySelector("#kg-svg"),
          details=root.querySelector("#kg-details"),
          stats=root.querySelector("#kg-stats");
    const index=new Map(graph.nodes.map(n=>[n.id,n]));
    const known=root._seenOfferGraphNodes||new Set();
    const justAdded=new Set(graph.nodes.filter(n=>!known.has(n.id)).map(n=>n.id));
    root._seenOfferGraphNodes=new Set(graph.nodes.map(n=>n.id));
    const layoutBox=root.querySelector(".kg-layout");
    const offers=graph.nodes.filter(n=>n.type==="offer");
    const edges=graph.edges||[];
    const byFrom=new Map(),byTo=new Map();
    edges.forEach(e=>{
      if(!byFrom.has(e.from))byFrom.set(e.from,[]);
      if(!byTo.has(e.to))byTo.set(e.to,[]);
      byFrom.get(e.from).push(e);
      byTo.get(e.to).push(e);
    });
    const prior=root._traceCartGraphView||{};
    let focus=(prior.focus===null||offers.some(n=>n.id===prior.focus))?
      (prior.focus===undefined?(offers[0]||{}).id||null:prior.focus):
      (offers[0]||{}).id||null;
    let active=index.has(prior.active)?prior.active:null;
    let scale=Number(prior.scale)||1,tx=Number(prior.tx)||0,
        ty=Number(prior.ty)||0,drag=null;
    function remember(){
      root._traceCartGraphView={focus,active,scale,tx,ty};
    }
    const summary=graph.stats||{};
    region.hidden=false;
    stats.replaceChildren();
    for(const [value,label] of [
      [summary.offers||0,"offers"],
      [summary.unique_title_claim_values||0,"distinct advertised values"],
      [summary.independent_reference_measurements||0,"unique third-party measurements"],
      [summary.verified_exact_sku_answers||0,"verified exact-SKU answers"]
    ]) {
      const box=el("div","kg-stat");
      box.appendChild(el("strong","",value));
      box.appendChild(el("span","",label));
      stats.appendChild(box);
    }
    const buttons={
      all:root.querySelector("#kg-all"), input:root.querySelector("#kg-input"),
      plus:root.querySelector("#kg-zoom-in"),minus:root.querySelector("#kg-zoom-out"),
      reset:root.querySelector("#kg-reset")
    };

    function addLinkList(container,label,values) {
      if(!values.length)return;
      container.appendChild(el("h4","",label));
      const list=el("ul","kg-source-list");
      values.forEach(v=>{
        const li=el("li");
        li.appendChild(el("strong","",v.title));
        if(v.note)li.appendChild(el("small","",v.note));
        if(v.url)li.appendChild(external("Read fetched source ↗",v.url));
        list.appendChild(li);
      });
      container.appendChild(list);
    }

    function showDetails(nodeId) {
      details.replaceChildren();
      if(root.classList.contains("live-workspace")){
        const close=el("button","kg-close","×");
        close.type="button";
        close.setAttribute("aria-label","Close details");
        close.addEventListener("click",()=>layoutBox.classList.remove("details-open"));
        details.appendChild(close);
      }
      const selected=index.get(nodeId);
      if(!selected) {
        details.appendChild(el("h3","","All offers · evidence network"));
        details.appendChild(el("p","",
          "Shared title values create comparison links, not verified product identities. Select an offer to see claims, question gaps and sources."));
        const summary=el("p","kg-missing",
          "No automatically verified winner: exact seller variant and checkout prices are not confirmed.");
        details.appendChild(summary);return;
      }
      if(selected.type==="offer"){
        const d=graph.offer_details[selected.id]||{};
        details.appendChild(el("span","kg-detail-type",
          selected.offer_kind==="INPUT_PRODUCT"?"INPUT PRODUCT":"SEARCH-INDEX OFFER"));
        details.appendChild(el("h3","",d.title||selected.label));
        details.appendChild(el("p","kg-missing",
          "Declared values below come from "+(d.claim_provenance||"an unverified title")+
          ". Neither a matching number nor brand spelling is identity proof."));
        if(d.indexed_price)
          details.appendChild(el("p","kg-quote","Index quote: "+
            d.indexed_price.value+" "+(d.indexed_price.currency||"")+
            " · NOT a current seller checkout price"));
        else details.appendChild(el("p","kg-quote","Checkout price: NOT VERIFIED"));
        if(d.url)details.appendChild(external("Open listing pointer ↗",d.url));
        details.appendChild(el("h4","","Parameters · unverified title/derived"));
        if((d.claims||[]).length){
          const tbl=el("table","kg-claim-table");
          (d.claims||[]).forEach(c=>{
            const tr=el("tr");
            tr.appendChild(el("th","",c.label));
            tr.appendChild(el("td","",String(c.value)+" · "+
              (c.status==="ARITHMETIC_FROM_UNVERIFIED_TITLE_VALUES"?
               "calculated from unverified title": "title claim, unverified")));
            tbl.appendChild(tr);
          });
          details.appendChild(tbl);
        } else details.appendChild(el("p","kg-missing",
            "No numeric configuration could be extracted from the title."));
        const original=graph.offer_details["offer-0"];
        if(original&&selected.id!=="offer-0"){
          const originalSpecs=new Map((original.claims||[]).map(c=>[c.parameter,String(c.value)]));
          const difference=(d.claims||[]).filter(c=>originalSpecs.has(c.parameter) &&
                                originalSpecs.get(c.parameter)!==String(c.value));
          if(difference.length){
            details.appendChild(el("h4","","Differences from input's stated values"));
            const diffs=el("ul","kg-source-list");
            difference.forEach(c=>diffs.appendChild(el("li","",
              c.label+": input "+originalSpecs.get(c.parameter)+" vs this index "+c.value+
              " (both claims, not tested)")));
            details.appendChild(diffs);
          }
        }
        const declared=(d.reference_observations||[]).filter(a=>
          a.source_kind!=="INDEPENDENT_TEST");
        const independent=(d.reference_observations||[]).filter(a=>
          a.source_kind==="INDEPENDENT_TEST");
        addLinkList(details,"Published product specifications · unverified variant",
          declared.map(a=>({
            title:(a.value||"Claim")+" · source declaration",
            note:"Source type: "+(a.source_kind||"unknown")+
                 " · SHA "+(a.source_sha256||"").slice(0,16)+"…",
            url:a.source_url,
          })));
        addLinkList(details,"Independent reference observations · variant check required",
          independent.map(a=>({
            title:(a.value||"Observation")+" · "+a.status,
            note:"Variant match: "+(a.variant_match||"unknown")+
                 " · SHA "+(a.source_sha256||"").slice(0,16)+"…",
            url:a.source_url,
          })));
        if((d.declared_claim_conflicts||[]).length){
          details.appendChild(el("h4","","Unresolved source discrepancies · "+
            d.declared_claim_conflicts.length));
          d.declared_claim_conflicts.forEach(c=>{
            const p=el("p","kg-missing",
              (c.type==="PUBLISHED_SOURCES_DISAGREE"?
               c.source_a_value+" vs "+c.source_b_value+" · two published sources":
               c.listing_value+" listed vs "+c.source_value+" in document")+
              " · potential model variant or methodology difference, NOT proved fraud.");
            details.appendChild(p);
            if(c.source_url)details.appendChild(external("Check source ↗",c.source_url));
          });
        }
        if((d.model_hints||[]).length){
          details.appendChild(el("h4","","Possible model leads · index only"));
          (d.model_hints||[]).forEach(h=>{
            details.appendChild(el("p","kg-missing",
              h.name+" ("+h.source_offer+") · NOT verified as the submitted SKU"));
          });
        }
        details.appendChild(el("h4","","Unresolved high-priority questions · "+
          (d.high_impact_questions||[]).length));
        const ol=el("ol","kg-questions-list");
        (d.high_impact_questions||[]).slice(0,12).forEach(q=>{
          const li=el("li","",q.question);
          li.appendChild(el("small","","OPEN · no verified exact-variant answer"));
          ol.appendChild(li);
        });
        details.appendChild(ol);
        details.appendChild(el("p","kg-footnote",
          "Full plan: "+(d.planned_question_count||0)+" source checks · "+
          "Qwen: "+(d.model_question_status||"NOT_STARTED")+
          " · Independent source: "+(d.source_check_status||"NOT_STARTED")));
        const jump=el("a","kg-jump","Open all questions for this offer ↓");
        jump.href="#offer-research-"+selected.ordinal;
        details.appendChild(jump);
        return;
      }
      if(selected.type==="title_claim"||selected.type==="derived_claim"){
        details.appendChild(el("span","kg-detail-type","ADVERTISED VALUE · NOT TESTED"));
        details.appendChild(el("h3","",selected.label));
        const incoming=byTo.get(nodeId)||[];
        const linked=incoming.filter(e=>
          ["TITLE_MENTIONS","CALCULATED_FROM_TITLE_CLAIMS"]
            .includes(e.relation));
        details.appendChild(el("p","",
          linked.length+" offer(s) contain or imply this value from their unverified titles. "+
          "They may have different brands, frames, batteries or components."));
        const list=el("ul","kg-source-list");
        linked.forEach(e=>{
          const o=index.get(e.from);
          const li=el("li");
          const b=el("button","kg-detail-offer",
            "#"+o.ordinal+" "+clip(o.label,75));
          b.type="button";b.addEventListener("click",()=>select(o.id));
          li.appendChild(b);
          li.appendChild(el("small","",e.provenance));
          list.appendChild(li);
        });
        details.appendChild(list);
        return;
      }
      if(selected.type==="research_gap"){
        details.appendChild(el("span","kg-detail-type","OPEN RESEARCH DIMENSION"));
        details.appendChild(el("h3","",selected.label));
        const incoming=(byTo.get(selected.id)||[])
          .filter(e=>e.relation==="EVIDENCE_NEEDED");
        details.appendChild(el("p","",
          incoming.length+" offers require source verification here."));
        const list=el("ul","kg-source-list");
        incoming.slice(0,33).forEach(e=>{
          const li=el("li");
          const o=index.get(e.from);
          const b=el("button","kg-detail-offer",
            "#"+o.ordinal+" "+clip(o.label,45));
          b.type="button";b.addEventListener("click",()=>select(o.id));
          li.appendChild(b);
          li.appendChild(el("small","",e.question+" · NOT ANSWERED"));
          list.appendChild(li);
        });
        details.appendChild(list);return;
      }
      details.appendChild(el("span","kg-detail-type",
        selected.type.replace(/_/g," ").toUpperCase()));
      details.appendChild(el("h3","",selected.label));
      if(selected.finding)details.appendChild(el("p","",selected.finding));
      if(selected.variant_match)
        details.appendChild(el("p","kg-missing",
          "Variant match: "+selected.variant_match));
      if(selected.status)details.appendChild(el("p","",selected.status));
      if(selected.sha256)details.appendChild(el("p","kg-footnote",
          "Saved source SHA-256: "+selected.sha256));
      if(selected.url)details.appendChild(external("Read source ↗",selected.url));
    }

    function buildLayout() {
      const specs=graph.nodes.filter(n=>n.type==="title_claim"||
                                    n.type==="derived_claim");
      const gaps=graph.nodes.filter(n=>n.type==="research_gap");
      const observations=graph.nodes.filter(n=>
        ["reference_observation","source_declaration","fetched_source",
         "source_disagreement","source_lead",
         "indexed_quote","decision_gate"].includes(n.type));
      const selected=focus&&index.get(focus)&&
        index.get(focus).type==="offer"?focus:null;
      // All offers stay visible. The right side changes according to focus.
      let shownSpecs;
      if(selected) {
        const specIds=new Set((byFrom.get(selected)||[])
          .filter(e=>["TITLE_MENTIONS","CALCULATED_FROM_TITLE_CLAIMS"]
            .includes(e.relation)).map(e=>e.to));
        shownSpecs=specs.filter(n=>specIds.has(n.id)).slice(0,12);
      } else {
        const popularity=new Map();
        edges.filter(e=>e.relation==="TITLE_MENTIONS").forEach(e=>
          popularity.set(e.to,(popularity.get(e.to)||0)+1));
        shownSpecs=specs.filter(n=>(popularity.get(n.id)||0)>=2)
          .sort((a,b)=>(popularity.get(b.id)||0)-(popularity.get(a.id)||0))
          .slice(0,12);
        if(shownSpecs.length<4)
          shownSpecs=specs.slice(0,Math.min(12,specs.length));
      }
      const gapIds=new Set();
      if(selected) (byFrom.get(selected)||[])
        .filter(e=>e.relation==="EVIDENCE_NEEDED").slice(0,7)
        .forEach(e=>gapIds.add(e.to));
      const shownGaps=selected?gaps.filter(n=>gapIds.has(n.id)):gaps.slice(0,3);
      const related=selected?(byFrom.get(selected)||[])
        .filter(e=>["HAS_SOURCE_OBSERVATION","INDEXED_PRICE_CLAIM",
                    "POTENTIAL_SOURCE_DISCREPANCY",
                    "SOURCE_DISCOVERY_LEAD"].includes(e.relation))
        .map(e=>e.to):
        observations.filter(n=>["reference_observation","source_declaration",
                       "source_disagreement","source_lead","indexed_quote"]
                       .includes(n.type)).map(n=>n.id);
      const seen=new Set(related);
      seen.add("decision:abstain");
      related.forEach(id=>(byFrom.get(id)||[])
        .filter(e=>["OBSERVED_IN_SOURCE","DISCREPANCY_REQUIRES_SOURCE_REVIEW",
                     "DISCOVERED_PAGE_FETCHED_AND_EXTRACTED"].includes(e.relation))
        .forEach(e=>seen.add(e.to)));
      const shownEvidence=observations.filter(n=>seen.has(n.id)).slice(0,13);
      const layout=new Map();
      function column(nodes,x,y0,y1) {
        nodes.forEach((n,i)=>{
          const slot=(i+.5)/Math.max(1,nodes.length);
          layout.set(n.id,{x,y:y0+(y1-y0)*slot});
        });
      }
      column(offers,114,20,640);
      column(shownSpecs,535,25,330);
      column(shownGaps,535,380,645);
      column(shownEvidence,915,45,630);
      const visible=edges.filter(e=>layout.has(e.from)&&layout.has(e.to)&&
        ["TITLE_MENTIONS","CALCULATED_FROM_TITLE_CLAIMS",
         "EVIDENCE_NEEDED","HAS_SOURCE_OBSERVATION","INDEXED_PRICE_CLAIM",
         "RESEARCH_GAP_PREVENTS_VERIFIED_DECISION",
         "POTENTIAL_SOURCE_DISCREPANCY","DISCREPANCY_REQUIRES_SOURCE_REVIEW",
         "SOURCE_DISCOVERY_LEAD","DISCOVERED_PAGE_FETCHED_AND_EXTRACTED",
         "OBSERVED_IN_SOURCE","INFORMS_DIMENSION",
         "SIMILAR_INDEX_MODEL_NAME_LEAD"].includes(e.relation));
      return {layout,visible};
    }

    function draw() {
      const {layout,visible}=buildLayout();
      canvas.replaceChildren();
      canvas.setAttribute("viewBox","0 0 "+WIDTH+" "+HEIGHT);
      const viewport=svg("g",{"class":"kg-canvas-group",
                                "transform":"translate("+tx+" "+ty+") scale("+scale+")"});
      const lines=svg("g",{"class":"kg-links"});
      visible.forEach(e=>{
        const a=layout.get(e.from),b=layout.get(e.to);
        const close=(e.relation==="TITLE_MENTIONS"||
                     e.relation==="EVIDENCE_NEEDED");
        const related=!focus||e.from===focus||e.to===focus||
          (active&&(e.from===active||e.to===active));
        const path=svg("path",{
          d:"M"+a.x+" "+a.y+" C"+(a.x+b.x)/2+" "+a.y+" "+
            (a.x+b.x)/2+" "+b.y+" "+b.x+" "+b.y,
          "class":"kg-link "+(e.relation==="TITLE_MENTIONS"||
            e.relation==="CALCULATED_FROM_TITLE_CLAIMS"?
            "kg-link-claim":e.relation==="EVIDENCE_NEEDED"||
            e.relation==="RESEARCH_GAP_PREVENTS_VERIFIED_DECISION"?
            "kg-link-gap":e.relation==="INDEXED_PRICE_CLAIM"?
            "kg-link-quote":e.relation==="POTENTIAL_SOURCE_DISCREPANCY"?
            "kg-link-warning":"kg-link-evidence")+
            (related?"":" kg-muted"),
          "data-relation":e.relation,
          "stroke-dasharray":e.relation==="TITLE_MENTIONS"||
            e.relation==="CALCULATED_FROM_TITLE_CLAIMS"?"5 4":
            e.relation==="EVIDENCE_NEEDED"?"2 5":"none"
        });
        const title=svg("title");
        title.textContent=e.relation.replace(/_/g," ")+" · "+
          (e.status||"unverified");
        path.appendChild(title);lines.appendChild(path);
      });
      viewport.appendChild(lines);
      const points=svg("g",{"class":"kg-nodes"});
      [...layout.entries()].forEach(([id,p])=>{
        const item=index.get(id), isOffer=item.type==="offer";
        const g=svg("g",{
          "class":"kg-node kg-type-"+item.type+
            (id===focus?" kg-selected":"")+
            (id===active?" kg-active":"")+
            (justAdded.has(id)?" kg-added":""),
          "role":"button","tabindex":"0",
          "aria-label":item.type+": "+item.label,
          "data-node-id":id,
          "transform":"translate("+p.x+" "+p.y+")"});
        const circle=svg("circle",{"r":isOffer?9:6});
        g.appendChild(circle);
        const text=svg("text",{"x":isOffer?17:12,"y":4});
        const short={
          power_w:"motor W",battery_ah:"battery Ah",
          battery_voltage_v:"battery V",battery_wh:"energy Wh",
          wheel_in:"wheel inches",gears:"gear count",
          speed_kmh:"claimed km/h",claimed_range_km:"range km",
          ram_gb:"RAM GB",capacity_gb:"storage GB",
          cpu_family:"CPU family",display_technology:"panel"
        };
        let display=clip(item.label,item.type==="research_gap"?37:32);
        if(item.type==="title_claim"||item.type==="derived_claim")
          display=clip(String(item.value)+" · "+
            (short[item.parameter]||item.parameter)+
            (item.type==="derived_claim"?" (calculated)":""),34);
        if(item.type==="indexed_quote")
          display="Index: "+clip(item.label,22);
        text.textContent=isOffer?
          "#"+String(item.ordinal).padStart(2,"0")+" "+clip(item.label,27):
          display;
        g.appendChild(text);
        const label=svg("title");label.textContent=item.label;
        g.appendChild(label);
        g.addEventListener("click",()=>select(id));
        g.addEventListener("keydown",event=>{
          if(event.key==="Enter"||event.key===" "){
            event.preventDefault();select(id);
          }
        });
        points.appendChild(g);
      });
      viewport.appendChild(points);canvas.appendChild(viewport);
      justAdded.clear();
    }

    function select(id) {
      if(root.classList.contains("live-workspace"))
        layoutBox.classList.add("details-open");
      active=id;
      if(index.get(id)&&index.get(id).type==="offer")focus=id;
      remember();showDetails(id);
      syncButtons();draw();
    }
    function syncButtons() {
      buttons.all.setAttribute("aria-pressed",String(!focus));
      buttons.input.setAttribute("aria-pressed",String(focus==="offer-0"));
    }
    function changeZoom(factor,px=WIDTH/2,py=HEIGHT/2) {
      const next=Math.max(.5,Math.min(3.2,scale*factor));
      tx=px-(px-tx)*(next/scale);
      ty=py-(py-ty)*(next/scale);
      scale=next;remember();draw();
    }
    buttons.all.addEventListener("click",()=>{
      focus=null;active=null;remember();showDetails(null);syncButtons();draw();});
    buttons.input.addEventListener("click",()=>select("offer-0"));
    buttons.plus.addEventListener("click",()=>changeZoom(1.2));
    buttons.minus.addEventListener("click",()=>changeZoom(1/1.2));
    buttons.reset.addEventListener("click",()=>{
      tx=0;ty=0;scale=1;remember();draw();
    });
    canvas.addEventListener("wheel",event=>{
      if(!event.cancelable)return;
      event.preventDefault();
      const b=canvas.getBoundingClientRect();
      const px=(event.clientX-b.left)*WIDTH/b.width,
            py=(event.clientY-b.top)*HEIGHT/b.height;
      changeZoom(event.deltaY<0?1.13:1/1.13,px,py);
    },{passive:false});
    canvas.addEventListener("pointerdown",event=>{
      if(event.target.closest(".kg-node"))return;
      drag={x:event.clientX,y:event.clientY,tx,ty};
      canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener("pointermove",event=>{
      if(!drag)return;
      const bounds=canvas.getBoundingClientRect();
      tx=drag.tx+(event.clientX-drag.x)*WIDTH/bounds.width;
      ty=drag.ty+(event.clientY-drag.y)*HEIGHT/bounds.height;
      remember();draw();
    });
    canvas.addEventListener("pointerup",()=>{drag=null;});
    canvas.addEventListener("pointercancel",()=>{drag=null;});
    syncButtons();showDetails(active||focus);draw();remember();
    return {select,graph,stats:groupCounts(graph)};
  }
  if(typeof window!=="undefined")window.TraceCartKnowledgeGraph={create};
  if(typeof module!=="undefined"&&module.exports)
    module.exports={clip,safeUrl,groupCounts};
})();
