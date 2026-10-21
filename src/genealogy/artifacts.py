"""Local, durable research-case artifact bundles.

Unlike public exports, these files retain the complete validated case and are
intended for researcher handoff, backup, and offline review.  Callers must
choose an access-controlled destination when a case includes non-public data.
"""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable

from .case import NESTED_REFERENCES, ResearchCase, reference_values, validate_case
from .models import Claim, Evidence, Finding, Hypothesis, Record, ResearchQuestion
from .research import EvidenceCompleteness, UnresolvedWork


BUNDLE_SCHEMA_VERSION = 1
"""Version of the platform-neutral artifact-bundle contract."""

BUNDLE_MANIFEST_FILENAME = "bundle-manifest.json"
BUNDLE_CONTENT_FILENAMES = (
    "case.json", "case-state.json", "claim-index.json", "evidence-index.json",
    "reference-index.json", "unresolved-work.json", "research-brief.md",
)
BUNDLE_FILENAMES = (BUNDLE_MANIFEST_FILENAME, *BUNDLE_CONTENT_FILENAMES)


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _records(case: ResearchCase, kind: type[Record]) -> list[Record]:
    return [record for record in case.records(kind) if isinstance(record, kind)]


def evidence_completeness(case: ResearchCase) -> EvidenceCompleteness:
    """Return evidence coverage directly from a loaded durable case."""
    claims = _records(case, Claim)
    findings = _records(case, Finding)
    evidence_by_claim = {item.claim_id for item in _records(case, Evidence)}
    return EvidenceCompleteness(
        claims=len(claims),
        claims_with_citations=sum(bool(item.citation_ids) for item in claims),
        claims_with_evidence=sum(item.id in evidence_by_claim for item in claims),
        findings=len(findings),
        findings_with_evidence=sum(bool(item.evidence_ids) for item in findings),
    )


def unresolved_work(case: ResearchCase) -> UnresolvedWork:
    """Return stable ids for unfinished questions and evidence gaps."""
    evidence_by_claim = {item.claim_id for item in _records(case, Evidence)}
    return UnresolvedWork(
        open_question_ids=tuple(item.id for item in _records(case, ResearchQuestion)
                                if item.status.casefold() not in {"resolved", "closed"}),
        open_hypothesis_ids=tuple(item.id for item in _records(case, Hypothesis)
                                  if item.status.casefold() not in {"resolved", "closed", "rejected"}),
        draft_finding_ids=tuple(item.id for item in _records(case, Finding)
                                if item.status.casefold() in {"draft", "open"}),
        uncited_claim_ids=tuple(item.id for item in _records(case, Claim) if not item.citation_ids),
        unevidenced_claim_ids=tuple(item.id for item in _records(case, Claim)
                                    if item.id not in evidence_by_claim),
        unsupported_finding_ids=tuple(item.id for item in _records(case, Finding)
                                       if not item.evidence_ids),
    )


def research_brief(case: ResearchCase) -> str:
    """Render a platform-neutral Markdown research handoff from ``case``."""
    completeness, unresolved = evidence_completeness(case), unresolved_work(case)
    questions = {item.id: item for item in _records(case, ResearchQuestion)
                 if item.id in unresolved.open_question_ids}
    hypotheses = {item.id: item for item in _records(case, Hypothesis)
                  if item.id in unresolved.open_hypothesis_ids}
    findings = _records(case, Finding)
    lines = [f"# {case.title}", "", case.summary or "No case summary recorded.", "",
             "## Evidence coverage", "",
             f"- Claims with citations: {completeness.claims_with_citations}/{completeness.claims}",
             f"- Claims with evidence assessments: {completeness.claims_with_evidence}/{completeness.claims}",
             f"- Findings with evidence: {completeness.findings_with_evidence}/{completeness.findings}",
             "", "## Open research questions", ""]
    lines.extend(f"- **{item.id}** ({item.priority}): {item.question}" for item in questions.values())
    if not questions:
        lines.append("- None.")
    lines.extend(["", "## Open hypotheses", ""])
    lines.extend(f"- **{item.id}**: {item.statement}" for item in hypotheses.values())
    if not hypotheses:
        lines.append("- None.")
    lines.extend(["", "## Findings", ""])
    lines.extend(f"- **{item.id}** [{item.status}; {item.confidence}]: {item.conclusion}" for item in findings)
    if not findings:
        lines.append("- None.")
    lines.extend(["", "## Evidence gaps", ""])
    for label, ids in (("Claims without citations", unresolved.uncited_claim_ids),
                       ("Claims without evidence assessments", unresolved.unevidenced_claim_ids),
                       ("Findings without evidence", unresolved.unsupported_finding_ids)):
        lines.append(f"- {label}: {', '.join(ids) if ids else 'none'}")
    return "\n".join(lines) + "\n"


def _references(record: Record) -> Iterable[tuple[str, str]]:
    for field in ("parent_id", "place_id", "subject_id", "object_id", "source_id", "claim_id",
                  "citation_id", "event_ids", "participant_ids", "claim_ids", "citation_ids",
                  "related_ids", "evidence_ids", "entity_ids"):
        value = getattr(record, field, None)
        if isinstance(value, str):
            yield field, value
        elif isinstance(value, list):
            yield from ((field, item) for item in value if isinstance(item, str))
    yield from ((nested, item) for nested in NESTED_REFERENCES for item in reference_values(record, nested))


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def build_case_artifact_bundle(case: ResearchCase) -> dict[str, str]:
    """Build complete local bundle contents without writing files.

    The result has stable file names suitable for an offline handoff or archive.
    It deliberately does not apply the public-export privacy projection.
    """
    errors = validate_case(case)
    if errors:
        raise ValueError("cannot bundle invalid research case:\n" + "\n".join(f"- {error}" for error in errors))
    all_records = [(kind, record) for kind, records in case.record_sets.items() for record in records]
    kinds = {record.id: kind for kind, record in all_records}
    inbound: dict[str, list[dict[str, str]]] = {record.id: [] for _, record in all_records}
    references = []
    for kind, record in sorted(all_records, key=lambda item: item[1].id):
        links = [{"field": field, "id": target, "record_type": kinds.get(target)}
                 for field, target in _references(record)]
        references.append({"id": record.id, "record_type": kind, "references": links})
        for link in links:
            inbound[link["id"]].append({"field": link["field"], "id": record.id, "record_type": kind})
    claims = _records(case, Claim)
    evidence = _records(case, Evidence)
    evidence_by_claim: dict[str, list[str]] = {}
    for item in evidence:
        evidence_by_claim.setdefault(item.claim_id, []).append(item.id)
    completeness, unresolved = evidence_completeness(case), unresolved_work(case)
    state = {
        "case": {"id": case.id, "title": case.title, "schema_version": case.schema_version,
                 "created_at": case.created_at, "updated_at": case.updated_at},
        "record_counts": {kind: len(records) for kind, records in sorted(case.record_sets.items())},
        "evidence_completeness": asdict(completeness), "unresolved_work": asdict(unresolved),
    }
    contents = {
        "case.json": _json(case.to_dict()),
        "case-state.json": _json(state),
        "claim-index.json": _json({"claims": [
            {"id": item.id, "subject_id": item.subject_id, "predicate": item.predicate,
             "citation_ids": item.citation_ids, "evidence_ids": sorted(evidence_by_claim.get(item.id, [])),
             "status": item.status, "confidence": item.confidence}
            for item in sorted(claims, key=lambda item: item.id)]}),
        "evidence-index.json": _json({"evidence": [
            {"id": item.id, "claim_id": item.claim_id, "citation_id": item.citation_id,
             "supports": item.supports, "assessment": item.assessment, "confidence": item.confidence}
            for item in sorted(evidence, key=lambda item: item.id)]}),
        "reference-index.json": _json({"references": references, "referenced_by": [
            {"id": record_id, "references": sorted(items, key=lambda item: (item["id"], item["field"]))}
            for record_id, items in sorted(inbound.items())]}),
        "unresolved-work.json": _json(asdict(unresolved)),
        "research-brief.md": research_brief(case),
    }
    contents[BUNDLE_MANIFEST_FILENAME] = _json({
        "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
        "bundle_type": "genealogy-research-case-artifact",
        "privacy": "private-by-default",
        "case": {"id": case.id, "schema_version": case.schema_version},
        "files": [
            {
                "name": filename,
                "bytes": len(contents[filename].encode("utf-8")),
                "sha256": _sha256(contents[filename]),
            }
            for filename in BUNDLE_CONTENT_FILENAMES
        ],
    })
    return contents


def _read_manifest(directory: Path) -> dict[str, Any]:
    try:
        manifest = json.loads((directory / BUNDLE_MANIFEST_FILENAME).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"missing bundle manifest: {BUNDLE_MANIFEST_FILENAME}") from error
    except json.JSONDecodeError as error:
        raise ValueError("bundle manifest is not valid JSON") from error
    if not isinstance(manifest, dict):
        raise ValueError("bundle manifest must be a JSON object")
    if manifest.get("bundle_schema_version") != BUNDLE_SCHEMA_VERSION:
        raise ValueError("unsupported or missing bundle schema version")
    if manifest.get("bundle_type") != "genealogy-research-case-artifact":
        raise ValueError("unexpected bundle type")
    if manifest.get("privacy") != "private-by-default":
        raise ValueError("bundle manifest must declare private-by-default privacy")
    return manifest


def read_case_artifact_bundle(directory: Path) -> ResearchCase:
    """Verify a complete bundle and return its validated durable research case.

    This reads only the platform-neutral local bundle contract.  It never makes
    network requests and does not apply a public-export privacy projection.
    """
    if not directory.is_dir():
        raise ValueError(f"bundle source is not a directory: {directory}")
    manifest = _read_manifest(directory)
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("bundle manifest files must be a list")
    expected = set(BUNDLE_CONTENT_FILENAMES)
    listed = {entry.get("name") for entry in files if isinstance(entry, dict)}
    if listed != expected or len(files) != len(expected):
        raise ValueError("bundle manifest must list exactly the required artifact files")
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("bundle manifest file entries must be objects")
        filename, byte_count, digest = entry.get("name"), entry.get("bytes"), entry.get("sha256")
        if filename not in expected or type(byte_count) is not int or byte_count < 0:
            raise ValueError("bundle manifest contains an invalid file entry")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("bundle manifest contains an invalid SHA-256 digest")
        try:
            content = (directory / filename).read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise ValueError(f"bundle is missing required artifact: {filename}") from error
        encoded = content.encode("utf-8")
        if len(encoded) != byte_count or _sha256(content) != digest:
            raise ValueError(f"bundle artifact does not match manifest: {filename}")
    try:
        case_data = json.loads((directory / "case.json").read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("bundle case.json is not valid JSON") from error
    case = ResearchCase.from_dict(case_data)
    case_metadata = manifest.get("case")
    if not isinstance(case_metadata, dict) or case_metadata != {
        "id": case.id, "schema_version": case.schema_version,
    }:
        raise ValueError("bundle manifest case metadata does not match case.json")
    return case


def _atomic_write(path: Path, content: str) -> None:
    """Durably replace one private bundle file without exposing partial text."""
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
            suffix=".tmp", delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def write_case_artifact_bundle(case: ResearchCase, directory: Path) -> dict[str, Path]:
    """Write a complete private bundle, with its manifest replaced last.

    Each file is written to a private temporary peer and atomically replaced.
    An interrupted refresh can therefore leave an older manifest, but never a
    manifest that validates mixed or partial file content.
    """
    contents = build_case_artifact_bundle(case)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not directory.is_dir():
        raise ValueError(f"bundle destination is not a directory: {directory}")
    os.chmod(directory, 0o700)
    paths: dict[str, Path] = {}
    for filename in BUNDLE_CONTENT_FILENAMES:
        path = directory / filename
        _atomic_write(path, contents[filename])
        paths[filename] = path
    manifest_path = directory / BUNDLE_MANIFEST_FILENAME
    _atomic_write(manifest_path, contents[BUNDLE_MANIFEST_FILENAME])
    paths[BUNDLE_MANIFEST_FILENAME] = manifest_path
    return paths
