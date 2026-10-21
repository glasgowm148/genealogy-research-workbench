"""A citation's abstract: the researcher's reading of the record."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Citation, Claim, ClaimStatus, LivingStatus as L, Name, Person, Source,
                              record_from_dict)
from genealogy.site import build_site

ABSTRACT = "Baptism of Ann <Fable>, born 17 January 1837, daughter of Robert and Mary."


def case(abstract=ABSTRACT, sensitivity=A.PUBLIC):
    c = ResearchCase("fictional-abstracts", "Fictional abstracts")
    c.add_many([
        Person("ann", names=[Name("Ann Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Source("register", "Invented parish register", "register", sensitivity=A.PUBLIC),
        Citation("entry-75", "register", locator="entry 75", abstract=abstract, sensitivity=sensitivity),
        Claim("ann-born", "ann", "birth", "1837", citation_ids=["entry-75"], status=ClaimStatus.SUPPORTED, sensitivity=A.PUBLIC),
    ])
    return c


class AbstractTests(unittest.TestCase):
    def build(self, c, directory):
        out = Path(directory)
        build_site(c, ProjectConfig(name="Fictional"), out)
        return out

    def test_the_abstract_is_shown_with_its_citation_and_exported(self):
        c = case()
        self.assertEqual([], validate_case(c))
        record = c.records("Citation")[0]
        self.assertEqual(record, record_from_dict("Citation", record.to_dict()))
        with tempfile.TemporaryDirectory() as directory:
            out = self.build(c, directory)
            shown = "<p><strong>Abstract:</strong> Baptism of Ann &lt;Fable&gt;, born 17 January 1837, daughter of Robert and Mary.</p>"
            self.assertIn("<p><strong>Locator:</strong> entry 75</p>" + shown, (out / "sources.html").read_text())
            dossier = next((out / "people").glob("*.html")).read_text()
            self.assertIn('<td data-label="What it says">Baptism of Ann &lt;Fable&gt;, born 17 January 1837, daughter of Robert and Mary.</td>', dossier)
            self.assertEqual(ABSTRACT, json.loads((out / "data/site.json").read_text())["citations"][0]["abstract"])

    def test_a_private_citation_keeps_its_abstract_private(self):
        with tempfile.TemporaryDirectory() as directory:
            out = self.build(case(sensitivity=A.PRIVATE), directory)
            everything = "".join(p.read_text(errors="ignore") for p in out.rglob("*") if p.is_file())
            self.assertNotIn("17 January 1837", everything)

    def test_an_abstract_must_be_text(self):
        self.assertIn("entry-75.abstract must be a string or null", validate_case(case(abstract=["not", "text"])))


if __name__ == "__main__":
    unittest.main()
