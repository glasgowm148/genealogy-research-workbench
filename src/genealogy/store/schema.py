"""Versioned SQLite schema: migrations, version checks and table metadata."""

from __future__ import annotations

from importlib.resources import files
import sqlite3

from .errors import IncompatibleSchemaError

#: The schema this workbench writes. Raise it with a new numbered migration.
SCHEMA_VERSION = 2

#: Ordered migrations: (version reached, SQL resource name).
MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, "0001_initial.sql"),
    (2, "0002_legacy_resolution.sql"),
)

#: Tables whose rows are addressable entities, registered in ``entity``.
ENTITY_TABLES: tuple[str, ...] = (
    "person", "place", "repository", "source", "source_holding", "source_copy", "record", "citation",
    "transcription", "mention", "documentary_relation", "event", "claim", "claim_evidence", "assessment",
    "finding", "question", "search", "hypothesis", "study", "research_group", "note", "haplogroup",
    "dna_observation", "asset", "approval", "external_observation", "proposal", "dependency",
)

#: Every table, in an order that satisfies foreign keys for restoration, with
#: the columns that identify a row. Native exports follow this order.
TABLE_KEYS: dict[str, tuple[str, ...]] = {
    "schema_meta": ("key",),
    "change_set": ("id",),
    "entity": ("id",),
    "asset": ("id",),
    "repository": ("id",),
    "place": ("id",),
    "person": ("id",),
    "person_name": ("id",),
    "external_id": ("id",),
    "route_alias": ("path",),
    "source": ("id",),
    "source_holding": ("id",),
    "source_copy": ("id",),
    "record": ("id",),
    "citation": ("id",),
    "transcription": ("id",),
    "transcription_revision": ("transcription_id", "revision"),
    "mention": ("id",),
    "documentary_relation": ("id",),
    "event": ("id",),
    "event_participant": ("event_id", "person_id", "role"),
    "claim": ("id",),
    "claim_evidence": ("id",),
    "assessment_scope": ("id",),
    "assessment": ("id",),
    "assessment_revision": ("assessment_id", "revision"),
    "dependency": ("id",),
    "finding": ("id",),
    "question": ("id",),
    "search": ("id",),
    "hypothesis": ("id",),
    "study": ("id",),
    "research_group": ("id",),
    "note": ("id",),
    "link": ("from_id", "to_id", "role"),
    "haplogroup": ("id",),
    "dna_observation": ("id",),
    "approval": ("id",),
    "import_batch": ("id",),
    "external_observation": ("id",),
    "remote_baseline": ("system", "external_value"),
    "proposal": ("id",),
    "proposal_event": ("seq",),
    "import_origin": ("entity_id", "import_batch_id", "input_path", "pointer"),
    "legacy_item": ("id",),
    "entity_merge": ("id",),
    "audit_log": ("seq",),
}


def _entity_triggers(table: str) -> str:
    return f"""
CREATE TRIGGER {table}_entity_insert BEFORE INSERT ON {table}
BEGIN
  INSERT INTO entity(id, type) VALUES (NEW.id, '{table}');
END;
CREATE TRIGGER {table}_entity_delete AFTER DELETE ON {table}
BEGIN
  DELETE FROM entity WHERE id = OLD.id;
END;
CREATE TRIGGER {table}_id_fixed BEFORE UPDATE OF id ON {table}
BEGIN
  SELECT RAISE(ABORT, 'identifiers are permanent; use a supported merge or split');
END;
"""


def migration_sql(name: str) -> str:
    sql = files("genealogy.store.migrations").joinpath(name).read_text(encoding="utf-8")
    if name == "0001_initial.sql":
        sql += "".join(_entity_triggers(table) for table in ENTITY_TABLES)
    return sql


def stored_version(conn: sqlite3.Connection) -> int | None:
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'").fetchone()
    if not exists:
        return None
    row = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
    if row is None:
        raise IncompatibleSchemaError("database has a schema_meta table without a schema_version; it is not a workbench project database")
    try:
        return int(row[0])
    except ValueError as error:
        raise IncompatibleSchemaError(f"unreadable schema_version {row[0]!r}") from error


def check_version(version: int | None, path: object) -> None:
    if version is None:
        raise IncompatibleSchemaError(f"{path} is not a workbench project database (no schema version); run 'genealogy init' or 'genealogy db init'")
    if version > SCHEMA_VERSION:
        raise IncompatibleSchemaError(
            f"{path} uses database schema version {version}, newer than this workbench supports ({SCHEMA_VERSION}). "
            "Upgrade genealogy-research-workbench; do not edit the database with an older version."
        )
    if version < SCHEMA_VERSION:
        raise IncompatibleSchemaError(
            f"{path} uses database schema version {version}; this workbench uses {SCHEMA_VERSION}. "
            "Run 'genealogy db migrate' (it backs the database up first)."
        )


def apply_migrations(conn: sqlite3.Connection, *, from_version: int | None,
                     to_version: int | None = None) -> list[int]:
    """Apply pending migrations (up to ``to_version``) in one transaction each; returns versions reached."""
    applied: list[int] = []
    start = from_version or 0
    for version, name in MIGRATIONS:
        if version <= start or (to_version is not None and version > to_version):
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            # executescript() would commit part-way; run statements one by one.
            for statement in _statements(migration_sql(name)):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(version),))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        applied.append(version)
    return applied


def _statements(sql: str) -> list[str]:
    """Split a migration into complete statements (triggers included)."""
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        stripped = line.strip()
        if not buffer and (not stripped or stripped.startswith("--")):
            continue
        buffer += line
        if sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        raise ValueError("migration ends with an incomplete statement")
    return statements
