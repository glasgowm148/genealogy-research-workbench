"""Fictional regressions for real-world export variations (encodings, roles, ids)."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from genealogy.adapters import GedcomAdapter, OneTreeAdapter
from genealogy.adapters._gedcom_text import decode_ansel, decode_gedcom
from genealogy.case import CaseStore, ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.importing import import_file
from genealogy.models import Claim, Confidence, Event, Evidence, Finding, LivingStatus, Person, Relationship, Source
from genealogy.cli import main

HEADER = "0 HEAD\n1 GEDC\n2 VERS 5.5.1\n1 CHAR {charset}\n"
FAMILY = (
    "0 @I1@ INDI\n1 NAME Ãmile /Ãrvall/\n1 SEX M\n1 DEAT Y\n"
    "0 @I2@ INDI\n1 NAME Ingrid /Söderby/\n1 SEX F\n1 BURI\n2 DATE 1901\n"
    "0 @I3@ INDI\n1 NAME Olav /Ãrvall/\n1 FAMC @F1@\n2 PEDI adopted\n"
    "0 @F1@ FAM\n1 HUSB @I1@\n1 WIFE @I2@\n1 CHIL @I3@\n0 TRLR\n"
)


def people(batch):
    return {entity.id.rsplit(":", 1)[-1]: entity for entity in batch.entities if isinstance(entity, Person)}


class EncodingTests(unittest.TestCase):
    def names(self, raw: bytes) -> list[str]:
        return sorted(name.value for person in people(GedcomAdapter().ingest(raw)).values() for name in person.names)

    def test_declared_and_bom_encodings_decode_to_the_same_names(self):
        text = FAMILY.replace("Ã", "É")
        expected = ["Ingrid Söderby", "Olav Érvall", "Émile Érvall"]
        variants = {
            "utf-8": (HEADER.format(charset="UTF-8") + text).encode("utf-8"),
            "utf-8 bom": b"\xef\xbb\xbf" + (HEADER.format(charset="UTF-8") + text).encode("utf-8"),
            "utf-16 bom": (HEADER.format(charset="UNICODE") + text).encode("utf-16"),
            "utf-16le no bom": (HEADER.format(charset="UNICODE") + text).encode("utf-16-le"),
            "ansi": (HEADER.format(charset="ANSI") + text).encode("cp1252"),
            "mac": (HEADER.format(charset="MACINTOSH") + text).encode("mac_roman"),
            "crlf": (HEADER.format(charset="UTF-8") + text).replace("\n", "\r\n").encode("utf-8"),
            "cr only": (HEADER.format(charset="UTF-8") + text).replace("\n", "\r").encode("utf-8"),
        }
        for label, raw in variants.items():
            with self.subTest(label=label):
                self.assertEqual(self.names(raw), expected)

    def test_ansel_combining_marks_precede_their_base_letter(self):
        self.assertEqual(decode_ansel(b"\xe2Emile \xe8o \xf0c \xa5"), "Émile ö ç Æ")
        raw = HEADER.format(charset="ANSEL").encode() + FAMILY.replace("Ã", "\x00").encode("latin-1").replace(b"\x00", b"\xe2E").replace("ö".encode("latin-1"), b"\xe8o")
        self.assertEqual(self.names(raw), ["Ingrid Söderby", "Olav Érvall", "Émile Érvall"])

    def test_undecodable_bytes_name_the_line_instead_of_guessing(self):
        raw = (HEADER.format(charset="UTF-8") + "0 @I1@ INDI\n1 NAME A /B/\n").encode() + b"1 NOTE \xe9t\xe9\n"
        with self.assertRaisesRegex(ValueError, r"line 7 is not valid UTF-8"):
            GedcomAdapter().ingest(raw)
        with self.assertRaisesRegex(ValueError, "unsupported character set"):
            GedcomAdapter().ingest(HEADER.format(charset="KLINGON").encode() + b"0 @I1@ INDI\n")
        with self.assertRaisesRegex(ValueError, "not ANSEL"):
            decode_gedcom(HEADER.format(charset="ANSEL").encode() + b"0 @I1@ INDI\n1 NAME \x8f\n")

    def test_mislabelled_utf8_is_decoded_as_utf8_with_a_warning(self):
        text, encoding, warnings = decode_gedcom((HEADER.format(charset="ANSI") + "0 @I1@ INDI\n1 NAME Zoë\n").encode("utf-8"))
        self.assertEqual(encoding, "utf-8")
        self.assertIn("Zoë", text)
        self.assertTrue(warnings)


class StructureTests(unittest.TestCase):
    def assert_valid(self, batch):
        case = ResearchCase(id="fictional", title="Fictional")
        batch.add_to_case(case)
        self.assertEqual(validate_case(case), [])
        return case

    def test_raw_newlines_inside_notes_are_kept_and_reported(self):
        raw = ("0 HEAD\n0 @I1@ INDI\n1 NAME Ada /Quillon/\n1 NOTE First line of a long biography,\n"
               "an unencoded second line,<br>\n1851 census line in the note\n</p>\n"
               "1 BIRT\n2 DATE 1840\n0 TRLR\n")
        batch = GedcomAdapter().ingest(raw)
        person = people(batch)["I1"]
        self.assertEqual(person.notes, "First line of a long biography,\nan unencoded second line,<br>\n1851 census line in the note\n</p>")
        self.assertTrue(any(isinstance(item, Event) and item.kind == "birth" for item in batch.entities))
        self.assertTrue(any("3 GEDCOM lines" in warning for warning in batch.warnings))
        for broken in ("0 @I1@ INDI\nnot a gedcom line\n", "0 @I1@ INDI\n3 NAME Wrong\n"):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                GedcomAdapter().ingest(broken)

    def test_parent_roles_are_kept_never_flattened_to_birth_parents(self):
        raw = (
            "0 @I1@ INDI\n1 NAME Father /Fable/\n0 @I2@ INDI\n1 NAME Mother /Fable/\n"
            "0 @I3@ INDI\n1 NAME Adopted /Fable/\n1 FAMC @F1@\n2 PEDI adopted\n"
            "0 @I4@ INDI\n1 NAME Step /Fable/\n0 @I5@ INDI\n1 NAME Unstated /Fable/\n"
            "0 @I6@ INDI\n1 NAME Challenged /Fable/\n1 FAMC @F1@\n2 STAT DISPROVEN\n"
            "0 @F1@ FAM\n1 HUSB @I1@\n1 WIFE @I2@\n1 CHIL @I3@\n1 CHIL @I4@\n2 _FREL Step\n2 _MREL Natural\n1 CHIL @I5@\n1 CHIL @I6@\n"
        )
        case = self.assert_valid(GedcomAdapter().ingest(raw))
        links = {(item.subject_id[-2:], item.object_id[-2:]): item for item in case.records(Relationship) if item.kind == "parent"}
        self.assertEqual((links[("I3", "I1")].pedigree, links[("I3", "I2")].pedigree), ("adopted", "adopted"))
        self.assertEqual((links[("I4", "I1")].pedigree, links[("I4", "I2")].pedigree), ("step", "birth"))
        self.assertIsNone(links[("I5", "I1")].pedigree)
        self.assertEqual(links[("I6", "I1")].confidence, Confidence.DISPROVED)
        self.assertEqual(links[("I6", "I1")].tree_status, "disproven")

    def test_names_identifiers_sources_quality_and_death_evidence(self):
        raw = (
            "0 @S1@ SOUR\n1 TITL Invented register\n1 AUTH Imaginary Clerk\n1 PUBL Nowhere Press, 1901\n1 REPO @R1@\n2 CALN Shelf 9\n"
            "0 @R1@ REPO\n1 NAME Fictional Archive\n"
            "0 @N1@ SNOTE A shared fictional note.\n"
            "0 @I1@ INDI\n1 NAME Rev. Ada Mae /de Quillon/ Jr.\n2 GIVN Ada Mae\n2 SURN de Quillon\n2 NICK Addie\n2 _MARN Pell\n"
            "1 _UID 0A1B2C3D\n1 REFN Quillon-1\n2 TYPE WikiTree\n1 _FSFTID FICT-123\n1 EXID 99\n2 TYPE https://example.invalid/ids\n"
            "1 SNOTE @N1@\n1 BURI\n2 PLAC Invented Yard\n1 EMIG\n2 DATE 1888\n1 SSN 000-00-0000\n1 _MILT\n2 DATE 1870\n"
            "1 SOUR @S1@\n2 PAGE folio 3\n2 QUAY 3\n1 EMAIL fictional@@example.invalid\n"
        )
        batch = GedcomAdapter().ingest(raw)
        case = self.assert_valid(batch)
        person = case.records(Person)[0]
        birth = person.names[0]
        self.assertEqual((birth.value, birth.given, birth.surname), ("Rev. Ada Mae de Quillon Jr.", "Ada Mae", "de Quillon"))
        self.assertEqual({name.kind for name in person.names}, {"birth", "nickname", "married"})
        self.assertIn("Ada Mae Pell", [name.value for name in person.names])
        systems = {identifier.system: identifier.value for identifier in person.external_ids}
        self.assertEqual(systems["gedcom:refn:WikiTree"], "Quillon-1")
        self.assertEqual(systems["gedcom:familysearch"], "FICT-123")
        self.assertIn("gedcom:uid", systems)
        self.assertEqual(person.notes, "A shared fictional note.")
        self.assertEqual(person.living, LivingStatus.DECEASED)
        self.assertEqual({event.kind for event in case.records(Event)}, {"burial", "emigration"})
        source = case.records(Source)[0]
        self.assertEqual((source.author, source.publication, source.repository), ("Imaginary Clerk", "Nowhere Press, 1901", "Fictional Archive (call number Shelf 9)"))
        self.assertIn("QUAY 3 — direct and primary evidence", case.records(Evidence)[0].assessment)
        self.assertEqual(case.records(Evidence)[0].confidence, Confidence.UNKNOWN)
        unsupported = next(warning for warning in batch.warnings if warning.startswith("Unsupported GEDCOM"))
        self.assertIn("INDI.SSN×1", unsupported)
        self.assertIn("INDI._MILT×1", unsupported)
        self.assertFalse(any("000-00-0000" in json.dumps(record.to_dict()) for record in batch.entities))

    def test_gedcom7_void_pointers_are_not_reported_as_missing_people(self):
        batch = GedcomAdapter().ingest("0 HEAD\n1 GEDC\n2 VERS 7.0\n0 @I1@ INDI\n1 NAME A /Fable/\n0 @F1@ FAM\n1 HUSB @VOID@\n1 WIFE @I1@\n0 TRLR\n")
        self.assertFalse([warning for warning in batch.warnings if "missing person" in warning])


class OneTreeVariationTests(unittest.TestCase):
    def test_wikitree_dates_status_marks_spouses_and_marriages(self):
        payload = {"data": {
            "Fable-1": {"Name": "Fable-1", "Id": 1, "FirstName": "Ada", "MiddleName": "Mae", "LastNameAtBirth": "Fable", "LastNameCurrent": "Quill",
                        "LastNameOther": "Fabel", "Nicknames": "Addie", "Gender": "Female", "BirthDate": "1850-00-00", "DeathDate": "1900-03-00", "Privacy": 60,
                        "DataStatus": {"BirthDate": "before", "DeathDate": "guess"}, "Father": 3,
                        "Spouses": [{"Id": 2, "Name": "Quill-2", "marriage_date": "1872-06-00", "marriage_location": "Invented Chapel"}]},
            "Quill-2": {"Name": "Quill-2", "Id": 2, "FirstName": "Rowan", "LastNameAtBirth": "Quill", "DeathDate": "1910-00-00", "Privacy": 40,
                        "Spouses": [{"Id": 1, "Name": "Fable-1", "marriage_date": "1872-06-00", "marriage_location": "Invented Chapel"}]},
            "Fable-3": {"Name": "Fable-3", "Id": 3, "FirstName": "Elder", "LastNameAtBirth": "Fable", "DeathDate": "0000-00-00", "IsLiving": 0, "Privacy": 60},
        }}
        payload["data"]["Fable-1"]["DataStatus"]["Father"] = "5"
        batch = OneTreeAdapter().ingest(payload)
        case = ResearchCase(id="fictional", title="Fictional")
        batch.add_to_case(case)
        self.assertEqual(validate_case(case), [])
        events = {(event.kind, event.participant_ids[0][-7:]): event for event in case.records(Event)}
        self.assertEqual(events[("birth", "Fable-1")].date, "BEF 1850")
        self.assertEqual(events[("death", "Fable-1")].date, "ABT 1900-03")
        self.assertEqual(events[("marriage", "Fable-1")].date, "1872-06")
        self.assertEqual(len(events[("marriage", "Fable-1")].participant_ids), 2)
        self.assertNotIn(("death", "Fable-3"), events)
        spouses = [item for item in case.records(Relationship) if item.kind == "spouse"]
        self.assertEqual(len(spouses), 1)
        father = next(item for item in case.records(Relationship) if item.kind == "parent")
        self.assertEqual((father.pedigree, father.tree_status), ("non-biological", "non-biological"))
        ada = next(person for person in case.records(Person) if person.id.endswith("Fable-1"))
        self.assertEqual((ada.names[0].value, ada.names[0].given, ada.names[0].surname), ("Ada Mae Fable", "Ada Mae", "Fable"))
        self.assertEqual({name.kind for name in ada.names}, {"birth", "married", "alias", "nickname"})
        elder = next(person for person in case.records(Person) if person.id.endswith("Fable-3"))
        self.assertEqual(elder.living, LivingStatus.DECEASED)
        self.assertTrue(any(claim.predicate == "sex" and claim.value == "Female" for claim in case.records(Claim)))


class ReimportTests(unittest.TestCase):
    TREE = "0 @I1@ INDI\n1 NAME Ada /Fable/\n1 DEAT Y\n0 @I2@ INDI\n1 NAME Rowan /Fable/\n1 DEAT Y\n0 @F1@ FAM\n1 HUSB @I1@\n1 CHIL @I2@\n"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        self.assertEqual(main(["init", str(self.root), "--name", "Fictional"]), 0)
        self.input = Path(self.temp.name) / "tree.ged"

    def tearDown(self):
        self.temp.cleanup()

    def load(self):
        config = ProjectConfig.load(self.root / "genealogy.toml")
        return CaseStore(self.root / config.case_directory).load(config.default_case), config

    def run_import(self, text, **options):
        self.input.write_text(text, encoding="utf-8")
        case, config = self.load()
        return import_file(self.root, case, config, self.input, publish_deceased=True, **options)

    def test_update_keeps_added_research_and_backs_up_the_previous_case(self):
        self.run_import(self.TREE)
        case, config = self.load()
        case.add(Finding(id="finding-ada", conclusion="Ada's line needs a parish search", related_ids=["gedcom:person:I1"]))
        CaseStore(self.root / config.case_directory).save(case)
        with self.assertRaisesRegex(ValueError, "--update"):
            self.run_import(self.TREE + "0 @I3@ INDI\n1 NAME New /Fable/\n")
        report = self.run_import(self.TREE + "0 @I3@ INDI\n1 NAME New /Fable/\n", update=True)
        self.assertEqual(report["status"], "updated")
        updated, _ = self.load()
        self.assertEqual(len(updated.records(Person)), 3)
        self.assertEqual([item.id for item in updated.records(Finding)], ["finding-ada"])
        self.assertEqual(updated.finding_ids, ["finding-ada"])
        backup = self.root / report["backup"]
        self.assertTrue(backup.is_file())
        self.assertIn("finding-ada", backup.read_text())
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)

    def test_update_refuses_to_orphan_research_and_changes_nothing(self):
        self.run_import(self.TREE)
        case, config = self.load()
        case.add(Finding(id="finding-rowan", conclusion="Rowan research", related_ids=["gedcom:person:I2"]))
        CaseStore(self.root / config.case_directory).save(case)
        before = (self.root / "cases" / f"{config.default_case}.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "Nothing was changed"):
            self.run_import("0 @I1@ INDI\n1 NAME Ada /Fable/\n", update=True)
        self.assertEqual((self.root / "cases" / f"{config.default_case}.json").read_bytes(), before)

    def test_update_needs_an_earlier_import_and_excludes_replace(self):
        with self.assertRaisesRegex(ValueError, "earlier gedcom import"):
            self.run_import(self.TREE, update=True)
        with self.assertRaisesRegex(ValueError, "either"):
            self.run_import(self.TREE, update=True, replace=True)

    def test_replace_keeps_a_private_backup(self):
        self.run_import(self.TREE)
        report = self.run_import("0 @I9@ INDI\n1 NAME Other /Tree/\n", replace=True)
        self.assertTrue((self.root / report["backup"]).is_file())
        self.assertEqual(len(self.load()[0].records(Person)), 1)



class GedzipTests(unittest.TestCase):
    def archive(self, entries):
        import io, zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        return buffer.getvalue()

    def test_gedcom7_archive_imports_and_keeps_media_private(self):
        tree = "0 HEAD\n1 GEDC\n2 VERS 7.0\n0 @I1@ INDI\n1 NAME Ada /Fable/\n1 DEAT Y\n1 OBJE @O1@\n0 @O1@ OBJE\n1 FILE media/ada.jpg\n2 FORM image/jpeg\n0 TRLR\n"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            self.assertEqual(main(["init", str(root), "--name", "Fictional"]), 0)
            source = Path(temporary) / "family.gdz"
            source.write_bytes(self.archive({"gedcom.ged": tree, "media/ada.jpg": b"\xff\xd8not-a-real-photo"}))
            config = ProjectConfig.load(root / "genealogy.toml")
            case = CaseStore(root / config.case_directory).load(config.default_case)
            report = import_file(root, case, config, source, publish_deceased=True)
            self.assertEqual((report["format"], report["people"], report["published_people"]), ("gedzip", 1, 1))
            self.assertTrue(any("1 media file was kept only in the private copy" in w for w in report["warnings"]))
            self.assertTrue((root / "private" / "imports" / f"{report['sha256']}.gdz").is_file())
            self.assertEqual(main(["--project", str(root), "build"]), 0)
            self.assertFalse(any(path.suffix == ".jpg" for path in (root / "dist").rglob("*")))

    def test_a_missing_export_is_named_rather_than_called_too_large(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            self.assertEqual(main(["init", str(root), "--name", "Fictional"]), 0)
            config = ProjectConfig.load(root / "genealogy.toml")
            case = CaseStore(root / config.case_directory).load(config.default_case)
            with self.assertRaisesRegex(ValueError, "No export file found at .*absent.gdz"):
                import_file(root, case, config, Path(temporary) / "absent.gdz")

    def test_archives_without_one_gedcom_are_rejected(self):
        from genealogy.importing import gedzip_gedcom
        with self.assertRaisesRegex(ValueError, "gedcom.ged"):
            gedzip_gedcom(self.archive({"a.ged": "0 HEAD", "b.ged": "0 HEAD"}))
        with self.assertRaisesRegex(ValueError, "not a valid ZIP"):
            gedzip_gedcom(b"not a zip")
        data, notes = gedzip_gedcom(self.archive({"Family.GED": "0 HEAD"}))
        self.assertEqual((data, notes), (b"0 HEAD", []))


if __name__ == "__main__":
    unittest.main()
