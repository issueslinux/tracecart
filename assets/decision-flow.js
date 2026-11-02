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

  function mount() {
    const app=document.getElementById("decision-app");
    if (!app) return;
    const loading=document.getElementById("flow-loading"),
          status=document.getElementById("job-state");
    let polls=0;
    async function loadOnce() {
      try {
        const response=await fetch(app.dataset.source,{
          credentials:"same-origin",cache:"no-store",headers:{"Accept":"application/json"}});
        if(!response.ok) throw new Error("HTTP "+response.status);
        const data=await response.json();
        if(data.state==="QUEUED"||data.state==="RUNNING") {
          status.textContent=data.state==="QUEUED"?"Queued":"Research in progress";
          if(++polls<=MAX_POLLS) setTimeout(loadOnce,POLL_MS);
          else {
            loading.replaceChildren(node("h2","","Research still in progress"),
              node("p","","Reload this page to check again. No duplicate purchase or request was made."));
          }
          return;
        }
        if(data.state!=="READY") {
          status.textContent="Unavailable";
          loading.replaceChildren(node("h2","","Research failed"),
            node("p","",String(data.error_type||"Unknown error")));
          return;
        }
        status.textContent="Complete";
        document.getElementById("status-indicator").style.backgroundColor="#6faf8d";
        data.audit_url=app.dataset.audit;
        renderEvidence(data); renderGraph(data);
        loading.hidden=true;
      } catch(_) {
        status.textContent="Connection error";
        loading.replaceChildren(node("h2","","Cannot load saved research"),
          node("p","","Check the local TraceCart server and refresh this page."));
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
