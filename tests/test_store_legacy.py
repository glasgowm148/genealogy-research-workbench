"""Schema version 2: items kept for review are resolved, never altered or deleted."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from genealogy.cli import main
from genealogy.store import ConstraintError, StaleRevisionError, migrate_store, open_store
from genealogy.store import core as store_core
from genealogy.store.native import export_document, import_document
from genealogy.store.operations import status
from genealogy.store.schema import SCHEMA_VERSION, apply_migrations

from store_fixtures import Fixture


def version_one_database(path: Path) -> None:
    """A database as workbench 0.9 wrote it, holding one item kept for review."""
    conn = store_core.connect(path)
    apply_migrations(conn, from_version=None, to_version=1)
    with conn:
        conn.execute("INSERT INTO schema_meta(key, value) VALUES ('project_id', 'old')")
        conn.execute("INSERT INTO legacy_item(id, input_path, pointer, disposition, reason, payload_json) "
                     "VALUES ('leg-1', 'research/old.json', '/claims/0', 'conflict', 'two values differ', '{}')")
    conn.close()


def add_item(fx: Fixture, item_id: str, input_path: str, disposition: str = "conflict") -> None:
    with fx.write() as tx:
        tx.insert("legacy_item", {"id": item_id, "input_path": input_path, "pointer": "", "disposition": disposition,
                                  "reason": "kept for review", "payload_json": "{}"})


class Migration(unittest.TestCase):
    def test_a_version_one_database_migrates_with_a_backup_and_keeps_its_items(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.sqlite"
            version_one_database(path)
            result = migrate_store(path)
            self.assertEqual((result["from"], result["to"]), (1, SCHEMA_VERSION))
            self.assertTrue(Path(result["backup"]).is_file())
            store = open_store(path)
            item = store.require("legacy_item", "leg-1")
            self.assertEqual((item["revision"], item["resolution"], item["reason"]), (1, None, "two values differ"))
            store.close()
            backup = store_core.connect(Path(result["backup"]))
            self.assertEqual(backup.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0], "1")
            backup.close()

    def test_a_native_export_from_version_one_imports_and_is_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory) / "old.sqlite"
            version_one_database(old)
            conn = store_core.connect(old)
            document = export_document(store_core.Store(old, conn))
            conn.close()
            self.assertEqual(document["schema_version"], 1)
            store = import_document(json.loads(json.dumps(document)), Path(directory) / "new.sqlite")
            self.assertEqual(int(store.meta("schema_version")), SCHEMA_VERSION)
            self.assertIsNone(store.require("legacy_item", "leg-1")["resolution"])
            store.close()


class Resolution(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture()
        self.r = self.fx.research
        add_item(self.fx, "leg-a", "research/a.json")
        add_item(self.fx, "leg-b", "research/sub/b.json", "unsupported")
        add_item(self.fx, "leg-c", "research_other/c.json")

    def tearDown(self) -> None:
        self.fx.close()

    def test_resolving_records_the_decision_and_leaves_the_item_as_recorded(self) -> None:
        before = self.fx.project.store.require("legacy_item", "leg-a")
        with self.fx.write(actor="reviewer") as tx:
            self.r.resolve_legacy_item(tx, "leg-a", resolution="older export; superseded", expected_revision=1,
                                       resolved_by="reviewer")
        after = self.fx.project.store.require("legacy_item", "leg-a")
        self.assertEqual(after["resolution"], "older export; superseded")
        self.assertEqual((after["revision"], after["resolved_by"]), (2, "reviewer"))
        self.assertEqual({k: after[k] for k in ("reason", "payload_json", "disposition")},
                         {k: before[k] for k in ("reason", "payload_json", "disposition")})
        audit = self.fx.project.store.one("SELECT action FROM audit_log WHERE table_name='legacy_item' "
                                          "AND row_id='leg-a' ORDER BY seq DESC LIMIT 1")
        self.assertEqual(audit["action"], "update")
        self.assertEqual(status(self.fx.project)["legacy_items_open"], 2)

    def test_stale_empty_and_repeated_resolutions_are_refused(self) -> None:
        with self.assertRaises(StaleRevisionError):
            with self.fx.write() as tx:
                self.r.resolve_legacy_item(tx, "leg-a", resolution="x", expected_revision=5)
        with self.assertRaisesRegex(ConstraintError, "what was decided"):
            with self.fx.write() as tx:
                self.r.resolve_legacy_item(tx, "leg-a", resolution="  ", expected_revision=1)
        with self.fx.write() as tx:
            self.r.resolve_legacy_item(tx, "leg-a", resolution="done", expected_revision=1)
        with self.assertRaisesRegex(ConstraintError, "already resolved"):
            with self.fx.write() as tx:
                self.r.resolve_legacy_item(tx, "leg-a", resolution="again", expected_revision=2)

    def test_listing_filters_by_state_disposition_and_input_folder(self) -> None:
        with self.fx.write() as tx:
            self.r.resolve_legacy_item(tx, "leg-a", resolution="done", expected_revision=1)
        self.assertEqual([i["id"] for i in self.r.legacy_items()], ["leg-b", "leg-c"])
        self.assertEqual([i["id"] for i in self.r.legacy_items(open_only=False, input_prefix="research")],
                         ["leg-a", "leg-b"])
        self.assertEqual([i["id"] for i in self.r.legacy_items(disposition="unsupported")], ["leg-b"])

    def test_the_cli_resolves_one_item_or_a_file_of_decisions_in_one_transaction(self) -> None:
        project = str(self.fx.directory)
        self.fx.project.close()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--project", project, "legacy", "resolve", "leg-a", "--resolution", "superseded",
                                   "--expected-revision", "1", "--actor", "reviewer"]), 0)
        decisions = self.fx.root / "decisions.json"
        decisions.write_text(json.dumps([{"id": "leg-b", "expected_revision": 1, "resolution": "held elsewhere"},
                                         {"id": "leg-c", "expected_revision": 9, "resolution": "stale"}]))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertNotEqual(main(["--project", project, "legacy", "resolve", "--from", str(decisions)]), 0)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["--project", project, "legacy", "list"]), 0)
        self.assertEqual([i["id"] for i in json.loads(out.getvalue())], ["leg-b", "leg-c"])
        self.fx.project = open_store_project(self.fx.directory)


def open_store_project(directory: Path):
    from genealogy.store import open_project
    return open_project(directory)


if __name__ == "__main__":
    unittest.main()
