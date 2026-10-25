"""Consistent backups of a whole project, and verified restoration.

A backup directory contains:

* ``database.sqlite``: a consistent copy taken with SQLite's online backup API
  (safe while other connections read or write; copying the live file is not);
* ``package/``: the native JSON export with copies of every referenced file;
* ``project/``: ``genealogy.toml`` and the user-maintained customisation
  directories (``templates/``, ``theme/``, ``content/``, ``skills/``) and
  ``AGENTS.md`` / ``README.md`` when present;
* ``manifest.json``: workbench and schema versions, the logical digest of the
  data and the hash of every file.

Restoration writes into a new, empty directory, places the database where the
restored configuration expects it and each file under its asset root, then
checks SQLite integrity, the schema version, every file hash and the logical
digest. Database files are not compared byte for byte.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any

from .assets import sha256_file
from .core import open_store
from .errors import ConstraintError
from .native import logical_digest, verify_package, write_package
from .project import MANAGED_ROOT, Project, StorageSettings, load_config, workbench_version
from .schema import SCHEMA_VERSION

CUSTOMISATION = ("genealogy.toml", "AGENTS.md", "README.md", "templates", "theme", "content", "skills")
BACKUP_FORMAT = "genealogy-backup"
BACKUP_VERSION = 1


def _hash_tree(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha256_file(path)
            for path in sorted(root.rglob("*")) if path.is_file()}


def create_backup(project: Project, destination: Path | None = None, *, label: str | None = None,
                  created_at: str | None = None, exclude_roots: tuple[str, ...] = ()) -> dict[str, Any]:
    """Back up the database, configuration and files; ``exclude_roots`` are recorded by hash only."""
    created = created_at or project.store.clock()
    if destination is None:
        stamp = created.replace(":", "").replace("-", "")
        destination = project.directory / project.settings.backups / f"{stamp}{('-' + label) if label else ''}"
    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise ConstraintError(f"{destination} is not empty; backups never overwrite")
    destination.mkdir(parents=True, exist_ok=True)
    os.chmod(destination, 0o700)
    database = destination / "database.sqlite"
    target = sqlite3.connect(str(database))
    try:
        project.store.conn.backup(target)
    finally:
        target.close()
    os.chmod(database, 0o600)
    package = write_package(project, destination / "package", exclude_roots=exclude_roots)
    if package["missing_assets"]:
        shutil.rmtree(destination)
        raise ConstraintError(f"{len(package['missing_assets'])} referenced files are missing or changed "
                              f"(e.g. {package['missing_assets'][0]}); run 'genealogy assets verify' and resolve them "
                              "before backing up")
    customisation = destination / "project"
    customisation.mkdir()
    for name in CUSTOMISATION:
        source = project.directory / name
        if source.is_dir():
            shutil.copytree(source, customisation / name)
        elif source.is_file():
            shutil.copy2(source, customisation / name)
    manifest = {
        "format": BACKUP_FORMAT, "format_version": BACKUP_VERSION, "created_at": created,
        "workbench_version": workbench_version(), "schema_version": SCHEMA_VERSION,
        "project_id": project.store.meta("project_id"), "database_path": project.settings.database,
        "asset_roots": {name: str(path) for name, path in project.roots().items()},
        "logical_digest": logical_digest(project.store),
        "database_sha256": sha256_file(database),
        "project_files": _hash_tree(customisation),
        "asset_count": len(package["files"]),
        "referenced_only": len(package["referenced"]), "excluded_roots": sorted(exclude_roots),
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    problems = verify_backup(destination)
    if problems:
        raise ConstraintError("backup did not verify: " + "; ".join(problems[:5]))
    return {"path": str(destination), **manifest}


def verify_backup(backup: Path) -> list[str]:
    backup = Path(backup)
    problems: list[str] = []
    try:
        manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"manifest.json unreadable: {error}"]
    if manifest.get("format") != BACKUP_FORMAT or manifest.get("format_version") != BACKUP_VERSION:
        return [f"not a supported backup (format {manifest.get('format')!r} version {manifest.get('format_version')!r})"]
    database = backup / "database.sqlite"
    if not database.is_file() or sha256_file(database) != manifest["database_sha256"]:
        problems.append("database.sqlite is missing or changed")
    else:
        conn = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                problems.append("database.sqlite failed SQLite integrity_check")
            if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                problems.append("database.sqlite has broken references")
        finally:
            conn.close()
    problems.extend(f"package: {problem}" for problem in verify_package(backup / "package"))
    current = _hash_tree(backup / "project") if (backup / "project").is_dir() else {}
    if current != manifest.get("project_files"):
        problems.append("project configuration files differ from the manifest")
    return problems


def restore_backup(backup: Path, target: Path) -> dict[str, Any]:
    """Restore into a new directory and verify the result logically."""
    backup = Path(backup)
    target = Path(target)
    problems = verify_backup(backup)
    if problems:
        raise ConstraintError("backup is not restorable: " + "; ".join(problems[:5]))
    if target.exists() and any(target.iterdir()):
        raise ConstraintError(f"{target} is not empty; restore into a new directory")
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    if manifest["schema_version"] > SCHEMA_VERSION:
        raise ConstraintError(f"backup uses schema {manifest['schema_version']}; upgrade the workbench to restore it")
    target.mkdir(parents=True, exist_ok=True)
    for item in sorted((backup / "project").iterdir()):
        destination = target / item.name
        shutil.copytree(item, destination) if item.is_dir() else shutil.copy2(item, destination)
    settings = StorageSettings.from_config(load_config(target))
    database = target / settings.database
    database.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup / "database.sqlite", database)
    os.chmod(database, 0o600)
    roots: dict[str, Path] = {MANAGED_ROOT: target / settings.assets}
    relocated: dict[str, str] = {}
    for name, value in settings.asset_roots.items():
        if Path(value).is_absolute():
            roots[name] = target / "restored-external" / name
            relocated[name] = str(roots[name])
        else:
            roots[name] = target / value
    files = json.loads((backup / "package" / "manifest.json").read_text(encoding="utf-8"))["files"]
    for item in files:
        _, root, relative = item["path"].split("/", 2)
        destination = roots[root] / relative
        if destination.exists():
            if sha256_file(destination) != item["sha256"]:
                raise ConstraintError(f"restored file {destination} already exists with different content")
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup / "package" / item["path"], destination)
    referenced = json.loads((backup / "package" / "manifest.json").read_text(encoding="utf-8")).get("referenced", [])
    unverified: list[str] = []
    for item in referenced:
        candidate = roots[item["root"]] / item["path"]
        if not candidate.is_file() or sha256_file(candidate) != item["sha256"]:
            unverified.append(f"{item['root']}:{item['path']}")
    store = open_store(database)
    try:
        restored_digest = logical_digest(store)
    finally:
        store.close()
    if restored_digest != manifest["logical_digest"]:
        raise ConstraintError("restored database does not match the backup's logical digest")
    for item in files:
        _, root, relative = item["path"].split("/", 2)
        if sha256_file(roots[root] / relative) != item["sha256"]:
            raise ConstraintError(f"restored file {relative} does not match its recorded hash")
    return {"target": str(target), "database": str(database), "logical_digest": restored_digest,
            "files": len(files), "relocated_roots": relocated,
            "referenced_not_restored": unverified,
            "note": ("absolute asset roots were restored under restored-external/; update [storage.asset_roots] "
                     "to point at them") if relocated else None}
