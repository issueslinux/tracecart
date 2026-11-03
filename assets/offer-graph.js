/* TraceCart read-only offer knowledge graph. No external framework/dependency.
 * Every edge carries a provenance type. Similar titles/values NEVER imply SKU identity.
 * The SVG renders ALL saved nodes in a fit-to-view overview, and JSON preserves ALL
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
  // Show all available factual observations, not repeated empty questions.
  // Open gaps and the generic abstention gate remain in the saved graph JSON
  // and evidence-gap panel, but are not rendered as SVG nodes or connections.
  // The overview is a purchase-comparison diagram, not a dump of every
  // DB index node. Prices and advertised title facts are drawn *inside*
  // their offer cards; open generic missing checks and summary price nodes
  // are not duplicated as circles. Every source-bearing node remains
  // present in the diagram or source detail drawer, and full JSON is unchanged.
  function layoutAllNodes(nodes,options={}) {
    const singleColumn=options.singleColumn===true;
    const cols=singleColumn?1:2;
    const offers=(nodes||[]).filter(n=>n.type==="offer")
      .sort((a,b)=>(Number(a.ordinal)||Number(a.id.split("-")[1])+1)-
                    (Number(b.ordinal)||Number(b.id.split("-")[1])+1));
    const evidence=(nodes||[]).filter(n=>[
      "title_claim","derived_claim","evidence_facet","model_family",
      "source_declaration","seller_declaration","reference_observation",
      "fetched_source","source_disagreement","source_lead",
    ].includes(n.type));
    const layout=new Map();
    let bottom=0;
    if(offers.length){
      const selected=offers.find(o=>o.id==="offer-0")||offers[0];
      layout.set(selected.id,{x:55,y:56,w:970,h:87,kind:"input"});
      bottom=143;
      let slot=0;
      offers.forEach(offer=>{
        if(offer.id===selected.id)return;
        const col=slot%cols,row=Math.floor(slot/cols);
        const y=196+row*112;
        layout.set(offer.id,{x:55+col*515,y,w:singleColumn?1004:475,
                             h:94,kind:"offer"});
        bottom=Math.max(bottom,y+91);
        slot++;
      });
    }
    const topEvidence=bottom+96;
    // Shared title attributes are meaningful, as are actual fetched
    // documents. A source value is NEVER dropped just for lacking a laptop
    // field or because the input is an unknown product category.
    evidence.forEach((item,i)=>{
      const col=i%cols,row=Math.floor(i/cols);
      const y=topEvidence+row*72;
      layout.set(item.id,{x:55+col*515,y,w:singleColumn?1004:475,h:60,
                           kind:"evidence"});
      bottom=Math.max(bottom,y+60);
    });
    return {layout,bounds:{width:1090,height:Math.max(880,bottom+72)},
            evidenceStart:evidence.length?topEvidence:null,
            offerCount:offers.length,
            sourceCount:evidence.length};
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
    // All is the default. Selecting an offer highlights it, never hides nodes.
    let focus=(prior.focus===null||offers.some(n=>n.id===prior.focus))?
      (prior.focus===undefined?null:prior.focus):null;
    let active=index.has(prior.active)?prior.active:null;
    let scale=Number(prior.scale)||1,tx=Number(prior.tx)||0,
        ty=Number(prior.ty)||0,drag=null;
    let autoFit=prior.autoFit!==false;
    function remember(){
      root._traceCartGraphView={focus,active,scale,tx,ty,autoFit};
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
        const sourceState=d.source_check_status||"NOT_STARTED";
        const sourceExplanation=sourceState==="NO_MATCHED_INDEPENDENT_SOURCE"?
          "No matching published facts for this listing (not proof none exist).":
          sourceState==="GENERAL_DOCUMENT_DECLARATIONS_FETCHED_SKU_UNVERIFIED"?
          "Published technical specifications found; exact SKU and tests unverified.":
          sourceState.startsWith("SOURCE_NOT_VERIFIED_")?
          "Source retrieval failed its checks; see source tasks.":
          sourceState.replace(/_/g," ").toLowerCase();
        details.appendChild(el("p","kg-footnote",
          "Source evidence: "+sourceExplanation+
          " · Missing evidence remains visible in the right-hand research panel."));
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
      const singleColumn=region.clientWidth<720;
      region.classList.toggle("kg-narrow-network",singleColumn);
      const box=layoutAllNodes(graph.nodes,{singleColumn});
      const {layout,bounds}=box;
      const relations=new Set([
        "ALTERNATIVE_INDEX_LEAD","TITLE_MENTIONS",
        "CALCULATED_FROM_TITLE_CLAIMS","HAS_DOCUMENTED_FACET",
        "FACET_HAS_SOURCE_FACT","OBSERVED_IN_SOURCE",
        "SELLER_PAGE_DECLARES","HAS_SOURCE_OBSERVATION",
        "SELLER_PAGE_MODEL_IDENTITY","INDEX_TITLE_MATCHES_DECLARED_MODEL",
        "POTENTIAL_SOURCE_DISCREPANCY","DISCREPANCY_REQUIRES_SOURCE_REVIEW",
        "SOURCE_DISCOVERY_LEAD","DISCOVERED_PAGE_FETCHED_AND_EXTRACTED",
        "SIMILAR_INDEX_MODEL_NAME_LEAD","ARITHMETIC_INPUT"
      ]);
      const visible=edges.filter(e=>layout.has(e.from)&&layout.has(e.to)
        &&relations.has(e.relation));
      return {...box,layout,visible,bounds};
    }

    function draw() {
      const {layout,visible,bounds,evidenceStart,offerCount,sourceCount}=buildLayout();
      // Use a vertically scrollable *full-size* network. Fitting 50+ nodes
      // into a single 300px-high view makes every label unreadable.
      if(autoFit){
        scale=Math.min(1.1,(WIDTH-28)/bounds.width);
        tx=(WIDTH-bounds.width*scale)/2;
        ty=12;
      }
      root.dataset.visibleGraphNodes=String(layout.size);
      root.dataset.visibleGraphLinks=String(visible.length);
      const count=root.querySelector("#live-graph-count");
      if(count){
        count.textContent=offerCount+" offers · "+
          sourceCount+" source/title facts · "+
          (graph.stats?.unverified_index_quotes||0)+
          " index prices shown on cards · open checks in audit";
      }
      canvas.replaceChildren();
      const viewHeight=Math.max(HEIGHT,Math.ceil(bounds.height*Math.max(1,scale)));
      canvas.setAttribute("viewBox","0 0 "+WIDTH+" "+viewHeight);
      const actualWidth=canvas.parentElement.clientWidth||800;
      canvas.style.height=Math.max(420,Math.ceil(actualWidth*viewHeight/WIDTH))+"px";
      canvas.style.minHeight="0";
      const viewport=svg("g",{"class":"kg-canvas-group",
        "transform":"translate("+tx+" "+ty+") scale("+scale+")"});
      const sections=svg("g",{"class":"kg-section-headings"});
      const heading=(y,label)=>{
        const text=svg("text",{"x":55,"y":y,
          "class":"kg-section-title"});
        text.textContent=label;
        sections.appendChild(text);
      };
      heading(37,"SELECTED PRODUCT");
      if(offerCount>1)heading(180,"ALTERNATIVE LISTINGS · TITLE CLAIMS, NOT VERIFIED SELLER PRICES");
      if(evidenceStart!==null)
        heading(evidenceStart-25,"ATTRIBUTES & EVIDENCE · ORIGINAL SOURCE PROVENANCE RETAINED");
      viewport.appendChild(sections);
      const lines=svg("g",{"class":"kg-links"});
      visible.forEach(e=>{
        const a=layout.get(e.from),b=layout.get(e.to);
        const alternative=e.relation==="ALTERNATIVE_INDEX_LEAD";
        const related=!focus||e.from===focus||e.to===focus||
          (active&&(e.from===active||e.to===active));
        const ax=a.x+a.w/2,ay=a.y+a.h;
        const bx=b.x+b.w/2,by=b.y;
        const path=svg("path",{
          d:"M"+ax+" "+ay+" C"+ax+" "+(ay+by)/2+" "+
            bx+" "+(ay+by)/2+" "+bx+" "+by,
          "class":"kg-link "+
             (alternative?"kg-link-alternative":
              e.relation==="TITLE_MENTIONS"?"kg-link-claim":
              e.relation==="POTENTIAL_SOURCE_DISCREPANCY"?
              "kg-link-warning":"kg-link-provenance")+
             (related?"":" kg-muted"),
          "data-relation":e.relation,
          "stroke-dasharray":alternative?"5 7":
            e.relation==="TITLE_MENTIONS"?"3 5":"none",
        });
        const tooltip=svg("title");
        tooltip.textContent=e.relation.replace(/_/g," ")+
          " · "+(e.status||"unverified");
        path.appendChild(tooltip);
        lines.appendChild(path);
      });
      viewport.appendChild(lines);
      const points=svg("g",{"class":"kg-nodes"});
      [...layout.entries()].forEach(([id,p])=>{
        const item=index.get(id),isOffer=item.type==="offer";
        const d=isOffer?graph.offer_details[id]||{}:{};
        const g=svg("g",{
          "class":"kg-node kg-card-node kg-type-"+item.type+
            (id===focus?" kg-selected":"")+
            (id===active?" kg-active":"")+
            (justAdded.has(id)?" kg-added":""),
          "role":"button","tabindex":"0",
          "aria-label":item.type+": "+item.label,
          "data-node-id":id,
          "transform":"translate("+p.x+" "+p.y+")"});
        g.appendChild(svg("rect",{
          x:0,y:0,width:p.w,height:p.h,rx:9,
          "class":"kg-card-bg"
        }));
        if(isOffer){
          const input=id==="offer-0";
          const title=svg("text",{"x":14,"y":input?44:43,
                                "class":"kg-card-title"});
          title.textContent=clip(item.label,input?76:39);
          g.appendChild(title);
          const marker=svg("text",{"x":14,"y":18,
                               "class":"kg-card-eyebrow"});
          marker.textContent=input?"INPUT · SELECTED PRODUCT":
            "#"+String(item.ordinal).padStart(2,"0")+" · SEARCH-INDEX LISTING";
          g.appendChild(marker);
          const price=d.indexed_price;
          const seenPrice=(input&&d.input_price&&d.input_price.price)?
            d.input_price.price+" "+d.input_price.currency:
            price?price.value+" "+(price.currency||""):"PRICE UNKNOWN";
          const cost=svg("text",{"x":p.w-13,"y":18,
            "text-anchor":"end","class":"kg-card-price"+
              (input?" kg-card-input-price":"")});
          cost.textContent=seenPrice;
          g.appendChild(cost);
          const values=(d.title_facts||[])
            .filter(f=>!f.key.startsWith("spec_"))
            .map(f=>f.label);
          const meaningful=values.length?values:
            (d.claims||[]).slice(0,3).map(c=>c.label+": "+c.value);
          const facts=svg("text",{"x":14,"y":input?67:67,
                              "class":"kg-card-subtitle"});
          facts.textContent=clip(meaningful.slice(0,4).join(" · ")||
            "No comparable quantity/variant declared in listing title",input?92:43);
          g.appendChild(facts);
          if(!input&&d.unit_price){
            const unit=svg("text",{"x":p.w-13,"y":p.h-8,
              "text-anchor":"end","class":"kg-card-unit"});
            unit.textContent=d.unit_price.amount+" "+d.unit_price.currency+
              "/"+d.unit_price.per+" · INDEXED ONLY";
            g.appendChild(unit);
          }
          if(input&&d.input_price){
            const inputNote=svg("text",{"x":p.w-13,"y":p.h-9,
              "text-anchor":"end","class":"kg-card-unit"});
            inputNote.textContent="Price observed; checkout NOT verified";
            g.appendChild(inputNote);
          }
        }else{
          const eyebrow=svg("text",{"x":13,"y":18,
                                  "class":"kg-card-eyebrow"});
          eyebrow.textContent=item.type.replace(/_/g," ").toUpperCase()+
            " · "+(item.claim_status==="UNVERIFIED_TITLE_LABEL"?
                   "TITLE ONLY":"SOURCE DATA");
          g.appendChild(eyebrow);
          const value=svg("text",{"x":13,"y":43,
                                   "class":"kg-card-fact"});
          const display=item.source_property?
            item.source_property+": "+(item.value||item.label):
            item.label;
          value.textContent=clip(display,44);
          g.appendChild(value);
        }
        const label=svg("title");
        label.textContent=item.label+(isOffer&&d.indexed_price?
          "\nIndex price: "+d.indexed_price.value+" "+d.indexed_price.currency:"")+
          (isOffer&&d.unit_price?
          "\nUnit quote: "+d.unit_price.amount+" "+d.unit_price.currency+
          "/"+d.unit_price.per:"");
        g.appendChild(label);
        g.addEventListener("click",()=>select(id));
        g.addEventListener("keydown",event=>{
          if(event.key==="Enter"||event.key===" "){
            event.preventDefault();select(id);
          }
        });
        points.appendChild(g);
      });
      viewport.appendChild(points);
      canvas.appendChild(viewport);
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
      autoFit=false;
      const next=Math.max(.15,Math.min(5,scale*factor));
      tx=px-(px-tx)*(next/scale);
      ty=py-(py-ty)*(next/scale);
      scale=next;remember();draw();
    }
    buttons.all.addEventListener("click",()=>{
      focus=null;active=null;autoFit=true;remember();showDetails(null);syncButtons();draw();
      canvas.parentElement.scrollTop=0;
      root.dispatchEvent(new Event("tracecart:selection-changed"));});
    buttons.input.addEventListener("click",()=>select("offer-0"));
    buttons.plus.addEventListener("click",()=>changeZoom(1.2));
    buttons.minus.addEventListener("click",()=>changeZoom(1/1.2));
    buttons.reset.addEventListener("click",()=>{
      autoFit=true;remember();draw();
      canvas.parentElement.scrollTop=0;
    });
    canvas.addEventListener("wheel",event=>{
      // Normal wheel scrolls the long graph. Ctrl/Meta+wheel zooms.
      if(!event.cancelable||(!event.ctrlKey&&!event.metaKey))return;
      event.preventDefault();
      const b=canvas.getBoundingClientRect();
      const boxHeight=Number((canvas.getAttribute("viewBox")||"").split(/\s+/)[3])||HEIGHT;
      const px=(event.clientX-b.left)*WIDTH/b.width,
            py=(event.clientY-b.top)*boxHeight/b.height;
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
      autoFit=false;
      tx=drag.tx+(event.clientX-drag.x)*WIDTH/bounds.width;
      ty=drag.ty+(event.clientY-drag.y)*HEIGHT/bounds.height;
      remember();draw();
    });
    canvas.addEventListener("pointerup",()=>{drag=null;});
    canvas.addEventListener("pointercancel",()=>{drag=null;});
    syncButtons();showDetails(active||focus);draw();remember();
    // Model findings cite these existing immutable graph node IDs; clicking
    // "Evidence" opens precisely that source/claim in the detail panel.
    root._traceCartGraphController={select,graph};
    return {select,graph,stats:groupCounts(graph)};
  }
  if(typeof window!=="undefined")window.TraceCartKnowledgeGraph={create};
  if(typeof module!=="undefined"&&module.exports)
    module.exports={clip,safeUrl,groupCounts,layoutAllNodes};
})();