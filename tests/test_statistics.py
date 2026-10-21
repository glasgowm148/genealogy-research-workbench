"""The statistics page: counts of the public record only, as tables with bars, small on a large site."""
from __future__ import annotations

from html import unescape
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Claim, ClaimStatus as S, Confidence as C, Event, Finding, LivingStatus as L, Name,
                              Person, Place, Relationship)
from genealogy.site import ROUTES, STATISTICS_ROWS, _anchor, build_site
from genealogy.sitecheck import check_site

GRADES = {"checked": {"label": "Checked by records", "meaning": "Two records agree.", "confidence": "documented"},
          "ruled_out": {"label": "Ruled out", "meaning": "The records exclude this link.", "confidence": "disproved"}}


def person(pid, name, events=(), given=None):
    """A public person; each event is (kind, date, place_id)."""
    surname = re.sub(r"[/]", "", name).split()[-1]
    return [Person(pid, names=[Name(name, given=given, surname=surname)], living=L.DECEASED, sensitivity=A.PUBLIC,
                   event_ids=[f"{pid}-{n}" for n in range(len(events))]),
            *(Event(f"{pid}-{n}", kind, date=date, place_id=place, participant_ids=[pid], sensitivity=A.PUBLIC)
              for n, (kind, date, place) in enumerate(events))]


def statistics_case():
    case = ResearchCase("fictional-statistics", "Fictional statistics")
    case.add_many([
        Place("pl-a", "Lowtown, Invented Shire, Fableland"), Place("pl-b", "Port Mere, Inventia"), Place("pl-c", "Hamlet"),
        *person("p0001", "Ada /Fable/", [("birth", "1801", "pl-a"), ("death", "1870", "pl-b"), ("Marriage", "1822", "pl-a")]),
        *person("p0002", "Tobin Fable", [("birth", "ABT 1770", "pl-a"), ("death", "1840", "pl-a"), ("marriage", "1795", None)], given="Tobin"),
        *person("p0003", "Iris Fabel", [("birth", "1803", "pl-a"), ("death", "1880", "pl-b")]),
        # Baptised, not born, at a place with no broader jurisdiction; buried, not died.
        *person("p0004", "Bram Fable", [("baptism", "1805", "pl-c"), ("burial", "1850", "pl-b")]),
        *person("p0005", "Ada Vale", [("birth", "1910", "pl-b")]),
        *person("p0006", "Nell Vale"),
        Relationship("r-1", "p0001", "p0002", "parent", confidence=C.DOCUMENTED, sensitivity=A.PUBLIC),
        Relationship("r-3", "p0003", "p0002", "parent", sensitivity=A.PUBLIC),
        Relationship("r-4", "p0004", "p0002", "father", sensitivity=A.PUBLIC),
        Relationship("r-5", "p0005", "p0002", "parent", confidence=C.DISPROVED, sensitivity=A.PUBLIC),
        Relationship("r-6", "p0006", "p0001", "parent", confidence=C.DOCUMENTED, grade="checked", sensitivity=A.PUBLIC),
        Relationship("r-7", "p0006", "p0005", "parent", confidence=C.DISPROVED, grade="ruled_out", sensitivity=A.PUBLIC),
        Claim("c-1", "p0001", "occupation", "weaver", status=S.SUPPORTED, sensitivity=A.PUBLIC),
        Claim("c-2", "p0002", "occupation", "miller", status=S.SUPPORTED, sensitivity=A.PUBLIC),
        Claim("c-3", "p0003", "occupation", "baker", status=S.DISPUTED, sensitivity=A.PUBLIC),
        Claim("c-sex", "p0003", "sex", "F", sensitivity=A.PUBLIC),
        Finding("f-1", "Ada was a weaver.", related_ids=["p0001"], recorded_on="2026-03-01", sensitivity=A.PUBLIC),
        Finding("f-2", "Tobin was a miller.", related_ids=["p0002"], recorded_on="2026-05", sensitivity=A.PUBLIC),
        Finding("f-3", "Iris was a baker.", related_ids=["p0003"], recorded_on="2025", sensitivity=A.PUBLIC),
        Finding("f-4", "Bram was baptised.", related_ids=["p0004"], sensitivity=A.PUBLIC),
        # Withheld: a living child of Tobin born at a private place, a private event and a private finding.
        Place("pl-secret", "SECRET-Town, SECRET-Country", sensitivity=A.PRIVATE),
        Person("p-secret", names=[Name("SECRET-Given SECRET-Surname", given="SECRET-Given", surname="SECRET-Surname")], living=L.LIVING,
               sensitivity=A.PUBLIC, event_ids=["p-secret-b"]),
        Event("p-secret-b", "SECRET-birthkind", date="1995", place_id="pl-secret", participant_ids=["p-secret"], sensitivity=A.PUBLIC),
        Relationship("r-secret", "p-secret", "p0002", "parent", confidence=C.DOCUMENTED, sensitivity=A.PUBLIC),
        Event("e-secret", "SECRET-ceremony", date="1987", place_id="pl-b", participant_ids=["p0005"], sensitivity=A.PRIVATE),
        Finding("f-secret", "SECRET-finding", related_ids=["p0005"], recorded_on="1987-01-01", sensitivity=A.PRIVATE),
        Claim("c-secret", "p0005", "occupation", "SECRET-claim", status=S.REJECTED, sensitivity=A.PRIVATE),
    ])
    return case


def config(name="Fictional statistics"):
    return ProjectConfig(name=name, grades=GRADES, names={"variants": {"Fable": ["Fabel"]}})


def rows(html, key):
    """(cells, count) for each row of the table headed ``key``, as a reader sees them."""
    table = html.split(f'aria-labelledby="{key}"', 1)[1].split("</table>", 1)[0]
    found = []
    for row in re.findall(r"<tr>(.*?)</tr>", table.split("<tbody>", 1)[1]):
        cells = [unescape(re.sub(r"<[^>]+>", "", cell)) for cell in re.findall(r"<td[^>]*>(.*?)</td>", row)]
        found.append((tuple(cells[:-1]), int(cells[-1].replace(",", ""))))
    return found


class StatisticsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        case = statistics_case()
        assert validate_case(case) == []
        cls.paths = build_site(case, config(), cls.root)
        cls.html = (cls.root / "statistics.html").read_text()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_the_page_is_a_route_in_every_menu_and_the_site_index(self):
        self.assertEqual(("statistics", "Statistics"), ROUTES["statistics.html"])
        for page in ("index.html", "catalogue.html", "sitemap.html"):
            self.assertIn('href="statistics.html"', (self.root / page).read_text(), page)
        self.assertIn('<title>Statistics — Fictional statistics</title>', self.html)
        self.assertEqual([], check_site(self.root)["broken"])

    def test_people_by_birth_century_with_baptisms_when_no_birth_is_dated(self):
        self.assertEqual([(("1700–1799",), 1), (("1800–1899",), 3), (("1900–1999",), 1)], rows(self.html, "birth-centuries"))
        self.assertIn("1 person has no recorded year.", self.html)

    def test_people_by_broadest_region_link_to_the_places_page(self):
        self.assertEqual([(("Fableland",), 3), (("Inventia",), 1), (("Places without a broader jurisdiction",), 1)], rows(self.html, "birth-regions"))
        anchor = _anchor("region:Fableland")
        self.assertIn(f'href="places.html#{anchor}">Fableland</a>', self.html)
        self.assertIn(f'id="{anchor}"', (self.root / "places.html").read_text())

    def test_given_names_and_canonical_surnames(self):
        # "Ada /Fable/" counts as Ada; a recorded given name is used as given.
        # A name only one person bears is counted, not listed.
        self.assertEqual([(("Ada",), 2)], rows(self.html, "given-names"))
        self.assertIn("4 names recorded once.", self.html)
        # Iris Fabel is counted under Fable, the surname [names.variants] groups her spelling under.
        self.assertEqual([(("Fable",), 4), (("Vale",), 2)], rows(self.html, "surnames"))
        self.assertIn('href="catalogue.html?surname=Fable">Fable</a>', self.html)

    def test_largest_families_leave_out_disproved_and_withheld_children(self):
        # Tobin: Ada, Iris and Bram; not Ada Vale (disproved) nor the withheld child. Ada Vale's only link is graded "ruled out".
        self.assertEqual([(("Tobin Fable",), 3), (("Ada /Fable/",), 1)], rows(self.html, "families"))  # names as recorded

    def test_places_migrations_and_event_kinds(self):
        self.assertEqual([(("Lowtown, Invented Shire, Fableland",), 5), (("Port Mere, Inventia",), 4), (("Hamlet",), 1)], rows(self.html, "places"))
        # Bram's baptism place has no broader jurisdiction, so his move is not counted; Tobin stayed.
        self.assertEqual([(("Fableland", "Inventia"), 2)], rows(self.html, "migrations"))
        self.assertIn("1 person was born and died in the same one.", self.html)
        self.assertEqual([(("Birth",), 4), (("Death",), 3), (("Marriage",), 2), (("Baptism",), 1), (("Burial",), 1)], rows(self.html, "event-kinds"))

    def test_research_progress_is_left_to_its_own_page(self):
        # The research tables duplicated progress.html; the page links there instead.
        for key in ("research-progress", "claim-status", "relationship-confidence", "findings-by-year"):
            self.assertNotIn(f'id="{key}"', self.html, key)
        self.assertIn('<a href="progress.html">Research progress</a>', self.html)

    def test_tables_are_accessible_and_bars_need_no_script(self):
        tables = re.findall(r'<h[23] id="([a-z-]+)">[^<]+</h[23]>(?:<p class="meta">[^<]*</p>)?<div class="table-wrap"><table class="statistics" aria-labelledby="([a-z-]+)">', self.html)
        self.assertEqual(8, len(tables))
        self.assertTrue(all(heading == label for heading, label in tables))
        self.assertIn('<th scope="col">Born in</th><th scope="col">Died in</th><th scope="col">People</th>', self.html)
        self.assertIn('<td class="count"><div class="meter"><div class="bar-track" aria-hidden="true"><div class="bar" style="--w:100%"></div></div>'
                      '<span>3</span></div></td>', self.html)
        self.assertIn('style="--w:33%"', self.html)
        main = self.html.split('<main id="main-content">', 1)[1].split("</main>", 1)[0]
        self.assertNotIn("<script", main)
        self.assertNotRegex(main, r"\son[a-z]+=")
        self.assertNotIn("site-data.js", self.html)

    def test_no_withheld_record_is_named_or_counted(self):
        for path in self.paths.values():
            if path.suffix in (".html", ".json", ".js", ".csv", ".ged", ".geojson", ".xml"):
                self.assertNotIn("SECRET-", path.read_text(), path)
        self.assertNotIn("1987", self.html)
        self.assertNotIn("Rejected", self.html)
        self.assertIn("6 people, 11 events and 3 places", self.html)

    def test_a_table_with_nothing_to_count_is_left_out(self):
        case = ResearchCase("fictional-sparse", "Fictional sparse")
        case.add_many(person("p0001", "Ada Fable", [("birth", "1801", "pl-a")]) + [Place("pl-a", "Lowtown")])
        with tempfile.TemporaryDirectory() as temp:
            build_site(case, ProjectConfig(name="Sparse"), Path(temp))
            html = (Path(temp) / "statistics.html").read_text()
        for key in ("birth-regions", "families", "migrations", "research-progress", "claim-status", "relationship-confidence", "findings-by-year"):
            self.assertNotIn(f'id="{key}"', html, key)
        for key in ("birth-centuries", "given-names", "surnames", "places", "event-kinds"):
            self.assertIn(f'id="{key}"', html, key)
        with tempfile.TemporaryDirectory() as temp:
            build_site(ResearchCase("fictional-empty", "Empty"), ProjectConfig(name="Empty"), Path(temp))
            html = (Path(temp) / "statistics.html").read_text()
        self.assertIn('<p class="empty-state">No public people are available.</p>', html)
        self.assertNotIn("<table", html)


class LargeStatisticsTests(unittest.TestCase):
    def test_the_page_stays_small_and_each_table_is_capped(self):
        from test_scale import PEOPLE, large_case  # tests/ is on the path under unittest discovery
        with tempfile.TemporaryDirectory() as temp:
            build_site(large_case(), ProjectConfig(name="Fictional large"), Path(temp))
            page = Path(temp) / "statistics.html"
            html = page.read_text()
            self.assertLess(page.stat().st_size, 100_000)
            # On a large site a region links to its own page.
            self.assertIn('href="places/fableland.html">Fableland</a>', html)
            self.assertTrue((Path(temp) / "places" / "fableland.html").is_file())
        self.assertEqual(STATISTICS_ROWS, len(rows(html, "families")))
        self.assertEqual(STATISTICS_ROWS, len(rows(html, "places")))
        parents = len({(n - 1) // 2 for n in range(1, PEOPLE)})  # each person after the first has a parent
        self.assertIn(f"{parents - STATISTICS_ROWS:,} more not listed.", html)
        self.assertIn(f"{PEOPLE - STATISTICS_ROWS:,} more not listed.", html)  # one place per person
        self.assertEqual([(("Fable",), PEOPLE)], rows(html, "surnames"))


if __name__ == "__main__":
    unittest.main()
