"""The sidebar search: one small index of titles, and a search box on every page."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Event, Finding, LivingStatus as L, Name, Person, Place, ResearchQuestion, Source, Study)
from genealogy.site import _owned, build_site

LONG = "Ada Fable and Bram Fable are the couple married at Invented Parish in 1822, " * 3
FORM = re.compile(r'<form class="site-search" role="search" action="((?:\.\./)?)catalogue\.html" method="get">'
                  r'<label for="site-search-input">[^<]+</label><input id="site-search-input" type="search" name="q"[^>]*>'
                  r'<p class="site-search-count" aria-live="polite"></p><ul class="site-search-results" id="site-search-results" hidden></ul></form>')


def case() -> ResearchCase:
    c = ResearchCase("fictional-search", "Fictional search")
    c.add_many([
        Place("pl1", "Invented Town, Fableshire, Fableland", sensitivity=A.PUBLIC),
        Person("p0001", names=[Name("Ada Fable", surname="Fable")], living=L.DECEASED, event_ids=["p0001-b", "p0001-d"],
               notes="NOTEBODY-SENTINEL: only on the dossier.", sensitivity=A.PUBLIC),
        Event("p0001-b", "birth", date="ABT 1801", place_id="pl1", participant_ids=["p0001"], sensitivity=A.PUBLIC),
        Event("p0001-d", "death", date="1870", participant_ids=["p0001"], sensitivity=A.PUBLIC),
        Person("p0002", names=[Name("Bram Fable", surname="Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Source("s1", "Invented parish register", "parish-register", sensitivity=A.PUBLIC),
        Study("st1", "Who were Ada Fable's parents?", summary="SUMMARY-SENTINEL", body="BODY-SENTINEL", related_ids=["p0001"],
              status="reviewed", updated_on="2026-09-01", sensitivity=A.PUBLIC),
        Finding("f1", LONG, related_ids=["p0001"], status="reviewed", recorded_on="2026-09-02", sensitivity=A.PUBLIC),
        ResearchQuestion("q1", "Where was Bram Fable buried?", related_ids=["p0002"], sensitivity=A.PUBLIC),
        # Withheld: nothing about these may reach the index or any other output.
        Person("p0009", names=[Name("SECRET-PERSON Fable")], living=L.LIVING, sensitivity=A.PUBLIC),
        Place("pl9", "SECRET-PLACE, Fableland", sensitivity=A.PRIVATE),
        Source("s9", "SECRET-SOURCE register", sensitivity=A.PRIVATE),
        Study("st9", "SECRET-STUDY title", related_ids=["p0001"], sensitivity=A.PRIVATE),
        Finding("f9", "SECRET-FINDING about Ada.", related_ids=["p0001"], recorded_on="2026-01-01", sensitivity=A.PRIVATE),
        Finding("f8", "SECRET-LINKED finding about a living person.", related_ids=["p0009"], recorded_on="2026-01-01", sensitivity=A.PUBLIC),
        ResearchQuestion("q9", "SECRET-QUESTION about Ada?", related_ids=["p0001"], sensitivity=A.PRIVATE),
    ])
    return c


class SiteSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.out = Path(cls.directory.name)
        c = case()
        assert validate_case(c) == []
        build_site(c, ProjectConfig(name="Fictional"), cls.out)
        cls.index = json.loads((cls.out / "data/search-index.json").read_text())
        cls.by_kind = {}
        for entry in cls.index:
            cls.by_kind.setdefault(entry["k"], []).append(entry)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_every_public_record_with_a_page_or_anchor_is_indexed_by_title_and_one_line(self):
        self.assertEqual({"person": 2, "place": 1, "study": 1, "source": 1, "finding": 1, "question": 1},
                         {kind: len(rows) for kind, rows in self.by_kind.items()})
        for entry in self.index:
            self.assertLessEqual(set(entry), {"t", "k", "u", "s"})
        ada = next(e for e in self.by_kind["person"] if e["t"] == "Ada Fable")
        self.assertEqual("b. c. 1801 – d. 1870", ada["s"])
        self.assertTrue(ada["u"].startswith("people/p-"))
        # A place is its name as recorded, which already ends with its region.
        self.assertEqual({"t": "Invented Town, Fableshire, Fableland", "k": "place"}, {k: v for k, v in self.by_kind["place"][0].items() if k != "u"})
        self.assertEqual(("Who were Ada Fable's parents?", "2026-09-01"), (self.by_kind["study"][0]["t"], self.by_kind["study"][0]["s"]))
        self.assertEqual(("Invented parish register", "Parish-register"), (self.by_kind["source"][0]["t"], self.by_kind["source"][0]["s"]))
        self.assertEqual(("Where was Bram Fable buried?", "Open"), (self.by_kind["question"][0]["t"], self.by_kind["question"][0]["s"]))
        finding = self.by_kind["finding"][0]
        self.assertEqual("2026-09-02", finding["s"])
        # A long conclusion is shortened to one line, at a word break.
        self.assertEqual("Ada Fable and Bram Fable are the couple married at Invented Parish in 1822…", finding["t"])

    def test_every_route_lands_on_its_page_and_anchor(self):
        for entry in self.index:
            path, _, anchor = entry["u"].partition("#")
            page = (self.out / path).read_text()
            if anchor:
                self.assertIn(f'id="{anchor}"', page, entry)

    def test_the_script_carries_the_same_index(self):
        script = (self.out / "data/search-index.js").read_text()
        prefix = "window.GENEALOGY_SEARCH_INDEX="
        self.assertTrue(script.startswith(prefix) and script.endswith(";\n"))
        self.assertEqual(self.index, json.loads(script[len(prefix):-2]))
        for name in ("data/search-index.json", "data/search-index.js"):
            self.assertTrue(_owned(name))
            self.assertIn(name, json.loads((self.out / ".genealogy-site-manifest.json").read_text()))

    def test_withheld_records_bodies_and_notes_stay_out(self):
        for name in ("data/search-index.json", "data/search-index.js"):
            text = (self.out / name).read_text()
            for sentinel in ("NOTEBODY-SENTINEL", "SUMMARY-SENTINEL", "BODY-SENTINEL", "SECRET-"):
                self.assertNotIn(sentinel, text, name)
        for path in self.out.rglob("*"):
            if path.is_file():
                self.assertNotIn("SECRET-", path.read_text(errors="ignore"), path)

    def test_every_page_has_the_search_box_which_without_script_searches_the_catalogue(self):
        pages = json.loads((self.out / "data/routes.json").read_text())
        self.assertGreater(len(pages), 10)
        for route in pages:
            html = (self.out / route).read_text()
            match = FORM.search(html)
            self.assertIsNotNone(match, route)
            self.assertEqual("../" if "/" in route else "", match[1], route)
            self.assertEqual(1, html.count('id="site-search-input"'), route)
            # In the sidebar header: after the site name, before the main navigation.
            self.assertLess(html.index('class="site-brand'), match.start())
            self.assertLessEqual(match.end(), html.index('<nav aria-label="Main navigation">'))


class LargeSiteSearchTests(unittest.TestCase):
    def test_the_index_stays_small_and_covers_every_record_on_the_large_fixture(self):
        from test_scale import PEOPLE, large_case  # tests/ is on the path under unittest discovery
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(large_case(), ProjectConfig(name="Fictional"), out)
            raw = (out / "data/search-index.json").read_bytes()
            index = json.loads(raw)
            kinds = {}
            for entry in index:
                kinds[entry["k"]] = kinds.get(entry["k"], 0) + 1
            # Each person's place, source, finding and study, the shared register and the open draft finding.
            self.assertEqual({"person": PEOPLE, "place": PEOPLE, "source": PEOPLE + 1, "finding": PEOPLE + 1, "study": PEOPLE}, kinds)
            self.assertLess(len(raw) / len(index), 150)
            self.assertNotIn(b"BODY-ONLY-ON-THE-STUDY-PAGE", raw)
            self.assertNotIn(b"Whether the register entries", raw)  # nor a study's summary
            self.assertNotIn(b"SECRET-STUDY", raw)
            anchors: dict[str, str] = {}
            for entry in index:
                path, _, anchor = entry["u"].partition("#")
                if path not in anchors:
                    anchors[path] = (out / path).read_text()
                if anchor:
                    self.assertIn(f'id="{anchor}"', anchors[path])
            self.assertTrue(any(e["u"].startswith("places/") for e in index))
            self.assertTrue(any(e["u"].startswith("findings/page-") for e in index))


if __name__ == "__main__":
    unittest.main()
