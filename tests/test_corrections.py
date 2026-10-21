"""The corrections page and per-person "Suggest a correction" links, built only when a contact is configured."""
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, unquote, urlsplit

from genealogy.case import ResearchCase
from genealogy.config import ProjectConfig
from genealogy.models import AccessLevel as A, LivingStatus as L, Name, Person
from genealogy.site import build_site


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.anchors = []  # (href, text)
        self._href = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self.anchors.append([self._href, ""])

    def handle_data(self, data):
        if self._href is not None:
            self.anchors[-1][1] += data

    def handle_endtag(self, tag):
        if tag == "a":
            self._href = None


def anchors(text):
    parser = Anchors()
    parser.feed(text)
    return [(href, label) for href, label in parser.anchors]


def case():
    fixture = ResearchCase("fictional", "Fictional corrections case")
    for record in (
        Person("p0001", names=[Name('Ada "Fable" & <Co>')], living=L.DECEASED, sensitivity=A.PUBLIC),
        Person("p0002", names=[Name("Robin Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Person("SECRET-ID", names=[Name("SECRET-NAME")], living=L.LIVING, notes="SECRET-NOTES", sensitivity=A.PUBLIC),
    ):
        fixture.add(record)
    return fixture


def config(**site):
    result = ProjectConfig(name="Fictional", raw={"site": site})
    result.validate()
    return result


class ContactConfigTests(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "genealogy.toml"
            path.write_text("[project]\nname = 'Fictional'\n[site]\n" + text, encoding="utf-8")
            return ProjectConfig.load(path)

    def test_accepts_an_address_an_https_url_and_a_note(self):
        loaded = self.load("contact_email = 'corrections+fable@example.invalid'\n"
                           "contact_url = 'https://example.invalid/contact?topic=corrections'\n"
                           "corrections_note = 'Replies may take a few weeks.'\n")
        self.assertEqual("corrections+fable@example.invalid", loaded.raw["site"]["contact_email"])
        self.assertEqual("https://example.invalid/contact?topic=corrections", loaded.raw["site"]["contact_url"])
        self.assertEqual("Replies may take a few weeks.", loaded.raw["site"]["corrections_note"])

    def test_rejects_anything_but_one_plain_address(self):
        for value in ("''", "'ada'", "'ada@@example.invalid'", "'ada@fable@example.invalid'", "'@example.invalid'",
                      "'ada@'", "'ada fable@example.invalid'", "'ada@example.invalid, bob@example.invalid'",
                      "'ada@example.invalid;bob@example.invalid'", "'ada@example.invalid?cc=bob@example.invalid'",
                      "'<ada@example.invalid>'", '"ada\\u0000@example.invalid"', '"ada\\n@example.invalid"',
                      '"ada\\u200b@example.invalid"', "42", "['ada@example.invalid']"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "site.contact_email"):
                self.load(f"contact_email = {value}\n")

    def test_rejects_urls_that_are_not_plain_https(self):
        for value in ("'http://example.invalid/contact'", "'javascript:alert(1)'", "'mailto:ada@example.invalid'",
                      "'https://user:secret@example.invalid/'", "'https:///contact'", "'//example.invalid/contact'",
                      "'https://example.invalid/a b'", '"https://example.invalid/\\u0007"', "'contact.html'", "true"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "site.contact_url"):
                self.load(f"contact_url = {value}\n")

    def test_note_must_be_text_and_site_must_be_a_table(self):
        with self.assertRaisesRegex(ValueError, "site.corrections_note"):
            self.load("corrections_note = 3\n")
        with self.assertRaisesRegex(ValueError, r"\[site\] must be a table"):
            ProjectConfig(raw={"site": "corrections@example.invalid"}).validate()

    def test_build_refuses_an_unvalidated_unsafe_contact(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaisesRegex(ValueError, "site.contact_url"):
            build_site(case(), ProjectConfig(raw={"site": {"contact_url": "javascript:alert(1)"}}), Path(temp))
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual([], list(Path(temp).iterdir()))


class CorrectionsPageTests(unittest.TestCase):
    def build(self, root, **site):
        return build_site(case(), config(**site), root)

    def html(self, paths):
        return {name: path.read_text(encoding="utf-8") for name, path in paths.items() if name.endswith(".html")}

    def dossier(self, pages, pid):
        return next(text for name, text in pages.items() if name.startswith("people/") and f'data-person-id="{pid}"' in text)

    def test_unset_contact_builds_no_page_and_no_links(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.build(Path(temp), corrections_note="A note with no contact is not shown.")
            self.assertNotIn("corrections.html", paths)
            self.assertNotIn("corrections.html", json.loads(paths["data/routes.json"].read_text()))
            for name, path in paths.items():
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("corrections.html", text, name)
                self.assertNotIn("Suggest a correction", text, name)
                self.assertNotIn("mailto:", text, name)
                self.assertNotIn("A note with no contact", text, name)

    def test_email_contact_builds_page_footer_and_dossier_mailto(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.build(Path(temp), contact_email="corrections+fable@example.invalid",
                               base_url="https://example.invalid/family/",
                               corrections_note="Replies <b>may</b> take a few weeks.\nThank you.")
            pages = self.html(paths)
            page = pages["corrections.html"]
            self.assertIn("<h1>Corrections</h1>", page)
            for words in ("What a useful correction contains", "the address of their page", "The detail that is wrong",
                          "The record that shows it", "Please do not send details of people who may still be living",
                          "should also go to that tree"):
                self.assertIn(words, page)
            self.assertIn(("mailto:corrections+fable@example.invalid", "corrections+fable@example.invalid"), anchors(page))
            self.assertIn('<p class="preserve-lines">Replies &lt;b&gt;may&lt;/b&gt; take a few weeks.\nThank you.</p>', page)
            self.assertIn("corrections.html", json.loads(paths["data/routes.json"].read_text()))
            self.assertIn("https://example.invalid/family/corrections.html", paths["sitemap.xml"].read_text())
            for name, text in pages.items():
                prefix = "../" if "/" in name else ""
                footer = text.split('<footer class="site-footer">', 1)[1]
                self.assertIn((f"{prefix}corrections.html", "Corrections"), anchors(footer), name)
                nav = text.split('<nav aria-label="Main navigation">', 1)[1].split("</nav>", 1)[0]
                self.assertIn((f"{prefix}corrections.html", "Corrections"), anchors(nav), name)
            self.assertIn(("corrections.html", "Corrections"), anchors(pages["sitemap.html"].split("<h2>Explore</h2>", 1)[1]))

            dossier = self.dossier(pages, "p0001")
            href = next(href for href, label in anchors(dossier) if label == "Suggest a correction")
            self.assertIn("&amp;body=", dossier)  # the query separator is escaped in the attribute
            url = urlsplit(href)
            self.assertEqual(("mailto", "corrections+fable@example.invalid"), (url.scheme, url.path))
            query = parse_qs(url.query, keep_blank_values=True)
            self.assertEqual(['Correction: Ada "Fable" & <Co> (p0001)'], query["subject"])
            self.assertNotIn('"', href.split("?", 1)[1])
            self.assertNotIn("<", href)
            page_url = "https://example.invalid/family/" + next(name for name, text in pages.items() if text is dossier)
            self.assertTrue(query["body"][0].startswith(f"Page: {page_url}\r\n"), query["body"])
            self.assertIn("The record that shows it:", query["body"][0])
            self.assertIn(("../corrections.html", "What to include"), anchors(dossier))
            other = self.dossier(pages, "p0002")
            self.assertIn("subject=Correction%3A%20Robin%20Fable%20%28p0002%29&amp;", other)

    def test_mailto_body_has_no_page_address_without_base_url(self):
        with tempfile.TemporaryDirectory() as temp:
            pages = self.html(self.build(Path(temp), contact_email="corrections@example.invalid"))
            href = next(href for href, label in anchors(self.dossier(pages, "p0002")) if label == "Suggest a correction")
            body = parse_qs(urlsplit(href).query, keep_blank_values=True)["body"][0]
            self.assertNotIn("Page:", body)
            self.assertNotIn("http", body)

    def test_url_only_contact_links_dossiers_to_the_corrections_page(self):
        with tempfile.TemporaryDirectory() as temp:
            pages = self.html(self.build(Path(temp), contact_url="https://example.invalid/contact?a=1&b=<2>"))
            self.assertIn('href="https://example.invalid/contact?a=1&amp;b=&lt;2&gt;"', pages["corrections.html"])
            self.assertIn(("https://example.invalid/contact?a=1&b=<2>", "Send a correction online"), anchors(pages["corrections.html"]))
            self.assertIn(("../corrections.html", "Suggest a correction"), anchors(self.dossier(pages, "p0001")))
            for name, text in pages.items():
                self.assertNotIn("mailto:", text, name)

    def test_rebuild_without_a_contact_removes_the_page_and_its_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = self.build(root, contact_email="corrections@example.invalid")
            self.assertTrue(first["corrections.html"].is_file())
            second = self.build(root)
            self.assertFalse((root / "corrections.html").exists())
            self.assertNotIn("corrections.html", json.loads((root / ".genealogy-site-manifest.json").read_text()))
            for name, path in second.items():
                self.assertNotIn("Suggest a correction", path.read_text(encoding="utf-8"), name)
                self.assertNotIn("corrections.html", path.read_text(encoding="utf-8"), name)

    def test_withheld_person_is_absent_from_every_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.build(root, contact_email="corrections@example.invalid", contact_url="https://example.invalid/contact",
                       base_url="https://example.invalid/")
            files = [path for path in root.rglob("*") if path.is_file()]
            self.assertIn(root / "corrections.html", files)
            for path in files:
                text = unquote(unescape(path.read_text(encoding="utf-8")))
                for sentinel in ("SECRET-ID", "SECRET-NAME", "SECRET-NOTES"):
                    self.assertNotIn(sentinel, text, path)


if __name__ == "__main__":
    unittest.main()
