"""CLI contract: offline by default, network only behind explicit --fetch."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts_extract_snapshot import main


class ExtractorCLITests(unittest.TestCase):
    def test_offline_cli_returns_evidence(self):
        product = {"@type": "Product", "name": "Przykład CLI",
                   "offers": {"@type": "Offer", "price": "13.00", "priceCurrency": "PLN"}}
        html = ("<script type='application/ld+json'>" +
                json.dumps(product) + "</script>")
        with TemporaryDirectory() as directory:
            file = Path(directory) / "snapshot.html"
            file.write_text(html, encoding="utf-8")
            output = StringIO()
            with redirect_stdout(output):
                main(["--url", "https://shop.example.org/p/cli",
                      "--input", str(file)])
        result = json.loads(output.getvalue())
        self.assertEqual(result["fields"]["price"], "13.00")
        self.assertEqual(result["acquisition_method"], "STATIC_HTML")

    def test_explicit_fetch_calls_acquisition(self):
        output = StringIO()
        with patch("scripts_extract_snapshot.acquire_public_product", return_value={
            "status": "ROBOTS_DENIED", "seller_verified": False}) as call:
            with redirect_stdout(output):
                main(["--url", "https://shop.example.org/p/cli", "--fetch"])
        call.assert_called_once_with("https://shop.example.org/p/cli", enable_render=False)
        self.assertEqual(json.loads(output.getvalue())["status"], "ROBOTS_DENIED")

    def test_unintended_network_or_renderer_flag_rejected(self):
        with self.assertRaises(SystemExit):
            main(["--url", "https://shop.example.org/p/cli",
                  "--enable-render", "--input", "/does/not/exist"])


if __name__ == "__main__":
    unittest.main()
