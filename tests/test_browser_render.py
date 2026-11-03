"""Only robots-approved successful pages may use the graphical renderer."""
import json
import subprocess
import unittest
from unittest.mock import patch
from pathlib import Path

from browser_render import approved_static_body,rendered_browser_document

URL="https://example.org/products/alpha123"
BODY=b"<html><head><title>Alpha123</title></head><body>JS product shell</body></html>"


class GraphicalRendererTests(unittest.TestCase):
    def test_disabled_by_default_and_not_used_for_captcha(self):
        with self.assertRaises(ValueError):
            rendered_browser_document(URL,BODY,enabled=False)
        for body in (
            b"<html>captcha verification</html>",
            b"<html>Access denied</html>",
            b"<html>cf-mitigated challenge</html>",
            b""):
            self.assertFalse(approved_static_body(body))
            with self.assertRaises(ValueError):
                rendered_browser_document(URL,body,enabled=True)

    def test_backend_pin_and_no_arbitrary_url_shell_commands(self):
        payload={"source_url":URL,
                 "browser_request_scope":"SAME_ORIGIN_HTTPS_ONLY_PINNED_PUBLIC_IP",
                 "render_method":"ISOLATED_XVFB_CHROMIUM",
                 "html":"<html><body>Rendered product technical data: 42 GB</body></html>"}
        observed=[]
        def runner(cmd,**kwargs):
            observed.append((cmd,kwargs))
            return subprocess.CompletedProcess(cmd,0,
                stdout=json.dumps(payload).encode(),stderr=b"")
        with patch("browser_render._public_pinned_ipv4",
                   return_value="93.184.216.34"):
            result=rendered_browser_document(
                URL,BODY,runner=runner,enabled=True)
        self.assertIn(b"technical data",result)
        self.assertEqual(len(observed),1)
        self.assertEqual(observed[0][0][0],"node")
        self.assertEqual(observed[0][0][2],URL)
        self.assertEqual(observed[0][0][3],"example.org")
        self.assertEqual(observed[0][0][4],"93.184.216.34")
        self.assertFalse(observed[0][1].get("shell",False))

    def test_source_url_must_match_even_after_rendering(self):
        payload={"source_url":"https://attacker.example/private",
                 "browser_request_scope":"SAME_ORIGIN_HTTPS_ONLY_PINNED_PUBLIC_IP",
                 "render_method":"ISOLATED_XVFB_CHROMIUM",
                 "html":BODY.decode()}
        def runner(cmd,**kwargs):
            return subprocess.CompletedProcess(cmd,0,
                stdout=json.dumps(payload).encode(),stderr=b"")
        with patch("browser_render._public_pinned_ipv4",
                   return_value="93.184.216.34"):
            with self.assertRaises(ValueError):
                rendered_browser_document(URL,BODY,runner=runner,enabled=True)

    def test_static_robot_failure_never_launches_chromium(self):
        from generic_source_research import execute_generic_sources
        calls=[]
        def fetch(url,*args,**kwargs):
            calls.append(url)
            return b"User-agent: *\nDisallow: /\n"
        with patch("browser_render.rendered_browser_document",
                   side_effect=AssertionError("Should never use browser")):
            result=execute_generic_sources({
                "title":"Foomaker A123 phone","url":URL},
                "SMARTPHONE",fetch=fetch,enable_brand_discovery=False)
        self.assertEqual(result["reference_answers"],[])
        self.assertEqual(len(calls),1)


if __name__=="__main__":
    unittest.main()
