/* TraceCart read-only offer knowledge graph. No external framework/dependency.
 * Every edge carries a provenance type. Similar titles/values NEVER imply SKU identity.
 * The SVG draws a bounded neighborhood, while the JSON endpoint preserves ALL
 * offers, source-linked observations and their unanswered research dimensions.
 */
(function () {
  "use strict";
  const NS="http://www.w3.org/2000/svg";
  const WIDTH=1120,HEIGHT=880;
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
        const coverage=d.source_coverage||{};
        details.appendChild(el("p","kg-coverage",
          (coverage.documented_field_count||0)+" retrieved specification values · "+
          (coverage.source_documents||0)+" downloaded documents · "+
          (d.high_impact_questions||[]).length+" outstanding checks. "+
          "Published specifications and seller-page details are NOT independent tests."));
        if(d.indexed_price)
          details.appendChild(el("p","kg-quote","Index quote: "+
            d.indexed_price.value+" "+(d.indexed_price.currency||"")+
            " · NOT a current seller checkout price"));
        else details.appendChild(el("p","kg-quote","Checkout price: NOT VERIFIED"));
        if(d.url)details.appendChild(external("Open listing pointer ↗",d.url));
        if((d.claims||[]).length){
          details.appendChild(el("h4","","Title-only parameters · unverified"));
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
        }
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
        addLinkList(details,"Retrieved product data · publisher declarations",
          declared.map(a=>({
            title:(a.source_property?a.source_property+": ":"")+
                  (a.value||"Source claim"),
            note:"Published value, not lab measured · "+(a.source_kind||"unknown")+
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
        details.appendChild(el("h4","","Remaining evidence gaps · "+
          (d.high_impact_questions||[]).length));
        const ol=el("ol","kg-questions-list");
        (d.high_impact_questions||[]).slice(0,12).forEach(q=>{
          const li=el("li","",q.question);
          li.appendChild(el("small","",q.reason||
            "New evidence needed; existing documents do not answer this."));
          ol.appendChild(li);
        });
        details.appendChild(ol);
        details.appendChild(el("p","kg-footnote",
          "Source check: "+(d.source_check_status||"NOT_STARTED")+
          " · Model batch: "+(d.model_question_status||"NOT_STARTED")+
          " · Earlier generic question catalogue is not evidence or active work."));
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
      if(selected.type==="source_disagreement"){
        details.appendChild(el("span","kg-detail-type","UNRESOLVED PUBLISHED CLAIM"));
        details.appendChild(el("h3","",selected.label));
        details.appendChild(el("p","kg-missing",
          "The indexed listing and a published source, or two different sources, "+
          "disagree. This is NOT an independent measurement or proof the seller "+
          "offers the same hardware variant. Confirm exact SKU and test conditions."));
        const receipts=(byFrom.get(selected.id)||[]).filter(e=>
          e.relation==="DISCREPANCY_REQUIRES_SOURCE_REVIEW");
        const realDocs=receipts.map(e=>index.get(e.to)).filter(n=>n&&n.url);
        addLinkList(details,"Fetched documents to check",realDocs.map(n=>({
          title:n.publisher||n.label,
          note:"Downloaded source SHA256: "+(n.sha256||"").slice(0,18)+"…",
          url:n.url,
        })));
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
      if(selected.source_property)
        details.appendChild(el("p","kg-quote",
          selected.source_property+": "+(selected.value||"")));
      if(selected.reason)
        details.appendChild(el("p","kg-missing",selected.reason));
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
      // Evidence is the center of the graph, not the old 24x12 generic
      // question catalogue. Preserve the entire saved graph in JSON, but
      // show all source facts of the focused offer before unsourced leads.
      const selected=focus&&index.get(focus)&&
        index.get(focus).type==="offer"?focus:null;
      const chosen=selected||"offer-0";
      const isRelevant=new Set();
      const directRelations=new Set([
        "SELLER_PAGE_DECLARES","HAS_SOURCE_OBSERVATION",
        "HAS_DOCUMENTED_FACET","HAS_UNRESOLVED_VERIFICATION_GAP",
        "INDEXED_PRICE_CLAIM","SOURCE_DISCOVERY_LEAD",
        "SELLER_PAGE_MODEL_IDENTITY","POTENTIAL_SOURCE_DISCREPANCY",
      ]);
      (byFrom.get(chosen)||[]).forEach(e=>{
        if(directRelations.has(e.relation))isRelevant.add(e.to);
      });
      // Every property node is linked to an actual document receipt and
      // many are also grouped under an evidence facet. Do not cap at
      // 13 observations as the previous graph did.
      [...isRelevant].forEach(id=>(byFrom.get(id)||[]).forEach(e=>{
        if(["FACET_HAS_SOURCE_FACT","OBSERVED_IN_SOURCE",
            "DISCREPANCY_REQUIRES_SOURCE_REVIEW"].includes(e.relation)){
          isRelevant.add(e.to);
        }
      }));
      // Publisher claims elsewhere can contradict the input; show actual
      // discrepancies globally, never silently hide them in seller #4.
      graph.nodes.filter(n=>n.type==="source_disagreement").slice(0,3)
        .forEach(n=>isRelevant.add(n.id));
      const show=(node)=>!selected||isRelevant.has(node.id);
      const visibleOffers=selected?
        [index.get(selected),...offers.filter(n=>n.id!==selected).slice(0,5)]:
        offers;
      const facets=graph.nodes.filter(n=>(
        n.type==="evidence_facet"||n.type==="model_family")&&show(n)
      ).slice(0,12);
      const documented=graph.nodes.filter(n=>
        ["source_declaration","seller_declaration","reference_observation"]
          .includes(n.type)&&show(n)
      ).slice(0,32);
      const sources=graph.nodes.filter(n=>
        ["fetched_source","source_lead"].includes(n.type)&&show(n)
      ).slice(0,6);
      const quotes=graph.nodes.filter(n=>n.type==="indexed_quote"&&show(n))
        .slice(0,5);
      const discrepancies=graph.nodes.filter(n=>n.type==="source_disagreement"
        &&isRelevant.has(n.id)).slice(0,3);
      const questions=graph.nodes.filter(n=>n.type==="verification_gap"
        &&show(n)).slice(0,6);
      const specs=graph.nodes.filter(n=>["title_claim","derived_claim"]
        .includes(n.type));
      const linked=selected?new Set((byFrom.get(selected)||[])
        .filter(e=>["TITLE_MENTIONS","CALCULATED_FROM_TITLE_CLAIMS"]
          .includes(e.relation)).map(e=>e.to)):null;
      const shownSpecs=specs.filter(n=>!selected||linked.has(n.id))
        .slice(0,7);
      const layout=new Map();
      function column(nodes,x,y0,y1){
        nodes.forEach((n,i)=>{
          const slot=(i+.5)/Math.max(1,nodes.length);
          layout.set(n.id,{x,y:y0+(y1-y0)*slot});
        });
      }
      column(visibleOffers,92,28,837);
      column(facets,355,42,573);
      column(shownSpecs,355,630,843);
      column(documented,666,32,844);
      column(sources,976,35,225);
      column(quotes,976,239,336);
      column(discrepancies,976,351,438);
      column(questions,976,465,848);
      const relations=new Set([
        "TITLE_MENTIONS","CALCULATED_FROM_TITLE_CLAIMS",
        "HAS_DOCUMENTED_FACET","FACET_HAS_SOURCE_FACT",
        "OBSERVED_IN_SOURCE","INDEXED_PRICE_CLAIM",
        "HAS_UNRESOLVED_VERIFICATION_GAP","GAP_BLOCKS_VERIFIED_PURCHASE",
        "SELLER_PAGE_MODEL_IDENTITY","INDEX_TITLE_MATCHES_DECLARED_MODEL",
        "POTENTIAL_SOURCE_DISCREPANCY","DISCREPANCY_REQUIRES_SOURCE_REVIEW",
        "SOURCE_DISCOVERY_LEAD","DISCOVERED_PAGE_FETCHED_AND_EXTRACTED",
        "SIMILAR_INDEX_MODEL_NAME_LEAD","ARITHMETIC_INPUT",
      ]);
      const visible=edges.filter(e=>layout.has(e.from)&&layout.has(e.to)
        &&relations.has(e.relation));
      return {layout,visible};
    }

    function draw() {
      const {layout,visible}=buildLayout();
      root.dataset.visibleGraphNodes=String(layout.size);
      root.dataset.visibleGraphLinks=String(visible.length);
      const count=root.querySelector("#live-graph-count");
      if(count){
        count.textContent=(graph.stats.offers||0)+" offers · "+
          layout.size+"/"+graph.nodes.length+" nodes visible · "+
          visible.length+" displayed links";
      }
      canvas.replaceChildren();
      canvas.setAttribute("viewBox","0 0 "+WIDTH+" "+HEIGHT);
      const viewport=svg("g",{"class":"kg-canvas-group",
                                "transform":"translate("+tx+" "+ty+") scale("+scale+")"});
      const lines=svg("g",{"class":"kg-links"});
      visible.forEach(e=>{
        const a=layout.get(e.from),b=layout.get(e.to);
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
            "kg-link-warning":e.relation==="OBSERVED_IN_SOURCE"?
            "kg-link-provenance":"kg-link-evidence")+
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
        const circle=svg("circle",{"r":isOffer?(item.ordinal===1?11:8):6});
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
        let display=clip(item.label,item.type==="verification_gap"?33:36);
        if(item.type==="source_declaration")
          display=clip((item.source_property?
            item.source_property+": ":"")+(item.value||item.label),43);
        if(item.type==="evidence_facet")display=clip(item.label,29);
        if(item.type==="seller_declaration")display=clip(item.label,43);
        if(item.type==="verification_gap"){
          const missing={
            identity:"Exact model?",
            seller_variant:"Seller variant?",
            technical:"Technical specs?",
            independent_test:"Independent test?",
            operating:"Performance test?",
            contents:"Kit contents?",
            warranty:"Warranty terms?",
            repair:"Parts & repairs?",
            checkout:"Checkout total?",
            legality:"Road-use proof?",
            compatibility:"Compatibility test?",
          };
          display=missing[item.dimension]||clip(item.label,24);
        }
        if(item.type==="title_claim"||item.type==="derived_claim")
          display=clip(String(item.value)+" · "+
            (short[item.parameter]||item.parameter)+
            (item.type==="derived_claim"?" (calculated)":""),34);
        if(item.type==="indexed_quote")
          display="Index: "+clip(item.label,22);
        text.textContent=isOffer?
          "#"+String(item.ordinal).padStart(2,"0")+" "+clip(item.label,29):
          display;
        g.appendChild(text);
        if(isOffer&&item.id===focus){
          const d=graph.offer_details[item.id]||{};
          const facts=(d.source_coverage||{}).documented_field_count||0;
          const open=(d.high_impact_questions||[]).length;
          const caption=svg("text",{"x":17,"y":21,
            "class":"kg-offer-caption"});
          caption.textContent=facts+" published specs · "+open+" checks left";
          g.appendChild(caption);
        }
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
      root.dispatchEvent(new Event("tracecart:selection-changed"));
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
      focus=null;active=null;remember();showDetails(null);syncButtons();draw();
      root.dispatchEvent(new Event("tracecart:selection-changed"));});
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
