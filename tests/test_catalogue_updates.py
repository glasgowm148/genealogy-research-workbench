"""Update priority in the catalogue: a change's significance, the "Needs updated" line and chips under a name, and their data."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, grade_errors, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import AccessLevel as A, Finding, record_from_dict
from genealogy.site import build_site

from test_catalogue_find_person import GRADES, change, config, finder_records  # tests/ is on the path under unittest discovery

ROOT = Path(__file__).resolve().parents[1]


def update_records():
    """The Find a person people, with significance on three pending changes, estimates on two links, and a withheld finding
    whose change names a public link and carries a sentinel note."""
    records = finder_records()
    by_id = {r.id: r for r in records}
    by_id["fd-father"].changes[0]["significance"] = 55
    by_id["fd-jory"].changes[1]["significance"] = 70
    by_id["fd-gwen"].changes[0]["significance"] = 99  # reviewed: nothing is pending, so nothing shows
    by_id["r-father"].estimate = 98
    by_id["r-spouse"].estimate = 90
    by_id["fd-secret"].changes[0].update(significance=100, note="SECRET-UPDATE-NOTE")
    records.append(Finding("fd-secret-2", "SECRET-UPDATE-FINDING about Iris.", related_ids=["f09"], status="draft", recorded_on="2026-01-01",
                           changes=[change("r-bram-wife", None, "possible", "SECRET-UPDATE-NOTE-2") | {"significance": 100}], sensitivity=A.PRIVATE))
    return records


def update_case() -> ResearchCase:
    case = ResearchCase("fictional-updates", "Fictional updates")
    case.add_many(update_records())
    return case


def cell(html: str, pid: str) -> str:
    """A catalogue row's Individual cell."""
    return re.search(rf'<tr data-person-id="{pid}"[^>]*><td>(.*?)</td>', html)[1]


class SignificanceValidationTests(unittest.TestCase):
    def finding(self, **extra):
        return Finding("fd", "A change.", changes=[change("r", None, "probable") | extra])

    def test_a_whole_number_from_0_to_100_or_none(self):
        for value in (0, 55, 100, None):
            case = ResearchCase("c", "C")
            case.add(self.finding(significance=value))
            self.assertFalse([e for e in validate_case(case) if "significance" in e], value)
        for value in (-1, 101, 5.5, "55", True):
            case = ResearchCase("c", "C")
            case.add(self.finding(significance=value))
            self.assertIn("fd.changes[0].significance must be a whole number from 0 to 100, or null", validate_case(case), value)

    def test_round_trips(self):
        record = self.finding(significance=55)
        again = record_from_dict("Finding", json.loads(json.dumps(record.to_dict())))
        self.assertEqual(55, again.changes[0]["significance"])
        self.assertEqual(record, again)

    def test_documented(self):
        self.assertIn("significance", (ROOT / "docs/research.md").read_text(encoding="utf-8"))
        deployment = (ROOT / "docs/deployment.md").read_text(encoding="utf-8")
        for words in ("Update priority: new fathers first", "Update significance", "Father changes: highest confidence", "`priority`", "`father-changes`"):
            self.assertIn(words, deployment)


class CatalogueUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.out = Path(cls.directory.name)
        case = update_case()
        assert validate_case(case) == [] and grade_errors(case, GRADES) == [], (validate_case(case), grade_errors(case, GRADES))
        build_site(case, config(), cls.out / "named")
        build_site(case, ProjectConfig(name="No tree named", grades=GRADES), cls.out / "unnamed")
        cls.html = (cls.out / "named/catalogue.html").read_text(encoding="utf-8")
        script = (cls.out / "named/data/site-data.js").read_text(encoding="utf-8")
        cls.data = json.loads(script.removeprefix("window.GENEALOGY_SITE_DATA=").removesuffix(";\n"))
        cls.people = {p["id"]: p for p in cls.data["people"]}

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_the_line_and_chips_under_the_name(self):
        ada = cell(self.html, "f01")
        self.assertIn('<span class="record-id">Fable-1</span><span class="update-line">Needs updated on FableTree · significance 55</span><span class="update-chips">', ada)
        # A new link is "added"; a new confidence names the project's grade and the link's estimate, coloured and linked as that value.
        self.assertIn('<a class="badge evidence-badge badge-documented update-chip" href="evidence.html#confidence-documented">'
                      '<span class="badge-glyph" aria-hidden="true">✓</span>father added</a>', ada)
        self.assertIn('<a class="badge evidence-badge badge-probable update-chip" href="evidence.html#grade-strongly_supported">'
                      '<span class="badge-glyph" aria-hidden="true">~</span>spouse now Strongly supported 90%</a>', ada)
        chips = lambda pid: re.findall(r'</span>([^<]+)</a>', cell(self.html, pid).split('class="update-chips"', 1)[1])
        self.assertEqual(["father replaced"], chips("f06"))
        self.assertIn('Needs updated on FableTree</span>', cell(self.html, "f06"))  # no significance recorded
        self.assertEqual(["father now Disproved", "father replaced"], chips("f10"))
        self.assertIn("significance 70", cell(self.html, "f10"))
        self.assertEqual(["spouse now Strongly supported 90%", "child replaced", "child replaced"], chips("f04"))
        self.assertEqual(["child added"], chips("f02"))

    def test_nothing_pending_nothing_shown(self):
        # Gwen's change is reviewed; Cora's and Iris's only changes are in withheld findings; Esme has none.
        for pid in ("f03", "f05", "f07", "f09"):
            self.assertNotIn("update-line", cell(self.html, pid), pid)
        self.assertNotIn("significance 99", self.html)
        self.assertNotIn("significance 100", self.html)

    def test_the_tree_is_named_from_configuration(self):
        unnamed = (self.out / "unnamed/catalogue.html").read_text(encoding="utf-8")
        self.assertIn('<span class="update-line">Needs updated on the tree · significance 55</span>', cell(unnamed, "f01"))
        self.assertEqual("FableTree", self.data["site"]["tree_name"])
        script = (self.out / "unnamed/data/site-data.js").read_text(encoding="utf-8")
        self.assertNotIn('"tree_name"', script)

    def test_the_shared_data_carries_significance_and_estimate(self):
        changes = {pid: p.get("changes") for pid, p in self.people.items() if p.get("changes")}
        self.assertEqual({
            # [relationship, action, new value, significance, estimate], trailing blanks left off.
            "f01": [["father", "add", "documented", 55, 98], ["spouse", "regrade", "strongly_supported", None, 90]],
            "f02": [["child", "add", "documented", 55, 98]],
            "f04": [["spouse", "regrade", "strongly_supported", None, 90], ["child", "replace", "probable"], ["child", "replace", "possible", 70]],
            "f06": [["father", "replace", "probable"]],
            "f08": [["child", "regrade", "disproved"]],
            "f10": [["father", "regrade", "disproved"], ["father", "replace", "possible", 70]],
        }, changes)

    def test_nothing_withheld_reaches_any_output(self):
        for path in self.out.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="ignore")
                for secret in ("SECRET-UPDATE", "SECRET-FINDING", "SECRET-PERSON", "fd-secret"):
                    self.assertNotIn(secret, text, path)

    def test_the_page_reads_without_javascript_and_stays_small_at_scale(self):
        from test_scale import large_case
        large = large_case()
        large.add_many(update_records())
        build_site(large, config(), self.out / "large")
        pages = self.out / "large"
        first = (pages / "catalogue.html").read_text(encoding="utf-8")
        self.assertIn("Needs updated on FableTree · significance 55", cell(first, "f01"))
        for path in [pages / "catalogue.html", *(pages / "catalogue").glob("*.html")]:
            self.assertLess(path.stat().st_size, 100_000, path)


if __name__ == "__main__":
    unittest.main()
