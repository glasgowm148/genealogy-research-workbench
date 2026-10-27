"""Project database: constraints, atomicity, concurrency, identity and research semantics."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from genealogy.store import (
    ConstraintError, IncompatibleSchemaError, LockedError, NameInput, Research, StaleRevisionError, create_store,
    open_store,
)
from genealogy.store import core as store_core
from genealogy.store.assets import register_asset, verify_assets
from genealogy.store.schema import SCHEMA_VERSION
from genealogy.store.projection import public_case
from genealogy.case import validate_case

from store_fixtures import Fixture


class SchemaAndReferences(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture()
        self.r = self.fx.research

    def tearDown(self) -> None:
        self.fx.close()

    def test_foreign_keys_are_enforced_on_every_connection(self) -> None:
        conn = store_core.connect(self.fx.project.database_path)
        self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        conn.close()
        with self.assertRaisesRegex(ConstraintError, "FOREIGN KEY"):
            with self.fx.write() as tx:
                self.r.add_citation(tx, source_id="src-missing")

    def test_value_and_uniqueness_rules_reject_with_clear_errors(self) -> None:
        a = self.fx.person("Ada Harrow")
        with self.assertRaisesRegex(ConstraintError, "CHECK"):
            with self.fx.write() as tx:
                tx.insert("place", {"id": "plc-x", "name": "Nowhere", "latitude": 95.0, "longitude": 1.0})
        with self.assertRaisesRegex(ConstraintError, "relationship predicate"):
            with self.fx.write() as tx:
                self.r.relationship_claim(tx, child_id=a, relative_id=a, role="uncle")
        with self.assertRaises(ConstraintError):
            with self.fx.write() as tx:
                self.r.relationship_claim(tx, child_id=a, relative_id=a, role="father")
        with self.fx.write() as tx:
            self.r.map_external(tx, a, "wikitree", "Harrow-1")
        b = self.fx.person("Bea Harrow")
        with self.assertRaisesRegex(ConstraintError, "already identifies"):
            with self.fx.write() as tx:
                self.r.map_external(tx, b, "wikitree", "Harrow-1")
        with self.fx.write() as tx:  # a competing assignment is recorded, not forced
            self.r.map_external(tx, b, "wikitree", "Harrow-1", status="candidate")
        self.assertEqual(self.r.find_external("wikitree", "Harrow-1", statuses=("current",)), [a])

    def test_estimates_need_their_kind_and_bounds(self) -> None:
        a, b = self.fx.person("Ada Harrow"), self.fx.person("Wren Harrow")
        with self.fx.write() as tx:
            claim = self.r.relationship_claim(tx, child_id=a, relative_id=b, role="father")
        with self.assertRaisesRegex(ConstraintError, "estimate_kind"):
            with self.fx.write() as tx:
                self.r.assess(tx, claim, new=True, estimate_percent=60)
        with self.assertRaises(ConstraintError):
            with self.fx.write() as tx:
                self.r.assess(tx, claim, new=True, estimate_percent=140, estimate_kind="subjective")

    def test_identifiers_are_permanent(self) -> None:
        a = self.fx.person("Ada Harrow")
        with self.assertRaisesRegex(ConstraintError, "permanent"):
            with self.fx.write() as tx:
                tx.conn.execute("UPDATE person SET id='per-new' WHERE id=?", (a,))

    def test_incompatible_versions_fail_with_actionable_errors(self) -> None:
        path = self.fx.project.database_path
        conn = sqlite3.connect(path)
        conn.execute("UPDATE schema_meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION + 1),))
        conn.commit()
        conn.close()
        with self.assertRaisesRegex(IncompatibleSchemaError, "newer than this workbench supports"):
            open_store(path)


class Atomicity(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture()
        self.r = self.fx.research

    def tearDown(self) -> None:
        self.fx.close()

    def test_failed_operation_rolls_back_rows_audit_and_change_set(self) -> None:
        store = self.fx.project.store
        before = {t: store.one(f"SELECT count(*) n FROM {t}")["n"] for t in ("person", "audit_log", "change_set")}
        with self.assertRaises(ConstraintError):
            with self.fx.write() as tx:
                self.r.create_person(tx, names=[NameInput("Ada Harrow")])
                self.r.add_citation(tx, source_id="src-missing")
        after = {t: store.one(f"SELECT count(*) n FROM {t}")["n"] for t in ("person", "audit_log", "change_set")}
        self.assertEqual(before, after)

    def test_every_change_is_audited_with_its_change_set(self) -> None:
        a = self.fx.person("Ada Harrow")
        with self.fx.write(actor="agent:reviewer", reason="correct the label") as tx:
            tx.update("person", a, {"label": "Ada of Fennick"}, expected_revision=1)
        audit = self.fx.project.store.all("SELECT a.*, c.actor, c.reason FROM audit_log a JOIN change_set c ON "
                                          "c.id=a.change_set_id WHERE row_id=? AND action='update'", (a,))
        self.assertEqual(audit[0]["actor"], "agent:reviewer")
        self.assertEqual(json.loads(audit[0]["before_json"])["label"], None)
        self.assertEqual(json.loads(audit[0]["after_json"])["label"], "Ada of Fennick")

    def test_interrupted_file_registration_leaves_no_broken_reference(self) -> None:
        evidence = self.fx.root / "will.txt"
        evidence.write_text("Invented will text", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            with self.fx.write() as tx:
                register_asset(self.fx.project, tx, evidence, kind="capture")
                raise RuntimeError("power cut before commit")
        self.assertEqual(self.fx.project.store.one("SELECT count(*) n FROM asset")["n"], 0)
        report = verify_assets(self.fx.project)
        self.assertEqual(report["missing"], [])
        self.assertEqual(len(report["orphans"]), 1)  # an unreferenced content-addressed copy, safe to delete

    def test_changed_capture_is_detected(self) -> None:
        evidence = self.fx.directory / "evidence" / "census.txt"
        evidence.parent.mkdir()
        evidence.write_text("original bytes", encoding="utf-8")
        self.fx.project.settings.asset_roots["evidence"] = "evidence"
        with self.fx.write() as tx:
            register_asset(self.fx.project, tx, evidence, root="evidence", kind="capture")
        evidence.write_text("edited bytes", encoding="utf-8")
        self.assertEqual(len(verify_assets(self.fx.project)["changed"]), 1)

    def test_a_file_kept_in_place_and_registered_again_is_superseded_not_changed(self) -> None:
        evidence = self.fx.directory / "evidence" / "gazetteer.json"
        evidence.parent.mkdir()
        evidence.write_text("first version", encoding="utf-8")
        self.fx.project.settings.asset_roots["evidence"] = "evidence"
        with self.fx.write() as tx:
            first = register_asset(self.fx.project, tx, evidence, root="evidence")
        evidence.write_text("second version", encoding="utf-8")
        with self.fx.write() as tx:
            second = register_asset(self.fx.project, tx, evidence, root="evidence", supersedes_id=first["id"])
        evidence.write_text("third version", encoding="utf-8")
        with self.fx.write() as tx:
            register_asset(self.fx.project, tx, evidence, root="evidence", supersedes_id=second["id"])
        report = verify_assets(self.fx.project)
        self.assertEqual((report["changed"], len(report["superseded"])), ([], 2))
        evidence.write_text("an unregistered edit", encoding="utf-8")
        report = verify_assets(self.fx.project)
        self.assertEqual((len(report["changed"]), report["superseded"]), (3, []))


    def test_reintroduced_content_and_later_versions_require_registration(self) -> None:
        evidence = self.fx.directory / "evidence" / "gazetteer.json"
        evidence.parent.mkdir()
        self.fx.project.settings.asset_roots["evidence"] = "evidence"
        store = self.fx.project.store

        def register(text, previous=None):
            evidence.write_text(text, encoding="utf-8")
            with self.fx.write() as tx:
                return register_asset(self.fx.project, tx, evidence, root="evidence", supersedes_id=previous)

        first = register("first")
        second = register("second", first["id"])
        self.assertEqual(second["id"], register("second", second["id"])["id"])
        self.assertEqual([], store.all("SELECT * FROM note WHERE kind='asset_registration'"))
        self.assertEqual(first["id"], register("first", second["id"])["id"])
        self.assertEqual(2, store.one("SELECT count(*) n FROM asset")["n"])
        self.assertEqual([], verify_assets(self.fx.project)["changed"])
        self.assertEqual(first["id"], register("first", second["id"])["id"])
        notes = store.all("SELECT * FROM note WHERE kind='asset_registration'")
        self.assertEqual(1, len(notes))
        self.assertEqual("private", notes[0]["access"])
        # The caller still uses B as the terminal content-chain head.
        third = register("third", second["id"])
        self.assertEqual([], verify_assets(self.fx.project)["changed"])
        # Unregistered historical bytes must fail, even for the matching row.
        for text in ("first", "second", "unregistered"):
            evidence.write_text(text, encoding="utf-8")
            self.assertEqual(3, len(verify_assets(self.fx.project)["changed"]))
        register("second", third["id"])
        self.assertEqual([], verify_assets(self.fx.project)["changed"])
        register("first", third["id"])
        self.assertEqual([], verify_assets(self.fx.project)["changed"])
        self.assertEqual(3, store.one("SELECT count(*) n FROM asset")["n"])

    def test_interrupted_reintroduction_rolls_back_registration(self) -> None:
        evidence = self.fx.directory / "evidence" / "gazetteer.json"
        evidence.parent.mkdir()
        self.fx.project.settings.asset_roots["evidence"] = "evidence"
        evidence.write_text("first", encoding="utf-8")
        with self.fx.write() as tx:
            first = register_asset(self.fx.project, tx, evidence, root="evidence")
        evidence.write_text("second", encoding="utf-8")
        with self.fx.write() as tx:
            second = register_asset(self.fx.project, tx, evidence, root="evidence", supersedes_id=first["id"])
        evidence.write_text("first", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            with self.fx.write() as tx:
                register_asset(self.fx.project, tx, evidence, root="evidence", supersedes_id=second["id"])
                raise RuntimeError("interrupted")
        self.assertEqual([], self.fx.project.store.all("SELECT * FROM note WHERE kind='asset_registration'"))
        self.assertTrue(verify_assets(self.fx.project)["changed"])
        evidence.write_text("second", encoding="utf-8")
        self.assertEqual([], verify_assets(self.fx.project)["changed"])


class Concurrency(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture()
        self.r = self.fx.research
        self.a, self.b = self.fx.person("Ada Harrow"), self.fx.person("Wren Harrow")
        with self.fx.write() as tx:
            self.claim = self.r.relationship_claim(tx, child_id=self.a, relative_id=self.b, role="father")
            self.r.assess(tx, self.claim, new=True, status="possible", reasoning="first reading")

    def tearDown(self) -> None:
        self.fx.close()

    def test_two_agents_cannot_silently_overwrite_each_other(self) -> None:
        other = Research(open_store(self.fx.project.database_path))
        seen = self.r.current_assessment(self.claim)["current_revision"]
        with self.fx.write(actor="agent-one") as tx:
            self.r.assess(tx, self.claim, expected_revision=seen, status="probable", reasoning="agent one")
        with self.assertRaises(StaleRevisionError) as caught:
            with other.store.write(actor="agent-two") as tx:
                other.assess(tx, self.claim, expected_revision=seen, status="disproved", reasoning="agent two")
        self.assertEqual(caught.exception.actual, 2)
        self.assertEqual(caught.exception.current["reasoning"], "agent one")
        self.assertEqual(self.r.current_assessment(self.claim)["status"], "probable")
        other.store.close()

    def test_unstated_expectation_is_refused_for_an_existing_assessment(self) -> None:
        with self.assertRaises(StaleRevisionError):
            with self.fx.write() as tx:
                self.r.assess(tx, self.claim, status="documented")

    def test_lock_contention_is_reported_clearly(self) -> None:
        with mock.patch.object(store_core, "BUSY_TIMEOUT_MS", 50):
            blocker = store_core.connect(self.fx.project.database_path)
            waiting = store_core.Store(self.fx.project.database_path, store_core.connect(self.fx.project.database_path))
        blocker.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaisesRegex(LockedError, "another process"):
                with waiting.write(actor="late"):
                    pass
        finally:
            blocker.execute("ROLLBACK")
            blocker.close()
            waiting.close()


class ResearchSemantics(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture()
        self.r = self.fx.research

    def tearDown(self) -> None:
        self.fx.close()

    def test_reassessment_keeps_history_and_both_views_derive_from_it(self) -> None:
        """The fictional analogue of the 95%/44% regression."""
        child, father = self.fx.person("Isaac Harrow"), self.fx.person("Wren Harrow")
        with self.fx.write() as tx:
            claim = self.r.relationship_claim(tx, child_id=child, relative_id=father, role="father")
            self.r.assess(tx, claim, new=True, status="possible", estimate_percent=44, estimate_kind="subjective",
                          assessed_on="2026-10-22")
        with self.fx.write() as tx:
            self.r.assess(tx, claim, expected_revision=1, status="proved", estimate_percent=95,
                          estimate_kind="subjective", assessed_on="2026-10-23")
        self.assertEqual([h["estimate_percent"] for h in self.r.assessment_history(claim)], [44, 95])
        forward = self.r.relationship_views(child)[0]
        reverse = self.r.relationship_views(father)[0]
        self.assertEqual((forward["role"], reverse["role"]), ("father", "child"))
        self.assertEqual(forward["assessment"]["estimate_percent"], 95)
        self.assertEqual(reverse["assessment"]["estimate_percent"], 95)
        self.assertEqual(forward["claim_id"], reverse["claim_id"])

    def test_competing_fathers_stay_competing_and_wife_is_not_mother(self) -> None:
        child = self.fx.person("Isaac Harrow")
        wren, caleb, sarah = self.fx.person("Wren Harrow"), self.fx.person("Caleb Harrow"), self.fx.person("Sarah Harrow")
        with self.fx.write() as tx:
            first = self.r.relationship_claim(tx, child_id=child, relative_id=wren, role="father")
            second = self.r.relationship_claim(tx, child_id=child, relative_id=caleb, role="father")
            self.r.relationship_claim(tx, child_id=sarah, relative_id=wren, role="spouse")
            self.r.assess(tx, first, new=True, status="probable", estimate_percent=60, estimate_kind="subjective")
            self.r.assess(tx, second, new=True, status="possible", estimate_percent=30, estimate_kind="subjective")
        roles = {(v["relative_id"], v["role"]) for v in self.r.relationship_views(child)}
        self.assertEqual(roles, {(wren, "father"), (caleb, "father")})
        self.assertFalse(any(v["role"] == "mother" for v in self.r.relationship_views(child)))

    def test_record_mentions_survive_without_identification(self) -> None:
        with self.fx.write() as tx:
            source = self.r.register_source(tx, title="Invented will book")
            record = self.r.add_record(tx, title="Will of Wren Harrow", source_id=source, date_original="14 Oct 1805")
            testator = self.r.add_mention(tx, record_id=record, role="testator", name_as_written="Wren Harrow")
            isaac = self.r.add_mention(tx, record_id=record, role="son", name_as_written="Isaac")
            self.r.add_documentary_relation(tx, record_id=record, from_mention_id=isaac, to_mention_id=testator,
                                            relation="son", wording="my son Isaac")
            robert = self.r.create_person(tx, label="Fennick Robert", record_defined=True,
                                          names=[NameInput("Robert Harrow", kind="reading")])
        one, two = self.fx.person("Isaac Harrow"), self.fx.person("Isaac Harrow")
        with self.fx.write() as tx:
            a = self.r.identity_claim(tx, mention_id=isaac, person_id=one)
            b = self.r.identity_claim(tx, mention_id=isaac, person_id=two)
            self.r.assess(tx, a, new=True, status="preferred")
            self.r.assess(tx, b, new=True, status="compatible alternative")
        store = self.fx.project.store
        candidates = store.all("SELECT object_person_id FROM claim WHERE kind='identity' AND subject_mention_id=?", (isaac,))
        self.assertEqual({row["object_person_id"] for row in candidates}, {one, two})
        self.assertEqual(store.get("person", robert)["record_defined"], 1)
        self.assertIsNone(store.one("SELECT 1 FROM claim WHERE subject_mention_id=? AND kind='relationship'", (testator,)))

    def test_dependencies_flag_review_without_inventing_confidence(self) -> None:
        child, father = self.fx.person("Isaac Harrow"), self.fx.person("Wren Harrow")
        with self.fx.write() as tx:
            source = self.r.register_source(tx, title="Invented deed")
            record = self.r.add_record(tx, title="Deed", source_id=source)
            reading = self.r.add_transcription(tx, record_id=record, text="...to Isaac his son...")
            mention = self.r.add_mention(tx, record_id=record, name_as_written="Isaac")
            identity = self.r.identity_claim(tx, mention_id=mention, person_id=child)
            parentage = self.r.relationship_claim(tx, child_id=child, relative_id=father, role="father")
            self.r.assess(tx, parentage, new=True, status="probable", estimate_percent=70, estimate_kind="subjective")
            self.r.add_dependency(tx, dependent_id=identity, premise_id=reading)
            self.r.add_dependency(tx, dependent_id=parentage, premise_id=identity)
        with self.fx.write() as tx:
            self.r.withdraw_transcription(tx, reading, expected_revision=1, reason="re-read: names Israel, not Isaac")
        flagged = self.r.review_queue()
        self.assertEqual([row["dependent_id"] for row in flagged], [identity])
        self.assertEqual(self.r.current_assessment(parentage)["estimate_percent"], 70)
        with self.fx.write() as tx:
            self.r.assess(tx, identity, new=True, status="doubtful")
        self.assertIn(parentage, [row["dependent_id"] for row in self.r.review_queue()])
        self.assertEqual(self.r.current_assessment(parentage)["estimate_percent"], 70)

    def test_negative_searches_questions_and_withdrawn_findings_keep_meaning(self) -> None:
        person = self.fx.person("Ada Harrow")
        with self.fx.write() as tx:
            search = self.r.log_search(tx, scope="Invented parish burials 1860-1875", result="nothing found",
                                       outcome="negative", limitation="index only", links=[person])
            question = self.r.add_question(tx, question="Who were Ada's parents?", resume_condition="when the 1841 "
                                           "returns are indexed", links=[person])
            finding = self.r.add_finding(tx, statement="Ada was baptised in 1801", status="reviewed", links=[person])
        with self.fx.write() as tx:
            self.r.withdraw_finding(tx, finding, reason="the entry is for another Ada", expected_revision=1)
        store = self.fx.project.store
        self.assertEqual(store.get("search", search)["outcome"], "negative")
        self.assertEqual(store.get("question", question)["status"], "open")
        withdrawn = store.get("finding", finding)
        self.assertEqual((withdrawn["status"], withdrawn["status_original"]), ("withdrawn", "reviewed"))

    def test_merge_is_recorded_and_reversible(self) -> None:
        a, b = self.fx.person("Ada Harrow"), self.fx.person("Ada Harrow")
        with self.fx.write() as tx:
            self.r.map_external(tx, b, "wikitree", "Harrow-9")
            merge = self.r.merge_people(tx, survivor_id=a, retired_id=b, reason="same baptism")
        self.assertEqual(self.r.find_external("wikitree", "Harrow-9", statuses=("former",)), [a])
        with self.fx.write() as tx:
            self.r.undo_merge(tx, merge, reason="separate burials found")
        self.assertEqual(self.r.find_external("wikitree", "Harrow-9", statuses=("current",)), [b])

    def test_projection_hides_retired_merge_row_and_undo_restores_it(self) -> None:
        survivor, retired = self.fx.person("Glasgow 3654"), self.fx.person("Glasgow 3654")
        with self.fx.write() as tx:
            self.r.map_external(tx, survivor, "wikitree", "Glasgow-2454")
            self.r.map_external(tx, survivor, "wikitree", "Glasgow-3654", status="redirect",
                                redirect_to="Glasgow-2454")
            self.r.map_external(tx, retired, "wikitree", "Glasgow-3654")
            merge = self.r.merge_people(tx, survivor_id=survivor, retired_id=retired, reason="documented duplicate")
        projected, _ = public_case(self.fx.project, everything=True)
        survivor_projection = next(p for p in projected.records("Person") if p.id == survivor)
        self.assertEqual(survivor_projection.former_ids.count("Glasgow-3654"), 1)
        self.assertEqual([p.id for p in projected.records("Person")].count(survivor), 1)
        self.assertNotIn(retired, [p.id for p in projected.records("Person")])
        self.assertEqual([], validate_case(projected))
        with self.fx.write() as tx:
            self.r.undo_merge(tx, merge, reason="separate identity found")
        restored, _ = public_case(self.fx.project, everything=True)
        self.assertIn(retired, [p.id for p in restored.records("Person")])

    def test_merge_where_the_survivor_already_holds_the_id_as_a_redirect(self) -> None:
        a, b = self.fx.person("Isobel Harrow"), self.fx.person("Isobel Harrow")
        with self.fx.write() as tx:
            self.r.map_external(tx, a, "wikitree", "Harrow-2")
            self.r.map_external(tx, a, "wikitree", "Harrow-7", status="redirect")
            self.r.map_external(tx, b, "wikitree", "Harrow-7")
            merge = self.r.merge_people(tx, survivor_id=a, retired_id=b, reason="the tree merged them")
        self.assertEqual(self.r.find_external("wikitree", "Harrow-7", statuses=("current",)), [])
        self.assertEqual(self.r.find_external("wikitree", "Harrow-7", statuses=("redirect",)), [a])
        with self.fx.write() as tx:
            self.r.undo_merge(tx, merge, reason="test")
        self.assertEqual(self.r.find_external("wikitree", "Harrow-7", statuses=("current",)), [b])


class Packaging(unittest.TestCase):
    def test_migrations_are_packaged_and_create_a_current_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = create_store(Path(directory) / "x.sqlite", project_id="x")
            self.assertEqual(int(store.meta("schema_version")), SCHEMA_VERSION)
            store.close()


if __name__ == "__main__":
    unittest.main()
