"""The people catalogue as a research table: births, deaths, spouses and parents, each link with its own assessment badge."""
from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Claim, Confidence as C, Event, ExternalIdentifier, LivingStatus as L, Name, Person,
                              Place, Relationship)
from genealogy.site import build_site

GRADES = {"strongly_supported": {"label": "Strongly supported", "meaning": "Several records agree.", "confidence": "probable"}}
HEADINGS = ["Individual", "Birth", "Birth location", "Death", "Death location", "Spouse(s)", "Father", "Mother"]


def person(pid, name, surname, sex=None, *, sensitivity=A.PUBLIC, **kwargs):
    records = [Person(pid, names=[Name(name, surname=surname)], living=L.DECEASED, sensitivity=sensitivity, **kwargs)]
    if sex:
        records.append(Claim(f"{pid}-sex", pid, "sex", sex, sensitivity=sensitivity))
    return records


def table_records():
    """Fictional people whose rows show every kind of cell: approximate and exact dates, graded, estimated,
    unsexed, step and rejected links, and a withheld parent."""
    return [
        Place("tp1", "Lanternby, North Shire, Fableland", latitude=52.0, longitude=-1.0),
        Place("tp2", "Willowby, Inventia", latitude=48.0, longitude=3.0),
        *person("t0001", "Ada Table", "Table", "F", external_ids=[ExternalIdentifier("WikiTree", "Table-12")], event_ids=["t0001-b", "t0001-d"]),
        Event("t0001-b", "birth", date="ABT 1801", place_id="tp1", participant_ids=["t0001"], sensitivity=A.PUBLIC),
        Event("t0001-d", "death", date="1870-03-04", place_id="tp2", participant_ids=["t0001"], sensitivity=A.PUBLIC),
        *person("t0002", "Bram Table", "Table", "M"),
        *person("t0003", "Cora Vale", "Vale", "female"),
        *person("t0004", "Dov Table", "Table"),
        *person("t0005", "Esme Rook", "Rook", "M"),
        *person("t0006", "Finn Rook", "Rook", "M"),
        *person("t0007", "Gwen Vale", "Vale", "F"),
        *person("t0008", "SECRET-PARENT Table", "Table", "M", sensitivity=A.PRIVATE),
        *person("t0009", "Hugo Table", "Table", event_ids=["t0009-b"]),
        Event("t0009-b", "birth", date="1820", participant_ids=["t0009"], sensitivity=A.PUBLIC),
        Relationship("t-r1", "t0001", "t0002", "parent", confidence=C.DOCUMENTED, sensitivity=A.PUBLIC),
        Relationship("t-r2", "t0001", "t0003", "parent", confidence=C.PROBABLE, grade="strongly_supported", estimate=80, sensitivity=A.PUBLIC),
        Relationship("t-r3", "t0001", "t0004", "parent", confidence=C.POSSIBLE, sensitivity=A.PUBLIC),
        Relationship("t-r4", "t0001", "t0005", "spouse", confidence=C.POSSIBLE, estimate=70, sensitivity=A.PUBLIC),
        Relationship("t-r5", "t0006", "t0001", "spouse", confidence=C.DISPROVED, sensitivity=A.PUBLIC),
        Relationship("t-r6", "t0001", "t0007", "parent", confidence=C.DOCUMENTED, pedigree="step", sensitivity=A.PUBLIC),
        Relationship("t-r7", "t0001", "t0008", "parent", confidence=C.DOCUMENTED, sensitivity=A.PUBLIC),
        # Recorded twice: Bram is listed once, with the first link in id order.
        Relationship("t-r8", "t0001", "t0002", "father", sensitivity=A.PUBLIC),
    ]


def table_case() -> ResearchCase:
    case = ResearchCase("fictional-table", "Fictional table")
    case.add_many(table_records())
    return case


class Cells(HTMLParser):
    """Each row's cells as (class, text), keyed by the row's person id."""
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell, self.hidden = {}, None, None, False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr" and "data-person-id" in attrs:
            self.row = self.rows.setdefault(attrs["data-person-id"], [])
        elif tag == "td" and self.row is not None:
            self.cell = [attrs.get("class") or "", ""]
            self.row.append(self.cell)
        elif attrs.get("aria-hidden") == "true" and not self.hidden:
            self.hidden = tag  # a badge's glyph is decoration; the words carry the label

    def handle_endtag(self, tag):
        if tag == "td":
            self.cell = None
        elif tag == "tr":
            self.row = None
        elif tag == self.hidden:
            self.hidden = False

    def handle_data(self, data):
        if self.cell is not None and not self.hidden:
            self.cell[1] += data


class CatalogueTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.out = Path(cls.directory.name)
        case = table_case()
        assert validate_case(case) == []
        build_site(case, ProjectConfig(name="Fictional table", grades=GRADES), cls.out)
        cls.html = (cls.out / "catalogue.html").read_text(encoding="utf-8")
        parser = Cells()
        parser.feed(cls.html)
        cls.rows = parser.rows

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def row(self, pid):
        return re.search(rf'<tr data-person-id="{pid}".*?</tr>', self.html)[0]

    def test_the_eight_columns_and_their_sort_keys(self):
        heads = re.findall(r'<th scope="col" data-sort="([^"]+)">([^<]+)</th>', self.html)
        self.assertEqual(HEADINGS, [label for _, label in heads])
        self.assertEqual(["name", "birth", "birth-place", "death", "death-place", "spouse", "father", "mother"], [key for key, _ in heads])
        self.assertTrue(all(len(cells) == 8 for cells in self.rows.values()))
        # In name order without the script.
        self.assertEqual(["t0001", "t0002", "t0003", "t0004", "t0005", "t0006", "t0007", "t0009"], list(self.rows))

    def test_a_row_shows_readable_dates_places_and_relatives_with_their_badges(self):
        cells = self.rows["t0001"]
        # The first external id stands in for the record id.
        self.assertEqual(("", "Ada TableTable-12"), tuple(cells[0]))
        self.assertEqual([["date-approx", "c. 1801"], ["", "Lanternby, North Shire, Fableland"], ["date-exact", "4 Mar 1870"], ["", "Willowby, Inventia"]], cells[1:5])
        # The disproved spouse is left out; the possible one keeps its estimate.
        self.assertEqual(["", "Esme Rook Possible (70%)"], cells[5])
        # Bram once; Dov has no recorded sex, so is listed under Father as "Parent". A possible link leaves the cell unshaded.
        self.assertEqual(["", "Bram Table Documented" + "Dov TableParent Possible"], cells[6])
        # The project's grade wording, and a step-mother named as such; every link firm, so the cell is shaded.
        self.assertEqual(["kin-firm", "Cora Vale Strongly supported (80%)" + "Gwen ValeStep-mother Documented"], cells[7])
        row = self.row("t0001")
        self.assertIn('href="evidence.html#grade-strongly_supported" data-confidence="probable" data-grade="strongly_supported"><span class="badge-glyph" aria-hidden="true">~</span>Strongly supported (80%)</a>', row)
        self.assertIn('<span class="kin-role">Parent</span>', row)
        self.assertNotIn("Finn Rook", row)
        self.assertEqual(["", "Hugo Tablet0009"], self.rows["t0009"][0])
        self.assertEqual([["date-exact", "1820"], ["", "—"], ["", "—"], ["", "—"], ["", "—"], ["", "—"], ["", "—"]], self.rows["t0009"][1:])

    def test_the_search_text_keeps_names_ids_places_relatives_and_events(self):
        text = re.search(r'data-search-text="([^"]*)"', self.row("t0001"))[1]
        for word in ("Ada Table", "t0001", "Table-12", "Esme Rook", "Bram Table", "Cora Vale", "birth: ABT 1801 Lanternby, North Shire, Fableland",
                     "death: 1870-03-04 Willowby, Inventia"):
            self.assertIn(word, text)
        self.assertNotIn("Finn Rook", text)

    def test_the_shared_data_carries_the_first_external_id_only_where_there_is_one(self):
        script = (self.out / "data/site-data.js").read_text(encoding="utf-8")
        people = {p["id"]: p for p in json.loads(script.removeprefix("window.GENEALOGY_SITE_DATA=").removesuffix(";\n"))["people"]}
        self.assertEqual("Table-12", people["t0001"]["external_id"])
        self.assertNotIn("external_id", people["t0009"])

    def test_a_withheld_parent_appears_nowhere(self):
        for path in self.out.rglob("*"):
            if path.is_file():
                self.assertNotIn("SECRET-PARENT", path.read_text(encoding="utf-8", errors="ignore"), path)


if __name__ == "__main__":
    unittest.main()
