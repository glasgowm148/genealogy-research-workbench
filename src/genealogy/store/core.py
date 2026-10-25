"""The project database connection, short write transactions and the audit trail.

Every structured change goes through :meth:`Store.write`, which opens one short
``BEGIN IMMEDIATE`` transaction, records a change set (who, with what, from
where, why) and writes an audit row beside each mutation. A failure rolls back
the mutations and their audit rows together.

Never hold a write transaction open while browsing, downloading, calling a
model or waiting for a person: prepare the change first, then write it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any
import uuid

from .errors import ConstraintError, LockedError, NotFoundError, StaleRevisionError
from .schema import SCHEMA_VERSION, TABLE_KEYS, apply_migrations, check_version, stored_version

BUSY_TIMEOUT_MS = 5000


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def connect(path: Path | str, *, readonly: bool = False) -> sqlite3.Connection:
    """Open a connection with foreign keys enforced and a bounded lock wait."""
    if readonly:
        conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True, timeout=BUSY_TIMEOUT_MS / 1000,
                               isolation_level=None)
    else:
        conn = sqlite3.connect(str(path), timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        conn.close()
        raise ConstraintError("this SQLite build cannot enforce foreign keys; the workbench refuses to use it")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    if not readonly:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = FULL")
    return conn


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return None if row is None else {key: row[key] for key in row.keys()}


class Store:
    """One project's database. Create with :func:`create_store` or :func:`open_store`."""

    def __init__(self, path: Path, conn: sqlite3.Connection, *, clock: Callable[[], str] = utc_now):
        self.path = path
        self.conn = conn
        self.clock = clock

    # ------------------------------------------------------------- reading
    def one(self, sql: str, params: tuple | Mapping = ()) -> dict[str, Any] | None:
        return row_dict(self.conn.execute(sql, params).fetchone())

    def all(self, sql: str, params: tuple | Mapping = ()) -> list[dict[str, Any]]:
        return [row_dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def get(self, table: str, row_id: str) -> dict[str, Any] | None:
        _known(table)
        return self.one(f"SELECT * FROM {table} WHERE id = ?", (row_id,))

    def require(self, table: str, row_id: str) -> dict[str, Any]:
        row = self.get(table, row_id)
        if row is None:
            raise NotFoundError(f"no {table} with id {row_id!r}")
        return row

    def entity_type(self, entity_id: str) -> str | None:
        row = self.one("SELECT type FROM entity WHERE id = ?", (entity_id,))
        return row["type"] if row else None

    def meta(self, key: str) -> str | None:
        row = self.one("SELECT value FROM schema_meta WHERE key = ?", (key,))
        return row["value"] if row else None

    # ------------------------------------------------------------- writing
    @contextmanager
    def write(self, *, actor: str, reason: str | None = None, tool: str | None = None,
              source: str | None = None, change_set_id: str | None = None) -> Iterator["Tx"]:
        """One short atomic transaction with its change set and audit rows."""
        if self.conn.in_transaction:
            raise ConstraintError("a write transaction is already open on this connection; nest operations inside it")
        try:
            self.conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as error:
            if "locked" in str(error) or "busy" in str(error):
                raise LockedError(
                    f"the project database is being written by another process (waited {BUSY_TIMEOUT_MS} ms); "
                    "retry when it has finished") from error
            raise
        tx = Tx(self, change_set_id or new_id("cs"))
        try:
            self.conn.execute(
                "INSERT INTO change_set(id, actor, tool, source, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (tx.change_set_id, actor, tool, source, reason, self.clock()))
            yield tx
            self.conn.execute("COMMIT")
        except sqlite3.IntegrityError as error:
            self.conn.execute("ROLLBACK")
            raise ConstraintError(f"rejected by a database rule, nothing was written: {error}") from error
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _known(table: str) -> None:
    if table not in TABLE_KEYS:
        raise ValueError(f"unknown table {table!r}")


class Tx:
    """Audited mutations inside one :meth:`Store.write` transaction."""

    def __init__(self, store: Store, change_set_id: str):
        self.store = store
        self.change_set_id = change_set_id
        self.conn = store.conn

    def _audit(self, table: str, row_id: str, action: str, revision: int | None,
               before: Mapping[str, Any] | None, after: Mapping[str, Any] | None) -> None:
        self.conn.execute(
            "INSERT INTO audit_log(change_set_id, table_name, row_id, action, revision, before_json, after_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (self.change_set_id, table, row_id, action, revision,
             None if before is None else _json(dict(before)), None if after is None else _json(dict(after))))

    @staticmethod
    def _row_key(table: str, values: Mapping[str, Any]) -> str:
        keys = TABLE_KEYS[table]
        return "|".join(str(values.get(key)) for key in keys)

    def insert(self, table: str, values: Mapping[str, Any]) -> dict[str, Any]:
        _known(table)
        values = {key: value for key, value in values.items() if value is not None}
        columns = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        cursor = self.conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", tuple(values.values()))
        if TABLE_KEYS[table] == ("seq",):
            values = {**values, "seq": cursor.lastrowid}
        stored = self._fetch(table, values)
        self._audit(table, self._row_key(table, stored), "insert", stored.get("revision"), None, stored)
        return stored

    def _fetch(self, table: str, values: Mapping[str, Any]) -> dict[str, Any]:
        keys = TABLE_KEYS[table]
        where = " AND ".join(f"{key} = ?" for key in keys)
        row = self.store.one(f"SELECT * FROM {table} WHERE {where}", tuple(values[key] for key in keys))
        assert row is not None
        return row

    def update(self, table: str, row_id: str, changes: Mapping[str, Any], *,
               expected_revision: int | None = None) -> dict[str, Any]:
        """Change one row, refusing if it moved on from ``expected_revision``."""
        _known(table)
        if "id" in changes or "revision" in changes:
            raise ValueError("id and revision are managed by the store")
        current = self.store.get(table, row_id)
        if current is None:
            raise NotFoundError(f"no {table} with id {row_id!r}")
        if expected_revision is not None and current.get("revision") != expected_revision:
            raise StaleRevisionError(table, row_id, expected_revision, current.get("revision"), current)
        effective = {key: value for key, value in changes.items() if current.get(key) != value}
        if not effective:
            return current
        assignments = ", ".join(f"{key} = ?" for key in effective)
        bump = ", revision = revision + 1" if "revision" in current else ""
        guard = " AND revision = ?" if "revision" in current else ""
        params = (*effective.values(), row_id, *((current["revision"],) if guard else ()))
        cursor = self.conn.execute(f"UPDATE {table} SET {assignments}{bump} WHERE id = ?{guard}", params)
        if cursor.rowcount != 1:  # pragma: no cover - guarded by BEGIN IMMEDIATE
            raise StaleRevisionError(table, row_id, current.get("revision"), None)
        after = self.store.get(table, row_id)
        self._audit(table, row_id, "update", after.get("revision"), current, after)
        return after

    def delete(self, table: str, row_id: str, *, expected_revision: int | None = None) -> None:
        _known(table)
        current = self.store.get(table, row_id)
        if current is None:
            raise NotFoundError(f"no {table} with id {row_id!r}")
        if expected_revision is not None and current.get("revision") != expected_revision:
            raise StaleRevisionError(table, row_id, expected_revision, current.get("revision"), current)
        self.conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
        self._audit(table, row_id, "delete", current.get("revision"), current, None)

    def delete_where(self, table: str, where: Mapping[str, Any]) -> int:
        _known(table)
        clause = " AND ".join(f"{key} = ?" for key in where)
        rows = self.store.all(f"SELECT * FROM {table} WHERE {clause}", tuple(where.values()))
        for row in rows:
            self._audit(table, self._row_key(table, row), "delete", row.get("revision"), row, None)
        self.conn.execute(f"DELETE FROM {table} WHERE {clause}", tuple(where.values()))
        return len(rows)

    def upsert_link(self, from_id: str, to_id: str, role: str = "related", *, sort_order: int = 0,
                    note: str | None = None) -> None:
        existing = self.store.one("SELECT * FROM link WHERE from_id=? AND to_id=? AND role=?", (from_id, to_id, role))
        if existing is None:
            self.insert("link", {"from_id": from_id, "to_id": to_id, "role": role, "sort_order": sort_order, "note": note})


# ----------------------------------------------------------------- opening

def create_store(path: Path, *, project_id: str, clock: Callable[[], str] = utc_now,
                 workbench_version: str | None = None) -> Store:
    """Create a new, empty project database at ``path``."""
    path = Path(path)
    if path.exists():
        raise ConstraintError(f"{path} already exists; open it instead of creating it")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    apply_migrations(conn, from_version=None)
    conn.execute("BEGIN IMMEDIATE")
    for key, value in (("project_id", project_id), ("created_at", clock()),
                       ("created_by_workbench", workbench_version or "unknown")):
        conn.execute("INSERT INTO schema_meta(key, value) VALUES (?, ?)", (key, value))
    conn.execute("INSERT INTO assessment_scope(id, name, description) VALUES ('project', 'Project assessment', "
                 "'The project''s current working assessments')")
    conn.execute("COMMIT")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return Store(path, conn, clock=clock)


def open_store(path: Path, *, readonly: bool = False, clock: Callable[[], str] = utc_now) -> Store:
    """Open an existing database, refusing incompatible schema versions."""
    path = Path(path)
    if not path.is_file():
        raise NotFoundError(f"no project database at {path}; run 'genealogy init' or 'genealogy db init'")
    conn = connect(path, readonly=readonly)
    try:
        check_version(stored_version(conn), path)
    except BaseException:
        conn.close()
        raise
    return Store(path, conn, clock=clock)


def migrate_store(path: Path) -> dict[str, Any]:
    """Bring an older database up to :data:`SCHEMA_VERSION`, backing it up first."""
    path = Path(path)
    conn = connect(path)
    try:
        version = stored_version(conn)
        if version is None:
            raise ConstraintError(f"{path} is not a workbench project database")
        if version > SCHEMA_VERSION:
            check_version(version, path)
        if version == SCHEMA_VERSION:
            return {"status": "current", "schema_version": version}
        backup = path.with_name(f"{path.name}.pre-v{SCHEMA_VERSION}.backup")
        if backup.exists():
            raise ConstraintError(f"{backup} already exists; move it aside before migrating again")
        backup.touch(mode=0o600)   # private like the database it copies
        target = sqlite3.connect(str(backup))
        with target:
            conn.backup(target)
        target.close()
        applied = apply_migrations(conn, from_version=version)
        return {"status": "migrated", "from": version, "to": SCHEMA_VERSION, "applied": applied, "backup": str(backup)}
    finally:
        conn.close()
