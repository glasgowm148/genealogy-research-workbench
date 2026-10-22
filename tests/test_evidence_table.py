"""Each claim's records, readings, assessments and limits in one table."""
from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Citation, Claim, ClaimStatus, Evidence, LivingStatus as L, Name, Person,
                              Source, record_from_dict)
from genealogy.site import _anchor, build_site

LIMITATION = "The return gives no age <or> mother."


def case(limitation=LIMITATION):
    c = ResearchCase("fictional-evidence", "Fictional evidence")
    c.add_many([
        Person("ada", names=[Name("Ada Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Source("census", "Invented census", "census", sensitivity=A.PUBLIC),
        Source("register", "Invented register", "register", sensitivity=A.PUBLIC),
        Citation("household", "census", locator="schedule 12", abstract="Ada Fable, wife, of Mill Lane.",
                 quotation="Ada do. Wife", sensitivity=A.PUBLIC),
        Citation("entry", "register", locator="entry 4", quotation="Ada Fable, spinster", sensitivity=A.PUBLIC),
        Citation("index", "register", locator="index p. 2", sensitivity=A.PUBLIC),
        Citation("hidden", "register", abstract="SECRET-ABSTRACT of a private entry", sensitivity=A.PRIVATE),
        Claim("ada-married", "ada", "marriage", "1888", citation_ids=["entry", "household", "index"],
              status=ClaimStatus.SUPPORTED, sensitivity=A.PUBLIC),
        Claim("ada-private-claim", "ada", "residence", "Mill Lane", citation_ids=["hidden"], sensitivity=A.PUBLIC),
        Evidence("ev-household", "ada-married", "household", "Names her as wife.", limitation=limitation, sensitivity=A.PUBLIC),
        Evidence("ev-entry", "ada-married", "entry", "A spinster in 1887.", supports=False, sensitivity=A.PUBLIC),
        Evidence("ev-hidden", "ada-married", "household", "SECRET-ASSESSMENT", limitation="SECRET-LIMITATION"),
        Evidence("ev-on-hidden", "ada-married", "hidden", "Hidden entry agrees.", sensitivity=A.PUBLIC),
    ])
    return c


class EvidenceTableTests(unittest.TestCase):
    def build(self, directory, c=None):
        out = Path(directory)
        build_site(c or case(), ProjectConfig(name="Fictional"), out)
        return out, next((out / "people").glob("*.html")).read_text()

    def rows(self, dossier):
        table = re.search(r'<table class="evidence-table">.*?</table>', dossier)[0]
        return re.findall(r"<tbody>.*</tbody>", table)[0].split("</tr>")[:-1]

    def test_the_limitation_round_trips_and_must_be_text(self):
        c = case()
        self.assertEqual([], validate_case(c))
        record = next(e for e in c.records("Evidence") if e.id == "ev-household")
        self.assertEqual(LIMITATION, record_from_dict("Evidence", record.to_dict()).limitation)
        self.assertEqual(record, record_from_dict("Evidence", record.to_dict()))
        self.assertIn("ev-household.limitation must be a string or null", validate_case(case(limitation=["no"])))

    def test_each_record_is_one_row_with_its_reading_assessment_and_limitation(self):
        with tempfile.TemporaryDirectory() as directory:
            _, dossier = self.build(directory)
            self.assertIn('<caption>Records and assessments</caption>', dossier)
            self.assertIn('<th scope="col">Record</th><th scope="col">What it says</th><th scope="col">Assessment</th>'
                          '<th scope="col">Limitation</th>', dossier)
            self.assertNotIn("<h4>Evidence assessments</h4>", dossier)
            entry, household, index = self.rows(dossier)  # the claim's citation order
            self.assertIn(f'<tr id="{_anchor("ev-household")}">', household)
            self.assertIn('Invented census</a><br><span class="meta">schedule 12</span>', household)
            self.assertIn('<td data-label="What it says">Ada Fable, wife, of Mill Lane.</td>', household)  # abstract before quotation
            self.assertIn("<strong>Supports</strong>: Names her as wife.", household)
            self.assertIn('class="badge evidence-badge badge-', household)
            self.assertIn('<td data-label="Limitation">The return gives no age &lt;or&gt; mother.</td>', household)
            self.assertIn(f'<tr id="{_anchor("ev-entry")}">', entry)
            self.assertIn('<td data-label="What it says"><q>Ada Fable, spinster</q></td>', entry)
            self.assertIn("<strong>Challenges</strong>: A spinster in 1887.", entry)
            self.assertIn('<td data-label="Limitation">—</td>', entry)

    def test_a_citation_nobody_has_assessed_gets_its_own_row(self):
        with tempfile.TemporaryDirectory() as directory:
            _, dossier = self.build(directory)
            index = self.rows(dossier)[2]
            self.assertTrue(index.startswith("<tr><td"), index)
            self.assertIn("Invented register</a><br><span class=\"meta\">index p. 2</span>", index)
            self.assertIn('<td data-label="What it says">—</td>', index)
            self.assertIn('<td data-label="Assessment"><span class="meta">Not yet assessed</span></td><td data-label="Limitation">—</td>', index)

    def test_private_records_never_reach_the_table(self):
        with tempfile.TemporaryDirectory() as directory:
            out, dossier = self.build(directory)
            self.assertEqual(3, len(self.rows(dossier)))
            everything = "".join(p.read_text(errors="ignore") for p in out.rglob("*") if p.is_file())
            for secret in ("SECRET-ABSTRACT", "SECRET-ASSESSMENT", "SECRET-LIMITATION", "Hidden entry agrees", "residence: Mill Lane"):
                self.assertNotIn(secret, everything)


if __name__ == "__main__":
    unittest.main()
