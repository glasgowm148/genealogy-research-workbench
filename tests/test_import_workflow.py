"""Fictional imports through the end-user workflow."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest

from genealogy.cli import initialize_project, load_case, main
from genealogy.exports import project_for_public_export
from genealogy.importing import import_file

GEDCOM = '''0 HEAD
1 CHAR UTF-8
0 @I1@ INDI
1 NAME Invented /Ancestor/
1 BIRT
2 DATE 1 JAN 1800
2 PLAC Imaginary Harbour
1 DEAT Y
1 NOTE PRIVATE UNSOURCED SECRET
0 @I2@ INDI
1 NAME Protected /Living/
1 BIRT
2 DATE 2000
0 @I3@ INDI
1 NAME Restricted /Ancestor/
1 RESN privacy
1 DEAT Y
0 @F1@ FAM
1 HUSB @I1@
1 WIFE @I3@
1 CHIL @I2@
0 TRLR
'''


class ImportWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        initialize_project(self.project, 'Invented "Family"')
        self.source = self.root / "input.ged"
        self.source.write_text(GEDCOM)

    def tearDown(self):
        self.temporary.cleanup()

    def run_import(self, **kwargs):
        case, config = load_case(self.project)
        return import_file(self.project, case, config, self.source, **kwargs)

    def test_empty_named_project_and_private_default_preserve_original(self):
        case, config = load_case(self.project)
        self.assertEqual('Invented "Family"', config.name)
        self.assertEqual([], case.records("Person"))
        report = self.run_import()
        case, config = load_case(self.project)
        self.assertEqual(3, report["people"])
        self.assertFalse(project_for_public_export(case, config)["people"])
        preserved = list((self.project / "private" / "imports").glob("*.ged"))
        self.assertEqual(GEDCOM, preserved[0].read_text())
        self.assertEqual(0o600, preserved[0].stat().st_mode & 0o777)
        self.assertEqual(GEDCOM, self.source.read_text())

    def test_opt_in_reveals_only_reviewed_historical_facts_and_retains_notes_privately(self):
        self.run_import(publish_deceased=True)
        case, config = load_case(self.project)
        public = project_for_public_export(case, config)
        self.assertEqual(1, len(public["people"]))
        text = json.dumps(public)
        self.assertIn("Invented Ancestor", text)
        self.assertNotIn("PRIVATE UNSOURCED SECRET", text)
        self.assertNotIn("Restricted Ancestor", text)
        self.assertNotIn("Protected Living", text)
        self.assertIn("PRIVATE UNSOURCED SECRET", json.dumps(case.to_dict()))
        self.assertTrue(public["events"])
        self.assertFalse(public["sources"])

    def test_idempotence_refusal_and_invalid_replacement_are_atomic(self):
        self.run_import()
        casepath = self.project / "cases" / "research-case.json"
        before = casepath.read_bytes()
        self.assertEqual("unchanged", self.run_import()["status"])
        self.assertEqual(before, casepath.read_bytes())
        self.source.write_text("invalid gedcom")
        with self.assertRaisesRegex(ValueError, "not empty"):
            self.run_import()
        with self.assertRaisesRegex(ValueError, "invalid GEDCOM|no people"):
            self.run_import(replace=True)
        self.assertEqual(before, casepath.read_bytes())

    def test_onetree_provider_public_still_requires_opt_in(self):
        self.source = self.root / "tree.json"
        self.source.write_text(json.dumps({"data": {"Fiction-1": {
            "Name": "Fiction-1", "FirstName": "Invented", "LastNameAtBirth": "Example",
            "BirthDate": "1800-01-01", "DeathDate": "1880-01-01", "Privacy": 60,
        }}}))
        self.run_import()
        case, config = load_case(self.project)
        self.assertEqual([], project_for_public_export(case, config)["people"])
        self.run_import(replace=True, publish_deceased=True)
        case, config = load_case(self.project)
        self.assertEqual(1, len(project_for_public_export(case, config)["people"]))

    def test_historical_birth_qualifies_but_explicit_living_and_private_never_do(self):
        self.source = self.root / "tree.json"
        self.source.write_text(json.dumps([
            {"id": "past", "name": "Invented historical", "birth_date": "1800", "living": None},
            {"id": "living", "name": "Invented living", "birth_date": "1800", "living": True},
            {"id": "private", "name": "Invented private", "birth_date": "1800", "living": False,
             "sensitivity": "private"},
            {"id": "licensed", "name": "Invented licensed", "birth_date": "1800", "living": False,
             "sensitivity": "licensed"},
        ]))
        self.run_import(publish_deceased=True)
        case, config = load_case(self.project)
        people = project_for_public_export(case, config)["people"]
        self.assertEqual(1, len(people))
        self.assertEqual("Invented historical", people[0]["names"][0]["value"])

    def test_separate_source_review_publishes_bibliography_and_assertion_only(self):
        self.source.write_text("""0 HEAD
0 @I1@ INDI
1 NAME Invented /Historical/
1 DEAT Y
1 BIRT
2 DATE 1800
2 SOUR @S1@
3 PAGE Reviewed page 12
3 TEXT PRIVATE QUOTATION
0 @I2@ INDI
1 NAME Invented /Living/
1 BIRT
2 DATE 2000
2 SOUR @S2@
0 @S1@ SOUR
1 TITL Reviewed invented register
1 REPO Invented archive
0 @S2@ SOUR
1 TITL LIVING ONLY SOURCE TITLE
0 TRLR
""")
        with self.assertRaisesRegex(ValueError, "requires"):
            self.run_import(publish_reviewed_sources=True)
        self.run_import(publish_deceased=True)
        case, config = load_case(self.project)
        self.assertFalse(project_for_public_export(case, config)["sources"])
        self.run_import(replace=True, publish_deceased=True, publish_reviewed_sources=True)
        case, config = load_case(self.project)
        public = project_for_public_export(case, config)
        self.assertEqual(1, len(public["sources"]))
        self.assertEqual(1, len(public["citations"]))
        self.assertEqual("Reviewed page 12", public["citations"][0]["locator"])
        self.assertEqual("asserted", public["claims"][0]["status"])
        self.assertEqual("unknown", public["claims"][0]["confidence"])
        self.assertNotIn("PRIVATE QUOTATION", json.dumps(public))
        self.assertNotIn("LIVING ONLY SOURCE TITLE", json.dumps(public))
        self.assertIn("PRIVATE QUOTATION", json.dumps(case.to_dict()))

    def test_textual_historical_births_publish_without_changing_supplied_dates(self):
        historical = ("1 JAN 1800", "JAN 1800", "JAN1800", "1800", "1800-01-01",
                      "BEF 1 JAN 1800", "BET 1790 AND 1800", "FROM JAN 1790 TO DEC 1800")
        protected = ("1 JAN 2000", "JAN2000", "0000", "0000-00-00", "unknown", "about 1800 maybe",
                     "31 FEB 1800", "1800-99-99", "born in 1800", "AFT 1800", "FROM 1800",
                     "ABT 1800", "BET 1800 AND 2000", "BET 1900 AND 1800", "BEF unknown")
        for number, supplied in enumerate(historical + protected):
            with self.subTest(date=supplied):
                self.source.write_text(f"0 HEAD\n0 @I1@ INDI\n1 NAME Invented /Historical/\n1 BIRT\n2 DATE {supplied}\n0 TRLR\n")
                self.run_import(replace=True, publish_deceased=True)
                case, config = load_case(self.project)
                public = project_for_public_export(case, config)
                self.assertEqual(int(supplied in historical), len(public["people"]))
                self.assertEqual(supplied, case.records("Event")[0].date)

    def test_cli_formats_and_validation_fail_gracefully(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(0, main(["--project", str(self.project), "import", str(self.source)]))
        self.assertEqual(3, len(load_case(self.project)[0].records("Person")))
