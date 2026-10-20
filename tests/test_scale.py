"""Large projects: no page writes out a list of thousands of records."""
from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Citation, Claim, ClaimStatus, Event, Evidence, Finding,
                              LivingStatus as L, Name, Person, Relationship, Source)
from genealogy.site import INLINE_LIMIT, _anchor, build_site
from genealogy.sitecheck import check_site

PEOPLE = INLINE_LIMIT + 100


def large_case(people: int = PEOPLE) -> ResearchCase:
    case = ResearchCase("fictional-large", "Fictional large tree")
    records = [Source("register", "Invented register", "register", sensitivity=A.PUBLIC),
               Citation("register-1", "register", locator="entry 1", sensitivity=A.PUBLIC)]
    for n in range(people):
        pid = f"p{n:04d}"
        records += [
            Person(pid, names=[Name(f"Person {n:04d} Fable", surname="Fable")], living=L.DECEASED,
                   event_ids=[f"{pid}-b"], sensitivity=A.PUBLIC),
            Event(f"{pid}-b", "birth", date=str(1700 + n % 150), participant_ids=[pid], sensitivity=A.PUBLIC),
            Claim(f"{pid}-c", pid, "occupation", "weaver", citation_ids=["register-1"], status=ClaimStatus.SUPPORTED,
                  sensitivity=A.PUBLIC),
            Evidence(f"{pid}-e", f"{pid}-c", "register-1", "The register names the trade.", sensitivity=A.PUBLIC),
            Finding(f"{pid}-f", f"Finding about person {n:04d}.", related_ids=[pid], status="reviewed",
                    recorded_on=f"2026-{1 + n % 12:02d}-{1 + n % 28:02d}", sensitivity=A.PUBLIC),
        ]
        if n:
            records.append(Relationship(f"{pid}-r", pid, f"p{(n - 1) // 2:04d}", "parent", sensitivity=A.PUBLIC))
    records.append(Finding("open-1", "An open question still being worked.", related_ids=["p0001"], status="draft",
                           recorded_on="2026-10-20", sensitivity=A.PUBLIC))
    case.add_many(records)
    return case


class LargeSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.out = Path(cls.directory.name)
        case = large_case()
        assert validate_case(case) == []
        build_site(case, ProjectConfig(name="Fictional", raw={"site": {"base_url": "https://example.invalid/"}}), cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def text(self, path):
        return (self.out / path).read_text()

    def test_person_menus_and_lists_are_not_written_out(self):
        for page in ("tree.html", "compare.html", "connections.html"):
            html = self.text(page)
            self.assertLessEqual(html.count("<option"), 3, page)
            self.assertNotIn("Person 0123 Fable", html, page)
        self.assertIn(f"All {PEOPLE:,} people are listed in the", self.text("compare.html"))
        self.assertIn("recorded family connections. Each person's page lists", self.text("tree.html"))
        self.assertNotIn("Person 0123 Fable", self.text("sitemap.html"))

    def test_claims_relationships_and_findings_live_on_their_own_pages(self):
        research = self.text("research.html")
        self.assertNotIn(f'id="{_anchor("p0123-c")}"', research)
        self.assertIn("is shown, with its citations and evidence, on the page of the person", research)
        self.assertIn("An open question still being worked.", research)
        self.assertNotIn("Finding about person 0123.", research)
        # Links to a claim, relationship or finding reach the record where it is shown.
        dossier = next(p for p in (self.out / "people").glob("*.html") if 'data-person-id="p0123"' in p.read_text()).read_text()
        for record in ("p0123-c", "p0123-e", "p0123-r"):
            self.assertIn(f'id="{_anchor(record)}"', dossier)
        self.assertIn(f'#{_anchor("p0123-f")}', dossier)
        self.assertEqual([], check_site(self.out)["broken"])

    def test_pages_stay_small(self):
        sizes = {p.name: p.stat().st_size for p in self.out.glob("*.html")}
        for name in ("tree.html", "compare.html", "connections.html", "research.html", "sitemap.html", "findings.html", "index.html"):
            self.assertLess(sizes[name], 100_000, name)


if __name__ == "__main__":
    unittest.main()
