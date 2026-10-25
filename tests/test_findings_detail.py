"""Finding limitations, cited records and types, and the findings archive."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest

from db_helpers import private_view

from genealogy.case import ResearchCase, validate_case
from genealogy.cli import main
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Citation, Finding, LivingStatus as L, Name, Person, Source,
                              record_from_dict)
from genealogy.site import FINDINGS_PER_PAGE, LATEST_FINDINGS, build_site
from genealogy.sitecheck import check_site


def case(findings=()):
    c = ResearchCase("fictional-findings", "Fictional findings")
    c.add_many([
        Person("ada", names=[Name("Ada Fable", surname="Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Person("secret", names=[Name("SECRET LIVING")], living=L.LIVING, sensitivity=A.PUBLIC),
        Source("register", "Invented parish register", "register", sensitivity=A.PUBLIC),
        Citation("register-1801", "register", locator="1801, entry 4", sensitivity=A.PUBLIC),
        Source("private-letter", "PRIVATE LETTER", "letter", sensitivity=A.PRIVATE),
        Citation("letter-1", "private-letter", sensitivity=A.PRIVATE),
        *findings,
    ])
    return c


def build(c, directory):
    config = ProjectConfig(name="Fictional", raw={"site": {"base_url": "https://example.invalid/"}})
    build_site(c, config, Path(directory))
    return Path(directory)


class FindingDetailTests(unittest.TestCase):
    def test_limitations_records_and_type_are_shown_and_round_trip(self):
        finding = Finding("f1", "Ada was baptised in 1801.", related_ids=["ada"], status="qualified", recorded_on="2026-10-01",
                          limitations="The register is a later copy.", citation_ids=["register-1801"], kind="vital",
                          sensitivity=A.PUBLIC)
        c = case([finding])
        self.assertEqual([], validate_case(c))
        self.assertEqual(finding, record_from_dict("Finding", finding.to_dict()))
        with tempfile.TemporaryDirectory() as directory:
            out = build(c, directory)
            log = (out / "findings.html").read_text()
            self.assertIn("<strong>Limits:</strong> The register is a later copy.", log)
            self.assertIn('<a class="badge evidence-badge badge-kind finding-kind" href="evidence.html#finding-kind" data-kind="vital">Vital</a>', log)
            self.assertIn("Invented parish register (1801, entry 4)", log)
            self.assertIn("The register is a later copy.", (out / "research.html").read_text())
            self.assertIn("Limits: The register is a later copy.", (out / "findings.xml").read_text())
            self.assertEqual("The register is a later copy.", json.loads((out / "data/site.json").read_text())["findings"][0]["limitations"])

    def test_a_finding_citing_a_private_record_is_withheld(self):
        c = case([Finding("f1", "PRIVATE CONCLUSION", related_ids=["ada"], citation_ids=["letter-1"], sensitivity=A.PUBLIC)])
        with tempfile.TemporaryDirectory() as directory:
            out = build(c, directory)
            everything = "".join(p.read_text(errors="ignore") for p in out.rglob("*") if p.is_file())
            self.assertNotIn("PRIVATE CONCLUSION", everything)
            self.assertNotIn("PRIVATE LETTER", everything)

    def test_validation_rejects_unknown_citations_and_blank_types(self):
        c = case([Finding("f1", "Ada.", citation_ids=["nowhere"], kind=" ", sensitivity=A.PUBLIC)])
        errors = "\n".join(validate_case(c))
        self.assertIn("f1.citation_ids references missing record: nowhere", errors)
        self.assertIn("f1.kind must be a non-empty string or null", errors)

    def test_cli_records_the_new_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "p"
            self.assertEqual(0, main(["init", str(root), "--name", "Fictional"]))
            for kind, record in (("Source", {"id": "register", "title": "Invented register", "source_type": "register", "sensitivity": "public"}),
                                 ("Citation", {"id": "register-1", "source_id": "register", "sensitivity": "public"})):
                path = Path(directory) / f"{kind}.json"
                path.write_text(json.dumps(record))
                self.assertEqual(0, main(["--project", str(root), "record", "add", kind, "--input", str(path)]))
            self.assertEqual(0, main(["--project", str(root), "finding", "add", "f1", "A conclusion.", "--cite", "register-1",
                                      "--limitations", "Only a copy.", "--kind", "record"]))
            stored = private_view(root)[0].records("Finding")[0]
            self.assertEqual((["register-1"], "Only a copy.", "record"), (stored.citation_ids, stored.limitations, stored.kind))


class ArchiveTests(unittest.TestCase):
    def findings(self, count):
        return [Finding(f"f{n:03d}", f"Conclusion number {n}.", related_ids=["ada"], recorded_on=f"2026-{1 + n // 28:02d}-{1 + n % 28:02d}",
                        sensitivity=A.PUBLIC) for n in range(count)]

    def test_long_logs_open_with_the_newest_and_keep_archive_pages_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            out = build(case(self.findings(120)), directory)
            log = (out / "findings.html").read_text()
            self.assertEqual(LATEST_FINDINGS, log.count('class="finding-entry"'))
            self.assertIn("Conclusion number 119.", log)
            self.assertNotIn("Conclusion number 10.", log)
            pages = sorted(p.name for p in (out / "findings").glob("page-*.html"))
            self.assertEqual(["page-1.html", "page-2.html", "page-3.html"], pages)
            first = (out / "findings/page-1.html").read_text()
            self.assertEqual(FINDINGS_PER_PAGE, first.count('class="finding-entry"'))
            self.assertIn("Conclusion number 0.", first)
            self.assertTrue(re.search(r"<title>(.*?)</title>", first)[1].startswith("Findings, page 1 —"))
            self.assertEqual([], check_site(out)["broken"])
            # A newer finding never moves an older one to another page.
            out = build(case(self.findings(140)), directory)
            self.assertIn("Conclusion number 0.", (out / "findings/page-1.html").read_text())
            self.assertIn("Conclusion number 99.", (out / "findings/page-2.html").read_text())
            self.assertIn("Conclusion number 100.", (out / "findings/page-3.html").read_text())

    def test_archive_pages_no_longer_needed_are_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            build(case(self.findings(120)), directory)
            out = build(case(self.findings(LATEST_FINDINGS)), directory)
            self.assertEqual([], list((out / "findings").glob("*.html")))
            self.assertEqual([], check_site(out)["broken"])

    def test_short_logs_have_no_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            out = build(case(self.findings(LATEST_FINDINGS)), directory)
            self.assertFalse((out / "findings").exists())
            self.assertEqual(LATEST_FINDINGS, (out / "findings.html").read_text().count('class="finding-entry"'))
            home = (out / "index.html").read_text()
            self.assertIn("All 30 findings", home)


if __name__ == "__main__":
    unittest.main()
