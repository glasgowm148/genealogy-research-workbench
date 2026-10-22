"""A finding records which relationship or claim it reassessed, and from what."""
from __future__ import annotations

import io
import json
from contextlib import redirect_stderr
from pathlib import Path
import tempfile
import unittest

from genealogy.case import ResearchCase, grade_errors, validate_case
from genealogy.cli import main
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Claim, ClaimStatus, Confidence as C, Finding, LivingStatus as L, Name,
                              Person, Relationship, record_from_dict)
from genealogy.site import _anchor, build_site

GRADES = {"strongly_supported": {"label": "Strongly supported", "meaning": "Several records agree.", "confidence": "probable"}}


def change(record_id, before, after, note=None):
    return {"record_id": record_id, "before": before, "after": after, "note": note}


def person(pid, name):
    return Person(pid, names=[Name(name, surname="Fable")], living=L.DECEASED, sensitivity=A.PUBLIC)


def case(findings=(), *, parent_confidence=C.DOCUMENTED, private_link=False):
    c = ResearchCase("fictional-changes", "Fictional changes")
    c.add_many([
        person("ada", "Ada Fable"), person("bram", "Bram Fable"), person("cara", "Cara Fable"),
        person("dora", "Dora Fable"), person("eli", "Eli Fable"),
        Relationship("ada-parent", "ada", "bram", "parent", confidence=parent_confidence, sensitivity=A.PUBLIC),
        Relationship("ada-partner", "ada", "cara", "spouse", confidence=C.PROBABLE, grade="strongly_supported", sensitivity=A.PUBLIC),
        Relationship("dora-parent", "dora", "ada", "parent", confidence=C.PROBABLE, sensitivity=A.PUBLIC),
        Relationship("ada-sibling", "ada", "eli", "sibling", confidence=C.POSSIBLE, sensitivity=A.PUBLIC),
        Relationship("ada-hidden", "ada", "cara", "parent", confidence=C.POSSIBLE,
                     sensitivity=A.PRIVATE if private_link else A.PUBLIC),
        Claim("ada-born", "ada", "birth", "1801", status=ClaimStatus.SUPPORTED, confidence=C.DOCUMENTED, sensitivity=A.PUBLIC),
        *findings,
    ])
    return c


def history():
    return [
        Finding("f-early", "Bram fits as Ada's father.", related_ids=["ada"], recorded_on="2026-03-01", sensitivity=A.PUBLIC,
                changes=[change("ada-parent", "unknown", "possible")]),
        Finding("f-late", "The baptism names Bram as Ada's father.", related_ids=["ada"], recorded_on="2026-09-08", sensitivity=A.PUBLIC,
                changes=[change("ada-parent", "possible", "documented", "Baptism entry found."),
                         change("ada-partner", "possible", "strongly_supported"),
                         change("dora-parent", None, "probable"),
                         change("ada-sibling", "unknown", "possible"),
                         change("ada-born", "probable", "documented")]),
    ]


def config(directory):
    path = Path(directory) / "genealogy.toml"
    path.write_text('[project]\nname = "Fictional changes"\n[site]\nbase_url = "https://example.invalid/"\n'
                    '[grades.strongly_supported]\nlabel = "Strongly supported"\nmeaning = "Several records agree."\nconfidence = "probable"\n')
    return ProjectConfig.load(path)


def dossier(out, pid):
    return next(p for p in (out / "people").glob("*.html") if f'data-person-id="{pid}"' in p.read_text()).read_text()


class ValidationTests(unittest.TestCase):
    def test_changes_round_trip_and_a_consistent_history_is_valid(self):
        c = case(history())
        self.assertEqual([], validate_case(c) + grade_errors(c, GRADES))
        finding = c.records("Finding")[1]
        self.assertEqual(finding, record_from_dict("Finding", json.loads(json.dumps(finding.to_dict()))))
        self.assertEqual(c.to_dict(), ResearchCase.from_dict(json.loads(json.dumps(c.to_dict()))).to_dict())

    def test_a_change_must_name_a_relationship_or_claim(self):
        c = case([Finding("f1", "Ada.", sensitivity=A.PUBLIC, changes=[change("nowhere", None, "possible"), change("ada", None, "possible")])])
        errors = "\n".join(validate_case(c))
        self.assertIn("f1.changes[].record_id references missing record: nowhere", errors)
        self.assertIn("f1.changes[].record_id must reference a Relationship or Claim: ada", errors)

    def test_malformed_changes_are_reported(self):
        for changes, message in (([["ada-parent", "possible"]], "f1.changes must be a list of objects"),
                                 ([{**change("ada-parent", "possible", "documented"), "why": "x"}], "f1.changes[0] has unknown keys: why"),
                                 ([{"record_id": "ada-parent", "before": "possible"}], "f1.changes[0].after must be a confidence value or grade key"),
                                 ([change("", None, "documented")], "f1.changes[0].record_id must be a non-empty id"),
                                 ([change("ada-parent", 3, "documented")], "f1.changes[0].before must be a string or null"),
                                 ([change("ada-parent", None, "documented", ["x"])], "f1.changes[0].note must be a string or null")):
            with self.subTest(message=message):
                self.assertIn(message, validate_case(case([Finding("f1", "Ada.", sensitivity=A.PUBLIC, changes=changes)])))

    def test_values_must_be_confidence_values_or_defined_grades(self):
        c = case([Finding("f1", "Ada.", sensitivity=A.PUBLIC, changes=[change("ada-parent", "likely", "documented")])])
        self.assertEqual([], validate_case(c))
        self.assertEqual(["f1.changes[0].before is neither a confidence value nor a grade defined under [grades]: likely"],
                         grade_errors(c, GRADES))
        graded = case([Finding("f1", "Ada.", sensitivity=A.PUBLIC, changes=[change("ada-partner", "possible", "strongly_supported")])])
        self.assertEqual([], grade_errors(graded, GRADES))
        self.assertIn("f1.changes[0].after is neither a confidence value nor a grade defined under [grades]: strongly_supported",
                      grade_errors(graded, {}))

    def test_the_latest_change_must_agree_with_the_record(self):
        # The earlier change ends at "possible", but only the latest must match.
        self.assertEqual([], grade_errors(case(history()), GRADES))
        stale = grade_errors(case(history(), parent_confidence=C.PROBABLE), GRADES)
        self.assertEqual(["f-late.changes[0].after is documented, but ada-parent is now probable; "
                          "the latest change to a record must end at its current grade or confidence"], stale)
        # A grade is compared by its key, not by the standard grade it counts as.
        wrong = case([Finding("f1", "Cara.", recorded_on="2026-01-01", sensitivity=A.PUBLIC, changes=[change("ada-partner", None, "probable")])])
        self.assertIn("but ada-partner is now strongly_supported", "\n".join(grade_errors(wrong, GRADES)))

    def test_undated_changes_come_before_dated_ones_and_ties_go_to_the_last_recorded(self):
        undated = Finding("f-undated", "Old note.", sensitivity=A.PUBLIC, changes=[change("ada-parent", None, "possible")])
        dated = Finding("f-dated", "Proved.", recorded_on="2026-01-01", sensitivity=A.PUBLIC, changes=[change("ada-parent", "possible", "documented")])
        self.assertEqual([], grade_errors(case([dated, undated]), GRADES))
        same_day = Finding("f-same", "Doubted again.", recorded_on="2026-01-01", sensitivity=A.PUBLIC, changes=[change("ada-parent", "documented", "possible")])
        self.assertEqual([], grade_errors(case([same_day, dated]), GRADES))
        self.assertEqual(1, len(grade_errors(case([dated, same_day]), GRADES)))


class RenderingTests(unittest.TestCase):
    def build(self, c):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        out = Path(self.directory.name) / "site"
        build_site(c, config(self.directory.name), out)
        return out

    def test_family_rows_and_claims_show_each_change_linked_to_its_finding(self):
        out = self.build(case(history()))
        ada = dossier(out, "ada")
        late, early = f'../research.html#{_anchor("f-late")}', f'../research.html#{_anchor("f-early")}'
        self.assertIn(f'<a href="{early}">Changed from Unassessed to Possible, 1 Mar 2026</a>', ada)
        self.assertIn(f'<a href="{late}">Changed from Possible to Documented, 8 Sep 2026</a>', ada)
        self.assertLess(ada.index("to Possible, 1 Mar 2026"), ada.index("to Documented, 8 Sep 2026"))
        self.assertIn(f'<a href="{late}">Changed from Possible to Strongly supported, 8 Sep 2026</a>', ada)  # partner, project wording
        self.assertIn(f'<a href="{late}">Recorded as Probable, 8 Sep 2026</a>', ada)  # child
        family = ada[ada.index('id="family-heading"'):ada.index("</section>", ada.index('id="family-heading"'))]
        for words in ("Possible to Documented", "Possible to Strongly supported", "Recorded as Probable", "Unassessed to Possible, 8 Sep 2026"):
            self.assertIn(words, family)  # parent, partner, child and recorded sibling rows
        claim = ada[ada.index(f'id="{_anchor("ada-born")}"'):]
        self.assertIn("Changed from Probable to Documented, 8 Sep 2026", claim[:claim.index("</article>")])
        self.assertIn("Changed from Probable to Documented, 8 Sep 2026", (out / "research.html").read_text())
        eli = dossier(out, "eli")
        self.assertIn(f'<a href="{late}">Changed from Unassessed to Possible, 8 Sep 2026</a>', eli[eli.index('id="family-heading"'):eli.index("</section>")])
        self.assertNotIn("Changed from", dossier(out, "cara").replace("Changed from Possible to Strongly supported", ""))

    def test_findings_log_research_page_and_feed_carry_a_chip_per_change(self):
        out = self.build(case(history()))
        chip = ('<a class="badge evidence-badge badge-documented change" href="evidence.html#confidence-documented" data-after="documented" data-before="possible">'
                '<span class="badge-glyph" aria-hidden="true">✓</span>Possible → Documented</a>')
        for page in ("findings.html", "research.html"):
            text = (out / page).read_text()
            self.assertIn(chip, text)
            self.assertIn('<a class="badge evidence-badge badge-probable change" href="evidence.html#grade-strongly_supported" data-after="strongly_supported" data-before="possible">'
                          '<span class="badge-glyph" aria-hidden="true">~</span>Possible → Strongly supported</a>', text)
            self.assertIn('<a class="badge evidence-badge badge-probable change" href="evidence.html#confidence-probable" data-after="probable">'
                          '<span class="badge-glyph" aria-hidden="true">~</span>Recorded as Probable</a>', text)
            self.assertIn(f'<a href="tree.html#{_anchor("ada-parent")}">Bram Fable is a parent of Ada Fable</a> {chip} <span class="meta">Baptism entry found.</span>', text)
        feed = (out / "findings.xml").read_text()
        self.assertIn("Changed: Bram Fable is a parent of Ada Fable: Possible → Documented; Ada Fable and Cara Fable are spouses: "
                      "Possible → Strongly supported; Ada Fable is a parent of Dora Fable: Recorded as Probable;", feed)
        self.assertIn("birth: 1801: Probable → Documented.", feed)
        self.assertEqual([change("ada-parent", "unknown", "possible")],
                         next(f for f in json.loads((out / "data/site.json").read_text())["findings"] if f["id"] == "f-early")["changes"])

    def test_a_finding_that_changed_a_withheld_link_is_withheld(self):
        secret = Finding("f-secret", "SECRET-CHANGE conclusion.", related_ids=["ada"], recorded_on="2026-05-01", sensitivity=A.PUBLIC,
                         limitations="SECRET-LIMITS", changes=[change("ada-hidden", "unknown", "possible", "SECRET-NOTE")])
        out = self.build(case([*history(), secret], private_link=True))
        everything = "".join(p.read_text(errors="ignore") for p in out.rglob("*") if p.is_file())
        for sentinel in ("SECRET-CHANGE", "SECRET-LIMITS", "SECRET-NOTE", "f-secret", "ada-hidden"):
            self.assertNotIn(sentinel, everything)
        self.assertIn("Possible → Documented", everything)  # the public findings still publish
        # Public, the same link and finding publish.
        out = self.build(case([*history(), secret]))
        self.assertIn("SECRET-CHANGE", (out / "findings.html").read_text())


class CommandTests(unittest.TestCase):
    def test_finding_add_records_changes_and_can_follow_an_edited_link(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "p"
            self.assertEqual(0, main(["init", str(root), "--name", "Fictional"]))
            for kind, record in (("Person", {"id": "ada", "names": [{"value": "Ada Fable"}], "living": "deceased", "sensitivity": "public"}),
                                 ("Person", {"id": "bram", "names": [{"value": "Bram Fable"}], "living": "deceased", "sensitivity": "public"}),
                                 ("Relationship", {"id": "ada-parent", "subject_id": "ada", "object_id": "bram", "kind": "parent",
                                                   "confidence": "possible", "sensitivity": "public"})):
                path = Path(directory) / f"{record['id']}.json"
                path.write_text(json.dumps(record))
                self.assertEqual(0, main(["--project", str(root), "record", "add", kind, "--input", str(path)]))
            project = ["--project", str(root)]
            self.assertEqual(0, main([*project, "finding", "add", "f1", "Bram fits.", "--recorded-on", "2026-03-01",
                                      "--change", "ada-parent::possible"]))
            case_file = next((root / "cases").glob("*.json"))
            stored = json.loads(case_file.read_text())
            self.assertEqual([change("ada-parent", None, "possible")], stored["record_sets"]["Finding"][0]["changes"])
            with redirect_stderr(io.StringIO()) as err:
                self.assertEqual(1, main([*project, "finding", "add", "f2", "Proved.", "--recorded-on", "2026-09-08",
                                          "--change", "ada-parent:possible:documented"]))
            self.assertIn("ada-parent is now possible", err.getvalue())
            with redirect_stderr(io.StringIO()) as err:
                self.assertEqual(1, main([*project, "finding", "add", "f2", "Proved.", "--change", "ada-parent"]))
            self.assertIn("--change must be RECORD_ID:BEFORE:AFTER", err.getvalue())
            # Edit the link first; the case is then invalid until the finding records the change.
            stored["record_sets"]["Relationship"][0]["confidence"] = "documented"
            case_file.write_text(json.dumps(stored))
            with redirect_stderr(io.StringIO()):
                self.assertEqual(1, main([*project, "validate"]))
            self.assertEqual(0, main([*project, "finding", "add", "f2", "Proved.", "--recorded-on", "2026-09-08",
                                      "--change", "ada-parent:possible:documented"]))
            self.assertEqual(0, main([*project, "validate"]))


if __name__ == "__main__":
    unittest.main()
