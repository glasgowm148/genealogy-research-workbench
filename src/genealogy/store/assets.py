"""Evidence files, captures and long prose kept outside the database.

Consistency protocol between files and database rows:

1. *Prepare*: a managed file is copied into a temporary file in the managed
   asset directory, flushed to disk, hashed, and atomically renamed to its
   content address ``<sha256[:2]>/<sha256><suffix>``. A referenced (in-place)
   file is hashed where it is.
2. *Commit*: only then is the ``asset`` row written, in a short transaction.

A failure in step 2 leaves at most an unreferenced content-addressed file,
which :func:`verify_assets` reports as an orphan and which is safe to delete;
it never leaves a committed row pointing at a missing file. Original captures
are immutable: :func:`verify_assets` reports any whose bytes changed, and an
exact-file publication approval stops applying to changed bytes because it is
matched by hash.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
from pathlib import Path
import tempfile
from typing import Any

from .core import Tx, new_id
from .errors import ConstraintError
from .project import MANAGED_ROOT, Project

CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def managed_path(sha256: str, suffix: str) -> str:
    return f"{sha256[:2]}/{sha256}{suffix.lower()}"


def prepare_managed(project: Project, source: Path) -> tuple[str, str, int]:
    """Copy ``source`` into the managed store; returns (relative path, sha256, size)."""
    root = project.root(MANAGED_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    digest = hashlib.sha256()
    size = 0
    handle, temporary = tempfile.mkstemp(prefix=".incoming-", dir=root)
    try:
        with os.fdopen(handle, "wb") as out, Path(source).open("rb") as src:
            for chunk in iter(lambda: src.read(CHUNK), b""):
                digest.update(chunk)
                size += len(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        sha = digest.hexdigest()
        relative = managed_path(sha, Path(source).suffix)
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and sha256_file(target) == sha:
            os.unlink(temporary)
        else:
            os.replace(temporary, target)
            os.chmod(target, 0o400)
        if sha256_file(target) != sha:
            raise ConstraintError(f"the copied asset {target} did not verify; nothing was registered")
        return relative, sha, size
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def locate_in_root(project: Project, root: str, path: Path) -> str:
    """The path of an existing file relative to a configured asset root."""
    base = project.root(root)
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(base):
        raise ConstraintError(f"{path} is outside asset root {root!r} ({base})")
    if not resolved.is_file():
        raise ConstraintError(f"{path} is not a file")
    return resolved.relative_to(base).as_posix()


def register_asset(project: Project, tx: Tx, source: Path, *, root: str = MANAGED_ROOT, kind: str = "file",
                   access: str = "private", provenance: str | None = None, captured_on: str | None = None,
                   immutable: bool = True, asset_id: str | None = None, prepared: tuple[str, str, int] | None = None,
                   supersedes_id: str | None = None) -> dict[str, Any]:
    """Register a file. Call :func:`prepare_managed` *before* opening ``tx`` for managed files.

    Passing ``prepared`` (from :func:`prepare_managed`) keeps the copy outside
    the transaction; without it a managed copy is made here, which is still
    safe (content-addressed) but holds the transaction for the copy.
    """
    source = Path(source)
    if root == MANAGED_ROOT:
        relative, sha, size = prepared or prepare_managed(project, source)
    else:
        relative = locate_in_root(project, root, source)
        sha = sha256_file(source)
        size = source.stat().st_size
    existing = tx.store.one("SELECT * FROM asset WHERE root=? AND path=? AND sha256=?", (root, relative, sha))
    if existing:
        return existing
    media_type = mimetypes.guess_type(source.name)[0]
    return tx.insert("asset", {
        "id": asset_id or new_id("asset"), "sha256": sha, "size": size, "media_type": media_type, "root": root,
        "path": relative, "kind": kind, "immutable": 1 if immutable else 0, "original_name": source.name,
        "captured_on": captured_on, "provenance": provenance, "access": access, "supersedes_id": supersedes_id,
    })


def asset_file(project: Project, asset: dict[str, Any]) -> Path:
    return project.root(asset["root"]) / asset["path"]


def verify_assets(project: Project, *, orphans: bool = True) -> dict[str, list[dict[str, Any]]]:
    """Check every referenced file exists with its recorded hash.

    A file kept in place that was replaced by a newer registered version
    (``supersedes_id``) at the same path is reported as superseded, not
    changed, when the path now holds that successor's bytes.
    """
    missing: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    superseded: list[dict[str, Any]] = []
    known: set[Path] = set()
    successors: dict[str, list[dict[str, Any]]] = {}
    for row in project.store.all("SELECT * FROM asset WHERE supersedes_id IS NOT NULL"):
        successors.setdefault(row["supersedes_id"], []).append(row)

    def latest_hashes(asset_id: str, root: str, path: str) -> set[str]:
        found, pending = set(), [asset_id]
        while pending:
            for row in successors.get(pending.pop(), []):
                if row["root"] == root and row["path"] == path:
                    found.add(row["sha256"])
                    pending.append(row["id"])
        return found

    for asset in project.store.all("SELECT * FROM asset ORDER BY id"):
        try:
            path = asset_file(project, asset)
        except ValueError as error:
            missing.append({"id": asset["id"], "path": asset["path"], "problem": str(error)})
            continue
        known.add(path.resolve())
        if not path.is_file():
            missing.append({"id": asset["id"], "root": asset["root"], "path": asset["path"]})
        elif path.stat().st_size != asset["size"] or sha256_file(path) != asset["sha256"]:
            row = {"id": asset["id"], "root": asset["root"], "path": asset["path"],
                   "immutable": bool(asset["immutable"])}
            later = latest_hashes(asset["id"], asset["root"], asset["path"])
            (superseded if later and sha256_file(path) in later else changed).append(row)
    unreferenced: list[dict[str, Any]] = []
    managed = project.root(MANAGED_ROOT)
    if orphans and managed.is_dir():
        for path in sorted(managed.rglob("*")):
            if path.is_file() and path.resolve() not in known:
                unreferenced.append({"path": path.relative_to(managed).as_posix()})
    return {"missing": missing, "changed": changed, "superseded": superseded, "orphans": unreferenced}
