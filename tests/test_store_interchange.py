"""Native round trip, backup/restore, imports, GEDCOM, publication, builds and WikiTree comparison."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import unittest

from genealogy.adapters import resolve_adapter
from genealogy.cli import main
from genealogy.store import open_project
from genealogy.store.assets import prepare_managed, register_asset
from genealogy.store.backup import create_backup, restore_backup, verify_backup
from genealogy.store.build import LeakError, build_from_database, tree_digest
from genealogy.store.gedcom_export import export_gedcom
from genealogy.store.native import dumps, export_document, import_document, logical_digest
from genealogy.store.operations import import_genealogy_file, upgrade_cases
from genealogy.store.projection import public_case
from genealogy.store import proposals
from genealogy.store.wikitree_sync import compare, verify_applied

from store_fixtures import GEDCOM_7, Fixture


def research_project(fx: Fixture) -> dict[str, str]:
    """A small but complete fictional research picture."""
    r = fx.research
    ids: dict[str, str] = {}
    ids["wren"] = fx.person("Wren Harrow", sex="male", birth="1801")
    ids["sarah"] = fx.person("Sarah Harrow", sex="female", birth="1805")
    ids["isaac"] = fx.person("Isaac Harrow", sex="male", birth="1830")
    ids["caleb"] = fx.person("Caleb Harrow", sex="male", birth="1799")
    ids["living"] = fx.person("Nova Harrow", living="living", birth="1990")
    ids["private"] = fx.person("Hidden Quillfeather", access="private", birth="1802")
    with fx.write() as tx:
        source = r.register_source(tx, title="Invented will book", access="public", originality="original")
        record = r.add_record(tx, title="Will of Wren Harrow", source_id=source, access="public",
                              summary="Names wife Sarah and son Isaac.")
        citation = r.add_citation(tx, source_id=source, record_id=record, locator="pp. 279-280", access="public")
        r.add_transcription(tx, record_id=record, text="I give to my son Isaac...", access="public")
        father = r.relationship_claim(tx, child_id=ids["isaac"], relative_id=ids["wren"], role="father", access="public")
        rival = r.relationship_claim(tx, child_id=ids["isaac"], relative_id=ids["caleb"], role="father", access="public")
        r.relationship_claim(tx, child_id=ids["sarah"], relative_id=ids["wren"], role="spouse", access="public")
        r.add_evidence(tx, claim_id=father, citation_id=citation, interpretation="The will names Isaac as son.")
        r.assess(tx, father, new=True, status="possible", estimate_percent=44, estimate_kind="subjective")
        r.assess(tx, rival, new=True, status="possible", estimate_percent=20, estimate_kind="subjective")
        hidden = r.relationship_claim(tx, child_id=ids["isaac"], relative_id=ids["private"], role="mother", access="public")
        r.assess(tx, hidden, new=True, status="possible")
        r.add_finding(tx, statement="The will names Isaac as Wren's son.", recorded_on="2026-10-23", status="current",
                      access="public", links=[ids["isaac"], ids["wren"], (citation, "citation")])
        r.add_finding(tx, statement="Hidden Quillfeather witnessed the will.", access="public", links=[ids["private"]])
        r.log_search(tx, scope="Invented burials 1860-1875", result="nothing found", outcome="negative",
                     access="public", links=[ids["isaac"]])
        r.add_question(tx, question="Which Isaac does the will mean?", access="public", links=[ids["isaac"]])
    with fx.write() as tx:
        r.assess(tx, father, expected_revision=1, status="proved", estimate_percent=95, estimate_kind="subjective")
    ids.update(father=father, rival=rival, citation=citation, record=record, source=source)
    return ids


class NativeAndBackup(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture()
        self.ids = research_project(self.fx)
        prose = self.fx.root / "brief.md"
        prose.write_text("# Research brief\n\nInvented prose about the Harrow will.\n", encoding="utf-8")
        prepared = prepare_managed(self.fx.project, prose)
        with self.fx.write() as tx:
            asset = register_asset(self.fx.project, tx, prose, kind="prose", prepared=prepared)
            self.fx.research.add_note(tx, asset_id=asset["id"], kind="brief", links=[self.ids["isaac"]])

    def tearDown(self) -> None:
        self.fx.close()

    def test_native_export_is_deterministic_and_round_trips(self) -> None:
        first = dumps(export_document(self.fx.project.store))
        self.assertEqual(first, dumps(export_document(self.fx.project.store)))
        restored = import_document(json.loads(first), self.fx.root / "copy.sqlite")
        self.assertEqual(dumps(export_document(restored)), first)
        self.assertEqual(logical_digest(restored), logical_digest(self.fx.project.store))
        document = json.loads(first)
        self.assertTrue(document["tables"]["assessment_revision"])
        self.assertTrue(document["tables"]["audit_log"])
        restored.close()

    def test_backup_restores_into_a_fresh_location_with_files(self) -> None:
        backup = create_backup(self.fx.project, self.fx.root / "backup")
        self.assertEqual(verify_backup(Path(backup["path"])), [])
        report = restore_backup(Path(backup["path"]), self.fx.root / "restored")
        restored = open_project(self.fx.root / "restored")
        self.assertEqual(logical_digest(restored.store), logical_digest(self.fx.project.store))
        asset = restored.store.one("SELECT * FROM asset WHERE kind='prose'")
        self.assertIn("Invented prose", (restored.root("managed") / asset["path"]).read_text(encoding="utf-8"))
        self.assertEqual(report["files"], 1)
        restored.close()

    def test_tampered_backup_is_refused(self) -> None:
        backup = Path(create_backup(self.fx.project, self.fx.root / "backup")["path"])
        target = next((backup / "package" / "files").rglob("*.md"))
        target.chmod(0o600)
        target.write_text("changed", encoding="utf-8")
        self.assertTrue(verify_backup(backup))
        with self.assertRaises(ValueError):
            restore_backup(backup, self.fx.root / "restored")


class PublicationAndBuild(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture()
        self.ids = research_project(self.fx)

    def tearDown(self) -> None:
        self.fx.close()

    def _all_text(self, root: Path) -> str:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace") + path.as_posix()
                         for path in root.rglob("*") if path.is_file())

    def test_private_material_is_absent_from_every_public_file(self) -> None:
        out = self.fx.root / "site"
        report = build_from_database(self.fx.project, out, build_date="2026-10-25")
        text = self._all_text(out)
        for leaked in ("Nova Harrow", "Hidden Quillfeather", self.ids["living"], self.ids["private"],
                       "witnessed the will"):
            self.assertNotIn(leaked, text)
        self.assertIn("Isaac Harrow", text)
        self.assertGreater(report["omission_count"], 0)
        self.assertFalse(list(out.rglob("*.sqlite")))

    def test_build_refuses_a_leak_and_keeps_the_previous_site(self) -> None:
        out = self.fx.root / "site"
        build_from_database(self.fx.project, out, build_date="2026-10-25")
        before = tree_digest(out)
        with self.fx.write() as tx:
            self.fx.research.add_finding(tx, statement="Isaac lodged with Hidden Quillfeather in 1851.",
                                         access="public", links=[self.ids["isaac"]])
        with self.assertRaises(LeakError):
            build_from_database(self.fx.project, out, build_date="2026-10-25")
        self.assertEqual(tree_digest(out), before)

    def test_builds_are_reproducible_and_need_no_previous_output(self) -> None:
        one, two = self.fx.root / "one", self.fx.root / "two"
        build_from_database(self.fx.project, two, build_date="2026-10-25")
        (two / "stale.html").write_text("left over from an old build", encoding="utf-8")
        build_from_database(self.fx.project, one, build_date="2026-10-25")
        build_from_database(self.fx.project, two, build_date="2026-10-25")
        self.assertFalse((two / "stale.html").exists())
        self.assertEqual(tree_digest(one), tree_digest(two))

    def test_build_never_replaces_a_directory_it_did_not_make(self) -> None:
        other = self.fx.root / "releases"
        other.mkdir()
        (other / "site-2026.tar.gz").write_bytes(b"not a site")
        with self.assertRaisesRegex(ValueError, "not made by a workbench build"):
            build_from_database(self.fx.project, other, build_date="2026-10-25")
        self.assertTrue((other / "site-2026.tar.gz").is_file())

    def test_exact_file_approvals_follow_the_bytes(self) -> None:
        crop = self.fx.directory / "evidence" / "will-crop.jpg"
        crop.parent.mkdir()
        crop.write_bytes(b"\xff\xd8 invented crop")
        full = self.fx.directory / "evidence" / "will-full-scan.jpg"
        full.write_bytes(b"\xff\xd8 invented full scan")
        self.fx.project.settings.asset_roots["evidence"] = "evidence"
        from genealogy.store.assets import sha256_file
        with self.fx.write() as tx:
            register_asset(self.fx.project, tx, crop, root="evidence", kind="image")
            register_asset(self.fx.project, tx, full, root="evidence", kind="image")
            self.fx.research.add_approval(tx, kind="exact_file", target="images/will-crop.jpg",
                                          sha256=sha256_file(crop), authority="Owner, in writing, 2026-10-25")
        out = self.fx.root / "site"
        build_from_database(self.fx.project, out, build_date="2026-10-25")
        self.assertTrue((out / "images" / "will-crop.jpg").is_file())
        self.assertFalse(any("full-scan" in p.name for p in out.rglob("*")))
        crop.write_bytes(b"\xff\xd8 re-cropped, different bytes")
        build_from_database(self.fx.project, out, build_date="2026-10-25")
        self.assertFalse((out / "images" / "will-crop.jpg").exists())

    def test_current_estimate_is_published_once_for_both_directions(self) -> None:
        case, _ = public_case(self.fx.project, build_year=2026)
        links = [r for r in case.records("Relationship") if r.id == self.ids["father"]]
        self.assertEqual([r.estimate for r in links], [95])
        self.assertFalse(any(r.object_id == self.ids["private"] for r in case.records("Relationship")))


class Imports(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture()
        self.ged = self.fx.root / "harrow.ged"
        self.ged.write_text(GEDCOM_7, encoding="utf-8")

    def tearDown(self) -> None:
        self.fx.close()

    def test_import_is_idempotent_and_refresh_matches_by_uid(self) -> None:
        first = import_genealogy_file(self.fx.project, self.ged, publish_deceased=True)
        self.assertEqual(first["status"], "imported")
        people = self.fx.project.store.one("SELECT count(*) n FROM person")["n"]
        self.assertEqual(import_genealogy_file(self.fx.project, self.ged, publish_deceased=True)["status"], "unchanged")
        renamed = self.fx.root / "harrow-2027.ged"
        renamed.write_text(GEDCOM_7.replace("@I3@", "@I30@").replace("2 DATE 1830", "2 DATE 1831"), encoding="utf-8")
        second = import_genealogy_file(self.fx.project, renamed, publish_deceased=True, lineage=first["lineage"])
        self.assertEqual(self.fx.project.store.one("SELECT count(*) n FROM person")["n"], people)
        self.assertEqual(self.fx.project.store.one("SELECT count(*) n FROM import_batch")["n"], 2)
        self.assertEqual(self.fx.project.store.one("SELECT count(*) n FROM asset WHERE kind='original_import'")["n"], 2)
        self.assertEqual(second["status"], "imported")

    def test_onetree_profiles_are_mapped_as_wikitree_ids(self) -> None:
        tree = self.fx.root / "tree.json"
        tree.write_text(json.dumps({"data": {"Fable-1": {"Name": "Fable-1", "FirstName": "Ada", "LastNameAtBirth": "Fable",
                                                          "BirthDate": "1800-01-01", "DeathDate": "1870-01-01",
                                                          "Privacy": 60}}}), encoding="utf-8")
        import_genealogy_file(self.fx.project, tree, format="one-tree")
        found = self.fx.research.find_external("wikitree", "Fable-1", statuses=("current",))
        self.assertEqual(len(found), 1)
        with self.fx.write() as tx:  # research naming the same profile reuses the person
            self.assertEqual(self.fx.research.find_external("wikitree", "Fable-1"), found)
            del tx

    def test_unknown_gedcom_structures_are_kept_verbatim(self) -> None:
        import_genealogy_file(self.fx.project, self.ged)
        rows = self.fx.project.store.all("SELECT fields_json FROM external_observation")
        self.assertTrue(any("_UNKNOWNTAG kept verbatim" in row["fields_json"] for row in rows))

    def test_legacy_cases_upgrade_into_shared_entities(self) -> None:
        cases = self.fx.directory / "cases"
        cases.mkdir()
        person = {"id": "person:ada", "names": [{"value": "Ada Harrow"}], "living": "deceased", "sensitivity": "public"}
        for name, extra in (("one", []), ("two", [{"id": "q:1", "question": "Who was Ada's father?",
                                                    "related_ids": ["person:ada"]}])):
            (cases / f"{name}.json").write_text(json.dumps({
                "schema_version": 1, "id": name, "title": name, "question_ids": [q["id"] for q in extra],
                "record_sets": {"Person": [person], "ResearchQuestion": extra}}), encoding="utf-8")
        (cases / "three.json").write_text(json.dumps({
            "schema_version": 1, "id": "three", "title": "three",
            "record_sets": {"Person": [{**person, "notes": "a different copy"}]}}), encoding="utf-8")
        report = upgrade_cases(self.fx.project)
        store = self.fx.project.store
        self.assertEqual(store.one("SELECT count(*) n FROM person")["n"], 1)
        self.assertEqual(len(report["conflicts"]), 1)
        self.assertEqual(store.one("SELECT count(*) n FROM legacy_item WHERE disposition='conflict'")["n"], 1)
        self.assertEqual(upgrade_cases(self.fx.project)["unchanged"], ["cases/one.json", "cases/three.json", "cases/two.json"])
        self.assertTrue((cases / "one.json").is_file())


class Gedcom(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture()
        self.ids = research_project(self.fx)

    def tearDown(self) -> None:
        self.fx.close()

    def test_gedcom_7_exports_competing_fathers_without_an_invented_couple(self) -> None:
        text, report = export_gedcom(self.fx.project.store, version="7.0", export_date="2026-10-25")
        self.assertIn("2 VERS 7.0", text)
        self.assertIn("2 TAG _GRWB_ASSESS", text)
        isaac = text.split(" INDI\n")
        record = next(chunk for chunk in isaac if "NAME Isaac /Harrow/" in chunk)
        self.assertEqual(record.count("1 FAMC"), 3)  # two candidate fathers and the separately assessed mother
        self.assertIn("proved; subjective estimate 95%", record)
        self.assertNotIn("QUAY", text)
        self.assertIn("1 UID ", text)
        self.assertGreater(report["omitted_or_simplified"]["findings (not in GEDCOM)"], 0)
        batch = resolve_adapter("gedcom").ingest(text)
        self.assertEqual(sum(type(e).__name__ == "Person" for e in batch.entities), 6)

    def test_gedcom_551_compatibility_and_public_filtering(self) -> None:
        case, _ = public_case(self.fx.project, build_year=2026)
        allowed = {r.id for records in case.record_sets.values() for r in records}
        text, _ = export_gedcom(self.fx.project.store, version="5.5.1", allowed=allowed)
        self.assertIn("2 VERS 5.5.1", text)
        self.assertIn("1 CHAR UTF-8", text)
        self.assertIn("0 @U1@ SUBM", text)
        self.assertNotIn("Quillfeather", text)
        self.assertNotIn("Nova", text)
        batch = resolve_adapter("gedcom").ingest(text)
        self.assertEqual(sum(type(e).__name__ == "Person" for e in batch.entities), 4)


class WikiTreeThreeWay(unittest.TestCase):
    base = {"FirstName": "Isaac", "BirthDate": "1786-00-00", "Father": "Harrow-7", "Bio": "Old bio"}

    def test_remote_local_conflict_and_redirect(self) -> None:
        local = {**self.base, "BirthDate": "1786-03-02", "Bio": "New sourced bio"}
        remote = {**self.base, "FirstName": "Isaac J.", "Bio": "Someone else's edit", "Name": "Harrow-12"}
        result = compare("Harrow-12", self.base, local, remote)
        states = {item.field: item.state for item in result.fields}
        self.assertEqual(states["BirthDate"], "local")
        self.assertEqual(states["FirstName"], "remote")
        self.assertEqual(states["Bio"], "conflict")
        self.assertEqual(result.proposal(), {"BirthDate": "1786-03-02"})
        self.assertEqual(result.merged()["FirstName"], "Isaac J.")
        moved = compare("Harrow-12", self.base, local, {**remote, "Name": "Harrow-99"})
        self.assertEqual(moved.redirect_to, "Harrow-99")
        self.assertTrue(compare("Harrow-12", self.base, local, None).remote_missing)

    def test_remote_deletion_is_preserved_and_verification_is_separate(self) -> None:
        remote = {key: value for key, value in self.base.items() if key != "Father"}
        result = compare("Harrow-12", self.base, dict(self.base), remote)
        self.assertEqual({i.field: i.state for i in result.fields}["Father"], "remote")
        self.assertTrue(any("removed on WikiTree" in note for note in result.notes))
        self.assertTrue(verify_applied({"BirthDate": "1786-03-02"}, {"BirthDate": "1786-03-02"})["verified"])


class Proposals(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture()
        self.ids = research_project(self.fx)

    def tearDown(self) -> None:
        self.fx.close()

    def test_stale_proposal_fails_whole_and_fresh_one_applies(self) -> None:
        document = {"format": "genealogy-change-proposal", "format_version": 1, "title": "Reassess rival",
                    "operations": [{"op": "assess", "claim": self.ids["rival"], "expected_revision": 1,
                                    "set": {"status": "unlikely", "reasoning": "dates conflict"}},
                                   {"op": "add_question", "set": {"question": "Is Caleb too old?"}}]}
        self.assertEqual(proposals.check(self.fx.project.store, document), [])
        with self.fx.write() as tx:
            self.fx.research.assess(tx, self.ids["rival"], expected_revision=1, status="possible", reasoning="other agent")
        with self.assertRaises(proposals.StaleProposalError):
            proposals.apply(self.fx.project.store, document, actor="agent")
        self.assertIsNone(self.fx.project.store.one("SELECT 1 FROM question WHERE question='Is Caleb too old?'"))
        document["operations"][0]["expected_revision"] = 2
        result = proposals.apply(self.fx.project.store, document, actor="agent", approved_by="owner")
        events = self.fx.project.store.all("SELECT to_status FROM proposal_event WHERE proposal_id=? ORDER BY seq",
                                           (result["proposal"],))
        self.assertEqual([e["to_status"] for e in events], ["proposed", "approved", "applied"])


class CommandLine(unittest.TestCase):
    def test_new_project_workflow(self) -> None:
        fx = Fixture()
        try:
            ged = fx.root / "harrow.ged"
            ged.write_text(GEDCOM_7, encoding="utf-8")
            project = str(fx.directory)
            self.assertEqual(main(["--project", project, "import", str(ged), "--publish-deceased"]), 0)
            self.assertEqual(main(["--project", project, "validate"]), 0)
            self.assertEqual(main(["--project", project, "build", "--output", str(fx.root / "site")]), 0)
            self.assertTrue((fx.root / "site" / "index.html").is_file())
            self.assertEqual(main(["--project", project, "native", "export", str(fx.root / "n.json")]), 0)
            self.assertEqual(main(["--project", project, "gedcom", "export", str(fx.root / "out.ged")]), 0)
            self.assertEqual(main(["--project", project, "backup", "create", str(fx.root / "bk")]), 0)
            self.assertEqual(main(["backup", "restore", str(fx.root / "bk"), str(fx.root / "restored")]), 0)
            shutil.rmtree(fx.root / "restored")
        finally:
            fx.close()


if __name__ == "__main__":
    unittest.main()
