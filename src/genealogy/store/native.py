"""The complete, versioned native JSON interchange of a project database.

``genealogy-native`` format version 1 contains every table (research,
revisions, dependencies, workflow, approvals, provenance, change sets and the
audit trail), rows ordered by their keys, so two exports of the same database
are byte-identical and diff readably. It is an *export*: the database stays the
authority. Re-importing creates a new database; it never merges into one.

A *package* is a directory holding ``native.json``, a ``manifest.json`` of
SHA-256 hashes and, optionally, ``files/<root>/<path>`` copies of every asset,
so evidence and prose travel with the structured data.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from .core import Store, connect
from .errors import ConstraintError, IncompatibleSchemaError
from .schema import SCHEMA_VERSION, TABLE_KEYS, apply_migrations

FORMAT = "genealogy-native"
FORMAT_VERSION = 1
#: Rows maintained by triggers, verified rather than imported.
DERIVED_TABLES = ("entity",)


def table_rows(store: Store, table: str) -> list[dict[str, Any]]:
    order = ", ".join(TABLE_KEYS[table])
    return store.all(f"SELECT * FROM {table} ORDER BY {order}")


def export_document(store: Store, *, exported_at: str | None = None) -> dict[str, Any]:
    tables = {table: table_rows(store, table) for table in TABLE_KEYS if table not in DERIVED_TABLES}
    document: dict[str, Any] = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "schema_version": int(store.meta("schema_version")),
        "project_id": store.meta("project_id"),
        "tables": tables,
    }
    if exported_at:
        document["exported_at"] = exported_at
    return document


def dumps(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def logical_digest(store: Store) -> str:
    """A hash of the logical content, independent of SQLite file layout."""
    return hashlib.sha256(dumps(export_document(store)).encode("utf-8")).hexdigest()


def check_document(document: Any) -> None:
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise IncompatibleSchemaError("not a genealogy-native export (format field missing or different)")
    version = document.get("format_version")
    if version != FORMAT_VERSION:
        raise IncompatibleSchemaError(
            f"native export format version {version!r} is not supported by this workbench (supports {FORMAT_VERSION}); "
            "use the workbench version that wrote it, or a newer one")
    schema = document.get("schema_version")
    if not isinstance(schema, int) or schema > SCHEMA_VERSION:
        raise IncompatibleSchemaError(
            f"native export was written with database schema {schema!r}; this workbench supports up to {SCHEMA_VERSION}. "
            "Upgrade the workbench before importing it.")
    if schema < 1:
        raise IncompatibleSchemaError(f"native export schema {schema} is not a workbench schema")
    unknown = set(document.get("tables", {})) - set(TABLE_KEYS)
    if unknown:
        raise IncompatibleSchemaError(f"native export has unknown tables: {', '.join(sorted(unknown))}")


def import_document(document: dict[str, Any], target: Path) -> Store:
    """Create a new database at ``target`` holding exactly the exported rows."""
    check_document(document)
    target = Path(target)
    if target.exists():
        raise ConstraintError(f"{target} already exists; native import creates a new database only")
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(target)
    schema = document["schema_version"]
    try:
        # An export from an older schema is loaded into that schema, then migrated forward.
        apply_migrations(conn, from_version=None, to_version=schema)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("PRAGMA defer_foreign_keys = ON")
        conn.execute("DELETE FROM schema_meta WHERE key <> 'schema_version'")
        tables = document["tables"]
        for table in TABLE_KEYS:
            if table in DERIVED_TABLES:
                continue
            for row in tables.get(table, []):
                if table == "schema_meta" and row["key"] == "schema_version":
                    continue
                columns = ", ".join(row)
                marks = ", ".join("?" for _ in row)
                conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", tuple(row.values()))
        problems = conn.execute("PRAGMA foreign_key_check").fetchall()
        if problems:
            raise ConstraintError(f"native export has {len(problems)} broken references, e.g. {tuple(problems[0])}")
        conn.execute("COMMIT")
        apply_migrations(conn, from_version=schema)
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        conn.close()
        target.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(f"{target}{suffix}").unlink(missing_ok=True)
        raise
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return Store(target, conn)


# ------------------------------------------------------------------ packages

def write_package(project: Any, destination: Path, *, include_files: bool = True,
                  exclude_roots: tuple[str, ...] = (), exported_at: str | None = None) -> dict[str, Any]:
    """Write a restorable package: native.json, copied files and a hash manifest.

    Files under ``exclude_roots`` (for example a root that is itself a Git
    checkout preserved elsewhere) are not copied; their hashes are listed as
    ``referenced`` so a restoration can verify them where they are provided.
    """
    from .assets import asset_file, sha256_file
    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise ConstraintError(f"{destination} is not empty; choose a new directory")
    destination.mkdir(parents=True, exist_ok=True)
    try:
        destination.chmod(0o700)
    except OSError:
        pass
    document = export_document(project.store, exported_at=exported_at)
    text = dumps(document)
    (destination / "native.json").write_text(text, encoding="utf-8")
    files: list[dict[str, Any]] = []
    referenced: list[dict[str, Any]] = []
    missing: list[str] = []
    if include_files:
        for asset in document["tables"]["asset"]:
            if asset["root"] in exclude_roots:
                referenced.append({"asset_id": asset["id"], "root": asset["root"], "path": asset["path"],
                                   "sha256": asset["sha256"]})
                continue
            source = asset_file(project, asset)
            relative = Path("files") / asset["root"] / asset["path"]
            if not source.is_file() or sha256_file(source) != asset["sha256"]:
                missing.append(asset["id"])
                continue
            target = destination / relative
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            files.append({"asset_id": asset["id"], "path": relative.as_posix(), "sha256": asset["sha256"]})
    manifest = {
        "format": f"{FORMAT}-package", "format_version": FORMAT_VERSION, "schema_version": SCHEMA_VERSION,
        "native_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "files": files,
        "referenced": referenced, "excluded_roots": sorted(exclude_roots),
        "missing_assets": missing, "files_included": include_files,
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def verify_package(package: Path) -> list[str]:
    from .assets import sha256_file
    package = Path(package)
    problems: list[str] = []
    try:
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"manifest.json unreadable: {error}"]
    native = package / "native.json"
    if not native.is_file() or hashlib.sha256(native.read_bytes()).hexdigest() != manifest.get("native_sha256"):
        problems.append("native.json is missing or does not match the manifest hash")
    for item in manifest.get("files", []):
        path = package / item["path"]
        if not path.is_file():
            problems.append(f"missing file {item['path']}")
        elif sha256_file(path) != item["sha256"]:
            problems.append(f"changed file {item['path']}")
    for asset_id in manifest.get("missing_assets", []):
        problems.append(f"asset {asset_id} was missing or changed when the package was written")
    return problems
