"""Project-level operations built on the services: upgrade, file import, status."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from ..adapters import resolve_adapter
from ..case import CaseStore, ResearchCase
from ..importing import MAX_IMPORT_BYTES, _IMPORT_ADAPTERS, _json_text, detect_format, gedzip_gedcom
from ..models import AccessLevel
from ..publication import review_deceased
from .assets import prepare_managed, register_asset
from .importer import CANONICAL_SYSTEM, DURABLE_SYSTEMS, new_loader
from .project import MANAGED_ROOT, Project
from .services import Research, stable_id


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def legacy_case_paths(project: Project) -> list[Path]:
    directory = project.directory / project.config.case_directory
    return sorted(directory.glob("*.json")) if directory.is_dir() else []


def upgrade_cases(project: Project, *, actor: str = "genealogy upgrade") -> dict[str, Any]:
    """Load every legacy JSON case into the database. Re-running is a no-op for unchanged files."""
    research = Research(project.store)
    report: dict[str, Any] = {"cases": [], "unchanged": [], "conflicts": []}
    for path in legacy_case_paths(project):
        raw = path.read_bytes()
        digest = _sha(raw)
        relative = path.relative_to(project.directory).as_posix()
        batch_id = stable_id("imp", "case", relative, digest)
        if project.store.get("import_batch", batch_id):
            report["unchanged"].append(relative)
            continue
        case = CaseStore(path.parent).load(path.stem)
        prepared = prepare_managed(project, path)
        with project.store.write(actor=actor, tool="genealogy upgrade", source=relative,
                                 reason="migrate a legacy JSON research case into the project database") as tx:
            asset = register_asset(project, tx, path, kind="original_import", prepared=prepared,
                                   provenance=f"legacy case file {relative}")
            tx.insert("import_batch", {"id": batch_id, "adapter": "legacy-json-case", "input_label": relative,
                                       "input_sha256": digest, "imported_at": project.store.clock(),
                                       "asset_id": asset["id"], "change_set_id": tx.change_set_id})
            loader = new_loader(research, tx, batch_id=batch_id, input_path=relative, origin="research",
                                input_sha256=digest)
            records = [record for records in case.record_sets.values() for record in records]
            loader.load(records)
            loader.finish()
            note_id = stable_id("not", "case", case.id)
            if not project.store.get("note", note_id):
                research.add_note(tx, id=note_id, kind="case", title=case.title, text=case.summary or case.title,
                                  links=[(rid, "question") for rid in case.question_ids if project.store.entity_type(rid)]
                                  + [(rid, "finding") for rid in case.finding_ids if project.store.entity_type(rid)])
            tx.conn.execute("UPDATE import_batch SET report_json=? WHERE id=?",
                            (json.dumps(loader.report, sort_keys=True), batch_id))
        report["cases"].append({"path": relative, "records": loader.report})
        report["conflicts"].extend(loader.conflicts)
    if report["cases"]:
        with project.store.write(actor=actor, tool="genealogy upgrade", reason="record case migration") as tx:
            tx.conn.execute("INSERT INTO schema_meta(key, value) VALUES ('legacy_cases_migrated', ?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (project.store.clock(),))
    return report


def _person_ids(research: Research, batch: Any, lineage: str) -> dict[str, str]:
    """Map adapter person ids to database ids by durable identifier, then lineage xref."""
    mapping: dict[str, str] = {}
    for entity in batch.entities:
        if type(entity).__name__ != "Person":
            continue
        found: list[str] = []
        for ident in entity.external_ids:
            if DURABLE_SYSTEMS.match(ident.system):
                found = research.find_external(CANONICAL_SYSTEM.get(ident.system, ident.system), ident.value)
                if found:
                    break
        if not found:
            for ident in entity.external_ids:
                found = research.find_external(f"xref:{lineage}", ident.value)
                if found:
                    break
        mapping[entity.id] = found[0] if found else stable_id("per", lineage, entity.id)
    return mapping


def import_genealogy_file(project: Project, source: Path, *, format: str = "auto", lineage: str | None = None,
                          publish_deceased: bool = False, publish_reviewed_sources: bool = False,
                          actor: str = "genealogy import") -> dict[str, Any]:
    """Import a GEDCOM, GEDCOM 7 archive or OneTree file into the database."""
    if publish_reviewed_sources and not publish_deceased:
        raise ValueError("--publish-reviewed-sources requires --publish-deceased")
    source = Path(source)
    if not source.is_file():
        raise ValueError(f"No export file found at {source}")
    if source.stat().st_size > MAX_IMPORT_BYTES:
        raise ValueError("Import requires a file of at most 32 MiB")
    raw = source.read_bytes()
    selected = detect_format(source.name, format)
    lineage = lineage or f"{selected}:{source.stem}"
    digest = _sha(raw)
    options = {"publish_deceased": publish_deceased, "publish_reviewed_sources": publish_reviewed_sources,
               "lineage": lineage}
    batch_id = stable_id("imp", selected, digest, json.dumps(options, sort_keys=True))
    if project.store.get("import_batch", batch_id):
        return {"status": "unchanged", "format": selected, "batch": batch_id}
    archive_notes: list[str] = []
    if selected == "gedzip":
        payload, archive_notes = gedzip_gedcom(raw)
    else:
        payload = raw if selected == "gedcom" else json.loads(_json_text(raw))
    try:
        batch = resolve_adapter(_IMPORT_ADAPTERS[selected]).ingest(payload)
    except (TypeError, KeyError, AttributeError, RecursionError) as error:
        raise ValueError(f"Invalid {selected} input: {error}") from error
    batch.warnings[:0] = archive_notes
    if not any(type(entity).__name__ == "Person" for entity in batch.entities):
        raise ValueError("Input produced no people; check its format and export structure")
    for entity in batch.entities:
        if entity.sensitivity == AccessLevel.PUBLIC:
            entity.sensitivity = AccessLevel.PRIVATE
    published = 0
    if publish_deceased:
        # The shared review decides *which* imported records may be public. It
        # strips details from its own copy; the database keeps the full import
        # and holds those details in private rows instead (see RecordLoader).
        review_batch = copy.deepcopy(batch)
        reviewed = ResearchCase(id="import", title="import")
        review_batch.add_to_case(reviewed)
        published = review_deceased(reviewed, review_batch, reviewed_sources=publish_reviewed_sources)
        public_ids = {record.id for records in reviewed.record_sets.values() for record in records
                      if record.sensitivity == AccessLevel.PUBLIC and type(record).__name__ != "ImportProvenance"}
        for entity in batch.entities:
            if entity.id in public_ids:
                entity.sensitivity = AccessLevel.PUBLIC
    research = Research(project.store)
    people = _person_ids(research, batch, lineage)

    def id_for(value: str) -> str:
        if value in people:
            return people[value]
        prefix = value.split(":", 2)[1][:3] if value.count(":") >= 2 else "imp"
        return stable_id(prefix, lineage, value)

    prepared = prepare_managed(project, source)
    relative = source.name
    with project.store.write(actor=actor, tool="genealogy import", source=str(source),
                             reason=f"import {selected} file") as tx:
        asset = register_asset(project, tx, source, kind="original_import", prepared=prepared,
                               provenance=f"{selected} import ({lineage})")
        tx.insert("import_batch", {"id": batch_id, "adapter": selected, "input_label": relative,
                                   "input_sha256": digest, "options_json": json.dumps(options, sort_keys=True),
                                   "imported_at": project.store.clock(), "asset_id": asset["id"],
                                   "change_set_id": tx.change_set_id})
        loader = new_loader(research, tx, batch_id=batch_id, input_path=relative, origin="imported",
                            input_sha256=digest, id_for=id_for, private_details=True)
        loader.load([entity for entity in batch.entities if type(entity).__name__ != "ImportProvenance"])
        loader.finish()
        observations = 0
        for item in batch.records:
            entity = None
            if item.entity_type == "person":
                entity = people.get(f"{batch.adapter}:person:{item.external_id.value}") or next(
                    (people[key] for key in people if key.endswith(f":{item.external_id.value}")), None)
                if entity:
                    research.map_external(tx, entity, f"xref:{lineage}", item.external_id.value, status="alias")
            system = "wikitree" if selected == "one-tree" else f"gedcom:{lineage}"
            _, created = research.record_observation(
                tx, system=system, external_value=item.external_id.value,
                fields={"raw": item.raw, "entity_type": item.entity_type}, entity_id=entity,
                asset_id=asset["id"], import_batch_id=batch_id)
            observations += created
        report = {"status": "imported", "format": selected, "sha256": digest, "lineage": lineage,
                  "records": loader.report, "observations": observations, "published_people": published,
                  "conflicts": loader.conflicts[:20], "conflict_count": len(loader.conflicts),
                  "warnings": batch.warnings[:20], "warning_count": len(batch.warnings),
                  "notes": ["Imported tree assertions are recorded as imported claims, not conclusions.",
                            "Every input record is kept verbatim as an external observation; unsupported "
                            "structures are listed in the warnings and preserved there."]}
        tx.conn.execute("UPDATE import_batch SET report_json=? WHERE id=?", (json.dumps(report, sort_keys=True), batch_id))
    return report


def status(project: Project) -> dict[str, Any]:
    store = project.store
    counts = {table: store.one(f"SELECT count(*) AS n FROM {table}")["n"]
              for table in ("person", "claim", "assessment", "source", "record", "citation", "mention", "finding",
                            "question", "search", "study", "asset", "approval", "proposal", "external_observation",
                            "legacy_item")}
    return {"database": str(project.database_path), "schema_version": int(store.meta("schema_version")),
            "project_id": store.meta("project_id"), "counts": counts,
            "review_needed": store.one("SELECT count(*) AS n FROM dependency WHERE status='review_needed'")["n"],
            "legacy_items_open": store.one("SELECT count(*) AS n FROM legacy_item WHERE resolution IS NULL")["n"],
            "legacy_cases": [p.relative_to(project.directory).as_posix() for p in legacy_case_paths(project)],
            "legacy_cases_migrated": store.meta("legacy_cases_migrated")}


__all__ = ["import_genealogy_file", "legacy_case_paths", "status", "upgrade_cases", "MANAGED_ROOT"]
