/* TraceCart / decision explorer. No dependencies, LLM-generated answers,
   external scripts, remote telemetry, checkout or automatic user consent. */
(function () {
  "use strict";

  const STATES = {
    SIMILAR: "SIMILAR_TECHNICAL_TIER_INDEX_ONLY",
    POSSIBLE: "POSSIBLE_ALTERNATIVE_NEEDS_SPEC_CHECK"
  };
  const POLL_MS = 1800;
  const MAX_POLLS = 110;

  function money(value, currency) {
    // Number(null) and Number("") are zero. A missing price must NOT be
    // rendered as a free offer or an actual 0.00 checkout amount.
    if (value === null || value === undefined || value === "" || value === false) {
      return "Brak ceny";
    }
    const n = Number(value);
    if (!Number.isFinite(n) || n <= 0) return "Brak ceny";
    return new Intl.NumberFormat("pl-PL", {
      minimumFractionDigits: 2, maximumFractionDigits: 2
    }).format(n) + " " + (currency || "");
  }

  function safeHref(url) {
    if (typeof url !== "string" || url.length > 1400) return null;
    if (/^\/cart\/status\/[A-Za-z0-9_-]{18,40}\/audit$/.test(url)) {
      return url;
    }
    try {
      const parsed = new URL(url);
      if (parsed.protocol !== "https:" ||
          parsed.username || parsed.password) return null;
      if (!parsed.hostname || parsed.hostname === "localhost" ||
          parsed.hostname === "127.0.0.1") return null;
      return parsed.href;
    } catch (err) {
      return null;
    }
  }

  function prioritize(data, answers) {
    const candidates = Array.isArray(data.candidates) ? data.candidates : [];
    const category = data.category;
    const goal = answers.priority || "balanced";
    const usage = answers.usage || "";
    const compatibility = answers.compatibility || "unknown";
    const acceptable = candidates.filter(function (c) {
      return Number.isFinite(Number(c.price)) && Number(c.price) > 0 &&
        (c.tier === STATES.SIMILAR || c.tier === STATES.POSSIBLE) &&
        !(c.price_warnings && c.price_warnings.length);
    });
    let options = acceptable.slice();
    const notes = [];
    if (category === "LAPTOP" && compatibility === "x86") {
      options = options.filter(c => c.cpu_architecture === "x86");
      notes.push("Wymagasz x86. Wskazówki ARM/Snapdragon nie są wybierane jako zamienniki.");
    } else if (category === "LAPTOP" && compatibility === "unknown") {
      notes.push("Zgodność Twojego oprogramowania z ARM/Snapdragon pozostaje nieustalona.");
    }
    if (category === "LAPTOP" && goal === "screen") {
      options = options.filter(c => c.specs && c.specs.display_technology === "OLED");
      notes.push("Wybrałeś OLED; indeks nie podaje technologii ekranu wszystkich laptopów.");
    }
    if (category === "LAPTOP" && usage === "demanding") {
      notes.push("Nie ma niezależnych testów GPU/wydajności dla wymagających aplikacji i gier.");
    }
    if (category === "E_BIKE" && (goal === "quality" || usage === "trails")) {
      notes.push("Brak niezależnych testów hamulców, baterii i serwisu wybranych rowerów.");
    }
    const fit = c => Number(c.technical_fit) || 0;
    const price = c => Number(c.price);
    options.sort(function (a, b) {
      if (goal === "price") {
        return price(a) - price(b) || fit(b) - fit(a);
      }
      if (goal === "screen") {
        return fit(b) - fit(a) || price(a) - price(b);
      }
      const tierA = a.tier === STATES.SIMILAR ? 0 : 1;
      const tierB = b.tier === STATES.SIMILAR ? 0 : 1;
      if (tierA !== tierB) return tierA - tierB;
      // Within comparable bands (10 heuristic points), price breaks ties.
      return Math.floor(fit(b) / 10) - Math.floor(fit(a) / 10) ||
             price(a) - price(b) || fit(b) - fit(a);
    });

    const candidate = options.length ? options[0] : null;
    const userConfirmed = answers.verification === "yes";
    const sellerPriceKnown = data.evidence &&
       data.evidence.selected_seller_price !== null &&
       data.evidence.selected_seller_price !== undefined;
    let outcome;
    let title;
    let explanation;
    if (!candidate) {
      outcome = "INSUFFICIENT_COMPARABLE_EVIDENCE";
      title = "Nie ma dość dowodów na konkretny wybór";
      explanation = "W tej ścieżce potrzebna jest oferta spełniająca wybrane warunki. Możesz zmienić odpowiedź lub sprawdzić produkty ze źródeł.";
    } else if (!userConfirmed) {
      outcome = "HOLD_FOR_PRICE_AND_SELLER_VERIFICATION";
      title = "Najpierw zweryfikuj ofertę";
      explanation = "Oto kandydat zgodny z Twoimi odpowiedziami. Cena pochodzi z wyszukiwarki; zanim zapłacisz, potwierdź ją oraz wariant i warunki u sprzedawcy.";
    } else {
      outcome = "CONDITIONAL_SHORTLIST_NOT_A_PURCHASE_AUTHORIZATION";
      title = "Kandydat do rozważenia — decyzja warunkowa";
      explanation = "Zaznaczyłeś, że sprawdziłeś cenę osobiście. TraceCart nie potwierdził tej deklaracji ani jakości produktu; przed wyborem porównaj gwarancję i rzeczywiste specyfikacje.";
    }
    if (!sellerPriceKnown) {
      notes.push("Cena początkowego produktu jest nieznana — nie obliczamy oszczędności względem niego.");
    }
    if (category === "LAPTOP" && usage === "demanding") {
      outcome = "HOLD_FOR_PERFORMANCE_EVIDENCE";
      title = "Wstrzymaj wybór do testu wydajności";
    }
    notes.push("Żadna cena konkurenta nie została tu potwierdzona w koszyku.");
    notes.push("Nie wykonano niezależnych testów jakości ani zakupu.");
    return {
      outcome, title, explanation, candidate,
      alternatives: options.slice(1, 4), notes,
      buyer_claimed_verification: userConfirmed,
      price_check_performed_by_tracecart: false,
      payment_authorized: false
    };
  }

  function node(tag, className, text) {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (text !== undefined && text !== null) result.textContent = String(text);
    return result;
  }

  function anchor(label, url, className) {
    const link = safeHref(url);
    if (!link) return node("span", className || "unavailable-link", "Brak potwierdzonego adresu");
    const a = node("a", className || "", label);
    a.href = link;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    return a;
  }

  function connector() {
    const container = node("div", "graph-connector");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 60 40");
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", "M30 0 V33");
    svg.appendChild(path);
    container.appendChild(svg);
    return container;
  }

  function fork() {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.classList.add("fork-svg");
    svg.setAttribute("viewBox", "0 0 720 30");
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("aria-hidden", "true");
    const line = document.createElementNS("http://www.w3.org/2000/svg", "path");
    line.setAttribute("d", "M360 0 V12 H120 V30 M360 12 V30 M360 12 H600 V30");
    svg.appendChild(line);
    return svg;
  }

  function progress(data, answers) {
    const total = Array.isArray(data.questions) ? data.questions.length : 0;
    const count = data.questions.filter(q => answers[q.id] !== undefined).length;
    return String(count) + " / " + String(total);
  }

  function renderQuestion(q, stepNumber, picked, answerHandler, editHandler) {
    const wrap = node("section", "graph-node question-node");
    const head = node("div", "question-header");
    head.appendChild(node("span", "question-num", "PYTANIE " + String(stepNumber).padStart(2, "0")));
    head.appendChild(node("small", "", "ODPOWIEDŹ UŻYTKOWNIKA"));
    wrap.appendChild(head);
    const body = node("div", "question-body");
    body.appendChild(node("h3", "", q.title));
    body.appendChild(node("p", "", q.detail));
    body.appendChild(fork());
    const choices = node("div", "choice-grid");
    choices.setAttribute("role", "group");
    choices.setAttribute("aria-label", q.title);
    for (const [index, option] of q.choices.entries()) {
      const chosen = picked === option.value;
      const btn = node("button", "choice-btn");
      btn.type = "button";
      btn.dataset.value = option.value;
      btn.dataset.picked = chosen ? "true" : "false";
      if (picked !== undefined) btn.disabled = true;
      btn.appendChild(node("span", "choice-key", String.fromCharCode(65 + index)));
      btn.appendChild(node("strong", "", option.label));
      btn.appendChild(node("small", "", option.hint));
      if (picked === undefined) {
        btn.addEventListener("click", () => answerHandler(q.id, option.value));
      }
      choices.appendChild(btn);
    }
    body.appendChild(choices);
    if (picked !== undefined) {
      const pickedOption = q.choices.find(c => c.value === picked);
      const review = node("div", "choice-review");
      review.appendChild(node("span", "", "WYBRANO → " +
        (pickedOption ? pickedOption.label : "Odpowiedź")));
      const edit = node("button", "", "Zmień odpowiedź ↶");
      edit.type = "button";
      edit.addEventListener("click", () => editHandler(q.id));
      review.appendChild(edit);
      body.appendChild(review);
    }
    wrap.appendChild(body);
    return wrap;
  }

  function renderFinal(data, answers, restart) {
    const verdict = prioritize(data, answers);
    const final = node("section", "final-card");
    final.appendChild(node("span", "outcome-tag", "OSTATECZNY WNIOSEK / WARUNKOWY"));
    final.appendChild(node("h2", "", verdict.title));
    final.appendChild(node("p", "", verdict.explanation));
    const candidate = verdict.candidate;
    if (candidate) {
      const block = node("div", "selected-candidate");
      block.appendChild(node("span", "flow-tag", "KANDYDAT BADAWCZY · " + candidate.source));
      block.appendChild(node("strong", "", candidate.title));
      block.appendChild(node("span", "price", money(candidate.price, candidate.currency)));
      block.appendChild(node("small", "",
        "Cena zaindeksowana, niezweryfikowana; zgodność opisów " +
        String(candidate.technical_fit) + "/100 (to NIE wynik testu jakości)."));
      const link = safeHref(candidate.link);
      if (link) block.appendChild(anchor("Sprawdź ofertę / wyszukaj w sklepie ↗",
                                          link, "alt-link"));
      final.appendChild(block);
    }
    final.appendChild(node("h3", "", "Co musi zostać sprawdzone"));
    const notes = node("ul");
    verdict.notes.forEach(note => notes.appendChild(node("li", "", note)));
    final.appendChild(notes);
    const actions = node("div", "action-row");
    const repeat = node("button", "action-button", "Zmień odpowiedzi ↶");
    repeat.type = "button";
    repeat.addEventListener("click", restart);
    actions.appendChild(repeat);
    actions.appendChild(anchor("Zobacz pełne źródła ↗",
      data.audit_url || "", "action-link secondary"));
    final.appendChild(actions);
    return final;
  }

  function renderAlternatives(data) {
    const list = document.getElementById("alternatives-cards");
    list.replaceChildren();
    const candidates = data.candidates || [];
    if (!candidates.length) {
      list.appendChild(node("p", "empty-list",
        "W indeksie mogą być produkty, lecz za mało danych technicznych, aby je rzetelnie zakwalifikować. Pełna lista jest w audycie."));
      return;
    }
    const wrapper = node("div", "alternative-list");
    candidates.slice(0, 9).forEach(function (c, i) {
      const item = node("article", "alternative-item");
      item.appendChild(node("div", "alt-index", String(i+1).padStart(2, "0")));
      const main = node("div");
      main.appendChild(node("h3", "alt-title", c.title));
      const kind = c.tier === STATES.SIMILAR ?
        "Zbliżone deklarowane parametry" : "Potrzebne dodatkowe parametry";
      const cpu = c.specs && c.specs.cpu_family ? " · " + c.specs.cpu_family : "";
      main.appendChild(node("p", "alt-summary", c.source + " · " + kind + cpu));
      if (c.link) main.appendChild(anchor(
        c.source_kind === "INDEXED_STORE_LINK" ? "Strona sklepu ↗" :
        "Szukaj w Google Shopping ↗", c.link, "alt-link"));
      if (c.price_warnings && c.price_warnings.length) {
        main.appendChild(node("p", "alt-warning", c.price_warnings.join(". ")));
      }
      item.appendChild(main);
      const aside = node("div", "alt-price", money(c.price,c.currency));
      aside.appendChild(node("small", "", "tylko indeks"));
      item.appendChild(aside);
      wrapper.appendChild(item);
    });
    list.appendChild(wrapper);
  }

  function renderEvidence(data) {
    const e = data.evidence || {};
    const show = (id,val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val === undefined || val === null ? "—" : String(val);
    };
    show("stat-cards",e.google_shopping_cards);
    show("stat-store-links",e.indexed_store_links);
    show("stat-verified",e.seller_confirmed_competitor_prices);
    show("stat-alternatives",e.unverified_similar_product_leads);
    const note = document.getElementById("counts-note");
    note.textContent =
      "Dawne catalog_alternatives_found = " + String(e.catalog_only || 0) +
      " dotyczy tylko katalogu OPF, nie " +
      String(e.google_shopping_cards || 0) + " kart wyszukiwarki. " +
      String(e.indexed_store_links || 0) +
      " linki do sklepów są indeksowane, nie potwierdzone zakupowo.";
    const warnings = document.getElementById("risk-list");
    warnings.replaceChildren();
    (data.warnings || []).slice(0, 6).forEach(w =>
      warnings.appendChild(node("li", "", w)));
    if (!warnings.childNodes.length) warnings.appendChild(node("li","",
      "Brak niezależnego potwierdzenia ceny i jakości."));
    renderAlternatives(data);
    document.getElementById("alternatives-region").hidden = false;
  }

  function renderGraph(data, answers) {
    const graph = document.getElementById("decision-graph");
    graph.replaceChildren();
    const intro = node("section", "graph-node graph-origin");
    intro.appendChild(node("span", "flow-tag", "PUNKT WYJŚCIA / TWÓJ PRODUKT"));
    intro.appendChild(node("h2", "", data.display_title || data.title));
    const detail = node("p", "alt-summary",
      data.source_provenance + " · " +
      (data.evidence.selected_seller_price === null ?
        "Cena w sklepie nieodczytana" :
        "Cena z odczytu: " + money(data.evidence.selected_seller_price,
                                   data.evidence.selected_currency)));
    intro.appendChild(detail);
    const footer = node("div", "origin-footer");
    footer.appendChild(node("span", "",
      String(data.evidence.google_shopping_cards || 0) +
      " kart indeksowych · " + String(data.evidence.indexed_store_links || 0) +
      " linki do ofert · 0 zakupowo potwierdzonych cen"));
    if (data.selected_url) footer.appendChild(anchor("Produkt źródłowy ↗",
                                               data.selected_url));
    intro.appendChild(footer);
    graph.appendChild(intro);

    const questions = data.questions || [];
    for (let index = 0; index < questions.length; index++) {
      const q = questions[index];
      graph.appendChild(connector());
      const answered = answers[q.id];
      graph.appendChild(renderQuestion(q,index+1,answered,
        function (id, value) {
          answers[id] = value;
          // Later nodes were never answered because choices are sequential.
          for (let idx=index+1;idx<questions.length;idx++) {
            delete answers[questions[idx].id];
          }
          renderGraph(data, answers);
        },
        function (id) {
          for (let idx=index;idx<questions.length;idx++) {
            delete answers[questions[idx].id];
          }
          renderGraph(data, answers);
        }));
      if (answered === undefined) break;
    }
    const allAnswered = questions.length > 0 &&
      questions.every(q => answers[q.id] !== undefined);
    document.getElementById("flow-counter").textContent = progress(data,answers);
    const finish = document.getElementById("flow-final");
    finish.replaceChildren();
    if (allAnswered) {
      finish.appendChild(connector());
      finish.appendChild(renderFinal(data,answers,function () {
        Object.keys(answers).forEach(key => delete answers[key]);
        renderGraph(data, answers);
      }));
      finish.hidden = false;
    } else {
      finish.hidden = true;
    }
    graph.hidden = false;
  }

  function mount() {
    const app = document.getElementById("decision-app");
    if (!app) return;
    const source = app.dataset.source;
    const load = document.getElementById("flow-loading");
    const status = document.getElementById("job-state");
    let pollCount = 0;
    async function loadOnce() {
      try {
        const response = await fetch(source,{credentials:"same-origin",
          cache:"no-store",headers:{"Accept":"application/json"}});
        if (!response.ok) throw new Error("HTTP " + response.status);
        const data = await response.json();
        if (data.state === "QUEUED" || data.state === "RUNNING") {
          status.textContent = data.state === "QUEUED" ? "W kolejce" : "Trwa analiza";
          if (++pollCount <= MAX_POLLS) {
            setTimeout(loadOnce, POLL_MS);
          } else {
            load.replaceChildren(node("h2","","Dłuższe oczekiwanie na źródła"),
              node("p","","Nie uruchomiliśmy ponownego zakupu ani wyszukiwania."));
            const retry = node("button","action-button","Sprawdź wynik ponownie");
            retry.addEventListener("click",function () {pollCount=0;loadOnce();});
            load.appendChild(retry);
          }
          return;
        }
        if (data.state !== "READY") {
          status.textContent = "Brak wyniku";
          load.replaceChildren(node("h2","","Analiza niedostępna"),
            node("p","","Zadanie zakończyło się błędem: " +
              String(data.error_type || "nieznany") + ". Możesz spróbować ponownie."));
          return;
        }
        status.textContent = "Gotowa";
        document.getElementById("status-indicator").style.backgroundColor="#6faf8d";
        data.audit_url = app.dataset.audit;
        renderEvidence(data);
        renderGraph(data,{});
        load.hidden = true;
      } catch (error) {
        status.textContent = "Błąd odczytu";
        load.replaceChildren(node("h2","","Nie udało się odczytać wyniku"),
          node("p","","Połączenie z lokalnym serwerem zostało przerwane. Treść źródeł pozostaje zapisana."));
        const retry = node("button","action-button","Spróbuj ponownie");
        retry.type="button";
        retry.addEventListener("click",loadOnce);
        load.appendChild(retry);
      }
    }
    loadOnce();
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {prioritize, money, safeHref, STATES};
  }
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded",mount);
    } else {
      mount();
    }
  }
})();
