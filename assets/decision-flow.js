/* TraceCart: autonomous, evidence-first decision tree. No buyer questionnaire. */
(function () {
  "use strict";
  const POLL_MS = 1800, MAX_POLLS = 110;

  function money(value, currency) {
    if (value === null || value === undefined || value === "" || value === false)
      return "Price unavailable";
    const n = Number(value);
    if (!Number.isFinite(n) || n <= 0) return "Price unavailable";
    return new Intl.NumberFormat("en-GB", {
      minimumFractionDigits: 2, maximumFractionDigits: 2
    }).format(n) + " " + (currency || "");
  }

  function safeHref(url) {
    if (typeof url !== "string" || url.length > 1400) return null;
    if (/^\/cart\/status\/[A-Za-z0-9_-]{18,40}\/audit$/.test(url)) return url;
    try {
      const p = new URL(url);
      if (p.protocol !== "https:" || p.username || p.password ||
          !p.hostname || p.port && p.port !== "443" ||
          /^(localhost|127\.|10\.|192\.168\.|169\.254\.|0\.)/i.test(p.hostname) ||
          /\.local$/i.test(p.hostname) || p.hostname.includes(":")) return null;
      return p.href;
    } catch (_) { return null; }
  }

  function node(tag, className, label) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (label !== undefined && label !== null) el.textContent = String(label);
    return el;
  }
  function anchor(label, href, className) {
    const safe = safeHref(href);
    if (!safe) return node("span", "unavailable-link", "Source link unavailable");
    const a = node("a", className || "alt-link", label);
    a.href = safe; a.rel = "noopener noreferrer"; a.target = "_blank";
    return a;
  }
  function connector() {
    const div = node("div", "graph-connector");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 60 40"); svg.setAttribute("aria-hidden", "true");
    const line = document.createElementNS("http://www.w3.org/2000/svg", "path");
    line.setAttribute("d", "M30 0 V33");
    svg.appendChild(line); div.appendChild(svg); return div;
  }

  function validCandidates(data) {
    return (Array.isArray(data.candidates) ? data.candidates : []).filter(c =>
      Number.isFinite(Number(c.price)) && Number(c.price) > 0 &&
      (!c.price_warnings || c.price_warnings.length === 0) &&
      (c.tier === "SIMILAR_TECHNICAL_TIER_INDEX_ONLY" ||
       c.tier === "POSSIBLE_ALTERNATIVE_NEEDS_SPEC_CHECK")
    ).sort((a,b) =>
      (Number(b.technical_fit) || 0) - (Number(a.technical_fit) || 0) ||
      Number(a.price) - Number(b.price));
  }

  function automaticVerdict(data) {
    const candidates = validCandidates(data);
    const distinct = [];
    if (data.category === "LAPTOP") {
      // ARM and x86 serve different software requirements: show both,
      // never silently choose one on behalf of the buyer.
      for (const architecture of ["ARM", "x86"]) {
        const matching = candidates.find(c => c.cpu_architecture === architecture);
        if (matching) distinct.push(matching);
      }
    } else if (candidates.length) {
      distinct.push(candidates[0]);
    }
    return {
      status: "ABSTAIN_UNVERIFIED_PRICE_AND_VARIANT",
      shortlist: distinct,
      reason: (data.research && data.research.conclusion &&
               data.research.conclusion.reason) ||
        "Exact variants and checkout prices have not been independently verified.",
      price_check_performed_by_tracecart: false,
      payment_authorized: false
    };
  }

  function renderAlternatives(data) {
    const target = document.getElementById("alternatives-cards");
    target.replaceChildren();
    if (!data.candidates || !data.candidates.length) {
      target.appendChild(node("p", "empty-list",
        "No sufficiently described alternatives. See the full source audit."));
      return;
    }
    const wrapper = node("div", "alternative-list");
    data.candidates.slice(0, 9).forEach(function (c,i) {
      const item = node("article", "alternative-item");
      item.appendChild(node("div", "alt-index", String(i+1).padStart(2,"0")));
      const main = node("div");
      main.appendChild(node("h3", "alt-title", c.title));
      main.appendChild(node("p", "alt-summary",
        (c.source || "Unknown source") + " · " +
        (c.cpu_architecture || "Architecture unknown") +
        " · Listing-title comparison only; not a quality score"));
      if (c.link) main.appendChild(anchor("Inspect source ↗", c.link));
      if (c.price_warnings && c.price_warnings.length)
        main.appendChild(node("p","alt-warning",c.price_warnings.join("; ")));
      item.appendChild(main);
      const price = node("div", "alt-price", money(c.price, c.currency));
      price.appendChild(node("small", "", "unverified index quote"));
      item.appendChild(price);
      wrapper.appendChild(item);
    });
    target.appendChild(wrapper);
    document.getElementById("alternatives-region").hidden = false;
  }

  function renderEvidence(data) {
    const e = data.evidence || {};
    for (const [id, value] of [
      ["stat-cards",e.google_shopping_cards],
      ["stat-store-links",e.indexed_store_links],
      ["stat-verified",e.seller_confirmed_competitor_prices],
      ["stat-alternatives",e.unverified_similar_product_leads]
    ]) document.getElementById(id).textContent =
      value === null || value === undefined ? "—" : String(value);
    document.getElementById("counts-note").textContent =
      "Legacy OPF catalog: " + (e.catalog_only || 0) +
      " identities. Google Shopping: " + (e.google_shopping_cards || 0) +
      " cards and " + (e.indexed_store_links || 0) +
      " indexed seller links. None is a confirmed checkout price.";
    const warnings = document.getElementById("risk-list");
    warnings.replaceChildren();
    (data.warnings || []).slice(0,6).forEach(w =>
      warnings.appendChild(node("li","",w)));
    if (!warnings.childNodes.length)
      warnings.appendChild(node("li","","Exact SKU, quality and checkout price require independent evidence."));
    renderAlternatives(data);
  }

  function renderResearchNode(q, step, sources) {
    const section = node("section","graph-node question-node");
    const header = node("div","question-header");
    header.appendChild(node("span","question-num","RESEARCH " + String(step).padStart(2,"0")));
    header.appendChild(node("small","",q.verdict || "OPEN"));
    section.appendChild(header);
    const body = node("div","question-body");
    body.appendChild(node("h3","",q.question));
    body.appendChild(node("p","",q.finding || "No verified answer in the saved sources."));
    const refs = node("div","action-row");
    (q.source_ids || []).forEach(id => {
      const source = sources.find(s=>s.id===id);
      if (source)
        refs.appendChild(anchor(source.publisher+" — "+source.kind+" ↗",
                               source.url,"action-link secondary"));
    });
    if (refs.childNodes.length) body.appendChild(refs);
    body.appendChild(node("small","",
      "Evidence status: "+q.verdict+" · Origin: "+q.origin+" · No buyer input requested"));
    section.appendChild(body);
    return section;
  }

  function renderConclusion(data) {
    const verdict=automaticVerdict(data);
    const section=node("section","final-card");
    section.appendChild(node("span","outcome-tag","RESEARCH CONCLUSION · NO PURCHASE AUTHORIZATION"));
    section.appendChild(node("h2","","No verified best buy yet"));
    section.appendChild(node("p","",verdict.reason));
    if (verdict.shortlist.length) {
      section.appendChild(node("h3","","Provisional configuration leads (not winners)"));
      verdict.shortlist.forEach(c => {
        const block=node("div","selected-candidate");
        block.appendChild(node("span","flow-tag",
          (c.cpu_architecture||"Unknown")+" · "+(c.source||"Index only")));
        block.appendChild(node("strong","",c.title));
        block.appendChild(node("span","price",money(c.price,c.currency)+" — index only"));
        if (c.link) block.appendChild(anchor("Inspect the indexed lead ↗",c.link));
        section.appendChild(block);
      });
    }
    section.appendChild(node("p","",
      "No price was checked at checkout. Independent tests of a different panel, battery or CPU are not measurements of this retailer SKU."));
    section.appendChild(anchor("Open full research audit ↗",
      data.audit_url||"","action-link secondary"));
    return section;
  }

  function renderGraph(data) {
    const graph = document.getElementById("decision-graph");
    graph.replaceChildren(); graph.hidden=false;
    const intro = node("section","graph-node graph-origin");
    intro.appendChild(node("span","flow-tag","INPUT PRODUCT · UNVERIFIED SELLER CLAIMS"));
    intro.appendChild(node("h2","",data.display_title||data.title));
    intro.appendChild(node("p","alt-summary",
      (data.source_provenance||"Unknown provenance")+" · "+
      money(data.evidence && data.evidence.selected_seller_price,
            data.evidence && data.evidence.selected_currency)));
    if (data.selected_url) intro.appendChild(anchor("Submitted product ↗",data.selected_url));
    graph.appendChild(intro);
    const research=data.research||{}, questions=research.questions||[],
          sources=research.sources||[];
    document.getElementById("flow-counter").textContent="0 / "+questions.length;
    const finish=document.getElementById("flow-final");
    finish.replaceChildren(); finish.hidden=true;
    // Autonomous progressive research path; there are no choice buttons and
    // no fabricated LLM answers. Every finding is grounded or OPEN.
    let i=0;
    const advance=()=>{
      if(i<questions.length) {
        graph.appendChild(connector());
        graph.appendChild(renderResearchNode(questions[i],i+1,sources));
        i++;
        document.getElementById("flow-counter").textContent=i+" / "+questions.length;
        setTimeout(advance,120);
      } else {
        finish.appendChild(connector());
        finish.appendChild(renderConclusion(data)); finish.hidden=false;
      }
    };
    advance();
  }

  // Show an actual source-directed plan immediately, even when the worker
  // is still fetching a slow seller page or waiting on a local LLM.
  function renderStaged(data) {
    const graph = document.getElementById("decision-graph");
    graph.replaceChildren(); graph.hidden = false;
    const product = node("section","graph-node graph-origin");
    product.appendChild(node("span","flow-tag","SOURCE RESEARCH STARTED"));
    product.appendChild(node("h2","",data.title || "Investigating submitted URL"));
    if (data.selected_url) product.appendChild(anchor("Source product ↗",data.selected_url));
    graph.appendChild(product);
    const stage = (data.progress_stage || "QUEUED").replace(/_/g," ");
    const intro = node("section","graph-node question-node");
    intro.appendChild(node("h3","",stage));
    intro.appendChild(node("p","",
      "Research begins with questions, not a buyer questionnaire. Planned checks are not completed tests. New product and offer evidence will appear here as it becomes available."));
    graph.appendChild(connector()); graph.appendChild(intro);
    document.getElementById("flow-counter").textContent="LIVE";
    document.getElementById("flow-final").hidden=true;
  }

  function renderOfferQueue(data, sourceUrl) {
    const target = document.getElementById("offer-research-cards");
    const offers = data.offers || [];
    target.replaceChildren();
    if (!offers.length) return;
    const total = offers.reduce((n,o)=>n+(o.question_count||0),0);
    document.getElementById("offer-plan-count").textContent =
      offers.length+" offers · "+new Intl.NumberFormat("en-GB").format(total)+
      " planned investigations · 0 confirmed answers from this plan";
    const url = sourceUrl.replace(/\.decision\.json$/, "/questions.json");
    offers.forEach((offer, index) => {
      const card=node("article","offer-research-card");
      card.id="offer-research-"+(index+1);
      const heading=node("div","offer-research-heading");
      const label=node("strong","",offer.title);
      heading.appendChild(label);
      heading.appendChild(node("span","offer-question-count",offer.question_count+" source questions"));
      card.appendChild(heading);
      card.appendChild(node("p","alt-summary",
        offer.source+" · "+offer.kind+" · "+
        money(offer.indexed_price,offer.currency)+
        " · Price unverified · Question status: PLANNED, not answered"));
      if (offer.url) card.appendChild(anchor("View indexed source ↗",offer.url));
      if(Array.isArray(offer.listing_title_claims) &&
         offer.listing_title_claims.length) {
        const facts=node("section","offer-title-hypotheses");
        facts.appendChild(node("h4","","Listing-title clues — NOT verified product facts"));
        const ul=node("ul");
        offer.listing_title_claims.forEach(c=>
          ul.appendChild(node("li","",c.display)));
        facts.appendChild(ul);
        const hints=offer.index_model_hints || [];
        if(hints.length) {
          facts.appendChild(node("h4","","Related model names in search-index titles"));
          hints.forEach(h=>{
            facts.appendChild(node("p","",
              h.model_hint+" — "+h.source_offer+
              " · indexed alternative only, NOT identity proof for this seller SKU."));
          });
        }
        const diagnostic=offer.research_diagnostics || {};
        (diagnostic.scenarios || []).forEach(sc=>{
          facts.appendChild(node("p","scenario-note",
            sc.assumption+": "+
            sc.energy_wh+" Wh; if "+sc.advertised_range_km+
            " km, implied "+sc.implied_wh_per_km+
            " Wh/km. HYPOTHETICAL, not measured."));
        });
        card.appendChild(facts);
      }
      const list=node("div","offer-question-scroll");
      const questions=node("ol","offer-question-list");
      const sentinel=node("p","offer-pagination-status","Loading first questions…");
      list.appendChild(questions); list.appendChild(sentinel);
      card.appendChild(list);
      const evidenceBox = node("section","offer-evidence-findings");
      evidenceBox.appendChild(node("small","",
        "Independent-source checks: pending. No exact-SKU result verified."));
      card.appendChild(evidenceBox);
      const modelBox = node("section","offer-llm-questions");
      modelBox.appendChild(node("small","",
        "Local LLM follow-up: not yet available. Questions do not count as evidence."));
      card.appendChild(modelBox);
      target.appendChild(card);
      let next=0, busy=false, done=false, observer;
      async function loadBatch() {
        if (busy || done) return;
        busy=true; sentinel.textContent="Loading next research questions…";
        try {
          const query=new URLSearchParams({
            offer:String(index), offset:String(next),limit:"24"
          });
          const response=await fetch(url+"?"+query,{
            credentials:"same-origin",cache:"no-store",
            headers:{"Accept":"application/json"}});
          if(!response.ok) throw new Error("HTTP "+response.status);
          const page=await response.json();
          if(page.offer_id!==offer.id || !Array.isArray(page.questions))
            throw new Error("Mismatched question page");
          page.questions.forEach(q=>{
            const li=node("li","offer-question-item");
            li.appendChild(node("span","question-priority",q.priority+" · "+q.status));
            li.appendChild(node("p","",q.question));
            if(q.finding) {
              li.appendChild(node("p","reference-observation",q.finding));
              if(q.evidence && q.evidence.source_url)
                li.appendChild(anchor("Verified page ↗",q.evidence.source_url));
            }
            questions.appendChild(li);
          });
          next=page.next_offset;
          done=next===null;
          sentinel.textContent=done ?
            "All "+page.total+" planned questions displayed. Verified answers: 0." :
            questions.childElementCount+" / "+page.total+" questions loaded · scroll to continue";
          if(done && observer) observer.disconnect();
        } catch(_) {
          sentinel.textContent="Question page unavailable; research will remain pending.";
          done=true;
          if(observer) observer.disconnect();
        } finally {busy=false;}
      }
      // No button or user choice. Fetch in small batches, automatically
      // continuing when the individual offer's scroll viewport reaches end.
      if(typeof IntersectionObserver!=="undefined") {
        observer=new IntersectionObserver(entries=>{
          if(entries.some(e=>e.isIntersecting)) loadBatch();
        },{root:list,threshold:0});
        observer.observe(sentinel);
      }
      loadBatch();
    });
  }

  function refreshDocumentedEvidence(data) {
    const cards=document.getElementById("offer-research-cards").children;
    const found=data.evidence_offers || {};
    const progress=data.evidence_progress || {};
    let total=0, exact=0;
    const distinct=new Set();
    Object.keys(found).forEach(id=>{
      const items=found[id].reference_answers||[];
      total+=items.length;
      items.forEach(item=>distinct.add((item.source_sha256||"")+
        ":"+(item.source_method||"")+":"+(item.value||"")));
      exact+=found[id].verified_for_exact_offer||0;
    });
    const totalPlanned=(data.offers||[]).reduce((n,o)=>n+(o.question_count||0),0);
    document.getElementById("offer-plan-count").textContent=
      (data.offers||[]).length+" offers · "+
      new Intl.NumberFormat("en-GB").format(totalPlanned)+" planned checks · "+
      distinct.size+" distinct independent measurements ("+
      total+" offer-linked references) · "+exact+" verified exact-SKU answers";
    for(let i=0;i<cards.length;i++) {
      const target=cards[i].querySelector(".offer-evidence-findings");
      if(!target) continue;
      const result=found["offer-"+i];
      if(!result) {
        target.textContent="Independent-source checks: "+
          (progress.status||"NOT_STARTED").replace(/_/g," ").toLowerCase();
        continue;
      }
      const signature=JSON.stringify([result.status,result.reference_answers]);
      if(target.dataset.signature===signature) continue;
      target.dataset.signature=signature;
      target.replaceChildren();
      const observations=result.reference_answers||[];
      const message=observations.length ?
        observations.length+" independent reference observations · NOT verified for the offered SKU" :
        data.category==="E_BIKE" ?
          "Independent review not retrieved · brand, exact model and battery configuration still require verification" :
          "No independently matched document collected for this exact model";
      target.appendChild(node("h4","",message));
      if(observations.length) {
        const ul=node("ul","evidence-observation-list");
        observations.forEach(e=>{
          const li=node("li");
          li.appendChild(node("p","",e.finding));
          li.appendChild(node("small","",
            "Offer-to-review match: "+e.variant_match.replace(/_/g," ")));
          li.appendChild(node("small","",
            e.reviewed_variant+" · Retrieved "+e.retrieved_at+
            " · SHA-256 "+e.source_sha256.slice(0,16)+"…"));
          li.appendChild(anchor(e.publisher+" — independently fetched ↗",
            e.source_url,"action-link secondary"));
          ul.appendChild(li);
        });
        target.appendChild(ul);
      } else {
        target.appendChild(node("small","",result.status.replace(/_/g," ")));
      }
    }
  }

  function refreshModelQuestions(data) {
    const cards=document.getElementById("offer-research-cards").children;
    const found=data.model_offers || {};
    for(let i=0;i<cards.length;i++) {
      const target=cards[i].querySelector(".offer-llm-questions");
      if(!target) continue;
      const result=found["offer-"+i];
      if(!result) continue;
      const label=result.state==="OK" ?
        "LOCAL LLM · "+result.questions.length+" source questions · not answered" :
        result.state==="RUNNING" ? "LOCAL LLM · composing source follow-ups…" :
        "LOCAL LLM · unavailable (invalid response or timeout); structured research plan remains available";
      if(target.dataset.signature===label) continue;
      target.dataset.signature=label;
      target.replaceChildren(node("h4","",label));
      if(result.state==="OK") {
        const list=node("ol");
        (result.questions||[]).forEach(q=>
          list.appendChild(node("li","",q.question)));
        target.appendChild(list);
      }
    }
  }

  async function renderKnowledgeGraph(app) {
    if(!app.dataset.knowledgeGraph||!window.TraceCartKnowledgeGraph)return;
    try {
      const response=await fetch(app.dataset.knowledgeGraph,{
        credentials:"same-origin",cache:"no-store",headers:{"Accept":"application/json"}});
      if(!response.ok)throw Error("Graph HTTP "+response.status);
      const graph=await response.json();
      window.TraceCartKnowledgeGraph.create(app,graph);
    } catch(_) {
      const region=document.getElementById("knowledge-graph-region");
      region.hidden=false;
      const body=document.getElementById("kg-details");
      body.replaceChildren(node("p","kg-missing",
        "Offer graph temporarily unavailable; original research and audit remain accessible."));
    }
  }

  function mount() {
    const app=document.getElementById("decision-app");
    if (!app) return;
    const loading=document.getElementById("flow-loading"),
          status=document.getElementById("job-state");
    let polls=0, lastStage="",lastOffers=-1,finished=false;
    renderStaged({
      title:app.dataset.productUrl || "Product received",
      selected_url:app.dataset.productUrl || null,
      progress_stage:"URL_ACCEPTED"
    });
    loading.hidden=true;
    // The first tree is visible before the first network response.
    async function loadOnce() {
      if (finished) return;
      try {
        const response=await fetch(app.dataset.source,{
          credentials:"same-origin",cache:"no-store",headers:{"Accept":"application/json"}});
        if(!response.ok) throw new Error("HTTP "+response.status);
        const data=await response.json();
        if(data.state==="QUEUED"||data.state==="RUNNING") {
          const stage=data.progress_stage||data.state;
          status.textContent=stage.replace(/_/g," ").toLowerCase();
          if(stage!==lastStage) {
            renderStaged(data); lastStage=stage;
          }
          const count=(data.offers||[]).length;
          if(count!==lastOffers) {
            renderOfferQueue(data,app.dataset.source);
            lastOffers=count;
          }
          if(++polls<=MAX_POLLS) setTimeout(loadOnce,polls<12?450:POLL_MS);
          else {
            status.textContent="Research continues";
            setTimeout(()=>{polls=0;loadOnce();},4000);
          }
          return;
        }
        if(data.state!=="READY") {
          finished=true;
          status.textContent="Unavailable";
          const graph=document.getElementById("decision-graph");
          graph.appendChild(node("p","alt-warning",
            "Research failed: "+String(data.error_type||"Unknown error")+
            ". No evidence was invented and no purchase was made."));
          return;
        }
        finished=true;
        status.textContent="Complete";
        document.getElementById("status-indicator").style.backgroundColor="#6faf8d";
        data.audit_url=app.dataset.audit;
        renderEvidence(data);
        renderGraph(data);
        renderOfferQueue(data,app.dataset.source);
        refreshModelQuestions(data);
        refreshDocumentedEvidence(data);
        renderKnowledgeGraph(app);
        if(data.model_progress_stage==="PER_OFFER_MODEL_QUEUED" ||
           (data.evidence_progress||{}).status==="RUNNING") {
          let followups=0;
          const updateSources=async()=>{
            if(++followups>130) return;
            try {
              const res=await fetch(app.dataset.source,{
                credentials:"same-origin",cache:"no-store"});
              if(res.ok) {
                const latest=await res.json();
                refreshModelQuestions(latest);
                refreshDocumentedEvidence(latest);
                if(latest.model_progress_stage!=="PER_OFFER_MODEL_QUEUED" &&
                   (latest.evidence_progress||{}).status!=="RUNNING") {
                  renderKnowledgeGraph(app);
                  return;
                }
              }
            } catch(_) {}
            setTimeout(updateSources,2400);
          };
          setTimeout(updateSources,2400);
        }
      } catch(_) {
        status.textContent="Source connection retry";
        if(++polls<=MAX_POLLS) setTimeout(loadOnce,1200);
      }
    }
    loadOnce();
  }
  if(typeof module!=="undefined"&&module.exports)
    module.exports={automaticVerdict,validCandidates,money,safeHref};
  if(typeof document!=="undefined") {
    if(document.readyState==="loading")
      document.addEventListener("DOMContentLoaded",mount);
    else mount();
  }
})();
