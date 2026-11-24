import tempfile, unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import jit_frontier as j

class SecurityTests(unittest.TestCase):
    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"index.html"
            p.write_text("sentinel")
            self.assertEqual(j.main(["--fixture","demo_sources.json","--out",d]),2)
            self.assertEqual(p.read_text(),"sentinel")
            self.assertFalse((Path(d)/"opportunities.json").exists())
    def test_redact_exception(self):
        with tempfile.TemporaryDirectory() as d:
            source=j.Source("Demo","A","research","Example","https://example.org","demo")
            with patch.object(j,"from_crossref",return_value=[source]), patch.object(j,"from_github",side_effect=ValueError("SYNTHETIC_SECRET")):
                self.assertEqual(j.main(["--a","A","--b","B","--out",d]),0)
            for name in ("opportunities.json","index.html"):
                self.assertNotIn("SYNTHETIC_SECRET",(Path(d)/name).read_text(encoding="utf-8"))
    def test_response_limit(self):
        opener=MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value=b"x"*(j.MAX_RESPONSE+1)
        with patch.object(j.urllib.request,"build_opener",return_value=opener):
            with self.assertRaises(ValueError): j.read_json_url("https://api.github.com/test")
    def test_host_and_redirect(self):
        with self.assertRaises(ValueError): j.read_json_url("https://example.org/")
        with self.assertRaises(ValueError): j.NoRedirect().redirect_request(None,None,302,"",{}, "https://example.org")
