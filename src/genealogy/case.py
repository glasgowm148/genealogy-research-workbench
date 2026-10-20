"""Durable, local research-case storage."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .markup import references as prose_references
from .models import (
    CASE_SCHEMA_VERSION, MODEL_TYPES, Claim, ClaimStatus, Confidence, Evidence,
    ExternalIdentifier, Finding, ImportProvenance, LivingStatus, Name, PLACE_PRECISIONS,
    Person, Place, Record, ResearchQuestion, access_level, is_raw_dna, record_from_dict,
)


def _reject_raw_dna(record: Record) -> None:
    if is_raw_dna(record):
        raise ValueError("raw DNA material cannot be stored in a research case")


@dataclass(slots=True)
class ResearchCase:
    id: str
    title: str
    summary: str = ""
    record_sets: dict[str, list[Record]] = field(default_factory=dict)
    question_ids: list[str] = field(default_factory=list)
    finding_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    schema_version: int = CASE_SCHEMA_VERSION

    def add(self, record: Record) -> None:
        self.add_many([record])

    def add_many(self, records: list[Record]) -> None:
        """Validate an entire batch before inserting it in linear time.

        Imports can contain tens of thousands of records. Build the identity
        index once per batch while still respecting externally edited cases.
        Reference validation remains at the existing save/export boundaries.
        """
        pending = list(records)
        seen = {current.id for values in self.record_sets.values() for current in values}
        for record in pending:
            if not isinstance(record, Record):
                raise TypeError("case records must be Record instances")
            _reject_raw_dna(record)
            if record.id in seen:
                raise ValueError(f"duplicate record id: {record.id}")
            seen.add(record.id)
        for record in pending:
            self.record_sets.setdefault(type(record).__name__, []).append(record)
            if isinstance(record, ResearchQuestion):
                self.question_ids.append(record.id)
            if isinstance(record, Finding):
                self.finding_ids.append(record.id)
        if pending:
            self.updated_at = datetime.now(UTC).isoformat()

    def records(self, kind: type[Record] | str) -> list[Record]:
        return self.record_sets.get(kind if isinstance(kind, str) else kind.__name__, [])

    def to_dict(self) -> dict[str, Any]:
        if type(self.schema_version) is not int or self.schema_version != CASE_SCHEMA_VERSION:
            raise ValueError(f"unsupported research case schema_version: {self.schema_version!r}")
        for records in self.record_sets.values():
            for record in records:
                _reject_raw_dna(record)
        return {
            "schema_version": self.schema_version,
            "id": self.id, "title": self.title, "summary": self.summary,
            "question_ids": self.question_ids, "finding_ids": self.finding_ids,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "record_sets": {kind: [record.to_dict() for record in records]
                            for kind, records in self.record_sets.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchCase":
        if not isinstance(data, dict):
            raise ValueError("research case must be a JSON object")
        schema_version = data.get("schema_version")
        if type(schema_version) is not int or schema_version != CASE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported or missing research case schema_version: {schema_version!r}; "
                f"expected {CASE_SCHEMA_VERSION}"
            )
        case = cls(id=data["id"], title=data["title"], summary=data.get("summary", ""),
                   question_ids=list(data.get("question_ids", [])),
                   finding_ids=list(data.get("finding_ids", [])),
                   created_at=data.get("created_at", datetime.now(UTC).isoformat()),
                   updated_at=data.get("updated_at", datetime.now(UTC).isoformat()),
                   schema_version=schema_version)
        record_sets = data.get("record_sets", {})
        if not isinstance(record_sets, dict):
            raise ValueError("research case record_sets must be an object")
        case.record_sets = {}
        for kind, records in record_sets.items():
            if kind not in MODEL_TYPES:
                raise ValueError(f"unsupported record type: {kind}")
            if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
                raise ValueError(f"research case {kind} record set must be a list of objects")
            case.record_sets[kind] = [record_from_dict(kind, item) for item in records]
        for records in case.record_sets.values():
            for record in records:
                _reject_raw_dna(record)
        errors = validate_case(case)
        if errors:
            raise ValueError("invalid research case:\n" + "\n".join(f"- {error}" for error in errors))
        return case


def validate_case(case: ResearchCase) -> list[str]:
    """Validate durable record identity, references, indices and place coordinates."""
    errors: list[str] = []
    if not isinstance(case.id, str) or not case.id:
        errors.append("research case id must be a non-empty string")
    if not isinstance(case.title, str) or not isinstance(case.summary, str):
        errors.append("research case title and summary must be strings")
    for index_name in ("question_ids", "finding_ids"):
        if not _string_list(getattr(case, index_name)):
            errors.append(f"{index_name} must be a list of non-empty ids")
    seen: set[str] = set()
    for kind, records in case.record_sets.items():
        expected_type = MODEL_TYPES.get(kind)
        if expected_type is None:
            errors.append(f"unsupported record set: {kind}")
        if not isinstance(records, list):
            errors.append(f"{kind} record set must be a list")
            continue
        for record in records:
            if expected_type is not None and type(record) is not expected_type:
                errors.append(f"{kind} record set contains {type(record).__name__}")
            if not isinstance(record, Record):
                errors.append(f"{kind} contains a non-record value")
                continue
            if not isinstance(record.id, str) or not record.id:
                errors.append(f"{kind} has a missing id")
            elif record.id in seen:
                errors.append(f"duplicate record id: {record.id}")
            seen.add(record.id)
    if type(case.schema_version) is not int or case.schema_version != CASE_SCHEMA_VERSION:
        errors.append("unsupported research case schema_version")
    id_kinds = {
        record.id: kind
        for kind, records in case.record_sets.items()
        if isinstance(records, list)
        for record in records
        if isinstance(record, Record) and isinstance(record.id, str) and record.id
    }
    references: dict[str, dict[str, str | None]] = {
        "Event": {"place_id": "Place", "participant_ids": "Person"},
        "Person": {"event_ids": "Event"},
        "Place": {"parent_id": "Place"},
        "Relationship": {"subject_id": "Person", "object_id": "Person", "claim_ids": "Claim"},
        "Citation": {"source_id": "Source"},
        "Claim": {"subject_id": None, "citation_ids": "Citation"},
        "Evidence": {"claim_id": "Claim", "citation_id": "Citation"},
        "Hypothesis": {"related_ids": None, "evidence_ids": "Evidence"},
        "ResearchQuestion": {"related_ids": None},
        "Finding": {"related_ids": None, "evidence_ids": "Evidence", "citation_ids": "Citation"},
        "Study": {"related_ids": None},
        "ImportProvenance": {"entity_ids": None},
    }
    for kind, records in case.record_sets.items():
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, Record):
                continue
            for reference_field, expected_kind in references.get(kind, {}).items():
                value = getattr(record, reference_field, None)
                values = value if isinstance(value, list) else [value]
                for reference in values:
                    if reference and reference not in seen:
                        errors.append(f"{record.id}.{reference_field} references missing record: {reference}")
                    elif reference and expected_kind and id_kinds.get(reference) != expected_kind:
                        errors.append(f"{record.id}.{reference_field} must reference a {expected_kind}: {reference}")
            if kind == "Study":
                for text_field in ("summary", "rationale", "body", "conclusion"):
                    text = getattr(record, text_field, None)
                    for reference in prose_references(text if isinstance(text, str) else ""):
                        if reference not in seen:
                            errors.append(f"{record.id}.{text_field} refers to missing record [[{reference}]]")
            sensitivity = access_level(getattr(record, "sensitivity", None))
            if sensitivity is None:
                errors.append(f"{record.id} has an invalid sensitivity")
            elif is_raw_dna(record):
                errors.append(f"{record.id} contains prohibited raw DNA material")
            if kind == "Person":
                living = getattr(record, "living", LivingStatus.UNKNOWN)
                if not (
                    type(living) is bool
                    or living is None
                    or isinstance(living, LivingStatus)
                ):
                    errors.append(f"{record.id} has an invalid living status")
            if kind == "Place":
                latitude, longitude = getattr(record, "latitude", None), getattr(record, "longitude", None)
                if (latitude is None) != (longitude is None):
                    errors.append(f"{record.id} must provide both latitude and longitude")
                if latitude is not None and longitude is not None:
                    if type(latitude) not in (int, float) or type(longitude) not in (int, float):
                        errors.append(f"{record.id} coordinates must be numbers")
                    elif not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                        errors.append(f"{record.id} coordinates are outside valid ranges")
            errors.extend(_validate_record_fields(record))
    for index_name, record_type in (("question_ids", "ResearchQuestion"), ("finding_ids", "Finding")):
        ids = getattr(case, index_name)
        if not _string_list(ids):
            continue
        if len(ids) != len(set(ids)):
            errors.append(f"{index_name} contains duplicate ids")
        indexed_records = case.records(record_type)
        actual = {
            record.id
            for record in indexed_records
            if isinstance(record, Record) and isinstance(record.id, str)
        } if isinstance(indexed_records, list) else set()
        if set(ids) != actual:
            errors.append(f"{index_name} must exactly index all {record_type} records")
    return errors


GRADE_KEY = r"[a-z0-9][a-z0-9_-]*"


def grade_errors(case: ResearchCase, grades: dict[str, dict[str, Any]]) -> list[str]:
    """Each record's grade must be one the project defines, counted as its confidence."""
    errors = []
    for record in (record for records in case.record_sets.values() for record in records):
        grade = getattr(record, "grade", None)
        if grade is None:
            continue
        if grade not in grades:
            errors.append(f"{record.id}.grade is not defined under [grades] in genealogy.toml: {grade}")
        elif str(record.confidence) != grades[grade]["confidence"]:
            errors.append(f"{record.id}.confidence must be {grades[grade]['confidence']} for grade {grade}")
    return errors


def _iso_date(value: str) -> bool:
    match = re.fullmatch(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", value)
    if not match:
        return False
    try:
        date(int(match[1]), int(match[2] or 1), int(match[3] or 1))
    except ValueError:
        return False
    return True


def _string(value: Any, *, optional: bool = False) -> bool:
    return (optional and value is None) or isinstance(value, str)


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item for item in value)


def _validate_external_ids(record: Record) -> list[str]:
    values = getattr(record, "external_ids", None)
    if values is None:
        return []
    if not isinstance(values, list) or not all(isinstance(item, ExternalIdentifier) for item in values):
        return [f"{record.id}.external_ids must contain ExternalIdentifier values"]
    errors: list[str] = []
    for item in values:
        if not _string(item.system) or not item.system or not _string(item.value) or not item.value:
            errors.append(f"{record.id}.external_ids require non-empty system and value")
        if not _string(item.url, optional=True) or type(item.verified) is not bool:
            errors.append(f"{record.id}.external_ids contain invalid url or verified fields")
    return errors


def _validate_record_fields(record: Record) -> list[str]:
    """Check direct-construction values as strictly as JSON rehydration."""
    errors = _validate_external_ids(record)
    string_fields = {
        "Place": ("name",),
        "Event": ("kind",),
        "Relationship": ("subject_id", "object_id", "kind"),
        "Source": ("title", "source_type"),
        "Citation": ("source_id",),
        "Claim": ("subject_id", "predicate", "value"),
        "Evidence": ("claim_id", "citation_id", "assessment"),
        "Hypothesis": ("statement", "status"),
        "ResearchQuestion": ("question", "priority", "status"),
        "Finding": ("conclusion", "status"),
        "Study": ("title", "status"),
        "ImportProvenance": ("adapter",),
    }
    for field_name in string_fields.get(type(record).__name__, ()):
        if not _string(getattr(record, field_name, None)) or not getattr(record, field_name):
            errors.append(f"{record.id}.{field_name} must be a non-empty string")
    optional_strings = (
        "parent_id", "date", "place_id", "description", "notes", "repository", "url",
        "access_note", "licence", "locator", "quotation", "transcription", "accessed_on",
        "rationale", "start_date", "end_date", "summary", "body", "conclusion", "pedigree", "tree_status",
        "author", "publication", "limitations", "abstract",
    )
    for field_name in optional_strings:
        if hasattr(record, field_name) and not _string(getattr(record, field_name), optional=True):
            errors.append(f"{record.id}.{field_name} must be a string or null")
    if isinstance(record, Finding) and record.kind is not None and not (_string(record.kind) and record.kind.strip()):
        errors.append(f"{record.id}.kind must be a non-empty string or null")
    grade = getattr(record, "grade", None)
    if grade is not None and not (_string(grade) and re.fullmatch(GRADE_KEY, grade)):
        errors.append(f"{record.id}.grade must be a grade key (lower-case letters, digits, '_' or '-') or null")
    list_fields = (
        "event_ids", "participant_ids", "claim_ids", "citation_ids", "related_ids",
        "evidence_ids", "entity_ids",
    )
    for field_name in list_fields:
        if hasattr(record, field_name) and not _string_list(getattr(record, field_name)):
            errors.append(f"{record.id}.{field_name} must be a list of non-empty ids")
    confidence = getattr(record, "confidence", None)
    if confidence is not None and not isinstance(confidence, Confidence):
        errors.append(f"{record.id}.confidence must be a recognised value")
    if isinstance(record, Claim) and not isinstance(record.status, ClaimStatus):
        errors.append(f"{record.id}.status must be a recognised claim status")
    if isinstance(record, Evidence) and type(record.supports) is not bool:
        errors.append(f"{record.id}.supports must be a boolean")
    if isinstance(record, Person):
        if not isinstance(record.names, list) or not all(isinstance(item, Name) for item in record.names):
            errors.append(f"{record.id}.names must contain Name values")
        else:
            for name in record.names:
                if not isinstance(name.value, str) or not name.value:
                    errors.append(f"{record.id}.names require a non-empty value")
                if not isinstance(name.confidence, Confidence):
                    errors.append(f"{record.id}.names require recognised confidence")
    for field_name in ("recorded_on", "updated_on"):
        value = getattr(record, field_name, None)
        if value is not None and not (isinstance(value, str) and _iso_date(value)):
            errors.append(f"{record.id}.{field_name} must be an ISO date (YYYY, YYYY-MM or YYYY-MM-DD)")
    estimate = getattr(record, "estimate", None)
    if estimate is not None and not (type(estimate) is int and 1 <= estimate <= 99):
        errors.append(f"{record.id}.estimate must be a whole percentage from 1 to 99")
    if isinstance(record, Place) and record.precision is not None and record.precision not in PLACE_PRECISIONS:
        errors.append(f"{record.id}.precision must be one of: {', '.join(PLACE_PRECISIONS)}")
    if isinstance(record, ImportProvenance):
        if not isinstance(record.observations, list) or not all(isinstance(item, dict) for item in record.observations):
            errors.append(f"{record.id}.observations must be a list of objects")
    return errors


@dataclass(slots=True)
class CaseStore:
    directory: Path | str

    def __post_init__(self) -> None:
        self.directory = Path(self.directory)

    def path_for(self, case_id: str) -> Path:
        if not case_id or Path(case_id).name != case_id:
            raise ValueError("case id must be a simple file name")
        return self.directory / f"{case_id}.json"

    def save(self, case: ResearchCase) -> Path:
        errors = validate_case(case)
        if errors:
            raise ValueError("cannot save invalid research case:\n" + "\n".join(f"- {error}" for error in errors))
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(case.id)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(case.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
        return path

    def load(self, case_id: str) -> ResearchCase:
        return ResearchCase.from_dict(json.loads(self.path_for(case_id).read_text(encoding="utf-8")))
