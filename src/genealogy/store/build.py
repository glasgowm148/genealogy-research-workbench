"""Reproducible static website builds from the project database.

``build_from_database`` renders into a fresh staging directory beside the
output, from declared inputs only: one database snapshot (read in a single
read transaction), ``genealogy.toml``, the approval rows and the approved
files. It never reads earlier output, fetches data or writes research. The
staging tree is scanned for anything the projection withheld (ids, external
ids, names, file names and hashes); only a clean build replaces the previous
output, which is kept until the new one is in place.
"""

from __future__ import annotations

from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any

from .errors import StoreError
from .project import Project
from .projection import public_case

TEXT_SUFFIXES = {".html", ".json", ".js", ".css", ".xml", ".txt", ".csv", ".ndjson", ".geojson", ".ged", ".svg",
                 ".atom", ".md", ".webmanifest", ""}
SITE_MANIFEST = ".genealogy-site-manifest.json"
PRIVATE_SUFFIXES = {".sqlite", ".sqlite3", ".db", ".sqlite-wal", ".sqlite-shm"}


class LeakError(StoreError):
    def __init__(self, findings: list[dict[str, str]], staging: Path):
        self.findings = findings
        self.staging = staging
        sample = "; ".join(f"{item['file']}: {item['term']}" for item in findings[:5])
        super().__init__(f"the built site would publish {len(findings)} withheld items ({sample}). The previous site "
                         f"was left in place; inspect {staging} and change the research's access or wording.")


WORD = re.compile(r"[\w'.-]+")


def leak_scan(root: Path, terms: set[str], files: set[str] = frozenset()) -> list[dict[str, str]]:
    """Find withheld terms as whole tokens in every output file (and withheld file names).

    Terms are indexed by their first word, so each file costs one pass over its
    own words rather than one search per term.
    """
    by_first: dict[str, list[tuple[str, list[str]]]] = {}
    for term in terms:
        words = WORD.findall(term)
        if term and len(term) >= 4 and words and any(character.isalpha() for character in term):
            by_first.setdefault(words[0], []).append((term, words))
    findings: list[dict[str, str]] = []

    def scan(text: str, where: str) -> None:
        tokens = WORD.findall(text)
        present = set(tokens)
        for token in present & by_first.keys():
            for term, words in by_first[token]:
                if len(words) == 1 or (all(word in present for word in words)
                                       and re.search(r"(?<![\w.-])" + re.escape(term) + r"(?![\w-])", text)):
                    findings.append({"file": where, "term": term})
                    return

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if files and hashlib.sha256(path.read_bytes()).hexdigest() in files:
            findings.append({"file": relative, "term": "the bytes of a withheld file"})
        if path.suffix.lower() in PRIVATE_SUFFIXES:
            findings.append({"file": relative, "term": "database file"})
            continue
        scan(relative.replace("/", " "), relative)
        if path.suffix.lower() in TEXT_SUFFIXES:
            scan(path.read_text(encoding="utf-8", errors="replace"), relative)
    return findings


def build_from_database(project: Project, output: Path | None = None, *, build_date: str | None = None,
                        report_path: Path | None = None) -> dict[str, Any]:
    from ..cli import build_project  # the shared site compiler
    config = project.config
    output = Path(output) if output else project.directory / config.exports.get("directory", "dist")
    output = output.resolve()
    if output == project.directory.resolve() or project.directory.resolve().is_relative_to(output):
        raise StoreError("the site output directory cannot contain the project")
    private_roots = [project.database_path.parent.resolve(), *project.roots().values()]
    if any(output == root or output.is_relative_to(root) for root in private_roots):
        raise StoreError(f"refusing to build into private storage ({output})")
    if output.exists() and (not output.is_dir() or (any(output.iterdir()) and not (output / SITE_MANIFEST).is_file())):
        raise StoreError(f"{output} exists and was not made by a workbench build; refusing to replace it. "
                         "Choose an empty or new output directory.")
    when = build_date or config.raw.get("site", {}).get("build_date") or date.today().isoformat()
    try:
        build_year = int(str(when)[:4])
    except ValueError as error:
        raise StoreError(f"build date must start with a year (YYYY-MM-DD), not {when!r}") from error
    staging = output.with_name(f".{output.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    store = project.store
    store.conn.execute("BEGIN")  # one consistent read snapshot for every part of the build
    try:
        case, omissions = public_case(project, build_year=build_year)
        build_project(case, config, staging)
        copied = []
        for item in omissions.published_assets:
            target = (staging / item["target"].lstrip("/")).resolve()
            if not target.is_relative_to(staging.resolve()):
                raise StoreError(f"approval target {item['target']} escapes the site")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item["path"], target)
            copied.append(item["target"])
    finally:
        store.conn.execute("COMMIT")
    # Exact-file approvals publish those bytes as approved; they are not rescanned.
    approved = {item.lstrip("/") for item in copied}
    findings = [item for item in leak_scan(staging, omissions.withheld_terms, omissions.withheld_files)
                if item["file"] not in approved]
    report = {
        "build_date": when, "output": str(output), "people": len(case.records("Person")),
        "relationships": len(case.records("Relationship")), "findings": len(case.records("Finding")),
        "published_files": sorted(copied), "omitted": omissions.counts(), "omission_count": len(omissions.items),
        "leaks": findings[:100],
    }
    destination = report_path or project.directory / project.settings.exports / "last-build-report.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({**report, "omissions": omissions.items}, indent=1, sort_keys=True) + "\n",
                           encoding="utf-8")
    if findings:
        raise LeakError(findings, staging)
    previous = output.with_name(f".{output.name}.previous")
    if previous.exists():
        shutil.rmtree(previous)
    if output.exists():
        os.replace(output, previous)
    os.replace(staging, output)
    if previous.exists():
        shutil.rmtree(previous)
    report["report"] = str(destination)
    return report


def tree_digest(root: Path) -> dict[str, str]:
    """Relative path -> SHA-256 for comparing two builds."""
    import hashlib
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(Path(root).rglob("*")) if path.is_file()}
