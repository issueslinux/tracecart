"""HTTP-level regression tests: real loopback server, no real AI or PayPal API."""
import json
from pathlib import Path
import re
import secrets
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from core import CheckoutStore, CONSENT_TEXT
from decision_tree import ReportStore
import cart_research

class MockPayPal:
    def __init__(self):
        self.created = 0
        self.reads = 0
        self.timeout = False
        self.record = None

    def create_order(self, record):
        self.created += 1
        self.record = record.copy()
        if self.timeout:
            raise TimeoutError("simulated uncertain sandbox response")
        return self._response(record)

    def get_order(self, oid):
        self.reads += 1
        if oid != "FAKEORDER123":
            raise ValueError("order not found")
        return self._response(self.record)

    @staticmethod
    def _response(record):
        return {
            "id": "FAKEORDER123",
            "status": "CREATED",
            "purchase_units": [{"reference_id": record["id"],
                                "amount": {"currency_code": "USD", "value": record["total"]}}],
            "links": [{"rel": "approve",
                       "href": "https://www.sandbox.paypal.com/checkoutnow?token=FAKEORDER123"}],
        }


class WebFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ready = threading.Event()
        self.done = threading.Event()
        self.port = None
        self.host_thread = threading.Thread(target=self._host_server, daemon=True)
        self.host_thread.start()
        self.assertTrue(self.ready.wait(5))
        self.base = "http://127.0.0.1:{}".format(self.port)
        response = self.request("GET", "/")
        self.assertEqual(response[0], 200)
        self.csrf = re.search(r'name="csrf" value="([^"]+)"', response[1]).group(1)

    def _host_server(self):
        # Production server keeps checkout serialized, SSE in a separate thread.
        server = app.StreamingHTTPServer(("127.0.0.1", 0), app.TraceCartHandler)
        server.store = CheckoutStore(str(Path(self.tmp.name) / "webquotes.sqlite"))
        server.reports = ReportStore(server.store.db)
        def cart_stub(item):
            def fetch(url, host, headers=None):
                return {"products": []} if host == "world.openproductsfacts.org" else {"items": []}
            with patch.object(cart_research, "generate_local_ai_questions", return_value=[]):
                return cart_research.research_cart(item, fetch=fetch)
        server.cart_jobs = cart_research.CartResearchJobs(
            str(Path(self.tmp.name) / "webquotes.sqlite"), runner=cart_stub)
        server.csrf = secrets.token_urlsafe(24)
        self.server = server
        self.port = server.server_port
        self.ready.set()
        try:
            server.serve_forever(poll_interval=0.03)
        finally:
            server.server_close()
            server.cart_jobs.close()
            server.store.db.close()
            self.done.set()

    def tearDown(self):
        self.server.shutdown()
        self.assertTrue(self.done.wait(5))
        self.host_thread.join(timeout=2)
        self.tmp.cleanup()

    def request(self, method, path, form=None, headers=None):
        h = {"Origin": self.base} if method == "POST" else {}
        if headers:
            h.update(headers)
        if form is not None:
            h["Content-Type"] = "application/x-www-form-urlencoded"
            data = urlencode(form).encode()
        else:
            data = b"" if method == "POST" else None
        req = Request(self.base + path, data=data, headers=h, method=method)
        try:
            with urlopen(req, timeout=15) as response:
                return response.status, response.read().decode()
        except HTTPError as exc:
            return exc.code, exc.read().decode()

    def quote(self):
        with patch.object(app, "ollama_suggestion", return_value=("ceramic-pendant", 2, "58.00")) as model:
            status, page = self.request("POST", "/propose", {
                "csrf": self.csrf, "description": "Two ceramic pendants please"
            })
            model.assert_called_once()
        self.assertEqual(status, 200)
        self.assertIn("58.00 USD", page)
        qid = re.search(r'name="quote_id" type="hidden" value="([^"]+)"', page).group(1)
        return qid

    def test_real_http_flow_blocked_without_consent_and_fake_gateway_only(self):
        qid = self.quote()
        paypal = MockPayPal()
        with patch.object(app, "SandboxPayPal", return_value=paypal):
            # POST without consent must fail and never invoke the gateway.
            status, _ = self.request("POST", "/create", {
                "csrf": self.csrf, "quote_id": qid
            })
            self.assertEqual(status, 400)
            self.assertEqual(paypal.created, 0)
            status, _ = self.request("POST", "/approve", {
                "csrf": self.csrf, "quote_id": qid,
                "consent": CONSENT_TEXT, "expected_total": "0.01"
            })
            self.assertEqual(status, 400)
            status, approved = self.request("POST", "/approve", {
                "csrf": self.csrf, "quote_id": qid,
                "consent": CONSENT_TEXT, "expected_total": "58.00"
            })
            self.assertEqual(status, 200)
            self.assertIn("APPROVED", approved)
            status, created = self.request("POST", "/create", {
                "csrf": self.csrf, "quote_id": qid
            })
            self.assertEqual(status, 200)
            self.assertIn("PAYER_ACTION_REQUIRED", created)
            self.assertIn("FAKEORDER123", created)
            self.assertEqual(paypal.created, 1)
            self.assertEqual(paypal.record["total"], "58.00")
            status, _ = self.request("POST", "/create", {
                "csrf": self.csrf, "quote_id": qid
            })
            self.assertEqual(status, 400)
            self.assertEqual(paypal.created, 1)
        status, _ = self.request("GET", "/quote/" + qid)
        self.assertEqual(status, 200)

    def test_timeout_recovery_is_get_only_from_web_ui(self):
        qid = self.quote()
        paypal = MockPayPal()
        paypal.timeout = True
        with patch.object(app, "SandboxPayPal", return_value=paypal):
            status, _ = self.request("POST", "/approve", {
                "csrf": self.csrf, "quote_id": qid,
                "consent": CONSENT_TEXT, "expected_total": "58.00"
            })
            self.assertEqual(status, 200)
            status, _ = self.request("POST", "/create", {
                "csrf": self.csrf, "quote_id": qid
            })
            self.assertEqual(status, 400)
            status, uncertain = self.request("GET", "/quote/" + qid)
            self.assertEqual(status, 200)
            self.assertIn("CREATE_UNCERTAIN", uncertain)
            self.assertIn("GET only", uncertain)
            paypal.timeout = False
            status, recovered = self.request("POST", "/reconcile", {
                "csrf": self.csrf, "quote_id": qid, "order_id": "FAKEORDER123"
            })
            self.assertEqual(status, 200)
            self.assertIn("PAYER_ACTION_REQUIRED", recovered)
            self.assertEqual(paypal.created, 1)
            self.assertEqual(paypal.reads, 1)

    def test_complete_tree_http_and_json_download(self):
        from pathlib import Path
        data = (Path(__file__).resolve().parents[1] /
                "examples" / "sample_research_fixture.json").read_text()
        status, form = self.request("GET", "/research")
        self.assertEqual(status, 200)
        self.assertIn("FICTIONAL", form)
        status, html = self.request("POST", "/research/analyze", {
            "csrf": self.csrf, "research_data": data,
        })
        self.assertEqual(status, 200)
        self.assertIn("Complete evidence and decision tree", html)
        self.assertIn("Critic:", html)
        self.assertIn("Export complete JSON", html)
        import html as hlib
        rid = re.search(r'/research/report/([a-zA-Z0-9_-]+)\.json', html).group(1)
        status, exported = self.request("GET", "/research/report/" + rid + ".json")
        self.assertEqual(status, 200)
        payload = json.loads(exported)
        self.assertEqual(payload["root"]["children"][-1]["status"], "ABSTAIN")
        self.assertTrue(payload["all_questions_preserved"])
        status, page = self.request("GET", "/research/report/" + rid)
        self.assertEqual(status, 200)
        self.assertIn("Every decision, objection, source and question", page)

    def test_research_cannot_generate_payment_authorization(self):
        from pathlib import Path
        data = (Path(__file__).resolve().parents[1] /
                "examples" / "sample_research_fixture.json").read_text()
        status, page = self.request("POST", "/research/analyze", {
            "csrf": self.csrf, "research_data": data
        })
        self.assertEqual(status, 200)
        self.assertNotIn("Create sandbox order", page)
        import sqlite3
        with sqlite3.connect(str(Path(self.tmp.name) / "webquotes.sqlite")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM quotes").fetchone()[0], 0)

    def test_live_source_collection_http_and_report(self):
        from decision_tree import analyze
        from source_collector import ProductCollector
        source = ProductCollector(
            robots_text="User-agent: *\nAllow: /product/\n",
            download=lambda url: (
                b'<script type="application/ld+json">{"@type":"Product",'
                b'"name":"Mock merchant product","sku":"1083","offers":'
                b'{"price":"9.95","priceCurrency":"USD",'
                b'"availability":"http://schema.org/InStock"}}</script>',
                '<script type="application/ld+json">{"@type":"Product",'
                '"name":"Mock merchant product","sku":"1083","offers":'
                '{"price":"9.95","priceCurrency":"USD",'
                '"availability":"http://schema.org/InStock"}}</script>',
            ))
        collected = source.collect(["https://www.adafruit.com/product/1083"])
        report = analyze({k: collected[k] for k in ("goal", "category", "offers")})
        report["source_collection"] = collected["collection"]
        with patch.object(app, "collect_and_analyze", return_value=(report, collected)) as fetch:
            status, form_page = self.request("GET", "/research")
            self.assertEqual(status, 200)
            self.assertIn("LIVE merchant source collection", form_page)
            status, body = self.request("POST", "/research/collect", {
                "csrf": self.csrf,
                "product_urls": "https://www.adafruit.com/product/1083"
            })
            self.assertEqual(status, 200)
            self.assertIn("come from the merchant", body.lower())
            self.assertIn("External customer reviews", body)
            self.assertIn("0</strong>", body)
            fetch.assert_called_once()
            rid = re.search(r'/research/report/([a-zA-Z0-9_-]+)\.json', body).group(1)
            status, text = self.request("GET", "/research/report/" + rid + ".json")
            self.assertEqual(status, 200)
            downloaded = json.loads(text)
            self.assertEqual(downloaded["source_collection"]["fetched_pages"], 1)

    def test_live_sources_with_separate_ai_critic_roles(self):
        from decision_tree import analyze
        from source_collector import ProductCollector
        from unittest.mock import patch
        collector = ProductCollector(
            robots_text="User-agent: *\nAllow: /product/\n",
            download=lambda u: (
                b'<script type="application/ld+json">{"@type":"Product",'
                b'"name":"Mock","offers":{"price":"9.95","priceCurrency":"USD"}}</script>',
                '<script type="application/ld+json">{"@type":"Product",'
                '"name":"Mock","offers":{"price":"9.95","priceCurrency":"USD"}}</script>'))
        collected = collector.collect(["https://www.adafruit.com/product/1083"])
        baseline = analyze({k: collected[k] for k in ("goal","category","offers")})
        from source_collector import attach_collection_provenance
        baseline = attach_collection_provenance(baseline, collected)
        with patch.object(app, "collect_and_analyze",
                          return_value=(baseline, collected)):
            with patch.object(app, "generate_question_proposals", side_effect=[
                    [{"trigger_question_id": "product_1083-price",
                      "text": "Does the price include applicable shipping fees?",
                      "origin": "model_researcher"}],
                    [{"trigger_question_id": "product_1083-price",
                      "text": "Can a separate merchant verify this quoted price?",
                      "origin": "model_critic"}],
                ]) as ai:
                status, body = self.request("POST", "/research/collect", {
                    "csrf": self.csrf,
                    "ask_ai": "yes",
                    "product_urls": "https://www.adafruit.com/product/1083"
                })
                self.assertEqual(status, 200)
                rid = re.search(r'/research/report/([a-zA-Z0-9_-]+)\.json', body).group(1)
                status, response = self.request("GET", "/research/report/" + rid + ".json")
                self.assertEqual(status, 200)
                exported = json.loads(response)
                self.assertEqual(exported["root"]["children"][-1]["details"]["model_generated_questions"], 2)
                self.assertEqual(ai.call_count, 2)

    def test_real_two_publisher_spec_crosscheck_http_and_export(self):
        import source_crosscheck as cross
        from unittest.mock import patch

        def fake_fetch(url):
            merchant = ('<h1>SHT40 Specifications & Features</h1>'
                        '<p>Relative humidity accuracy: up to ±1.8 %RH</p>'
                        '<p>Temperature accuracy: up to ±0.2 °C</p>'
                        '<script type="application/ld+json">{"@type":"Product",'
                        '"name":"SHT40 board","offers":{"price":"5.95",'
                        '"priceCurrency":"USD"}}</script>')
            oem = ('<h1>SHT40</h1><span>Typ. relative humidity accuracy</span>'
                   '<span>1.8</span><span>%RH</span><span>Typ. temperature accuracy</span>'
                   '<span>0.2</span><span>°C</span>')
            html = merchant if url == cross.MERCHANT_URL else oem
            return html.encode(), html

        with patch.object(cross, "_download", side_effect=lambda u, max_bytes: fake_fetch(u)):
            with patch.object(cross, "_check_robots",
                              return_value="User-agent: *\nAllow: /\n"):
                status, lab = self.request("GET", "/research")
                self.assertEqual(status, 200)
                self.assertIn("Cross-check SHT40 against Sensirion", lab)
                status, page = self.request("POST", "/research/crosscheck", {
                    "csrf": self.csrf
                })
                self.assertEqual(status, 200)
                self.assertIn("Two-publisher SHT40 documentation cross-check", page)
                self.assertIn("ABSTAIN", page)
                rid = re.search(r'/research/report/([a-zA-Z0-9_-]+)\.json', page).group(1)
                status, raw = self.request("GET", "/research/report/" + rid + ".json")
                self.assertEqual(status, 200)
                doc = json.loads(raw)
                self.assertEqual(len(doc["crosscheck"]), 2)
                self.assertTrue(all(x["documents_agree"] for x in doc["crosscheck"]))
                self.assertEqual(doc["root"]["children"][-1]["status"], "ABSTAIN")
                self.assertEqual(doc["source_collection"]["independent_product_tests_collected"], 0)

    def test_live_source_collection_rejects_non_allowlisted_website(self):
        status, body = self.request("POST", "/research/collect", {
            "csrf": self.csrf,
            "product_urls": "http://127.0.0.1:8765/product/247"
        })
        self.assertEqual(status, 400)
        import sqlite3
        with sqlite3.connect(str(Path(self.tmp.name) / "webquotes.sqlite")) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM research_reports").fetchone()[0], 0)

    def test_conditional_comparison_http_export_with_complete_tree(self):
        from pathlib import Path
        fixture=(Path(__file__).resolve().parents[1] /
                 "examples/comparison_three_laptops_FICTIONAL.json").read_text()
        status, form = self.request("GET", "/compare")
        self.assertEqual(status, 200)
        self.assertIn("FICTIONAL", form)
        status, page = self.request("POST", "/compare/analyze", {
            "csrf": self.csrf, "comparison_data": fixture
        })
        self.assertEqual(status, 200)
        self.assertIn("COMPARATIVE ANALYSIS", page)
        self.assertIn("10.0% more expensive", page)
        self.assertIn("NO_FORCED_WINNER", page)
        self.assertIn("Questions to seller / listing", page)
        self.assertIn("Has this exact unit been repaired", page)
        rid = re.search(r'/research/report/([a-zA-Z0-9_-]+)\.json', page).group(1)
        status, output = self.request("GET", "/research/report/"+rid+".json")
        self.assertEqual(status, 200)
        result=json.loads(output)
        self.assertEqual(result["root"]["children"][-1]["status"], "NO_FORCED_WINNER")
        self.assertTrue(result["comparison_summary"]["no_forced_winner"])
        self.assertEqual(len(result["comparison_summary"]["pairwise"]), 3)
        self.assertFalse(result["root"]["children"][-1]["details"]["eligible_for_payment"])
        self.assertIn("tradeoffs", [x["kind"] for x in result["root"]["children"]])

    def test_comparison_invalid_payload_cannot_invoke_payment(self):
        status, _=self.request("POST", "/compare/analyze", {
            "csrf": self.csrf, "comparison_data": '{"goal":"x"}'
        })
        self.assertEqual(status, 400)
        import sqlite3
        with sqlite3.connect(str(Path(self.tmp.name) / "webquotes.sqlite")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM quotes").fetchone()[0], 0)

    def test_interactive_decision_http_on_existing_laptop_job(self):
        # A real sanitized snapshot of the user's old x-kom job: OPF catalog
        # zero, but Shopping 12 cards + 3 index-store links.
        fixture=(Path(__file__).resolve().parents[1] /
                 "examples/live_lenovo_ideapad_index_evidence_2026-11-02.json")
        historical=json.loads(fixture.read_text(encoding="utf-8"))
        # The fixture is intentionally truncated to source + index evidence;
        # restore the legacy auditor's non-source structural fields so it
        # can render its full old-style tree as well.
        report=historical["report"]
        report["source_discovery"].update({"attempts":[],"web_hits":[]})
        report["root"]["id"]="research-root"
        report["root"]["kind"]="research"
        report["root"]["title"]="Historic laptop analysis"
        report["root"]["status"]="IN_PROGRESS"
        report["root"]["details"].update({
            "category":"laptop","local_ai_question_generation":"UNAVAILABLE_timeout"})
        report["root"]["children"][-1].update({
            "id":"cart-summary","title":"Legacy catalog-only summary","children":[]})
        jid="H"*24
        import sqlite3
        with sqlite3.connect(str(Path(self.tmp.name)/"webquotes.sqlite")) as db:
            db.execute(
                "INSERT INTO cart_research_jobs(id,item,state,created,result,error_type) "
                "VALUES (?,?,?,?,?,NULL)",
                (jid,json.dumps(historical["item"]),"READY",
                 "2026-11-02T20:10:00+00:00",json.dumps(historical["report"])))
        # Default is the clean progressive workspace, not 70 KB of 'None'.
        status,ui=self.request("GET","/cart/status/"+jid)
        self.assertEqual(status,200)
        self.assertIn("Paste a product URL",ui)
        self.assertIn('data-source="/cart/status/'+jid+'.decision.json"',ui)
        self.assertIn('data-audit="/cart/status/'+jid+'/audit"',ui)
        self.assertIn('src="/assets/live-workspace.js"',ui)
        self.assertIn('data-live="/cart/status/'+jid+'/live"',ui)
        self.assertNotIn("unit_economics:",ui)
        status,derived=self.request("GET","/cart/status/"+jid+".decision.json")
        self.assertEqual(status,200)
        payload=json.loads(derived)
        self.assertEqual(len(payload["offers"]),16)
        self.assertEqual(sum(x["question_count"] for x in payload["offers"]),4608)
        status,qjson=self.request("GET","/cart/status/"+jid+
                                  "/questions.json?offer=1&offset=24&limit=12")
        self.assertEqual(status,200)
        question_page=json.loads(qjson)
        self.assertEqual(question_page["offer_id"],"offer-1")
        self.assertEqual(question_page["offset"],24)
        self.assertEqual(len(question_page["questions"]),12)
        self.assertTrue(all(q["status"]=="PLANNED_NOT_INVESTIGATED"
                            for q in question_page["questions"]))
        bad,_=self.request("GET","/cart/status/"+jid+
                           "/questions.json?offer=999&offset=0&limit=24")
        self.assertEqual(bad,400)
        self.assertEqual(payload["evidence"]["catalog_only"],0)
        self.assertEqual(payload["evidence"]["google_shopping_cards"],12)
        self.assertEqual(payload["evidence"]["indexed_store_links"],3)
        self.assertEqual(payload["evidence"]["unverified_similar_product_leads"],4)
        self.assertEqual(payload["evidence"]["seller_confirmed_competitor_prices"],0)
        self.assertEqual(payload["evidence"]["unusually_low_raw_index_quotes"],3)
        self.assertEqual(payload["category"],"LAPTOP")
        self.assertIn("Snapdragon",payload["display_title"])
        self.assertFalse(payload["payment_authorized"])
        self.assertEqual(payload["questions"], [])
        self.assertEqual(payload["research"]["mode"],
                         "AUTONOMOUS_SOURCE_QUESTIONS_NO_BUYER_INPUT")
        self.assertEqual(len(payload["research"]["sources"]), 4)
        status,audit=self.request("GET","/cart/status/"+jid+"/audit")
        self.assertEqual(status,200)
        self.assertIn("catalog_alternatives_found:",audit)
        self.assertIn("Ważne: różne źródła mają osobne liczniki",audit)
        self.assertIn("12",audit)
        status,raw=self.request("GET","/cart/status/"+jid+".json")
        self.assertEqual(status,200)
        stored=json.loads(raw)
        self.assertEqual(stored["report"]["sha256"],historical["report"]["sha256"])
        self.assertEqual(stored["report"]["root"]["children"][-1]["details"][
            "catalog_alternatives_found"],0)
        self.assertNotIn("functional_alternatives",stored["report"]["indexed_shopping"])

    def test_live_json_fallback_returns_same_persisted_state_as_sse(self):
        fixture=(Path(__file__).resolve().parents[1] /
                 "examples/live_lenovo_ideapad_index_evidence_2026-11-02.json")
        saved=json.loads(fixture.read_text(encoding="utf-8"))
        jid="F"*24
        with self.server.cart_jobs._db() as db:
            db.execute("""INSERT INTO cart_research_jobs
                (id,item,state,created,result,error_type)
                VALUES (?,?,?,?,?,NULL)""",
                (jid,json.dumps(saved["item"]),"READY",
                 "2026-11-03T11:00:00Z",json.dumps(saved["report"])))
        with urlopen(self.base+"/cart/status/"+jid+"/live.json",timeout=5) as res:
            self.assertEqual(res.status,200)
            self.assertIn("application/json",res.headers["Content-Type"])
            payload=json.load(res)
        self.assertEqual(payload["state"],"READY")
        self.assertEqual(payload["graph"]["stats"]["offers"],16)
        self.assertEqual(len(payload["offer_queue"]),16)
        self.assertFalse(payload["payment_authorized"])
        self.server.cart_jobs._progress(jid,"PER_OFFER_MODEL_COMPLETE")
        with urlopen(self.base+"/cart/status/"+jid+"/live.json",timeout=5) as res:
            after=json.load(res)
        self.assertEqual(after["progress_stage"],"PER_OFFER_MODEL_COMPLETE")
        self.assertEqual(after["graph"]["stats"]["verified_exact_sku_answers"],0)

    def test_live_event_stream_is_ram_backed_and_nonblocking(self):
        from time import monotonic
        fixture=(Path(__file__).resolve().parents[1] /
                 "examples/live_lenovo_ideapad_index_evidence_2026-11-02.json")
        saved=json.loads(fixture.read_text(encoding="utf-8"))
        jid="S"*24
        with self.server.cart_jobs._db() as db:
            db.execute("""INSERT INTO cart_research_jobs
                (id,item,state,created,result,error_type)
                VALUES (?,?,?,?,?,NULL)""",
                (jid,json.dumps(saved["item"]),"READY",
                 "2026-11-03T11:00:00Z",json.dumps(saved["report"])))
        with urlopen(self.base+"/cart/status/"+jid+"/live",timeout=5) as res:
            self.assertEqual(res.status,200)
            self.assertIn("text/event-stream",res.headers["Content-Type"])
            first=res.readline().decode()
            event=res.readline().decode()
            data=res.readline().decode()
            self.assertTrue(first.startswith("id: "))
            self.assertEqual(event,"event: graph\n")
            payload=json.loads(data[len("data: "):])
            self.assertEqual(payload["graph"]["stats"]["offers"],16)
            self.assertFalse(payload["payment_authorized"])
            started=monotonic()
            status,page=self.request("GET","/cart")
            self.assertEqual(status,200)
            self.assertLess(monotonic()-started,2)
            self.assertIn("Paste a product URL",page)
            # Persisted progress wakes this same active connection.
            self.server.cart_jobs._progress(jid,"LIVE_STATUS_UPDATED")
            self.assertEqual(res.readline().decode(),"\n")
            self.assertTrue(res.readline().decode().startswith("id: "))
            self.assertEqual(res.readline().decode(),"event: graph\n")
            changed=json.loads(res.readline().decode()[len("data: "):])
            self.assertEqual(changed["progress_stage"],"LIVE_STATUS_UPDATED")

    def test_flow_assets_are_same_origin_and_not_inline_script_enabled(self):
        status,home=self.request("GET","/cart")
        self.assertEqual(status,200)
        self.assertIn("Paste a product URL",home)
        self.assertIn('id="kg-svg"',home)
        self.assertIn('action="/cart/add"',home)
        self.assertIn('name="product_url"',home)
        self.assertIn('name="csrf"',home)
        status,css=self.request("GET","/assets/decision-flow.css")
        self.assertEqual(status,200)
        self.assertIn("decision-graph",css)
        self.assertNotIn("@import",css)
        status,script=self.request("GET","/assets/decision-flow.js")
        self.assertEqual(status,200)
        self.assertIn("renderGraph",script)
        self.assertIn("ABSTAIN_UNVERIFIED_PRICE_AND_VARIANT",script)
        with urlopen(self.base+"/cart",timeout=8) as response:
            csp=response.headers.get("Content-Security-Policy")
            self.assertIn("style-src 'self'",csp)
            self.assertIn("script-src 'self'",csp)
            self.assertNotIn("'unsafe-inline'",csp)
            self.assertIn("frame-ancestors 'none'",csp)
        self.assertEqual(self.request("GET","/assets/unknown.js")[0],404)

    def test_pending_flow_projection_has_no_fake_ready_candidate(self):
        import sqlite3
        jid="Q"*24
        with sqlite3.connect(str(Path(self.tmp.name)/"webquotes.sqlite")) as db:
            db.execute(
                "INSERT INTO cart_research_jobs(id,item,state,created,result,error_type) "
                "VALUES (?,?,?,?,NULL,NULL)",
                (jid,json.dumps({"merchant_url":"https://example.com/laptop",
                                 "intake":"URL_EXTRACTION_PENDING"}),
                 "RUNNING","2026-11-02T20:10:00+00:00"))
        status,view=self.request("GET","/cart/status/"+jid)
        self.assertEqual(status,200)
        self.assertIn(".decision.json",view)
        status,projection=self.request("GET","/cart/status/"+jid+".decision.json")
        self.assertEqual(status,200)
        self.assertEqual(json.loads(projection)["state"],"RUNNING")
        self.assertNotIn("candidates",json.loads(projection))

    def test_allegro_403_returns_limited_ready_report_not_failed(self):
        from product_intake import SourceAccessDenied
        from test_allegro_fallback import ALLEGRO_URL
        import sqlite3
        import time
        with patch("product_intake.extract_product_page",
                   side_effect=SourceAccessDenied(403)):
            status, body = self.request("POST", "/cart/add", {
                "csrf": self.csrf, "product_url": ALLEGRO_URL})
            self.assertEqual(status, 200)
            with sqlite3.connect(str(Path(self.tmp.name) / "webquotes.sqlite")) as db:
                jid = db.execute("SELECT id FROM cart_research_jobs").fetchone()[0]
            for _ in range(100):
                result = self.server.cart_jobs.read(jid)
                if result["state"] in ("READY", "FAILED"):
                    break
                time.sleep(.02)
        self.assertEqual(result["state"], "READY")
        self.assertIsNone(result["item"]["price"])
        status, body = self.request("GET", "/cart/status/" + jid + "/audit")
        self.assertEqual(status, 200)
        self.assertIn("Limited URL-only identification", body)
        self.assertIn("HTTP_403", body)
        self.assertIn("18675491436", body)
        self.assertIn("NOT DOWNLOADED", body)
        self.assertIn("not disclosed by the source", body)
        status, raw = self.request("GET", "/cart/status/" + jid + ".json")
        self.assertEqual(status, 200)
        report = json.loads(raw)["report"]
        self.assertEqual(report["source_intake"]["intake_status"],
                         "URL_ONLY_UNVERIFIED")
        self.assertEqual(report["root"]["children"][2]["status"],
                         "URL_ONLY_UNVERIFIED")
        self.assertFalse(report["root"]["children"][-1]
                         ["details"]["payment_authorized"])

    def test_offer_knowledge_graph_http_distinguishes_claim_from_evidence(self):
        from tests.test_ebike_research import sample_record
        item=sample_record()
        jid="G"*24
        with self.server.cart_jobs._db() as db:
            db.execute("""INSERT INTO cart_research_jobs
                (id,item,state,created,result,error_type)
                VALUES (?,?,?,?,?,NULL)""",
                (jid,json.dumps(item["item"]),"READY",
                 "2026-11-03T10:00:00Z",json.dumps(item["report"])))
        status,page=self.request("GET","/cart/status/"+jid)
        self.assertEqual(status,200)
        self.assertIn("data-knowledge-graph=",page)
        self.assertIn("offer-graph.js",page)
        self.assertIn('id="kg-svg"',page)
        self.assertIn('id="live-question-tasks"',page)
        status,payload=self.request("GET",
            "/cart/status/"+jid+".knowledge-graph.json")
        self.assertEqual(status,200)
        graph=json.loads(payload)
        self.assertEqual(graph["schema_version"],
                         "tracecart.offer-knowledge-graph.v1")
        self.assertEqual(graph["stats"]["offers"],4)
        self.assertEqual(graph["stats"]
                         ["high_priority_unanswered_check_links"],96)
        self.assertEqual(graph["stats"]["verified_exact_sku_answers"],0)
        self.assertTrue(graph["provenance"]
                        ["reference_review_proves_offer_variant"] is False)
        self.assertTrue(all(q["relation"]!="VERIFIED_IDENTICAL_PRODUCT"
                            for q in graph["edges"]))
        status,script=self.request("GET","/assets/offer-graph.js")
        self.assertEqual(status,200)
        self.assertIn("TraceCartKnowledgeGraph",script)
        self.assertIn("NOT a current seller checkout price",script)

    def test_ebike_questions_are_prioritized_and_source_claims_unverified(self):
        """The live JSON must no longer expose 12 mechanical probes per facet."""
        from tests.test_ebike_research import sample_record
        item=sample_record()
        jid="R"*24
        with self.server.cart_jobs._db() as db:
            db.execute("""INSERT INTO cart_research_jobs
                (id,item,state,created,result,error_type) VALUES (?,?,?,?,?,NULL)""",
                (jid,json.dumps(item["item"]),"READY",
                 "2026-11-03T08:00:00Z",json.dumps(item["report"])))
        status,raw=self.request("GET","/cart/status/"+jid+".decision.json")
        self.assertEqual(status,200)
        projection=json.loads(raw)
        self.assertEqual(projection["category"],"E_BIKE")
        self.assertEqual(len(projection["offers"]),4)
        self.assertTrue(all(o["question_count"]==228 for o in
                            projection["offers"]))
        title=projection["offers"][0]
        self.assertEqual(title["research_diagnostics"]["scenarios"][0]
                         ["energy_wh"],540)
        self.assertFalse(title["index_model_hints"][0]["exact_seller_sku_verified"])
        self.assertFalse(projection["payment_authorized"])
        status,body=self.request("GET","/cart/status/"+jid+
                                 "/questions.json?offer=0&offset=0&limit=24")
        self.assertEqual(status,200)
        page=json.loads(body)
        self.assertEqual(page["total"],228)
        self.assertEqual(len(set(q["dimension"] for q in page["questions"])),24)
        self.assertEqual(page["questions"][0]["priority"],"P0")
        self.assertIn("energy in wh",page["questions"][1]["question"].casefold())
        self.assertTrue(all(q["finding"] is None for q in page["questions"]))
        self.assertEqual(page["verified_answers"],0)

    def test_fetched_reference_answers_visible_only_as_non_sku_evidence(self):
        """Readonly review findings carry URL+SHA, not an exact checkout claim."""
        from evidence_execution import execute_reference_checks
        from tests.test_evidence_execution import RECORD,SAMPLE_HTML,ROBOTS,SOURCE
        offer={"id":"offer-0","title":"Lenovo IdeaPad Slim 3 15Q8X10 OLED"}
        evidence=execute_reference_checks(offer,"LAPTOP",fetch=lambda url,*a,**k:
                             ROBOTS if url.endswith("/robots.txt") else SAMPLE_HTML)
        jid="Z"*24
        database=self.server.cart_jobs
        with database._db() as db:
            db.execute("""INSERT INTO cart_research_jobs
                    (id,item,state,created,result,error_type)
                    VALUES (?,?,?,?,?,NULL)""",
                    (jid,json.dumps(RECORD["item"]),"READY","2026-11-02T00:00:00Z",
                     json.dumps(RECORD["report"])))
            db.execute("""INSERT INTO cart_offer_evidence
                    (job_id,offer_idx,status,result_json) VALUES (?,?,?,?)""",
                    (jid,0,evidence["status"],json.dumps(evidence)))
            db.execute("""INSERT INTO cart_evidence_runs
                    (job_id,status,processed,planned) VALUES (?,?,?,?)""",
                    (jid,"COMPLETE",16,16))
        status,body=self.request("GET","/cart/status/"+jid+".decision.json")
        self.assertEqual(status,200)
        d=json.loads(body)
        self.assertEqual(d["evidence_progress"]["status"],"COMPLETE")
        self.assertEqual(d["evidence_offers"]["offer-0"]["variant_match"],
                         "MISMATCH_LISTED_OLED_REVIEWED_IPS")
        self.assertFalse(d["payment_authorized"])
        status,body=self.request("GET","/cart/status/"+jid+
                                 "/questions.json?offer=0&offset=24&limit=12")
        self.assertEqual(status,200)
        q=json.loads(body)
        reference=[x for x in q["questions"] if x["id"]=="offer-0-28"][0]
        self.assertEqual(reference["status"],
                         "REFERENCE_EVIDENCE_ONLY_EXACT_SKU_UNVERIFIED")
        self.assertEqual(reference["evidence"]["source_url"],SOURCE["url"])
        self.assertFalse(reference["evidence"]["verified_for_exact_offer"])
        self.assertEqual(q["verified_answers"],0)
        status,body=self.request("GET","/cart/status/"+jid+
                                 "/questions.json?offer=0&offset=120&limit=12")
        self.assertEqual(status,200)
        q=json.loads(body)
        self.assertIn("19 h 1 min",
            next(x for x in q["questions"] if x["id"]=="offer-0-124")["finding"])
        status,raw=self.request("GET","/cart/status/"+jid+".json")
        self.assertEqual(status,200)
        self.assertEqual(json.loads(raw)["report"],RECORD["report"])

    def test_url_only_cart_form_extracts_before_research(self):
        import time
        from unittest.mock import patch
        from product_intake import extract_from_html
        html = ('<script type="application/ld+json">'
                '{"@type":"Product","name":"Persil powder 45 washes",'
                '"gtin13":"8712561344494","offers":'
                '{"price":"34.90","priceCurrency":"PLN"}}'
                '</script>').encode()
        item, meta = extract_from_html("https://www.adafruit.com/product/1083",html)
        meta.update({"source_url":"https://www.adafruit.com/product/1083",
                     "page_sha256":"e"*64,
                     "retrieved_at":"2026-11-01T00:00:00+00:00"})
        with patch("product_intake.extract_product_page",return_value=(item,meta)):
            status, page = self.request("POST", "/cart/add", {
                "csrf": self.csrf,
                "product_url": "https://www.adafruit.com/product/1083"})
            self.assertEqual(status, 200)
            import sqlite3
            with sqlite3.connect(str(Path(self.tmp.name)/"webquotes.sqlite")) as db:
                jid=db.execute("SELECT id FROM cart_research_jobs").fetchone()[0]
            for _ in range(100):
                if self.server.cart_jobs.read(jid)["state"] in ("READY","FAILED"):
                    break
                time.sleep(.02)
        self.assertEqual(self.server.cart_jobs.read(jid)["state"],"READY")
        status, page = self.request("GET","/cart/status/"+jid+"/audit")
        self.assertEqual(status,200)
        self.assertIn("Original product page",page)
        self.assertIn("34.90 PLN",page)
        self.assertIn("page",page)
        status, payload = self.request("GET","/cart/status/"+jid+".json")
        self.assertEqual(status,200)
        report=json.loads(payload)["report"]
        self.assertEqual(report["source_intake"]["page_sha256"],"e"*64)
        self.assertEqual(report["root"]["children"][2]["kind"],"source_intake")

    def test_cart_add_triggers_async_research_without_payment(self):
        import time
        status, page = self.request("GET", "/cart")
        self.assertEqual(status, 200)
        self.assertIn("Product URL", page)
        status, response = self.request("POST", "/cart/add", {
            "csrf": self.csrf,
            "title": "Persil washing powder 45 loads",
            "price": "34.90", "currency": "PLN",
            "barcode": "8712561344494",
            "merchant_url": "https://example.org/demo/persil",
        })
        self.assertEqual(status, 200)
        # Get opaque job ID from persistence because the job may complete
        # before the HTTP response has rendered.
        import sqlite3
        with sqlite3.connect(str(Path(self.tmp.name) / "webquotes.sqlite")) as db:
            job_id = db.execute("SELECT id FROM cart_research_jobs").fetchone()[0]
            self.assertEqual(db.execute("SELECT COUNT(*) FROM quotes").fetchone()[0], 0)
        for _ in range(100):
            if self.server.cart_jobs.read(job_id)["state"] == "READY":
                break
            time.sleep(.02)
        self.assertEqual(self.server.cart_jobs.read(job_id)["state"], "READY")
        status, ready = self.request("GET", "/cart/status/" + job_id + "/audit")
        self.assertEqual(status, 200)
        self.assertIn("Other matching product identities found online", ready)
        self.assertIn("Complete expandable research", ready)
        self.assertIn("Selected product: cost per wash", ready)
        self.assertIn("0.7756 PLN / wash", ready)
        self.assertIn("NO", ready)
        status, raw = self.request("GET", "/cart/status/" + job_id + ".json")
        self.assertEqual(status, 200)
        report = json.loads(raw)["report"]
        self.assertEqual(report["root"]["children"][-1]["status"], "NO_FORCED_WINNER")
        self.assertFalse(report["root"]["children"][-1]["details"]["payment_authorized"])
        self.assertEqual(report["unit_economics"]["status"],
                         "CALCULATED_FROM_SELLER_CLAIMS")
        self.assertEqual(report["unit_economics"]["washes_declared_in_title"], 45)

    def test_backend_event_accepts_only_product_url(self):
        import time
        from urllib.error import HTTPError
        from unittest.mock import patch
        item = {"title": "Sample washing powder 40 loads",
                "price": None, "currency": None, "barcode": "",
                "merchant_url": "https://www.adafruit.com/product/4885"}
        source = {"source_url": item["merchant_url"],
                  "price_status": "NOT_FOUND",
                  "extraction_method": "Product JSON-LD",
                  "barcode_status": "NOT_FOUND",
                  "page_sha256": "b"*64,
                  "retrieved_at": "2026-11-01T00:00:00+00:00"}
        req = Request(
            self.base + "/api/cart/added",
            data=json.dumps({"product_url": item["merchant_url"]}).encode(),
            method="POST",
            headers={"Content-Type": "application/json",
                     "X-TraceCart-Event-Token": "backend-secret"})
        with patch.dict(app.os.environ, {"TRACECART_CART_WEBHOOK_TOKEN": "backend-secret"}):
            with patch("product_intake.extract_product_page",
                       return_value=(item, source)):
                with urlopen(req,timeout=8) as response:
                    self.assertEqual(response.status,202)
                    ack=json.loads(response.read())
                job_id=ack["job_id"]
                for _ in range(100):
                    result=self.server.cart_jobs.read(job_id)
                    if result["state"] in ("READY","FAILED"):break
                    time.sleep(.02)
        self.assertEqual(result["state"],"READY")
        self.assertIsNone(result["item"]["price"])
        self.assertEqual(result["report"]["source_intake"]["price_status"],"NOT_FOUND")
        self.assertFalse(result["report"]["root"]["children"][-1]
                         ["details"]["payment_authorized"])

    def test_authenticated_server_side_cart_event_returns_202_job(self):
        import os, time
        payload = {
            "title": "Persil powder for laundry",
            "price": "34.90", "currency": "PLN",
            "barcode": "8712561344494",
            "merchant_url": "https://example.org/demo/persil"
        }
        from urllib.error import HTTPError
        req = Request(self.base + "/api/cart/added",
                      data=json.dumps(payload).encode(),
                      method="POST",
                      headers={"Content-Type": "application/json",
                               "X-TraceCart-Event-Token": "secret-for-test"})
        with patch.dict(app.os.environ, {"TRACECART_CART_WEBHOOK_TOKEN": "secret-for-test"}):
            with urlopen(req, timeout=8) as response:
                self.assertEqual(response.status, 202)
                accepted = json.loads(response.read())
        self.assertTrue(accepted["accepted"])
        self.assertEqual(accepted["state"], "QUEUED")
        jid = accepted["job_id"]
        for _ in range(80):
            if self.server.cart_jobs.read(jid)["state"] == "READY":
                break
            time.sleep(.02)
        self.assertEqual(self.server.cart_jobs.read(jid)["state"], "READY")

    def test_cart_event_token_blocks_unauthorized_posts(self):
        payload = {
            "title": "Persil powder for laundry", "price": "34.90",
            "currency": "PLN", "barcode": "",
            "merchant_url": "https://example.org/demo/persil"
        }
        from urllib.error import HTTPError
        req = Request(self.base + "/api/cart/added",
                      data=json.dumps(payload).encode(), method="POST",
                      headers={"Content-Type": "application/json",
                               "X-TraceCart-Event-Token": "bad"})
        with patch.dict(app.os.environ, {"TRACECART_CART_WEBHOOK_TOKEN": "correct"}):
            with self.assertRaises(HTTPError) as e:
                urlopen(req, timeout=8)
            self.assertEqual(e.exception.code, 403)
        with patch.dict(app.os.environ, {}, clear=True):
            with self.assertRaises(HTTPError) as e:
                urlopen(req, timeout=8)
            self.assertEqual(e.exception.code, 503)

    def test_invalid_cart_input_rejected_before_job_and_checkout(self):
        status, _ = self.request("POST", "/cart/add", {
            "csrf": self.csrf, "title": "powder",
            "price": "-1", "currency": "PLN", "barcode": "",
            "merchant_url": "http://127.0.0.1:8770/unsafe",
        })
        self.assertEqual(status, 400)
        import sqlite3
        with sqlite3.connect(str(Path(self.tmp.name) / "webquotes.sqlite")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM cart_research_jobs").fetchone()[0], 0)

    def test_second_real_seller_url_live_comparison_is_exported_no_payment(self):
        from test_live_offer_compare import SELECTED, SECOND, META, BASE
        import sqlite3
        job_id = "A" * 24
        import cart_research as cart
        with patch.object(cart, "generate_local_ai_questions", return_value=[]):
            report = cart.research_cart(SELECTED, fetch=lambda u, host, headers=None: (
                {"items": []} if host == "prices.openfoodfacts.org"
                else {"products": []}))
        report["source_intake"] = {**BASE["source_intake"],
                                   "price_status": "SELLER_DECLARED",
                                   "extraction_method": "Product JSON-LD",
                                   "barcode_status": "FOUND",
                                   "availability_claim": "https://schema.org/InStock"}
        with sqlite3.connect(str(Path(self.tmp.name) / "webquotes.sqlite")) as db:
            db.execute(
                "INSERT INTO cart_research_jobs(id,item,state,created,result,error_type) "
                "VALUES (?,?,?,?,?,NULL)",
                (job_id, json.dumps(SELECTED), "READY",
                 "2026-11-02T00:00:00+00:00", json.dumps(report)))
        status, original = self.request("GET", "/cart/status/" + job_id + "/audit")
        self.assertEqual(status, 200)
        self.assertIn("Compare up to four other stores", original)
        self.assertIn("Search shopping listings", original)
        with patch("live_offer_compare.extract_product_page",
                   return_value=(SECOND, META)) as extractor:
            status, body = self.request("POST", "/cart/compare-live", {
                "csrf": self.csrf, "job_id": job_id,
                "competitor_url": SECOND["merchant_url"]})
        self.assertEqual(status, 200)
        self.assertIn("SECOND LIVE MERCHANT SOURCE", body)
        self.assertIn("-10.00%", body)
        self.assertIn("0.7200", body)
        self.assertIn("Delivery break-even", body)
        self.assertIn("8.00 PLN", body)
        self.assertIn("SELLER_CLAIMS_IN_STOCK", body)
        self.assertIn("NO_FORCED_WINNER", body)
        extractor.assert_called_once()
        rid = re.search(r'/research/report/([a-zA-Z0-9_-]+)\.json', body).group(1)
        status, raw = self.request("GET", "/research/report/" + rid + ".json")
        self.assertEqual(status, 200)
        report = json.loads(raw)
        self.assertEqual(report["live_competitor_comparison"]["status"],
                         "SAME_GTIN_SELLER_LISTED_PRICE_COMPARISON")
        self.assertEqual(report["root"]["children"][-1]["status"], "NO_FORCED_WINNER")
        with sqlite3.connect(str(Path(self.tmp.name) / "webquotes.sqlite")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM quotes").fetchone()[0], 0)

    def test_multiple_retailers_preserve_all_sources_and_no_purchase(self):
        from test_live_offer_compare import SELECTED, SECOND, BASE, META
        from product_intake import SourceAccessDenied
        import sqlite3
        job_id = "M" * 24
        import cart_research as cart
        with patch.object(cart, "generate_local_ai_questions", return_value=[]):
            base = cart.research_cart(SELECTED, fetch=lambda u, host, headers=None: (
                {"items": []} if host == "prices.openfoodfacts.org"
                else {"products": []}))
        base["source_intake"] = {**BASE["source_intake"],
                                 "price_status": "SELLER_DECLARED",
                                 "extraction_method": "Product JSON-LD",
                                 "barcode_status": "FOUND"}
        with sqlite3.connect(str(Path(self.tmp.name) / "webquotes.sqlite")) as db:
            db.execute(
                "INSERT INTO cart_research_jobs(id,item,state,created,result,error_type) "
                "VALUES (?,?,?,?,?,NULL)",
                (job_id, json.dumps(SELECTED), "READY",
                 "2026-11-02T06:00:00+00:00", json.dumps(base)))
        urls = ["https://seller2.example.net/p", "https://seller3.example.net/p"]
        def fetch(url):
            if "seller3" in url:
                raise SourceAccessDenied(403)
            return ({**SECOND, "merchant_url": url},
                    {**META, "source_url": url})
        with patch("live_offer_compare.extract_product_page",
                   side_effect=fetch) as extractor:
            status, body = self.request("POST", "/cart/compare-live", {
                "csrf": self.csrf, "job_id": job_id,
                "competitor_urls": "\n".join(urls)})
        self.assertEqual(status, 200)
        self.assertIn("BOUNDED MULTI-STORE EVIDENCE", body)
        self.assertIn("SECOND_PAGE_NOT_RETRIEVED", body)
        self.assertIn("SAME_GTIN_SELLER_LISTED_PRICE_COMPARISON", body)
        self.assertIn("No delivered-price winner", body)
        self.assertEqual(extractor.call_count, 2)
        rid = re.search(r'/research/report/([a-zA-Z0-9_-]+)\.json', body).group(1)
        status, raw = self.request("GET", "/research/report/" + rid + ".json")
        self.assertEqual(status, 200)
        report = json.loads(raw)
        self.assertEqual(report["multi_offer_summary"]["requested"], 2)
        self.assertEqual(report["multi_offer_summary"]["pages_retrieved"], 1)
        self.assertEqual(report["multi_offer_summary"]["source_qualified_comparisons"], 1)
        self.assertFalse(report["multi_offer_summary"]["payment_authorized"])
        with sqlite3.connect(str(Path(self.tmp.name) / "webquotes.sqlite")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM quotes").fetchone()[0], 0)

    def test_second_offer_csrf_rejection_does_not_fetch(self):
        from test_live_offer_compare import SELECTED, SECOND, BASE
        import sqlite3
        job_id = "B" * 24
        with sqlite3.connect(str(Path(self.tmp.name) / "webquotes.sqlite")) as db:
            db.execute(
                "INSERT INTO cart_research_jobs(id,item,state,created,result,error_type) "
                "VALUES (?,?,?,?,?,NULL)",
                (job_id, json.dumps(SELECTED), "READY",
                 "2026-11-02T00:00:00+00:00", json.dumps(BASE)))
        with patch("live_offer_compare.extract_product_page") as extractor:
            status, _ = self.request("POST", "/cart/compare-live", {
                "csrf": "invalid", "job_id": job_id,
                "competitor_url": SECOND["merchant_url"]})
        self.assertEqual(status, 400)
        extractor.assert_not_called()

    def test_cross_origin_host_and_csrf_rejected(self):
        status, _ = self.request("GET", "/", headers={"Host": "malicious.example"})
        self.assertEqual(status, 403)
        status, _ = self.request("POST", "/propose", {
            "csrf": self.csrf, "description": "Two ceramic pendants please"
        }, headers={"Origin": "null"})
        self.assertEqual(status, 400)
        status, _ = self.request("POST", "/propose", {
            "csrf": "BAD", "description": "Two ceramic pendants please"
        })
        self.assertEqual(status, 400)
        status, _ = self.request("POST", "/propose", {
            "csrf": self.csrf, "description": "Two ceramic pendants please"
        }, headers={"Host": "malicious.example"})
        self.assertEqual(status, 403)


    def test_marketplace_price_lead_survives_http_403_without_false_saving(self):
        from test_live_offer_compare import SELECTED, BASE
        from product_intake import SourceAccessDenied
        import sqlite3
        import cart_research as cart
        with patch.object(cart, "generate_local_ai_questions", return_value=[]):
            base = cart.research_cart(SELECTED, fetch=lambda url, host, headers=None: (
                {"items": []} if host == "prices.openfoodfacts.org"
                else {"products": []}))
        base["source_intake"] = {**BASE["source_intake"],
                                 "extraction_method": "Product JSON-LD",
                                 "barcode_status": "FOUND"}
        job_id = "L" * 24
        with sqlite3.connect(str(Path(self.tmp.name) / "webquotes.sqlite")) as db:
            db.execute(
                "INSERT INTO cart_research_jobs(id,item,state,created,result,error_type) "
                "VALUES (?,?,?,?,?,NULL)",
                (job_id, json.dumps(SELECTED), "READY",
                 "2026-11-02T00:00:00+00:00", json.dumps(base)))
        market_url = "https://allegro.pl/produkt/sample-stanley"
        def blocked(url):
            raise SourceAccessDenied(403)
        with patch("live_offer_compare.extract_product_page", side_effect=blocked):
            status, body = self.request("POST", "/cart/compare-live", {
                "csrf": self.csrf, "job_id": job_id,
                "marketplace_url": market_url,
                "marketplace_price": "29.99",
                "marketplace_currency": "PLN"})
        self.assertEqual(status, 200, body[:500])
        self.assertIn("MARKETPLACE PRICE LEADS", body)
        self.assertIn("29.99", body)
        self.assertIn("UNVERIFIED", body)
        rid = re.search(r'/research/report/([a-zA-Z0-9_-]+)\.json', body).group(1)
        status, raw = self.request("GET", "/research/report/" + rid + ".json")
        self.assertEqual(status, 200)
        report = json.loads(raw)
        self.assertEqual(report["live_competitor_comparison"]["status"], "SECOND_PAGE_NOT_RETRIEVED")
        self.assertEqual(report["marketplace_leads"]["potential_lower_price_leads"], 1)
        self.assertFalse(report["marketplace_leads"]["payment_authorized"])
        self.assertEqual(report["marketplace_leads"]["source_qualified_comparisons"], 0)
        with sqlite3.connect(str(Path(self.tmp.name) / "webquotes.sqlite")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM quotes").fetchone()[0], 0)


    def test_browser_extension_capture_survives_blocked_marketplace(self):
        from datetime import datetime, timezone
        from test_live_offer_compare import SELECTED, BASE
        from product_intake import SourceAccessDenied
        import sqlite3
        import cart_research as cart
        with patch.object(cart, "generate_local_ai_questions", return_value=[]):
            report = cart.research_cart(SELECTED, fetch=lambda url, host, headers=None: (
                {"items": []} if host == "prices.openfoodfacts.org"
                else {"products": []}))
        report["source_intake"] = {**BASE["source_intake"],
                                   "extraction_method": "Product JSON-LD",
                                   "barcode_status": "FOUND_CHECKSUM_VALID"}
        jid = "X" * 24
        with sqlite3.connect(str(Path(self.tmp.name) / "webquotes.sqlite")) as db:
            db.execute(
                "INSERT INTO cart_research_jobs(id,item,state,created,result,error_type) "
                "VALUES (?,?,?,?,?,NULL)",
                (jid, json.dumps(SELECTED), "READY",
                 "2026-11-02T00:00:00+00:00", json.dumps(report)))
        capture_url = "https://allegro.pl/oferta/stanley-air-kit-18637535530"
        browser_json = json.dumps({
            "version": 1, "method": "USER_SELECTED_VISIBLE_PRICE",
            "url": capture_url, "title": "STANLEY AIR KIT OL195",
            "price": "29.99", "currency": "PLN",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "gtin_claim": None, "price_evidence": "SELECTED_VISIBLE_TEXT",
        })
        with patch("live_offer_compare.extract_product_page",
                   side_effect=SourceAccessDenied(403)):
            status, body = self.request("POST", "/cart/compare-live", {
                "csrf": self.csrf, "job_id": jid,
                "browser_capture_json": browser_json,
            })
        self.assertEqual(status, 200)
        self.assertIn("MARKETPLACE PRICE LEADS", body)
        self.assertIn("29.99", body)
        rid = re.search(r"/research/report/([a-zA-Z0-9_-]+)\.json", body).group(1)
        status, raw = self.request("GET", "/research/report/" + rid + ".json")
        self.assertEqual(status, 200)
        output = json.loads(raw)
        self.assertEqual(output["live_competitor_comparison"]["status"],
                         "SECOND_PAGE_NOT_RETRIEVED")
        row = output["marketplace_leads"]["observations"][0]
        self.assertEqual(row["origin"], "USER_BROWSER_ACTIVE_TAB_NOT_SERVER_VERIFIED")
        self.assertFalse(row["source_page_downloaded_by_tracecart"])
        self.assertEqual(output["marketplace_leads"]["source_qualified_comparisons"], 0)
        self.assertFalse(output["marketplace_leads"]["payment_authorized"])
        with sqlite3.connect(str(Path(self.tmp.name) / "webquotes.sqlite")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM quotes").fetchone()[0], 0)

    def test_browser_capture_and_manual_price_must_not_conflict(self):
        status, _ = self.request("POST", "/cart/compare-live", {
            "csrf": self.csrf, "job_id": "Z" * 24,
            "browser_capture_json": "{}",
            "marketplace_price": "12.00",
            "marketplace_url": "https://allegro.pl/oferta/another",
        })
        self.assertIn(status, (400, 404))


if __name__ == "__main__":
    unittest.main()

# Single-page Chrome-extension capture via existing local UI, no checkout.
