"""Studies, dated findings, branches, place precision and prose markup."""
from __future__ import annotations

from html import unescape
from pathlib import Path
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.markup import references, render
from genealogy.models import (AccessLevel as A, Event, Finding, LivingStatus as L, Name, Person, Place, Relationship,
                              ResearchQuestion, Study)
from genealogy.site import build_site
from genealogy.sitecheck import check_site

def resolver(rid):
    return ("people/ada.html", "Ada Fable") if rid == "ada" else None


class MarkupTests(unittest.TestCase):
    def test_subset_renders_and_escapes(self):
        html = render("## Heading <b>\n\nA *small* **bold** `x<y` [site](https://example.invalid/a?b=1&c=2) "
                      "[bad](javascript:alert(1)) [[ada]] [[ada|her]] [[secret-id]] [[secret-id|a cousin]]\n\n"
                      "- one\n- two\n\n1. first\n\n> quoted <script>", resolver)
        self.assertIn("<h3>Heading &lt;b&gt;</h3>", html)
        self.assertIn("<em>small</em>", html)
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn("<code>x&lt;y</code>", html)
        self.assertIn('<a href="https://example.invalid/a?b=1&amp;c=2" rel="noreferrer">site</a>', html)
        self.assertNotIn('href="javascript', html)
        self.assertIn('<a href="people/ada.html">Ada Fable</a>', html)
        self.assertIn('<a href="people/ada.html">her</a>', html)
        self.assertNotIn("secret-id", html)
        self.assertIn("withheld record", html)
        self.assertIn("a cousin", html)
        self.assertIn("<ul><li>one</li><li>two</li></ul><ol><li>first</li></ol>", html)
        self.assertIn("<blockquote><p>quoted &lt;script&gt;</p></blockquote>", html)
        self.assertEqual(references("[[a]] and [[b|label]]"), ["a", "b"])


def research_case():
    case = ResearchCase("fictional-study", "Fictional study")
    for record in [
        Person("ada", names=[Name("Ada Fable", surname="Fable")], living=L.DECEASED, event_ids=["ada-b"], sensitivity=A.PUBLIC),
        Event("ada-b", "birth", date="1801", place_id="parish", participant_ids=["ada"], sensitivity=A.PUBLIC),
        Person("rowan", names=[Name("Rowan Fable", surname="Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Person("pip", names=[Name("Pip Vale", surname="Vale")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Person("secret", names=[Name("SECRET LIVING")], living=L.LIVING, sensitivity=A.PUBLIC),
        Relationship("r1", "rowan", "ada", "parent", sensitivity=A.PUBLIC),
        Place("parish", "Invented Parish", latitude=55.0, longitude=-4.0, precision="parish", sensitivity=A.PUBLIC),
        ResearchQuestion("q1", "Who were Ada's parents?", related_ids=["ada"], sensitivity=A.PUBLIC),
        Finding("f-old", "Ada was baptised in the invented parish.", related_ids=["ada"], status="reviewed", recorded_on="2026-03-02", sensitivity=A.PUBLIC),
        Finding("f-new", "Rowan is Ada's son.", related_ids=["rowan", "ada"], recorded_on="2026-10-01", sensitivity=A.PUBLIC),
        Finding("f-undated", "An undated observation.", related_ids=["pip"], sensitivity=A.PUBLIC),
        Study("s-public", "The Fable household", summary="Why the Fables matter.", rationale="Because [[ada]] is the earliest.",
              body="## Records\n\n[[rowan|Her son]] appears later. See [[f-new]].", conclusion="Probably one household.",
              related_ids=["ada", "rowan", "parish", "q1", "f-old"], updated_on="2026-10-01", sensitivity=A.PUBLIC),
        Study("s-private-subject", "STUDY ABOUT A LIVING PERSON", related_ids=["secret"], sensitivity=A.PUBLIC),
        Study("s-private-prose", "STUDY NAMING A LIVING PERSON", body="Mentions [[secret]].", sensitivity=A.PUBLIC),
    ]:
        case.add(record)
    return case


class StudySiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.paths = build_site(research_case(), ProjectConfig(name="Fictional", raw={"site": {"base_url": "https://example.invalid/"}}), cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def text(self, name):
        return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", self.paths[name].read_text())))

    def test_study_pages_link_both_ways_and_withhold_private_studies(self):
        studies = [name for name in self.paths if name.startswith("studies/")]
        self.assertEqual(len(studies), 1)
        page = self.paths[studies[0]].read_text()
        self.assertIn("<h1>The Fable household</h1>", page)
        self.assertIn("Why this study", page)
        self.assertIn(">Her son</a>", page)
        self.assertIn("Current conclusion", page)
        self.assertIn("Who were Ada&#x27;s parents?", page)
        dossier = next(path for name, path in self.paths.items() if name.startswith("people/") and "<h1>Ada Fable</h1>" in path.read_text()).read_text()
        self.assertIn(f'href="../{studies[0]}"', dossier)
        everything = "\n".join(path.read_text() for path in self.root.rglob("*") if path.is_file())
        for secret in ("SECRET LIVING", "STUDY ABOUT A LIVING PERSON", "STUDY NAMING A LIVING PERSON", "s-private"):
            self.assertNotIn(secret, everything)
        self.assertIn("The Fable household", self.text("studies.html"))

    def test_findings_log_is_dated_newest_first_with_feed(self):
        log = self.text("findings.html")
        self.assertLess(log.index("October 2026"), log.index("March 2026"))
        self.assertLess(log.index("Rowan is Ada's son"), log.index("Ada was baptised"))
        self.assertGreater(log.index("Undated findings"), log.index("March 2026"))
        self.assertIn("Studies: The Fable household", log)
        feed = ET.fromstring(self.paths["findings.xml"].read_text())
        ns = {"a": "http://www.w3.org/2005/Atom"}
        entries = feed.findall("a:entry", ns)
        self.assertEqual([e.find("a:updated", ns).text for e in entries], ["2026-10-01T00:00:00Z", "2026-03-02T00:00:00Z"])

    def test_branches_precision_and_links(self):
        branches = self.text("branches.html")
        self.assertRegex(branches, r"Fable 2 1801–1801 Invented Parish Ada Fable")
        self.assertIn('catalogue.html?surname=Fable', self.paths["branches.html"].read_text())
        self.assertIn("Group 1 2 Fable", branches)
        self.assertIn("1 people have no public recorded relatives", branches)
        places = self.paths["places.html"].read_text()
        self.assertIn("located to parish level", places)
        self.assertIn('class="broad"', places)
        result = check_site(self.root)
        self.assertEqual(result["broken"], [])
        self.assertEqual(result["missing_anchors"], [])

    def test_validation_of_dates_precision_and_prose_references(self):
        case = ResearchCase("invalid", "Invalid")
        case.add(Finding("f", "Text", recorded_on="2026-13-01"))
        case.add(Place("p", "Somewhere", precision="nearby"))
        case.add(Study("s", "Study", body="See [[nobody]].", updated_on="soon"))
        errors = "\n".join(validate_case(case))
        self.assertIn("f.recorded_on must be an ISO date", errors)
        self.assertIn("p.precision must be one of", errors)
        self.assertIn("s.body refers to missing record [[nobody]]", errors)
        self.assertIn("s.updated_on must be an ISO date", errors)


if __name__ == "__main__":
    unittest.main()
