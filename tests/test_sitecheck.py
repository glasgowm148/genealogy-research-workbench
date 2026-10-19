"""The static-site link checker on a fixture site and the fictional demo."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from genealogy.cli import main
from genealogy.sitecheck import LinkCheckOptions, check_site, pairs_of, ratchet, resolve

ROOT = Path(__file__).resolve().parents[1]


class LinkCheckTests(unittest.TestCase):
    def test_resolution_baseline_and_anchors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "dir").mkdir()
            (root / "dir" / "index.html").write_text('<p id="here">x</p>')
            (root / "page.html").write_text('<h1 id="top">x</h1>')
            (root / "index.html").write_text(
                '<a href="dir/">ok</a><a href="/dir">ok</a><a href="page.html#top">ok</a><a href="page.html#gone">anchor</a>'
                '<a href="missing.html">broken</a><a href="/page">fallback</a><a href="https://other.invalid/x">external</a>'
                '<img srcset="dir/index.html 1x, nope.png 2x"><script>var a = "<a href=nowhere.html>"</script><!-- <a href="old.html"> -->')
            result = check_site(root)
            self.assertEqual({(row["target"], row["how"]) for row in result["broken"]},
                             {("/missing.html", "missing"), ("/page", "html-fallback"), ("/nope.png", "missing")})
            self.assertEqual([row["anchor"] for row in result["missing_anchors"]], ["gone"])
            current = pairs_of(result["broken"])
            new, fixed = ratchet(current, {("index.html", "/missing.html"), ("index.html", "/old.html")})
            self.assertEqual(new, [("index.html", "/nope.png"), ("index.html", "/page")])
            self.assertEqual(fixed, [("index.html", "/old.html")])
            self.assertEqual(resolve("//elsewhere.invalid/x", frozenset()), (None, "outside-site"))
            absolute = check_site(root, LinkCheckOptions(host="example.invalid"))
            self.assertEqual(len(absolute["broken"]), 3)

    def test_cli_exit_status_and_baseline_update(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()) as output:
            site = Path(temporary) / "site"
            site.mkdir()
            (site / "index.html").write_text('<a href="index.html">home</a>')
            project = ROOT / "examples/demo"
            self.assertEqual(main(["--project", str(project), "check-links", str(site)]), 0)
            (site / "index.html").write_text('<a href="lost.html">x</a>')
            baseline = Path(temporary) / "baseline.json"
            self.assertEqual(main(["--project", str(project), "check-links", str(site), "--baseline", str(baseline)]), 1)
            self.assertEqual(main(["--project", str(project), "check-links", str(site), "--baseline", str(baseline), "--update-baseline"]), 0)
            self.assertEqual(json.loads(baseline.read_text())["count"], 1)
            self.assertEqual(main(["--project", str(project), "check-links", str(site), "--baseline", str(baseline)]), 0)
        self.assertIn("1 broken links", output.getvalue())


if __name__ == "__main__":
    unittest.main()
