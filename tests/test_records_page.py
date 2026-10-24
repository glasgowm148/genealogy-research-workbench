"""The records page: one row per public citation, with its year, people, type, place and strongest assessment."""
from __future__ import annotations

from html import unescape
import json
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Citation, Claim, Confidence, Event, Evidence, LivingStatus as L, Name, Person, Place,
                              Source)
from genealogy.site import RECORDS_ABSTRACT, RECORDS_PER_PAGE, ROUTES, _anchor, _owned, build_site
from genealogy.sitecheck import check_site

LONG = ("Baptism of Ada, daughter of Tobin and Wren Fable of Harbour Row, born the week before; "
        "the entry is in the curate's hand and names both godparents, a weaver and his wife, of the same row. ") * 2
CONFIG = ProjectConfig(name="Fictional records", source_types={"parish_register": {"label": "Parish registers"}})


def case() -> ResearchCase:
    c = ResearchCase("fictional-records", "Fictional records")
    people = [Person(pid, names=[Name(f"{given} Fable", surname="Fable")], living=L.DECEASED, sensitivity=A.PUBLIC)
              for pid, given in (("p0001", "Ada"), ("p0002", "Bram"), ("p0003", "Cora"), ("p0004", "Dov"))]
    people[0].event_ids = ["p0001-b"]
    c.add_many([
        *people,
        Place("pl1", "Invented Town, Fableshire, Fableland", sensitivity=A.PUBLIC),
        Event("p0001-b", "birth", date="ABT 1801", place_id="pl1", participant_ids=["p0001"], sensitivity=A.PUBLIC),
        Event("m1", "marriage", date="1822", place_id="pl1", participant_ids=["p0001", "p0002"], sensitivity=A.PUBLIC),
        Source("s1", "Invented parish register", "parish_register", sensitivity=A.PUBLIC),
        Source("s2", "Invented household returns", "census", sensitivity=A.PUBLIC),
        # The year comes from the event the claim concerns; the abstract is cut to one short line.
        Citation("c1", "s1", locator="entry 75", abstract=LONG, quality="original", sensitivity=A.PUBLIC),
        Claim("c1-claim", "p0001", "birth", "ABT 1801", citation_ids=["c1"], sensitivity=A.PUBLIC),
        Evidence("c1-e", "c1-claim", "c1", "Names Ada as the child baptised.", confidence=Confidence.DOCUMENTED, sensitivity=A.PUBLIC),
        # The year written in the locator wins; four people, three named.
        Citation("c2", "s2", locator="1841 return, folio 3", sensitivity=A.PUBLIC),
        *[Claim(f"c2-{pid}", pid, "occupation", "weaver", citation_ids=["c2"], sensitivity=A.PUBLIC) for pid in ("p0001", "p0002", "p0003", "p0004")],
        Evidence("c2-e1", "c2-p0001", "c2", "A weaver of the right age.", confidence=Confidence.POSSIBLE, sensitivity=A.PUBLIC),
        Evidence("c2-e2", "c2-p0002", "c2", "Named with his trade.", confidence=Confidence.PROBABLE, sensitivity=A.PUBLIC),
        # A claim about an event concerns the event's people; nobody has assessed it.
        Citation("c3", "s1", locator="entry 80", sensitivity=A.PUBLIC),
        Claim("c3-claim", "m1", "date", "1822", citation_ids=["c3"], sensitivity=A.PUBLIC),
        # Cited by nothing: undated, nobody named.
        Citation("c4", "s2", locator="folio 9", sensitivity=A.PUBLIC),
        # Only a challenge: shown as such.
        Citation("c5", "s2", locator="folio 12", sensitivity=A.PUBLIC),
        Claim("c5-claim", "p0003", "residence", "Harbour Row", citation_ids=["c5"], sensitivity=A.PUBLIC),
        Evidence("c5-e", "c5-claim", "c5", "Another Cora.", supports=False, confidence=Confidence.DISPROVED, sensitivity=A.PUBLIC),
        # Withheld: a private citation, a living person whose claim cites a public one, and a private source.
        Person("p0009", names=[Name("SECRET-PERSON Fable", surname="Fable")], living=L.LIVING, sensitivity=A.PUBLIC),
        Claim("c1-living", "p0009", "birth", "2001", citation_ids=["c1"], sensitivity=A.PUBLIC),
        Citation("c9", "s2", locator="SECRET-LOCATOR 1999", abstract="SECRET-CITATION abstract", sensitivity=A.PRIVATE),
        Source("s9", "SECRET-SOURCE register", "census", sensitivity=A.PRIVATE),
        Citation("c8", "s9", locator="entry 1", abstract="SECRET-SOURCE-CITATION", sensitivity=A.PUBLIC),
    ])
    return c


def rows(html: str) -> list[str]:
    body = html[html.index('<table class="records-table">'):]
    return re.findall(r"<tr>(<td data-label=\"Year\">.*?)</tr>", body[:body.index("</table>")])


def index(out: Path) -> dict:
    script = (out / "data/records-index.js").read_text()
    prefix = "window.GENEALOGY_RECORDS_INDEX="
    assert script.startswith(prefix) and script.endswith(";\n")
    return json.loads(script[len(prefix):-2])


class RecordsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.out = Path(cls.directory.name)
        c = case()
        assert validate_case(c) == [], validate_case(c)
        build_site(c, CONFIG, cls.out)
        cls.html = (cls.out / "records.html").read_text()
        cls.rows = rows(cls.html)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_the_page_is_a_route_in_the_navigation_and_the_site_index(self):
        self.assertEqual(("records", "Records"), ROUTES["records.html"])
        self.assertIn("records.html", json.loads((self.out / "data/routes.json").read_text()))
        self.assertIn('<a data-view="records" href="records.html" aria-current="page">All records</a>', self.html)
        self.assertIn('<a href="records.html">Records</a>', (self.out / "sitemap.html").read_text())
        self.assertIn("<title>Records — Fictional records</title>", self.html)
        self.assertEqual(1, self.html.count("<h1>"))

    def test_one_row_per_public_citation_oldest_first_and_undated_last(self):
        self.assertEqual(5, len(self.rows))
        self.assertEqual(["1801", "1822", "1841", "Undated", "Undated"], [re.match(r'<td data-label="Year">([^<]+)</td>', r)[1] for r in self.rows])
        # Undated rows follow their first person's name; a row naming nobody comes last.
        self.assertIn("Cora Fable", self.rows[3])
        self.assertIn('<td data-label="People">—</td>', self.rows[4])
        self.assertIn('<strong>5</strong> cited records', self.html)

    def test_a_row_names_the_people_type_place_evidence_and_record(self):
        first = self.rows[0]
        self.assertRegex(first, r'<td data-label="People"><a href="people/p-[0-9a-f]{64}\.html">Ada Fable</a></td>')
        self.assertIn('<td data-label="Record type">Parish registers</td>', first)
        self.assertRegex(first, r'<td data-label="Place"><a href="places/pl-[0-9a-f]{64}\.html">Invented Town, Fableshire, Fableland</a></td>')
        self.assertIn('<td data-label="Evidence"><a class="badge evidence-badge" href="evidence.html#confidence-documented">Documented</a></td>', first)
        self.assertIn(f'<a href="sources.html#{_anchor("c1")}">Invented parish register (entry 75)</a>', first)
        # The abstract is a second line, cut at a word break.
        shown = unescape(re.search(r'<p class="records-abstract">([^<]+)</p>', first)[1])
        self.assertLessEqual(len(shown), RECORDS_ABSTRACT)
        self.assertTrue(shown.endswith("…") and LONG.startswith(shown[:-1]))
        self.assertIn(f'id="{_anchor("c1")}"', (self.out / "sources.html").read_text())

    def test_three_people_then_a_count_and_the_strongest_assessment(self):
        census = self.rows[2]
        self.assertEqual(["Ada Fable", "Bram Fable", "Cora Fable"], re.findall(r'<a href="people/[^"]+">([^<]+)</a>', census))
        self.assertIn('<span class="meta">+1 more</span>', census)
        self.assertIn('<td data-label="Record type">Census</td>', census)
        self.assertIn(">Probable</a></td>", census)
        self.assertNotIn("Possible", census)
        self.assertIn('<td data-label="Place">—</td>', census)

    def test_an_event_claim_names_the_events_people_and_an_unassessed_record_says_so(self):
        marriage = self.rows[1]
        self.assertEqual(["Ada Fable", "Bram Fable"], re.findall(r'<a href="people/[^"]+">([^<]+)</a>', marriage))
        self.assertIn('<td data-label="Evidence"><span class="meta">Not yet assessed</span></td>', marriage)
        self.assertIn(">Disproved</a> <span class=\"meta\">challenges the claim</span>", self.rows[3])

    def test_the_status_strip_counts_the_citations(self):
        strip = re.search(r'<ul class="records-status">(.*?)</ul>', self.html)[1]
        self.assertEqual([("assessed", "3", "assessed"), ("unassessed", "2", "not yet assessed"), ("abstract", "1", "with an abstract"),
                          ("quality", "1", "with record quality stated")],
                         re.findall(r'<li data-status="([a-z]+)"><strong>(\d+)</strong> ([^<]+)</li>', strip))

    def test_the_filters_wait_for_the_script_and_the_table_needs_none(self):
        self.assertRegex(self.html, r'<form class="records-filters" data-records-filters [^>]*hidden>')
        self.assertIn('<div class="records-bar" data-records-bar hidden>', self.html)
        for name in ("q", "type", "year_from", "year_to", "evidence", "sort"):
            self.assertIn(f'name="{name}"', self.html)
        self.assertIn('<option value="parish-register">Parish registers (2)</option>', self.html)
        self.assertIn('<option value="census">Census (3)</option>', self.html)
        self.assertNotIn("records-index.js", self.html)  # the script loads it on this page only
        self.assertNotIn("site-data.js", self.html)
        self.assertNotIn("data-records-pages", self.html)  # one page is enough
        self.assertEqual([], check_site(self.out)["broken"])

    def test_the_index_carries_each_row_compactly(self):
        data = index(self.out)
        self.assertEqual({"parish-register": "Parish registers", "census": "Census"}, data["types"])
        self.assertEqual(5, len(data["rows"]))
        for row in data["rows"]:
            self.assertLessEqual(set(row), {"y", "p", "q", "n", "k", "l", "e", "s", "u", "c", "a"})
        first = data["rows"][0]
        self.assertEqual(1801, first["y"])
        self.assertEqual(["Documented", "confidence-documented"], first["e"])
        self.assertEqual("Invented Town, Fableshire, Fableland", first["l"][0])
        self.assertLessEqual(len(first["a"]), RECORDS_ABSTRACT)
        self.assertEqual(4, data["rows"][2]["n"])
        self.assertEqual(3, len(data["rows"][2]["p"]))
        self.assertIn("Dov Fable", data["rows"][2]["q"])
        self.assertEqual(["Disproved", "confidence-disproved", 1], data["rows"][3]["e"])
        self.assertNotIn("e", data["rows"][1])
        self.assertTrue(_owned("data/records-index.js"))
        self.assertIn("data/records-index.js", json.loads((self.out / ".genealogy-site-manifest.json").read_text()))

    def test_withheld_records_are_in_no_output(self):
        for path in self.out.rglob("*"):
            if path.is_file():
                text = path.read_text(errors="ignore")
                self.assertNotIn("SECRET-", text, path)
        self.assertNotIn("2001", (self.out / "data/records-index.js").read_text())


class LargeRecordsTests(unittest.TestCase):
    def test_a_large_site_pages_the_records_and_the_index_covers_every_one(self):
        from test_scale import PEOPLE, large_case  # tests/ is on the path under unittest discovery
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(large_case(), ProjectConfig(name="Fictional"), out)
            html = (out / "records.html").read_text()
            self.assertLess(len(html.encode()), 100_000)
            self.assertEqual(RECORDS_PER_PAGE, len(rows(html)))
            self.assertIn(f'data-total="{PEOPLE + 1}"', html)
            pages = sorted((out / "records").glob("page-*.html"), key=lambda p: int(p.stem.split("-")[1]))
            self.assertEqual(-(-(PEOPLE + 1) // RECORDS_PER_PAGE) - 1, len(pages))
            every_row = [row for text in [html, *(p.read_text() for p in pages)] for row in rows(text)]
            listed = [re.search(r'<td data-label="Details"><a href="[^"]+#(r-[0-9a-f]{64})"', row)[1] for row in every_row]
            self.assertEqual(PEOPLE + 1, len(listed))
            self.assertEqual(PEOPLE + 1, len(set(listed)))
            for page in pages:
                text = page.read_text()
                self.assertLess(len(text.encode()), 100_000, page)
                self.assertNotIn("site-data.js", text)
                self.assertNotIn("data-records-filters", text)
            second = (out / "records/page-2.html").read_text()
            self.assertIn("<title>Records, page 2 — Fictional</title>", second)
            self.assertIn('href="../records/page-2.html" aria-current="page">Records 101–200', second)
            self.assertIn('<a href="../records.html">Search and filter the records</a>', second)
            self.assertIn("data-records-pages", html)
            self.assertTrue(_owned("records/page-2.html"))
            self.assertEqual(PEOPLE + 1, len(index(out)["rows"]))
            self.assertEqual([], check_site(out)["broken"])
            # A smaller rebuild removes the pages no longer needed.
            build_site(large_case(20), ProjectConfig(name="Fictional"), out)
            self.assertEqual([], list((out / "records").glob("*.html")) if (out / "records").exists() else [])
            self.assertEqual(21, len(rows((out / "records.html").read_text())))


if __name__ == "__main__":
    unittest.main()
