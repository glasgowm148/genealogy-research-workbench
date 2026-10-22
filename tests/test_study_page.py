"""The study page: back link, type, stat strip, locator map, limits callout and links grouped by type."""
from __future__ import annotations

from html import unescape
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Event, Finding, LivingStatus as L, Name, Person, Place,
                              ResearchQuestion, Source, Study)
from genealogy.site import build_site
from genealogy.sitecheck import check_site


def study_case():
    case = ResearchCase("fictional-study-page", "Fictional study page")
    for record in [
        Place("mill", "Millbrook (invented)", latitude=55.0, longitude=-4.0, precision="exact", sensitivity=A.PUBLIC),
        Place("quay", "Quayside (invented)", latitude=55.5, longitude=-3.0, precision="parish", sensitivity=A.PUBLIC),
        Place("far", "Farfield (invented)", latitude=54.0, longitude=-2.0, sensitivity=A.PUBLIC),
        Place("nowhere", "Unlocated Hamlet (invented)", sensitivity=A.PUBLIC),
        Place("hidden-place", "SECRET-PLACE", latitude=10.0, longitude=10.0, sensitivity=A.PRIVATE),
        Person("ada", names=[Name("Ada Fable", surname="Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Person("rowan", names=[Name("Rowan Fable", surname="Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Person("cara", names=[Name("Cara Vale", surname="Vale")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Event("ada-b", "birth", date="1801", place_id="mill", participant_ids=["ada"], sensitivity=A.PUBLIC),
        Event("ada-m", "marriage", date="1825", place_id="quay", participant_ids=["ada", "rowan"], sensitivity=A.PUBLIC),
        Event("rowan-d", "death", date="1870", place_id="nowhere", participant_ids=["rowan"], sensitivity=A.PUBLIC),
        Person("pip", names=[Name("Pip Vale", surname="Vale")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Event("pip-d", "death", date="1880", place_id="nowhere", participant_ids=["pip"], sensitivity=A.PUBLIC),
        Event("cara-b", "birth", date="1805", place_id="far", participant_ids=["cara"], sensitivity=A.PUBLIC),
        Event("ada-secret", "census", date="1841", place_id="hidden-place", description="SECRET-EVENT", participant_ids=["ada"], sensitivity=A.PRIVATE),
        Source("register", "Invented register", sensitivity=A.PUBLIC),
        ResearchQuestion("q1", "Were Ada and Rowan married twice?", related_ids=["ada"], sensitivity=A.PUBLIC),
        Finding("f1", "Ada married Rowan at Quayside.", related_ids=["ada"], status="reviewed", sensitivity=A.PUBLIC),
        Finding("f2", "The study's own observation.", related_ids=["s"], sensitivity=A.PUBLIC),
        Study("s", "The Fable marriage", kind="place_study", summary="Where Ada and Rowan married.", rationale="Two quays share a name.",
              body="The register is the only record.", conclusion="At Quayside.",
              limitations="Shared places do not establish kinship.\n\nThe register is a <copy>.",
              related_ids=["ada", "rowan", "register", "q1", "f1"],
              groups=[{"id": "g", "title": "The lodgers", "member_ids": ["cara"]}], updated_on="2026-10-01", sensitivity=A.PUBLIC),
        Study("plain", "An unlocated study", related_ids=["pip"], sensitivity=A.PUBLIC),
        Study("withheld", "SECRET-STUDY", kind="SECRET-KIND", limitations="SECRET-LIMITS", related_ids=["ada"], sensitivity=A.PRIVATE),
    ]:
        case.add(record)
    return case


class StudyPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        case = study_case()
        assert validate_case(case) == [], validate_case(case)
        cls.paths = build_site(case, ProjectConfig(name="Fictional"), cls.root)
        pages = {name: path.read_text() for name, path in cls.paths.items() if name.startswith("studies/s-")}
        cls.page = next(html for html in pages.values() if "<h1>The Fable marriage</h1>" in html)
        cls.plain = next(html for html in pages.values() if "<h1>An unlocated study</h1>" in html)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def text(self, html):
        return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html)))

    def test_header_has_back_link_type_badge_and_stat_strip(self):
        self.assertIn('<p class="back-link"><a href="../studies.html">← Studies</a></p>', self.page)
        self.assertIn('<span class="badge study-kind" data-kind="place_study">Place study</span>', self.page)
        self.assertNotIn("study-kind", self.plain)
        stats = re.search(r'<ul class="study-stats".*?</ul>', self.page).group(0)
        # Ada, Rowan and the grouped Cara; five linked records; their four public events; f1 linked, f2 naming the study.
        self.assertEqual("3 people 5 linked records 4 events 2 findings linked", self.text(stats).strip())
        self.assertIn("1 person 1 linked record 1 event 0 findings linked", self.text(self.plain))

    def test_locator_marks_each_located_place_of_the_studys_people(self):
        header = re.search(r'<div class="study-header with-map">.*?</section></div>', self.page).group(0)
        self.assertIn('<p class="lead">Where Ada and Rowan married.</p><h2>Why this study</h2>', header)
        svg = re.search(r'<svg class="place-map".*?</svg>', header).group(0)
        self.assertIn('role="img" aria-label="Map of 3 places in this study"', svg)
        self.assertIn('href="../assets/world.svg"', svg)
        self.assertEqual(3, svg.count("<circle"))
        self.assertEqual(1, svg.count('class="broad"'))
        for name in ("Millbrook (invented)", "Quayside (invented)", "Farfield (invented)"):
            self.assertIn(f"<title>{name}</title>", svg)
        self.assertNotIn("Unlocated Hamlet", svg)
        # The crop holds every marker inside the basemap.
        left, top, width, height = map(float, re.search(r'viewBox="([^"]+)"', svg).group(1).split())
        self.assertAlmostEqual(width, 2 * height, places=0)
        for cx, cy in re.findall(r'cx="([\d.]+)" cy="([\d.]+)"', svg):
            self.assertTrue(left <= float(cx) <= left + width and top <= float(cy) <= top + height)
        self.assertTrue(0 <= left and left + width <= 960 and 0 <= top and top + height <= 480)
        self.assertIn('Places: <a href="../places/', header)
        # No located place: no map and a one-column header.
        self.assertNotIn('<svg class="place-map"', self.plain.split("<h2>Current conclusion</h2>")[0])
        self.assertNotIn("with-map", self.plain)

    def test_limits_callout_then_conclusion_then_grouped_links(self):
        limits = re.search(r'<aside class="study-limits".*?</aside>', self.page).group(0)
        self.assertIn('<h2 id="study-limits">What this does not show</h2><p>Shared places do not establish kinship.</p><p>The register is a &lt;copy&gt;.</p>', limits)
        self.assertNotIn("study-limits", self.plain)
        order = [self.page.index(h) for h in ('class="back-link"', 'class="study-stats"', 'class="study-header', 'class="study-body"',
                                              "<h2>Households and groups</h2>", 'class="study-limits"', "<h2>Current conclusion</h2>",
                                              "<h2>People and records in this study</h2>")]
        self.assertEqual(sorted(order), order)
        links = self.page[self.page.index("<h2>People and records in this study</h2>"):]
        headings = re.findall(r'<h3>(\w+) <span class="count">(\d+)</span></h3>', links)
        self.assertEqual([("People", "3"), ("Sources", "1"), ("Findings", "2"), ("Questions", "1")], headings)
        self.assertIn("Cara Vale", links)
        self.assertIn("The study&#x27;s own observation.", links)
        self.assertIn('data-status="reviewed"', links)
        self.assertNotIn("Related findings and questions", self.page)
        self.assertIn("No public people or records are linked.", self.text(build_empty()))

    def test_links_resolve_and_withheld_records_stay_out(self):
        result = check_site(self.root)
        self.assertEqual(result["broken"], [])
        self.assertEqual(result["missing_anchors"], [])
        everything = "\n".join(path.read_text() for path in self.root.rglob("*") if path.is_file() and path.suffix in (".html", ".json", ".js", ".csv", ".xml", ".ged"))
        for secret in ("SECRET-PLACE", "SECRET-EVENT", "SECRET-STUDY", "SECRET-KIND", "SECRET-LIMITS"):
            self.assertNotIn(secret, everything)

    def test_kind_and_limitations_are_validated(self):
        case = ResearchCase("invalid", "Invalid")
        case.add(Study("blank", "Study", kind="  "))
        case.add(Study("number", "Study", kind=3, limitations=["not text"]))
        errors = "\n".join(validate_case(case))
        self.assertIn("blank.kind must be a non-empty string or null", errors)
        self.assertIn("number.kind must be a non-empty string or null", errors)
        self.assertIn("number.limitations must be a string or null", errors)
        self.assertEqual([], validate_case(study_case()))


    def test_a_study_of_many_places_draws_a_bounded_map(self):
        case = ResearchCase("many-places", "Many places")
        case.add(Person("ada", names=[Name("Ada Fable", surname="Fable")], living=L.DECEASED, sensitivity=A.PUBLIC))
        for n in range(260):
            case.add(Place(f"pl{n:03d}", f"Place {n:03d} (invented)", latitude=50 + n / 100, longitude=-5 + n / 50, sensitivity=A.PUBLIC))
            case.add(Event(f"e{n:03d}", "residence", date=str(1800 + n % 50), place_id=f"pl{n:03d}", participant_ids=["ada"], sensitivity=A.PUBLIC))
        case.add(Study("wide", "A wide study", related_ids=["ada"], sensitivity=A.PUBLIC))
        with tempfile.TemporaryDirectory() as temporary:
            paths = build_site(case, ProjectConfig(name="Fictional"), Path(temporary))
            page = next(path.read_text() for name, path in paths.items() if name.startswith("studies/s-"))
        svg = re.search(r'<svg class="place-map".*?</svg>', page).group(0)
        self.assertIn('aria-label="Map of 260 places in this study"', svg)
        self.assertEqual(200, svg.count("<circle"))
        self.assertIn("The first 200 by name are drawn.", page)
        self.assertIn("and 230 more.", page)
        self.assertLess(len(page.encode()), 100_000)


def build_empty():
    case = ResearchCase("empty-study", "Empty study")
    case.add(Study("lonely", "A study of nothing", sensitivity=A.PUBLIC))
    with tempfile.TemporaryDirectory() as temporary:
        paths = build_site(case, ProjectConfig(name="Fictional"), Path(temporary))
        return next(path.read_text() for name, path in paths.items() if name.startswith("studies/s-"))


if __name__ == "__main__":
    unittest.main()
