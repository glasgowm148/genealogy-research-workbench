"""Bounded, local file import with explicit replacement and publication review."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .adapters import resolve_adapter
from .case import CaseStore, ResearchCase, validate_case
from .config import ProjectConfig
from .models import AccessLevel, ImportProvenance
from .publication import review_deceased

MAX_IMPORT_BYTES = 32 * 1024 * 1024
MAX_WARNINGS = 20


def detect_format(filename: str, selected: str = "auto") -> str:
    if selected != "auto":
        if selected not in ("gedcom", "one-tree"):
            raise ValueError("format must be auto, gedcom or one-tree")
        return selected
    suffix = Path(filename).suffix.casefold()
    if suffix in (".ged", ".gedcom"):
        return "gedcom"
    if suffix == ".json":
        return "one-tree"
    raise ValueError("Choose a .ged, .gedcom or OneTree .json file (or specify --format)")


def private_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError("private import paths must not be symbolic links")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
    path.chmod(0o600)


def import_file(directory: Path, case: ResearchCase, config: ProjectConfig, source: Path,
                *, format: str = "auto", publish_deceased: bool = False,
                replace: bool = False, publish_reviewed_sources: bool = False) -> dict[str, Any]:
    """Replace one empty/explicitly replaced case after complete validation.

    The original input is retained in ignored private storage. Repeating the same
    input and publication choice is a no-op; unrelated inputs never merge by ID.
    """
    if publish_reviewed_sources and not publish_deceased:
        raise ValueError("--publish-reviewed-sources requires --publish-deceased")
    if not source.is_file() or source.stat().st_size > MAX_IMPORT_BYTES:
        raise ValueError("Import requires a file of at most 32 MiB")
    raw = source.read_bytes()
    if len(raw) > MAX_IMPORT_BYTES:
        raise ValueError("Import requires a file of at most 32 MiB")
    selected = detect_format(source.name, format)
    enabled = config.adapters.get("enabled")
    if enabled is not None:
        if not isinstance(enabled, list) or not all(isinstance(value, str) for value in enabled):
            raise ValueError("adapters.enabled must be a list of adapter names")
        if selected not in {value.casefold().replace("_", "-") for value in enabled}:
            raise ValueError(f"adapter is not enabled by project configuration: {selected}")
    digest = hashlib.sha256(raw).hexdigest()
    signature = {"sha256": digest, "format": selected, "publish_deceased": publish_deceased, "publish_reviewed_sources": publish_reviewed_sources}
    for provenance in case.records("ImportProvenance"):
        if provenance.adapter == "file-import" and signature in provenance.observations:
            return {"status": "unchanged", "format": selected, "people": len(case.records("Person")),
                    "warnings": [], "warning_count": 0, "published_people": 0}
    if any(case.record_sets.values()) and not replace:
        raise ValueError("Case is not empty; use a new project or --replace to replace its records (no automatic merge)")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Input must use UTF-8 encoding; export it as UTF-8 and retry") from error
    try:
        payload = text if selected == "gedcom" else json.loads(text)
        batch = resolve_adapter(selected).ingest(payload)
    except (TypeError, KeyError, AttributeError, RecursionError) as error:
        raise ValueError(f"Invalid {selected} input: {error}") from error
    if not any(type(entity).__name__ == "Person" for entity in batch.entities):
        raise ValueError("Input produced no people; check its format and export structure")
    # This convenience workflow always requires an explicit publication choice,
    # even if a provider described its records as public. Legacy ingest remains
    # available for individually reviewed, typed adapter work.
    for entity in batch.entities:
        if entity.sensitivity == AccessLevel.PUBLIC:
            entity.sensitivity = AccessLevel.PRIVATE
    imported = ResearchCase(id=case.id, title=case.title, summary=case.summary)
    count = batch.add_to_case(imported)
    published = review_deceased(imported, batch, reviewed_sources=publish_reviewed_sources) if publish_deceased else 0
    imported.add(ImportProvenance(id=f"file-import:{digest}", adapter="file-import", observations=[signature]))
    errors = validate_case(imported)
    if errors:
        raise ValueError("Import failed validation: " + "; ".join(errors[:MAX_WARNINGS]))
    warnings = list(batch.warnings)
    if not publish_deceased:
        warnings.append("Publication review was not selected; default-private imported people remain private.")
    warnings.append("Imported tree assertions are unverified; review original sources before treating them as conclusions.")
    missing = sum(place.latitude is None for place in imported.records("Place"))
    if missing:
        warnings.append(f"{missing} places have no coordinates; maps omit them. No geocoding or network request was made.")
    report = {"status": "imported", "format": selected, "sha256": digest, "records": count,
              "people": len(imported.records("Person")), "published_people": published,
              "warnings": [str(warning)[:500] for warning in warnings[:MAX_WARNINGS]], "warning_count": len(warnings)}
    root = directory.resolve()
    private = (root / "private" / "imports").resolve()
    storage = (root / config.case_directory).resolve()
    if not private.is_relative_to(root) or not storage.is_relative_to(root):
        raise ValueError("Import storage escapes project directory")
    suffix = ".ged" if selected == "gedcom" else ".json"
    private_write(private / f"{digest}{suffix}", raw)
    private_write(private / f"{digest}.report.json", (json.dumps(report, indent=2) + "\n").encode())
    CaseStore(storage).save(imported)
    CaseStore(storage).path_for(imported.id).chmod(0o600)
    return report
