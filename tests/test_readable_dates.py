"""Readable dates, labels instead of record ids, relationship sentences and plurals across the site."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.dates import display_date, machine_date
from genealogy.labels import plural
from genealogy.models import (AccessLevel as A, Citation, Claim, Confidence as C, Event, Evidence, Finding, LivingStatus as L,
                              Name, Person, Place, Relationship, ResearchQuestion, Source, Study)
from genealogy.site import build_site
from genealogy.timelines import render_timeline_html


def text(html: str, gap: str = " ") -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", gap, html)).strip()


class DisplayDateTests(unittest.TestCase):
    def test_dates_read_as_a_reader_writes_them(self):
        cases = [
            (("1754-01-01", "year"), "1754"), (("1731-05-24", None), "24 May 1731"), (("1754-01", None), "Jan 1754"),
            (("1754-01-01", "month"), "Jan 1754"), (("1754-01-01", "decade"), "1750s"), (("1754-01-01", "unknown"), "1 Jan 1754"),
            (("ABT 1754", None), "c. 1754"), (("about 1754-01-01", "year"), "c. 1754"), (("EST 1265", None), "c. 1265 (estimated)"),
            (("1265", "estimated"), "c. 1265 (estimated)"), (("1754", "approximate"), "c. 1754"), (("CAL 1801", None), "c. 1801 (calculated)"),
            (("BEF 1800", None), "before 1800"), (("AFT 3 MAR 1850", None), "after 3 Mar 1850"),
            (("BET 1750 AND 1760", None), "between 1750 and 1760"), (("FROM 1750 TO 1760", None), "from 1750 to 1760"),
            (("1850-00-00", None), "1850"), (("1850-03-00", None), "Mar 1850"), (("12 MAR 1870", None), "12 Mar 1870"),
            (("Mar 4 1850", None), "4 Mar 1850"), (("@#DJULIAN@ 1 MAR 1750/51", None), "1 Mar 1750/51 (Julian)"),
            (("INT 1850 (about Easter)", None), "1850 (about Easter)"), (("2026-10-02", None), "2 Oct 2026"),
        ]
        for (value, precision), expected in cases:
            with self.subTest(value=value, precision=precision):
                self.assertEqual(expected, display_date(value, precision))

    def test_free_text_and_impossible_dates_pass_through_as_recorded(self):
        for value in ("born in the spring", "1850s", "1900-02-30", "31 FEB 1800", "BET 1750 AND later"):
            self.assertEqual(value, display_date(value))
        self.assertEqual("", display_date(None))
        self.assertEqual("", display_date("   "))

    def test_machine_dates_only_for_plain_dates(self):
        self.assertEqual("1754", machine_date("1754-01-01", "year"))
        self.assertEqual("1754-01", machine_date("1754-01-01", "month"))
        self.assertEqual("1870-03-12", machine_date("12 MAR 1870"))
        self.assertEqual("1850", machine_date("1850-00-00"))
        for value, precision in (("ABT 1754", None), ("BET 1750 AND 1760", None), ("1754", "approximate"), ("1754-01-01", "decade"),
                                 ("free text", None), ("1 MAR 1750/51", None), ("1900-02-30", None)):
            self.assertIsNone(machine_date(value, precision), value)

    def test_plural(self):
        self.assertEqual(["1 evidence assessment", "2 evidence assessments", "1 person", "3 people", "1 study", "1,204 studies"],
                         [plural(1, "evidence assessment"), plural(2, "evidence assessment"), plural(1, "person"), plural(3, "person"),
                          plural(1, "study"), plural(1204, "study")])

    def test_the_standalone_timeline_keeps_the_recorded_value(self):
        html = render_timeline_html({"events": [{"id": "e1", "kind": "birth", "date": "1754-01-01", "date_precision": "year"},
                                                {"id": "e2", "kind": "death", "date": "ABT 1800"}]})
        self.assertIn('<time datetime="1754" data-date="1754-01-01">1754</time>', html)
        self.assertIn('<span data-date="ABT 1800">c. 1800</span>', html)


def readable_case() -> ResearchCase:
    case = ResearchCase("fictional-readable", "Fictional readable")
    person = lambda pid, name, sex: [Person(pid, names=[Name(name, surname=name.split()[-1])], living=L.DECEASED, sensitivity=A.PUBLIC),
                                     Claim(f"{pid}-sex", pid, "sex", sex, sensitivity=A.PUBLIC)]
    case.add_many([
        Place("place:lantern", "Lanternford (fictional)", sensitivity=A.PUBLIC),
        *person("p0001", "Ada Fable", "F"), *person("p0002", "Bram Fable", "M"), *person("p0003", "Cara Fable", "F"),
        Event("e-ada-birth", "birth", date="1754-01-01", date_precision="year", place_id="place:lantern", participant_ids=["p0001"], sensitivity=A.PUBLIC),
        Event("e-ada-death", "death", date="ABT 1808", participant_ids=["p0001"], sensitivity=A.PUBLIC),
        Event("e-cara-birth", "birth", date="24 MAY 1780", place_id="place:lantern", participant_ids=["p0003"], sensitivity=A.PUBLIC),
        Event("e-wed", "marriage", date="1777-06-01", date_precision="month", place_id="place:lantern", participant_ids=["p0001", "p0002"], sensitivity=A.PUBLIC),
        Relationship("r-cara-ada", "p0003", "p0001", "parent", confidence=C.DOCUMENTED, sensitivity=A.PUBLIC),
        Relationship("r-ada-bram", "p0001", "p0002", "spouse", confidence=C.PROBABLE, sensitivity=A.PUBLIC),
        Source("s-register", "Invented register", "parish register", sensitivity=A.PUBLIC),
        Citation("c-entry", "s-register", locator="entry 4", sensitivity=A.PUBLIC),
        Claim("cl-birth", "p0003", "birth", "1780", citation_ids=["c-entry"], sensitivity=A.PUBLIC),
        Evidence("ev-birth", "cl-birth", "c-entry", "The entry names Cara.", sensitivity=A.PUBLIC),
        Finding("f-one", "Cara was baptised at Lanternford.", related_ids=["p0003", "place:lantern"], evidence_ids=["ev-birth"],
                recorded_on="2026-10-02", status="reviewed", sensitivity=A.PUBLIC),
        ResearchQuestion("q-one", "Where was Ada buried?", related_ids=["p0001", "place:lantern", "e-ada-death"], sensitivity=A.PUBLIC),
        Study("st-one", "The Lanternford Fables", related_ids=["p0001"], updated_on="2026-09-14", status="draft", sensitivity=A.PUBLIC),
    ])
    return case


class ReadableSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.paths = build_site(readable_case(), ProjectConfig(name="Fictional readable"), cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def page(self, name: str) -> str:
        return (self.root / name).read_text()

    def dossier(self, pid: str) -> str:
        return next(p for name, p in self.paths.items() if name.startswith("people/") and f'data-person-id="{pid}"' in p.read_text()).read_text()

    def test_fixture_is_valid(self):
        self.assertEqual([], validate_case(readable_case()))

    def test_event_dates_honour_their_precision_and_keep_the_recorded_value(self):
        ada = self.dossier("p0001")
        self.assertIn('<strong><time datetime="1754" data-date="1754-01-01">1754</time> · birth</strong>', ada)
        self.assertIn('<strong><span class="date" data-date="ABT 1808">c. 1808</span> · death</strong>', ada)
        self.assertIn('<time datetime="1777-06" data-date="1777-06-01">Jun 1777</time>', ada)
        self.assertNotIn(">1754-01-01<", ada)
        cara = self.dossier("p0003")
        self.assertIn('<time datetime="1780-05-24" data-date="24 MAY 1780">24 May 1780</time>', cara)
        timeline = self.page("timeline.html")
        self.assertIn('data-date="1754-01-01">1754</time>', timeline)

    def test_the_opening_sentence_reads_its_dates(self):
        intro = text(re.search(r'<p class="lead intro">(.*?)</p>', self.dossier("p0001"))[1], "")
        self.assertTrue(intro.startswith("Ada Fable was born in 1754 in Lanternford (fictional), and died c. 1808."), intro)
        cara = text(re.search(r'<p class="lead intro">(.*?)</p>', self.dossier("p0003"))[1], "")
        self.assertTrue(cara.startswith("Cara Fable was born on 24 May 1780 in Lanternford (fictional)."), cara)

    def test_stamps_read_as_dates(self):
        ada, cara = self.dossier("p0001"), self.dossier("p0003")
        self.assertIn('Updated <time datetime="2026-09-14">14 Sep 2026</time>', ada)
        self.assertIn('Recorded <time datetime="2026-10-02">2 Oct 2026</time>', cara)
        self.assertIn('<p class="meta"><time datetime="2026-10-02">2 Oct 2026</time></p>', self.page("findings.html"))
        index = json.loads((self.root / "data/search-index.json").read_text())
        self.assertIn({"t": "Cara was baptised at Lanternford.", "k": "finding", "s": "2 Oct 2026"}, [{k: r[k] for k in ("t", "k", "s")} for r in index if r["k"] == "finding"])

    def test_the_record_id_is_small_labelled_meta(self):
        self.assertIn('<p class="record-id meta">Record ID: p0001</p>', self.dossier("p0001"))
        place = next(p.read_text() for name, p in self.paths.items() if name.startswith("places/pl-"))
        self.assertIn("<h1>Lanternford (fictional)</h1>", place)
        self.assertIn('<p class="record-id meta">Record ID: place:lantern</p>', place)

    def test_references_name_places_and_events_not_their_ids(self):
        research = self.page("research.html")
        question = research[research.index("Where was Ada buried?"):]
        question = question[:question.index("</li>")]
        self.assertIn(">Lanternford (fictional)</a>", question)
        self.assertIn(">Death of Ada Fable, c. 1808</a>", question)
        self.assertNotIn(">place:lantern<", research)
        self.assertNotIn(">e-ada-death<", research)

    def test_relationships_read_the_right_way_round(self):
        tree = text(self.page("tree.html"))
        self.assertIn("Ada Fable is the mother of Cara Fable", tree)
        self.assertIn("Ada Fable and Bram Fable are spouses", tree)
        self.assertNotIn("— parent →", tree)

    def test_connected_groups_are_named_and_counts_agree(self):
        branches = self.page("branches.html")
        self.assertIn(">Group of 3 people around Ada Fable</a>", branches)
        self.assertIn('<th scope="row">Group of 3 people around Ada Fable</th>', self.page("progress.html"))
        self.assertIn("1 evidence assessment</p>", self.page("findings.html"))
        self.assertNotIn("1 evidence assessments", self.page("findings.html"))

    def test_place_lists_are_pills(self):
        branches = self.page("branches.html")
        self.assertRegex(branches, r'<td><ul class="pills"><li><a href="places/pl-[0-9a-f]{64}\.html">Lanternford \(fictional\)</a></li></ul></td>')
        # A place page lists its events as a table, in readable years, in date order.
        place = next(p.read_text() for name, p in self.paths.items() if name.startswith("places/pl-"))
        self.assertIn('<tr data-year="1754"><td>1754</td><td>Birth</td>', place)
        self.assertLess(place.index('<tr data-year="1754">'), place.index('<tr data-year="1777">'))

    def test_the_browser_data_carries_only_precisions_that_change_a_date(self):
        data = json.loads(re.search(r"=\s*(\{.*\})\s*;?\s*$", (self.root / "data/site-data.js").read_text(), re.S)[1])
        events = {e["id"]: e for e in data["events"]}
        self.assertEqual("year", events["e-ada-birth"]["date_precision"])
        self.assertNotIn("date_precision", events["e-cara-birth"])  # "unknown" prints the date as recorded


if __name__ == "__main__":
    unittest.main()
