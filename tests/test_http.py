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
        from http.server import HTTPServer
        server = HTTPServer(("127.0.0.1", 0), app.TraceCartHandler)
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
        status, body = self.request("GET", "/cart/status/" + jid)
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
        status, page = self.request("GET","/cart/status/"+jid)
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
        status, ready = self.request("GET", "/cart/status/" + job_id)
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


if __name__ == "__main__":
    unittest.main()
