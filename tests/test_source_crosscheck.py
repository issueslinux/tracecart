"""SHT40 nominal spec crosscheck from two separately attributed source documents."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from decision_tree import to_html_tree
from source_crosscheck import (MERCHANT_URL, OEM_URL, _check_robots,
                               collect_spec_crosscheck, parse_merchant_specs,
                               parse_oem_specs)


def _merchant(value="1.8", temp="0.2"):
    product = {"@type": "Product", "name": "SHT40 board",
               "offers": {"price": "5.95", "priceCurrency": "USD",
                          "availability": "https://schema.org/InStock"}}
    return ("""<html><h1>SHT40 Specifications &amp; Features</h1>
<p>Relative humidity accuracy: up to ±{} %RH</p>
<p>Temperature accuracy: up to ±{} °C</p>
<script type="application/ld+json">{}</script>
</html>""".format(value, temp, json.dumps(product)))


def _oem(value="1.8", temp="0.2"):
    return ("""<html><h1>SHT40</h1>
<h2>Typ. relative humidity accuracy</h2><span>{}</span><span>%RH</span>
<h2>Typ. temperature accuracy</h2><span>{}</span><span>°C</span>
</html>""".format(value, temp))


class CrosscheckTests(unittest.TestCase):
    def _collect(self, merchant=None, oem=None, robots=None):
        pages = {
            MERCHANT_URL: _merchant() if merchant is None else merchant,
            OEM_URL: _oem() if oem is None else oem
        }
        fetches = []

        def fetch(url):
            fetches.append(url)
            raw = pages[url].encode("utf-8")
            return raw, pages[url]

        r, payload = collect_spec_crosscheck(
            fetch_html=fetch,
            download_robots=lambda u: (
                robots.encode("utf-8") if robots is not None
                else b"User-agent: *\nAllow: /\n"
            ))
        return r, payload, fetches

    def test_two_source_realistic_match_and_provenance(self):
        report, data, fetches = self._collect()
        self.assertEqual(fetches, [MERCHANT_URL, OEM_URL])
        self.assertEqual(data["offers"][0]["price"], "5.95")
        self.assertEqual([x["documents_agree"] for x in report["crosscheck"]], [True, True])
        self.assertEqual(report["root"]["children"][-1]["status"], "ABSTAIN")
        self.assertEqual(report["source_collection"]["independent_product_tests_collected"], 0)
        self.assertEqual(report["source_collection"]["review_sources_collected"], 0)
        offer = next(x for x in report["root"]["children"] if x["kind"] == "offer")
        humidity = next(x for x in offer["children"] if x["id"].endswith("-typical_humidity_accuracy"))
        self.assertEqual(humidity["status"], "CORROBORATED")
        sources = [n for n in humidity["children"] if n["kind"] == "evidence"]
        self.assertEqual(len(sources), 2)
        self.assertEqual({x["details"]["publisher_domain"] for x in sources},
                         {"adafruit.com", "sensirion.com"})
        for source in sources:
            self.assertEqual(len(source["details"]["source_content_sha256"]), 64)
            self.assertIn("retrieved_at", source["details"])
        self.assertIn("laboratory", to_html_tree(report).lower())

    def test_conflicting_spec_creates_critic_objection(self):
        report, data, _ = self._collect(oem=_oem(value="2.1"))
        self.assertEqual(report["crosscheck"][0]["documents_agree"], False)
        offer = next(x for x in report["root"]["children"] if x["kind"] == "offer")
        humidity = next(x for x in offer["children"] if x["id"].endswith("-typical_humidity_accuracy"))
        self.assertEqual(humidity["status"], "CONFLICTED")
        critic = [x for x in humidity["children"] if x["kind"] == "critic"]
        self.assertEqual(len(critic), 1)
        self.assertEqual(report["root"]["children"][-1]["status"], "ABSTAIN")
        self.assertTrue(any(n["kind"] == "follow_up" for n in critic[0]["children"]))

    def test_oem_missing_spec_must_fail_no_fabrication(self):
        with self.assertRaises(ValueError):
            self._collect(oem="<h1>SHT40</h1><p>No accuracy stated here</p>")

    def test_markup_in_scripts_must_not_count_as_spec(self):
        fake = ("<h1>SHT40</h1>"
                '<script>Typ. relative humidity accuracy 1.8 %RH</script>'
                '<span>Typ. temperature accuracy</span><span>0.2</span><span>°C</span>')
        with self.assertRaises(ValueError):
            parse_oem_specs(fake)

    def test_forged_duplicate_nominal_spec_fails_closed(self):
        repeated = _oem() + _oem()
        with self.assertRaises(ValueError):
            parse_oem_specs(repeated)

    def test_robots_deny_blocks_both_fetches(self):
        with self.assertRaisesRegex(ValueError, "robots"):
            self._collect(robots="User-agent: *\nDisallow: /\n")

    def test_html_parsing_rejects_different_exact_model(self):
        with self.assertRaises(ValueError):
            parse_oem_specs(_oem().replace("<h1>SHT40</h1>", "<h1>SHT45</h1>"))
        with self.assertRaises(ValueError):
            parse_merchant_specs(_merchant().replace("SHT40 Specifications", "SHT45 Specifications"))

    def test_breakout_supply_voltage_not_compared_as_chip_volts(self):
        report, data, _ = self._collect()
        self.assertFalse(any("voltage" in q["id"] for q in data["offers"][0]["questions"]))
        self.assertTrue(all("NOT measured breakout-board performance" in x["scope"]
                            for x in report["crosscheck"]))
        proposal_text = " ".join(x["text"] for x in data["generated_questions"])
        self.assertIn("independent laboratory", proposal_text)

    def test_original_merchants_are_not_autorized_payments(self):
        report, data, _ = self._collect()
        self.assertFalse(report["root"]["children"][-1]["details"]["eligible_for_payment"])


if __name__ == "__main__":
    unittest.main()
