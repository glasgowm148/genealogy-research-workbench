"""Bounded, local file import with explicit replacement and publication review."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .adapters import resolve_adapter
from .case import CaseStore, ResearchCase, validate_case
from .config import ProjectConfig
from .models import AccessLevel, ImportProvenance, Record
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


def _json_text(raw: bytes) -> str:
    """JSON exports are UTF-8; accept a UTF-8 or UTF-16 byte-order mark."""
    for bom, encoding in ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
        if raw.startswith(bom):
            break
    else:
        encoding = "utf-8"
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError as error:
        line = raw.count(b"\n", 0, error.start) + 1
        raise ValueError(f"OneTree JSON must be UTF-8; line {line} is not valid UTF-8. Re-export it and retry") from error


def private_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError("private import paths must not be symbolic links")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
    path.chmod(0o600)


_IMPORT_ADAPTERS = {"gedcom": "gedcom", "one-tree": "one-tree"}


def _imported_ids(case: ResearchCase, adapter: str) -> set[str]:
    """Records owned by earlier file imports of one adapter, and their review history."""
    owned: set[str] = set()
    for provenance in case.records("ImportProvenance"):
        if provenance.adapter in (adapter, "file-import", "publication-review"):
            owned.add(provenance.id)
            if provenance.adapter == adapter:
                owned.update(provenance.entity_ids)
    return owned


def _backup(root: Path, case: ResearchCase, storage: Path) -> Path | None:
    """Keep a private copy of a case before an import replaces any of it."""
    current = CaseStore(storage).path_for(case.id)
    if not current.is_file():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = root / "private" / "imports" / "backups" / f"{case.id}-{stamp}.json"
    private_write(destination, current.read_bytes())
    return destination


def import_file(directory: Path, case: ResearchCase, config: ProjectConfig, source: Path,
                *, format: str = "auto", publish_deceased: bool = False,
                replace: bool = False, publish_reviewed_sources: bool = False,
                update: bool = False) -> dict[str, Any]:
    """Import one file into an empty case, or deliberately replace/update it.

    The original input is retained in ignored private storage. Repeating the same
    input and publication choice is a no-op; unrelated inputs never merge by ID.
    ``replace`` discards every existing record. ``update`` replaces only records
    created by earlier imports of the same format and keeps research added to the
    case; it refuses if that research would point at records the new export no
    longer contains. Either way the previous case is first backed up privately.
    """
    if publish_reviewed_sources and not publish_deceased:
        raise ValueError("--publish-reviewed-sources requires --publish-deceased")
    if replace and update:
        raise ValueError("choose either --replace or --update, not both")
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
    populated = any(case.record_sets.values())
    if populated and not (replace or update):
        raise ValueError("Case is not empty; use a new project, --update to refresh a previous import of this tree "
                         "while keeping added research, or --replace to discard every record (no automatic merge)")
    owned = _imported_ids(case, _IMPORT_ADAPTERS[selected]) if update else set()
    if update and not any(record_id in owned for record_id in
                          (record.id for record in case.records("ImportProvenance") if record.adapter == _IMPORT_ADAPTERS[selected])):
        raise ValueError(f"--update needs a case created by an earlier {selected} import; use --replace or a new project")
    try:
        # GEDCOM declares its own character set; the adapter decodes it.
        payload = raw if selected == "gedcom" else json.loads(_json_text(raw))
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
    retained: list[Record] = []
    if update:
        new_ids = {record.id for records in imported.record_sets.values() for record in records}
        retained = [record for records in case.record_sets.values() for record in records if record.id not in owned]
        clashes = [record.id for record in retained if record.id in new_ids]
        if clashes:
            raise ValueError("Update stopped: research records reuse IDs created by the new export: "
                             + ", ".join(clashes[:MAX_WARNINGS]) + ". Nothing was changed.")
        imported.add_many(retained)
        imported.question_ids = [rid for rid in case.question_ids if rid in {record.id for record in retained}]
        imported.finding_ids = [rid for rid in case.finding_ids if rid in {record.id for record in retained}]
    errors = validate_case(imported)
    if errors:
        if update:
            raise ValueError("Update stopped: research kept in the case would refer to records the new export no longer "
                             "contains. Nothing was changed. Correct these references, restore the missing people in the "
                             "export, or use --replace (a backup is kept): " + "; ".join(errors[:MAX_WARNINGS]))
        raise ValueError("Import failed validation: " + "; ".join(errors[:MAX_WARNINGS]))
    warnings = list(batch.warnings)
    if update:
        warnings.append(f"Updated the imported tree and kept {len(retained)} research records added to the case. "
                        "Edits made directly to previously imported records were replaced by the new export.")
    if not publish_deceased:
        warnings.append("Publication review was not selected; default-private imported people remain private.")
    warnings.append("Imported tree assertions are unverified; review original sources before treating them as conclusions.")
    missing = sum(place.latitude is None for place in imported.records("Place"))
    if missing:
        warnings.append(f"{missing} places have no coordinates; maps omit them. No geocoding or network request was made.")
    report = {"status": "updated" if update else "imported", "format": selected, "sha256": digest, "records": count,
              "people": len(imported.records("Person")), "published_people": published,
              "warnings": [str(warning)[:500] for warning in warnings[:MAX_WARNINGS]], "warning_count": len(warnings)}
    root = directory.resolve()
    private = (root / "private" / "imports").resolve()
    storage = (root / config.case_directory).resolve()
    if not private.is_relative_to(root) or not storage.is_relative_to(root):
        raise ValueError("Import storage escapes project directory")
    backup = _backup(root, case, storage) if populated else None
    if backup:
        report["backup"] = str(backup.relative_to(root))
        warnings.append(f"The previous case was backed up privately to {report['backup']}.")
        report["warnings"] = [str(warning)[:500] for warning in warnings[:MAX_WARNINGS]]
        report["warning_count"] = len(warnings)
    suffix = ".ged" if selected == "gedcom" else ".json"
    private_write(private / f"{digest}{suffix}", raw)
    private_write(private / f"{digest}.report.json", (json.dumps(report, indent=2) + "\n").encode())
    CaseStore(storage).save(imported)
    CaseStore(storage).path_for(imported.id).chmod(0o600)
    return report
