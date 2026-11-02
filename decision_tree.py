"""Evidence-first, auditable purchase research tree.

Inputs are externally collected offer/review excerpts. This module NEVER crawls
the web, invents reviews, or treats an AI-generated question as a verified fact.
The critic independently marks unsupported/conflicted claims and opens follow-ups.
All decision branches are preserved in a portable JSON/HTML tree.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from html import escape
import json
import re
import secrets
import sqlite3
from urllib.parse import urlsplit

MAX_OFFERS = 20
MAX_QUESTIONS = 60
MAX_EVIDENCE = 12
MAX_FOLLOWUPS = 100
MAX_DOC_BYTES = 70000


def _safe_url(value):
    if not isinstance(value, str) or len(value) > 1200:
        raise ValueError("URL required, maximum 1200 characters")
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or
            parsed.username or parsed.password or parsed.port not in (None, 80, 443)):
        raise ValueError("Only valid HTTP(S) source URLs without credentials")
    return value


def _short(value, limit=300):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("Nonempty text required (up to {})".format(limit))
    return value.strip()


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,50}", value):
        raise ValueError("IDs must be short alphanumeric strings")
    return value


def _dec(value):
    if not isinstance(value, str):
        raise ValueError("Price must be a string, not a floating-point estimate")
    try:
        d = Decimal(value)
    except InvalidOperation:
        raise ValueError("Invalid price")
    if not d.is_finite() or d < 0 or d > Decimal("1000000"):
        raise ValueError("Invalid price range")
    if d.as_tuple().exponent < -2:
        raise ValueError("Price supports at most two decimal places")
    return str(d.quantize(Decimal("0.01")))


def _node(kind, title, status, details=None, children=None, node_id=None):
    return {
        "id": node_id or secrets.token_hex(8), "kind": kind, "title": title,
        "status": status, "details": details or {}, "children": children or [],
    }


def _followup(qid, question, purpose, evidence_ids, origin):
    # The follow-up is an OPEN research task. It never includes an invented answer.
    return _node("follow_up", question, "OPEN",
                 {"trigger_question_id": qid, "evidence_ids": evidence_ids,
                  "purpose": purpose, "origin": origin})


def _offer_questions(category):
    base = [
        ("price", "Is the advertised total price independently verifiable?", 5),
        ("condition", "Does the listing disclose condition and defects?", 5),
        ("seller", "Are there reliable, independent signals about the seller?", 4),
        ("returns", "Are return and dispute conditions documented?", 4),
        ("alternatives", "Are there comparable, better-value listings?", 3),
    ]
    if "laptop" in category.lower() or "computer" in category.lower():
        base += [
            ("battery", "Is battery health confirmed for this exact unit?", 5),
            ("thermals", "Are thermal issues reported for this exact configuration?", 4),
        ]
    elif "ceramic" in category.lower() or "antique" in category.lower():
        base += [
            ("authenticity", "Is maker attribution supported by independent evidence?", 5),
            ("restoration", "Does the item have undisclosed restoration or damage?", 4),
        ]
    return base


def _valid_question(q):
    if not isinstance(q, dict):
        raise ValueError("Question object required")
    qid = _id(q.get("id"))
    statement = _short(q.get("text"), 400)
    importance = q.get("importance", 3)
    if type(importance) is not int or not 1 <= importance <= 5:
        raise ValueError("Question importance must be integer 1..5")
    sources = q.get("evidence", [])
    if not isinstance(sources, list) or len(sources) > MAX_EVIDENCE:
        raise ValueError("Too many evidence records")
    return qid, statement, importance, sources


def _publisher_key(url):
    """Conservative same-registrant grouping for common country-code suffixes.

    This is NOT a full public-suffix database. If in doubt, the analysis only
    treats two sources as separate publishers when their registrable-ish
    domains differ, which still does NOT guarantee editorial independence.
    """
    host = urlsplit(url).hostname.lower().strip(".")
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    if labels[-2:] in (["co", "uk"], ["com", "au"], ["com", "br"],
                       ["com", "pl"], ["co", "jp"]):
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _evaluate_evidence(qid, sources, origin_ids):
    children = []
    support = []
    contra = []
    seen = set()
    publisher_seen = set()
    for entry in sources:
        if not isinstance(entry, dict):
            raise ValueError("Evidence record must be object")
        eid = _id(entry.get("id"))
        if eid in origin_ids:
            raise ValueError("Duplicate evidence ID")
        origin_ids.add(eid)
        stance = entry.get("stance")
        if stance not in ("supports", "contradicts"):
            raise ValueError("Evidence stance must be supports or contradicts")
        href = _safe_url(entry.get("url"))
        snippet = _short(entry.get("excerpt"), 1000)
        source_type = entry.get("source_type", "unknown")
        if source_type not in ("listing", "review", "forum", "manufacturer",
                               "test", "seller", "document", "unknown"):
            raise ValueError("Unknown source type")
        source_key = href.lower().rstrip("/")
        publisher = _publisher_key(href)
        duplicates = source_key in seen
        duplicate_publisher = publisher in publisher_seen
        seen.add(source_key)
        publisher_seen.add(publisher)
        details = {
            "source_id": eid, "source_url": href, "source_type": source_type,
            "excerpt": snippet, "duplicate_url": duplicates,
            "publisher_domain": publisher, "duplicate_publisher": duplicate_publisher,
            "observation": _short(entry.get("observation", "Source excerpt"), 300)
        }
        if "sha256" in entry:
            if not isinstance(entry["sha256"], str) or not re.fullmatch(
                    r"[a-f0-9]{64}", entry["sha256"]):
                raise ValueError("Invalid source content hash")
            details["source_content_sha256"] = entry["sha256"]
        if "retrieved_at" in entry:
            timestamp = _short(entry["retrieved_at"], 45)
            if not re.fullmatch(r"20\d\d-\d\d-\d\dT[0-9:.+\-]+", timestamp):
                raise ValueError("Invalid source retrieval timestamp")
            details["retrieved_at"] = timestamp
        if "extraction_method" in entry:
            details["extraction_method"] = _short(entry["extraction_method"], 80)
        child = _node("evidence", "Evidence " + eid, stance.upper(),
                      details, node_id="source-" + eid)
        children.append(child)
        (support if stance == "supports" else contra).append((eid, publisher))
    positive_publishers = set(domain for _, domain in support)
    if support and contra:
        verdict = "CONFLICTED"
        reason = "Evidence supports and contradicts this claim."
    elif contra:
        verdict = "REFUTED"
        reason = "Supplied evidence contradicts this claim."
    elif len(positive_publishers) >= 2:
        verdict = "CORROBORATED"
        reason = "At least two different publisher domains support the claim; editorial independence still requires review."
    elif support:
        verdict = "SINGLE_SOURCE"
        reason = "Only one publisher domain supports the claim, including possible mirrored URLs."
    else:
        verdict = "UNANSWERED"
        reason = "No source evidence was supplied."
    critic = []
    if verdict != "CORROBORATED":
        implicated = [x for x, _ in (support + contra)]
        suggestions = {
            "CONFLICTED": ("Why do sources disagree and which applies to this exact item?",
                          "Find primary documentation or a directly comparable independent test."),
            "REFUTED": ("Can the contradicted claim be ruled out for this exact item?",
                        "Find counterevidence or verify the defect before relying on this offer."),
            "SINGLE_SOURCE": ("Can an independent source verify the same claim?",
                              "Seek a genuinely independent, attributable source."),
            "UNANSWERED": ("What external evidence is needed to answer this question?",
                           "Retrieve a primary source or reliable independent test."),
        }
        title, purpose = suggestions[verdict]
        challenge = _node("critic", "Critic: " + reason, "UNRESOLVED",
                          {"target_question_id": qid,
                           "evidence_ids": implicated, "challenge": title})
        challenge["children"].append(_followup(
            qid, title, purpose, implicated, "rule_based_critic"))
        critic.append(challenge)
    return verdict, reason, children + critic, len(support), len(contra)


def _model_proposals(raw, allowed_qids):
    """Model proposes only *unanswered* follow-up questions; it cannot create facts."""
    if raw is None:
        return []
    if type(raw) is not list or len(raw) > MAX_FOLLOWUPS:
        raise ValueError("Too many generated questions")
    result = []
    seen = set()
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) not in (
                {"trigger_question_id", "text"},
                {"trigger_question_id", "text", "origin"},
                {"trigger_question_id", "text", "origin", "selection"}):
            raise ValueError("Generated questions must include trigger and text")
        selection = entry.get("selection", "SELECTED")
        if selection not in ("SELECTED", "REJECTED_BUDGET"):
            raise ValueError("Invalid question selection")
        origin = entry.get("origin", "external_question_proposal")
        if origin not in ("external_question_proposal", "model_researcher", "model_critic"):
            raise ValueError("Invalid question origin")
        parent = _id(entry["trigger_question_id"])
        if parent not in allowed_qids:
            raise ValueError("Model generated a question for an unknown evidence issue")
        title = _short(entry["text"], 250)
        if not title.endswith("?"):
            raise ValueError("Generated follow-up must be a question")
        key = (parent, title.casefold())
        if key in seen:
            continue
        seen.add(key)
        result.append((parent, title, origin, selection))
    return result


def analyze(payload):
    """Create a complete tree, without hiding missing evidence or critic objections.

    No quantitative 'best product' claim is made from incomplete or biased inputs.
    """
    if not isinstance(payload, dict):
        raise ValueError("Analysis input must be a JSON object")
    if set(payload) - {"goal", "category", "offers", "generated_questions", "model_failures"}:
        raise ValueError("Unexpected analysis fields")
    goal = _short(payload.get("goal"), 300)
    category = _short(payload.get("category"), 80)
    offers = payload.get("offers")
    if not isinstance(offers, list) or not 1 <= len(offers) <= MAX_OFFERS:
        raise ValueError("Provide between 1 and 20 offers")
    root = _node("research", goal, "IN_PROGRESS", {
        "category": category,
        "scope": "Only provided offers and excerpts, no web retrieval was performed",
        "method": "rule_based_questions_and_independent_critic",
        "no_automatic_purchase": True,
    }, node_id="research-root")
    failures = payload.get("model_failures", [])
    if (not isinstance(failures, list) or len(failures) > 2 or
            any(type(x) is not dict or set(x) != {"role", "error_type"}
                or x.get("role") not in ("researcher", "critic")
                or not isinstance(x.get("error_type"), str)
                or not re.fullmatch(r"[A-Za-z]{2,35}", x["error_type"])
                for x in failures)):
        raise ValueError("Invalid model failure provenance")
    if failures:
        root["details"]["model_role_failures"] = failures
    criteria = _offer_questions(category)
    all_ids = set()
    all_qids = set()
    verdicts = {}
    question_nodes = {}
    for offer in offers:
        if not isinstance(offer, dict):
            raise ValueError("Offer must be object")
        if set(offer) - {"id", "title", "price", "currency", "url", "questions"}:
            raise ValueError("Unexpected offer fields")
        oid = _id(offer.get("id"))
        if oid in all_ids:
            raise ValueError("Duplicate offer id")
        all_ids.add(oid)
        price = _dec(offer.get("price"))
        currency = offer.get("currency")
        if currency not in ("USD", "PLN", "EUR"):
            raise ValueError("Supported research currencies: USD, PLN, EUR")
        url = _safe_url(offer.get("url"))
        title = _short(offer.get("title"), 180)
        offer_node = _node("offer", title, "RESEARCHED", {
            "offer_id": oid, "price": price, "currency": currency, "source_url": url,
        }, node_id="offer-" + oid)
        questions = offer.get("questions", [])
        if not isinstance(questions, list) or len(questions) > MAX_QUESTIONS:
            raise ValueError("Too many questions")
        # Include base criteria as unanswered rather than silently skipping them.
        definitions = {key: (label, importance, []) for key, label, importance in criteria}
        for q in questions:
            key, label, importance, evidence = _valid_question(q)
            if key in definitions and definitions[key][2]:
                raise ValueError("Duplicate question key")
            if key in definitions and key in (x.get("id") for x in questions if x is not q):
                raise ValueError("Duplicate question")
            definitions[key] = (label, importance, evidence)
        stats = {}
        for key, (label, importance, evidence) in definitions.items():
            qid = oid + "-" + key
            if qid in all_qids:
                raise ValueError("Duplicate question identifier")
            all_qids.add(qid)
            verdict, reason, children, ns, nc = _evaluate_evidence(qid, evidence, all_ids)
            qnode = _node("question", label, verdict, {
                "question_id": qid, "importance": importance,
                "support_count": ns, "contradiction_count": nc,
                "reason": reason, "derived_from": "category_rules_or_supplied_question"
            }, children, node_id="question-" + qid)
            offer_node["children"].append(qnode)
            question_nodes[qid] = qnode
            stats[qid] = {"verdict": verdict, "importance": importance}
        verdicts[oid] = stats
        root["children"].append(offer_node)
    proposals = _model_proposals(payload.get("generated_questions"), all_qids)
    proposal_review = []
    for qid, question, origin, selection in proposals:
        node = question_nodes[qid]
        matching_offer = next(
            o for o in root["children"] if o["kind"] == "offer"
            and node in o["children"])
        existing = {q["title"].casefold() for q in matching_offer["children"]
                    if q["kind"] == "question"}
        existing |= {child["title"].casefold()
                     for q in matching_offer["children"] if q["kind"] == "question"
                     for child in q["children"] if child["kind"] == "follow_up"}
        review = {"trigger_question_id": qid, "question": question, "origin": origin}
        if selection == "REJECTED_BUDGET":
            review["result"] = "REJECTED_BUDGET"
        elif question.casefold() in existing:
            review["result"] = "REJECTED_DUPLICATE"
        else:
            review["result"] = "OPEN_QUESTION_ADDED"
            node["children"].append(_followup(
                qid, question,
                "Search external offers, tests or reviews to answer this question.",
                [], origin))
        proposal_review.append(review)
    if proposal_review:
        root["children"].append(_node(
            "question_review", "Review of generated questions",
            "AUDIT_ONLY", {"candidates": proposal_review},
            node_id="question-review"))
    unresolved = {
        oid: [key for key, value in stats.items() if value["verdict"] != "CORROBORATED"]
        for oid, stats in verdicts.items()
    }
    # A source count does not establish product quality or model calibration.
    root["children"].append(_node(
        "decision", "Purchase decision / next step", "ABSTAIN",
        {"recommendation": "No purchase recommendation until material gaps and critic objections are reviewed.",
         "unresolved_by_offer": unresolved,
         "criterion_count_by_offer": {k: len(v) for k, v in verdicts.items()},
         "reason": "Evidence completeness is insufficient; do not turn source-count into a utility score.",
         "eligible_for_payment": False,
         "model_generated_questions": len(proposals)},
        node_id="decision-final"))
    root["status"] = "INVESTIGATED_WITH_OPEN_QUESTIONS"
    result = {"schema_version": 1,
              "generated_at": datetime.now(timezone.utc).isoformat(),
              "root": root, "all_questions_preserved": True,
              "provenance": "External excerpts supplied by the analyst; NOT independently fetched",
              "limitations": ["Source snippets are input claims, not independently validated.",
                              "Distinct URLs need not represent independent publishers.",
                              "Critic flags gaps; it does not confirm product defects."]}
    digest = sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    result["sha256"] = digest
    return result



def generate_question_proposals(report, role="researcher",
                                url="http://127.0.0.1:11435",
                                model="qwen2.5:1.5b-instruct"):
    """Use a local AI to propose questions, NEVER sources/answers or final verdicts.

    The critic and research agent are separate prompting roles and both outputs
    are constrained by a deterministic schema and existing question IDs.
    """
    if role not in ("researcher", "critic"):
        raise ValueError("Unknown model role")
    if url not in ("http://127.0.0.1:11435", "http://127.0.0.1:11434"):
        raise ValueError("Only explicitly approved local Ollama endpoints")
    from core import _request_json
    questions = []
    for offer in report["root"]["children"]:
        if offer["kind"] != "offer":
            continue
        for q in offer["children"]:
            if q["kind"] != "question":
                continue
            detail = q["details"]
            evidence = [
                {"source_id": n["details"]["source_id"],
                 "stance": n["status"],
                 "excerpt": n["details"]["excerpt"][:220]}
                for n in q["children"] if n["kind"] == "evidence"
            ]
            questions.append({"question_id": detail["question_id"],
                              "title": q["title"], "status": q["status"],
                              "evidence": evidence})
    priority = {"CONFLICTED": 0, "SINGLE_SOURCE": 1, "REFUTED": 2,
                "UNANSWERED": 3, "CORROBORATED": 4}
    questions.sort(key=lambda q: (priority.get(q["status"], 5),
                                  -len(q["evidence"]), q["question_id"]))
    # Avoid flooding a small local model with every unanswered baseline criterion.
    questions = questions[:8]
    prompt = (
        "You are an independent adversarial CRITIC. Challenge unsupported "
        "conclusions and conflicting evidence using falsifiable, answerable "
        "questions about external sources. Do not invent evidence. "
        if role == "critic" else
        "You are a RESEARCH agent. Generate novel answerable follow-up "
        "questions for external offers, reviews, independent tests and "
        "sources. Do not ask the buyer questions. Do not invent findings. "
    )
    prompt += ('Return STRICT JSON with the structure '
               '{"questions":[{"trigger_question_id":"EXISTING_ID",'
               '"text":"A concrete question?"}]}; at most four. '
               'Only use existing IDs. No explanations, conclusions or sources.')
    message = {
        "model": model, "stream": False, "format": "json",
        "options": {"temperature": 0, "num_predict": 280},
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(questions[:100], ensure_ascii=False)[:12000]},
        ]
    }
    response = _request_json(url + "/api/chat", "POST",
                             json.dumps(message).encode("utf-8"),
                             {"Content-Type": "application/json"}, timeout=55)
    raw = json.loads(response["message"]["content"])
    if not isinstance(raw, dict) or set(raw) != {"questions"}:
        raise ValueError("Model questions response must contain only questions")
    entries = raw["questions"]
    if not isinstance(entries, list) or len(entries) > 20:
        raise ValueError("Model returned too many questions")
    validated = _model_proposals(entries, {
        q["question_id"] for q in questions
    })
    # Keep rejected candidates for the final decision audit, not as active tasks.
    return [{"trigger_question_id": qid, "text": title,
             "origin": "model_" + role,
             "selection": "SELECTED" if i < 4 else "REJECTED_BUDGET"}
            for i, (qid, title, _, _) in enumerate(validated)]

def to_html_tree(report):
    """Expandable, escaped HTML; serializable complete tree, never truncate branches."""
    def esc(x):
        return escape(str(x), quote=True)

    def render(node, depth=0):
        details = node.get("details", {})
        rows = []
        for name, value in details.items():
            if name == "source_url" and value is not None:
                url = _safe_url(value)
                rows.append('<div><strong>source_url:</strong> <a rel="noopener noreferrer" target="_blank" href="{}">{}</a></div>'.format(
                    esc(url), esc(url)))
            else:
                rows.append("<div><strong>{}:</strong> {}</div>".format(
                    esc(name), esc(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value)))
        more = "".join(render(child, depth + 1) for child in node.get("children", []))
        return ('<details class="branch {}" {}>'
                '<summary><span class="badge">{}</span> <b>{}</b> <em>{}</em></summary>'
                '<div class="body">{}{}</div></details>').format(
            esc(node["kind"]), "open" if depth < 2 else "",
            esc(node["kind"].upper()), esc(node["title"]), esc(node["status"]),
            "".join(rows), more)
    return render(report["root"])


class ReportStore:
    """Only local durable reports, accessible by random opaque ID on loopback."""
    def __init__(self, db):
        self.db = db
        self.db.execute("CREATE TABLE IF NOT EXISTS research_reports ("
                        "id TEXT PRIMARY KEY, created REAL NOT NULL, body TEXT NOT NULL)")

    def save(self, report):
        import time
        rid = secrets.token_urlsafe(20)
        self.db.execute("INSERT INTO research_reports VALUES (?,?,?)",
                        (rid, time.time(), json.dumps(report, ensure_ascii=False)))
        self.db.commit()
        return rid

    def load(self, rid):
        if not isinstance(rid, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{20,40}", rid):
            raise ValueError("Invalid report ID")
        row = self.db.execute("SELECT body FROM research_reports WHERE id=?", (rid,)).fetchone()
        if row is None:
            raise ValueError("Report not found")
        return json.loads(row[0])
