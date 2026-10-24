"""Why each family link is shown, rejected links set apart, and the dossier's opening summary."""
from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, grade_errors, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Citation, Claim, Confidence as C, Event, Evidence, Finding, LivingStatus as L,
                              Name, Person, Place, Relationship, Source, Study, record_from_dict)
from genealogy.site import _anchor, _key, build_site
from genealogy.sitecheck import check_site

GRADES = {"ruled_out": {"label": "Ruled out", "meaning": "The records exclude this link.", "confidence": "disproved"}}


def person(pid, name, events=(), sex=None, notes=None):
    """A public person; each event is (kind, date, place_id)."""
    ids = [f"{pid}-{kind}" for kind, _, _ in events]
    records = [Person(pid, names=[Name(name, surname=name.split()[-1])], living=L.DECEASED, event_ids=ids, notes=notes, sensitivity=A.PUBLIC)]
    records += [Event(f"{pid}-{kind}", kind, date=date, place_id=place, participant_ids=[pid], sensitivity=A.PUBLIC) for kind, date, place in events]
    if sex:
        records.append(Claim(f"{pid}-sex", pid, "sex", sex, sensitivity=A.PUBLIC))
    return records


def family_case():
    case = ResearchCase("fictional-reasons", "Fictional reasons")
    case.add_many([
        Place("parish", "Invented Parish", sensitivity=A.PUBLIC), Place("town", "Invented Town", sensitivity=A.PUBLIC),
        *person("ada", "Ada Fable", [("birth", "ABT 1801", "parish"), ("death", "12 MAR 1870", "town")], "F"),
        *person("tobin", "Tobin Fable", [("birth", "1770", None)], "M", notes="Tobin kept the invented mill."),
        *person("wren", "Wren Fable", [("birth", "1772", None)], "F"),
        *person("corin", "Corin Vale", [("birth", "1770", None)], "M"),
        *person("bram", "Bram Fable", [("death", "1871", None)], "M"),
        *person("dora", "Dora Fable", [("birth", "1825", None)]), *person("eli", "Eli Fable", [("birth", "1827", None)]),
        *person("fen", "Fen Fable", [("birth", "1829", None)]),
        *person("iris", "Iris Fable", [("birth", "1802", None)], "F"),
        *person("pip", "Pip Vale", [("baptism", "3 MAY 1804", "parish"), ("burial", "1880", None)]),
        *person("quill", "Quill Vale"),
        Source("register", "Invented register", "parish register", sensitivity=A.PUBLIC),
        *[Citation(f"entry-{n}", "register", locator=f"entry {n}", sensitivity=A.PUBLIC) for n in range(1, 8)],
        Citation("household", "register", locator="household 9", sensitivity=A.PUBLIC),
        Claim("c-wren-plain", "ada", "mother", "Wren Fable", citation_ids=["entry-1"], sensitivity=A.PUBLIC),
        Claim("c-wren", "ada", "mother", "Wren Fable", rationale="The baptism names Wren as mother.",
              citation_ids=["entry-2", "entry-3", "entry-4", "entry-5", "entry-6", "entry-7"], sensitivity=A.PUBLIC),
        Evidence("ev-wren", "c-wren", "household", "The household lists Wren with Ada.", sensitivity=A.PUBLIC),
        Claim("c-tobin", "ada", "father", "Tobin Fable", rationale="A claim's reason, not shown.", citation_ids=["entry-1"], sensitivity=A.PUBLIC),
        # Own rationale first; claim rationale next (skipping a claim with none); a disproved rival.
        Relationship("r-tobin", "ada", "tobin", "parent", confidence=C.DOCUMENTED, claim_ids=["c-tobin"],
                     rationale="The banns name Tobin as her father.", sensitivity=A.PUBLIC),
        Relationship("r-wren", "ada", "wren", "parent", confidence=C.PROBABLE, claim_ids=["c-wren-plain", "c-wren"], sensitivity=A.PUBLIC),
        Relationship("r-corin", "ada", "corin", "parent", confidence=C.DISPROVED,
                     rationale="Corin was buried two years before Ada's birth.", sensitivity=A.PUBLIC),
        Relationship("r-bram", "ada", "bram", "spouse", confidence=C.DOCUMENTED, sensitivity=A.PUBLIC),
        Relationship("r-dora", "dora", "ada", "parent", sensitivity=A.PUBLIC),
        Relationship("r-eli", "eli", "ada", "parent", sensitivity=A.PUBLIC),
        Relationship("r-fen", "fen", "ada", "parent", confidence=C.DISPROVED, grade="ruled_out", sensitivity=A.PUBLIC),
        Relationship("r-iris", "iris", "tobin", "parent", sensitivity=A.PUBLIC),
        Finding("f-old", "Ada's baptism is the earlier of two entries.", related_ids=["ada"], recorded_on="2026-03-01", status="reviewed", sensitivity=A.PUBLIC),
        Finding("f-new", "Ada Fable's father is Tobin Fable.", related_ids=["ada"], recorded_on="2026-09-08", status="reviewed",
                confidence=C.DOCUMENTED, sensitivity=A.PUBLIC),
        Finding("f-undated", "An undated note on Ada.", related_ids=["ada"], status="draft", sensitivity=A.PUBLIC),
        Finding("f-tobin", "Tobin ran the invented mill.", related_ids=["tobin"], recorded_on="2025-05", status="reviewed", sensitivity=A.PUBLIC),
        Study("s-ada", "The Fable baptisms", related_ids=["ada"], updated_on="2026-10-01", status="draft", sensitivity=A.PUBLIC),
        # Withheld: a newer private finding, and a link resting on a private claim.
        Finding("f-secret", "SECRET-FINDING about Ada", related_ids=["ada"], recorded_on="2026-12-01", status="reviewed"),
        Claim("c-secret", "ada", "spouse", "Quill Vale", rationale="SECRET-RATIONALE"),
        Relationship("r-secret", "ada", "quill", "spouse", claim_ids=["c-secret"], rationale="SECRET-LINK", sensitivity=A.PUBLIC),
    ])
    return case


def text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


class FamilyReasonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.paths = build_site(family_case(), ProjectConfig(name="Fictional reasons", grades=GRADES), cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def dossier(self, pid):
        return next(p for name, p in self.paths.items() if name.startswith("people/") and f'data-person-id="{pid}"' in p.read_text()).read_text()

    def section(self, pid, heading):
        return self.dossier(pid).split(f"<h3>{heading}</h3>", 1)[1].split("<h3>", 1)[0].split("</section>", 1)[0]

    def item(self, pid, heading, name):
        return next(li for li in re.findall(r"<li>.*?</li>(?=<li>|</ul>)", self.section(pid, heading)) if f">{name}</a>" in li)

    def test_fixture_is_valid_and_the_rationale_round_trips(self):
        case = family_case()
        self.assertEqual([], validate_case(case))
        self.assertEqual([], grade_errors(case, GRADES))
        row = next(r for r in case.records("Relationship") if r.id == "r-tobin")
        self.assertEqual(row, record_from_dict("Relationship", row.to_dict()))
        bad = family_case()
        bad.add(Relationship("r-bad", "ada", "quill", "parent", rationale=["no"], sensitivity=A.PUBLIC))
        self.assertIn("r-bad.rationale must be a string or null", validate_case(bad))

    def test_the_links_own_rationale_comes_first(self):
        tobin = self.item("ada", "Parents", "Tobin Fable")
        self.assertIn('<p class="meta link-reason"><strong>Reason:</strong> The banns name Tobin as her father.</p>', tobin)
        self.assertNotIn("A claim's reason", tobin)
        self.assertIn(f'Supporting records: <a href="../sources.html#{_anchor("entry-1")}">Invented register (entry 1)</a></p>', tobin)

    def test_else_the_first_linked_claim_that_gives_a_reason(self):
        wren = self.item("ada", "Parents", "Wren Fable")
        self.assertIn("<strong>Reason:</strong> The baptism names Wren as mother.</p>", wren)
        # Claims' citations in order, then the evidence's; five shown, then a count.
        records = re.search(r'<p class="meta link-records">(.*?)</p>', wren)[1]
        self.assertEqual("Supporting records: Invented register (entry 1), Invented register (entry 2), Invented register (entry 3), "
                         "Invented register (entry 4), Invented register (entry 5) and 3 more", text(records))
        self.assertEqual(5, records.count('href="../sources.html#'))
        more = re.search(r'<details class="link-records-more">(.*?)</details>', wren)[1]
        self.assertIn("<summary>Show 3 additional supporting records</summary>", more)
        self.assertIn("Additional supporting records: Invented register (entry 6), Invented register (entry 7), Invented register (household 9)", text(more))
        self.assertEqual(3, more.count('href="../sources.html#'))

    def test_else_no_reason_and_no_records(self):
        bram = self.item("ada", "Spouses and partners", "Bram Fable")
        self.assertNotIn("link-reason", bram)
        self.assertNotIn("link-records", bram)

    def test_a_rejected_parent_is_set_apart_and_does_not_compete(self):
        parents = self.section("ada", "Parents")
        self.assertNotIn("Corin Vale", parents)
        self.assertNotIn("Competing parent records", self.dossier("ada"))
        rejected = self.section("ada", "Rejected and superseded links")
        self.assertIn("Assessed evidence contradicts these links. They are kept, with their reasons, so the reasoning stays visible.", text(rejected))
        corin = self.item("ada", "Rejected and superseded links", "Corin Vale")
        self.assertIn('<a class="badge evidence-badge badge-conflict" href="../evidence.html#confidence-disproved" data-confidence="disproved">'
                      '<span class="badge-glyph" aria-hidden="true">✕</span>Disproved</a>', corin)
        self.assertIn("<strong>Reason:</strong> Corin was buried two years before Ada&#x27;s birth.", corin)
        # The list comes last in the family section, after the siblings.
        family = self.dossier("ada").split('<h2 id="family-heading">Family</h2>', 1)[1].split("</section>", 1)[0]
        self.assertEqual(["Parents", "Spouses and partners", "Children", "Siblings", "Rejected and superseded links"], re.findall(r"<h3>(.*?)</h3>", family))
        # Every link is still listed under "All recorded relationships".
        self.assertRegex(text(self.dossier("ada").split('<h2 id="relationships">All recorded relationships</h2>', 1)[1]), r"Corin Vale is the father of Ada Fable ✕\s*Disproved")

    def test_a_grade_counting_as_disproved_is_set_apart_with_its_wording(self):
        self.assertNotIn("Fen Fable", self.section("ada", "Children"))
        fen = self.item("ada", "Rejected and superseded links", "Fen Fable")
        self.assertIn(">Ruled out</a>", fen)
        self.assertEqual("Mother Ada Fable b. c. 1801 – d. 1870 ✕Ruled out", text(self.item("fen", "Rejected and superseded links", "Ada Fable")))
        self.assertIn("No public parents recorded.", self.dossier("fen"))

    def test_the_opening_sentences(self):
        def intro(pid):
            found = re.search(r'<p class="lead intro">(.*?)</p>', self.dossier(pid))
            return text(found[1]) if found else None
        self.assertEqual("Ada Fable was born c. 1801 in Invented Parish, and died on 12 Mar 1870 in Invented Town. "
                         "This page lists Tobin Fable and Wren Fable as parents, one spouse or partner and two children.", intro("ada"))
        self.assertEqual("Iris Fable was born in 1802. This page lists Tobin Fable as a parent.", intro("iris"))
        self.assertEqual("Pip Vale was baptised on 3 May 1804 in Invented Parish, and buried in 1880.", intro("pip"))
        self.assertEqual("Bram Fable died in 1871. This page lists one spouse or partner.", intro("bram"))
        # Only rejected links: no relatives are listed.
        self.assertEqual("Corin Vale was born in 1770.", intro("corin"))
        self.assertIsNone(intro("quill"))  # no events and no current links: nothing is written
        self.assertIn('<a href="../places/pl-' + _key("parish") + '.html">Invented Parish</a>', self.dossier("ada"))

    def test_notes_replace_the_opening_sentences(self):
        tobin = self.dossier("tobin")
        self.assertNotIn('class="lead intro"', tobin)
        self.assertIn('<h2 id="biography">Biography and notes</h2><p class="preserve-lines">Tobin kept the invented mill.</p>', tobin)
        self.assertIn("Tobin ran the invented mill.", tobin.split('class="latest-finding"', 1)[1].split("</aside>", 1)[0])

    def test_latest_finding_box(self):
        ada = self.dossier("ada")
        box = ada.split('<aside class="latest-finding"', 1)[1].split("</aside>", 1)[0]
        self.assertIn('<h2 id="latest-finding-heading">Latest finding</h2>', box)
        self.assertIn(f'<a href="../research.html#{_anchor("f-new")}">Ada Fable&#x27;s father is Tobin Fable.</a>', box)
        self.assertIn('data-status="reviewed" data-confidence="documented"><span class="badge-glyph" aria-hidden="true">✓</span>Reviewed · Documented</a>', box)
        self.assertIn('<p class="meta">Recorded <time datetime="2026-09-08">8 Sep 2026</time></p>', box)
        # The related study was updated after the newest finding.
        self.assertIn('<p class="meta research-date">Research last recorded <time datetime="2026-10-01">1 Oct 2026</time></p>', box)
        self.assertNotIn("earlier of two entries", box)
        # After the header and before the names and the family section.
        self.assertLess(ada.index('class="record-id meta"'), ada.index('class="lead intro"'))
        self.assertLess(ada.index('class="lead intro"'), ada.index('class="latest-finding"'))
        self.assertLess(ada.index('class="latest-finding"'), ada.index('<h2 id="names">Names</h2>'))
        self.assertLess(ada.index('<h2 id="names">Names</h2>'), ada.index('id="family-heading"'))
        self.assertIn('<p class="meta research-date">Research last recorded <time datetime="2025-05">May 2025</time></p>', self.dossier("tobin"))
        self.assertNotIn("latest-finding", self.dossier("iris"))  # no dated finding about her

    def test_withheld_records_never_appear(self):
        for name, path in self.paths.items():
            if path.suffix in {".html", ".js", ".json", ".csv", ".ged", ".xml", ".geojson"}:
                body = path.read_text()
                for sentinel in ("SECRET-FINDING", "SECRET-RATIONALE", "SECRET-LINK"):
                    self.assertNotIn(sentinel, body, name)
        self.assertNotIn("Quill Vale", self.section("ada", "Spouses and partners"))
        self.assertNotIn("2026-12-01", self.dossier("ada"))

    def test_no_broken_links(self):
        self.assertEqual([], check_site(self.root)["broken"])


if __name__ == "__main__":
    unittest.main()
