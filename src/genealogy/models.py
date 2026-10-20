"""Stable, source-first data contracts independent of any genealogy service."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import re
from typing import Any


CASE_SCHEMA_VERSION = 1


class Confidence(StrEnum):
    DOCUMENTED = "documented"
    PROBABLE = "probable"
    POSSIBLE = "possible"
    DISPROVED = "disproved"
    UNKNOWN = "unknown"


class ClaimStatus(StrEnum):
    ASSERTED = "asserted"
    SUPPORTED = "supported"
    DISPUTED = "disputed"
    REJECTED = "rejected"


class AccessLevel(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    RESTRICTED = "restricted"
    LICENSED = "licensed"
    RAW_DNA = "raw_dna"


# Kept as a friendly compatibility name for callers which describe this as data
# sensitivity.  AccessLevel is the canonical cross-platform term.
Sensitivity = AccessLevel


class LivingStatus(StrEnum):
    LIVING = "living"
    DECEASED = "deceased"
    UNKNOWN = "unknown"


def _plain(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    return value


def access_level(value: Any) -> AccessLevel | None:
    """Return a recognised access level without treating malformed data as public."""
    try:
        return AccessLevel(value)
    except (TypeError, ValueError):
        return None


def is_raw_dna(record: "Record") -> bool:
    """Raw DNA is forbidden from durable portable cases, irrespective of type."""
    return (
        access_level(getattr(record, "sensitivity", None)) is AccessLevel.RAW_DNA
        or contains_raw_dna_material(record.to_dict())
    )


def contains_raw_dna_material(value: Any) -> bool:
    """Detect raw genetic payloads hidden below an otherwise safe record."""
    forbidden = ("rawdna", "rawgenetic", "genotype", "segment", "vcf", "bam", "fastq", "sequence", "allele")
    if isinstance(value, dict):
        for name, child in value.items():
            normalised = re.sub(r"[^a-z0-9]", "", str(name).casefold())
            # OneTree template parameter dictionaries can use opaque
            # FamilySearch-style IDs as keys. An ID beginning VCF is not a
            # variant-call field; still inspect its value for genetic fields.
            opaque_id = re.fullmatch(r"[A-Z0-9]{4}-[A-Z0-9]{3,4}", str(name))
            if (not opaque_id and any(token in normalised for token in forbidden)) or contains_raw_dna_material(child):
                return True
    elif isinstance(value, list):
        return any(contains_raw_dna_material(item) for item in value)
    return False


@dataclass(slots=True)
class Record:
    """Base record with a stable JSON-compatible representation."""

    id: str

    def to_dict(self) -> dict[str, Any]:
        return _plain(asdict(self))


@dataclass(slots=True)
class ExternalIdentifier:
    system: str
    value: str
    url: str | None = None
    verified: bool = False


@dataclass(slots=True)
class Name:
    value: str
    kind: str = "unknown"  # birth, married, preferred, alias, transcription
    language: str | None = None
    script: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    confidence: Confidence = Confidence.UNKNOWN
    # Optional structured parts as supplied (GEDCOM GIVN/SURN or /surname/).
    given: str | None = None
    surname: str | None = None


@dataclass(slots=True)
class Place(Record):
    name: str
    parent_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    external_ids: list[ExternalIdentifier] = field(default_factory=list)
    sensitivity: Sensitivity = Sensitivity.PUBLIC
    # How exactly the coordinates locate the place, as supplied or reviewed:
    # PLACE_PRECISIONS below. None means not stated, never "exact".
    precision: str | None = None


@dataclass(slots=True)
class Event(Record):
    kind: str
    date: str | None = None
    date_precision: str = "unknown"
    place_id: str | None = None
    participant_ids: list[str] = field(default_factory=list)
    description: str | None = None
    external_ids: list[ExternalIdentifier] = field(default_factory=list)
    sensitivity: Sensitivity = Sensitivity.PUBLIC


@dataclass(slots=True)
class Person(Record):
    names: list[Name] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list)
    external_ids: list[ExternalIdentifier] = field(default_factory=list)
    living: LivingStatus | bool | None = LivingStatus.UNKNOWN
    notes: str | None = None
    sensitivity: Sensitivity = Sensitivity.PRIVATE


@dataclass(slots=True)
class Relationship(Record):
    """A recorded link between two people.

    ``kind="parent"`` reads "subject's parent is object": ``subject_id`` is the
    child and ``object_id`` the parent. Spouse/partner links are symmetric.
    """

    subject_id: str
    object_id: str
    kind: str
    confidence: Confidence = Confidence.UNKNOWN
    claim_ids: list[str] = field(default_factory=list)
    start_date: str | None = None
    end_date: str | None = None
    sensitivity: Sensitivity = Sensitivity.PRIVATE
    # Supplied nature of a parent link: birth, adopted, foster, step, sealing or
    # another provider term. None means the input did not say; it is not "birth".
    pedigree: str | None = None
    # The source tree's own mark, e.g. WikiTree "uncertain" or GEDCOM "challenged".
    # It is displayed as the tree's statement and never raises ``confidence``.
    tree_status: str | None = None
    # An assessed probability (1–99 %) recorded with the reasoning in claims or
    # findings. Imports never set it; 0 and 100 are not estimates.
    estimate: int | None = None


@dataclass(slots=True)
class Source(Record):
    title: str
    source_type: str = "unknown"
    repository: str | None = None
    author: str | None = None
    publication: str | None = None
    url: str | None = None
    access_note: str | None = None
    licence: str | None = None
    external_ids: list[ExternalIdentifier] = field(default_factory=list)
    sensitivity: Sensitivity = Sensitivity.PRIVATE


@dataclass(slots=True)
class Citation(Record):
    source_id: str
    locator: str | None = None
    quotation: str | None = None
    transcription: str | None = None
    accessed_on: str | None = None
    sensitivity: Sensitivity = Sensitivity.PRIVATE


@dataclass(slots=True)
class Claim(Record):
    subject_id: str
    predicate: str
    value: str
    citation_ids: list[str] = field(default_factory=list)
    status: ClaimStatus = ClaimStatus.ASSERTED
    confidence: Confidence = Confidence.UNKNOWN
    rationale: str | None = None
    sensitivity: Sensitivity = Sensitivity.PRIVATE


@dataclass(slots=True)
class Evidence(Record):
    claim_id: str
    citation_id: str
    assessment: str
    supports: bool = True
    confidence: Confidence = Confidence.UNKNOWN
    sensitivity: Sensitivity = Sensitivity.PRIVATE


@dataclass(slots=True)
class Hypothesis(Record):
    statement: str
    related_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    status: str = "open"
    confidence: Confidence = Confidence.UNKNOWN
    sensitivity: Sensitivity = Sensitivity.PRIVATE


@dataclass(slots=True)
class ResearchQuestion(Record):
    question: str
    related_ids: list[str] = field(default_factory=list)
    priority: str = "normal"
    status: str = "open"
    sensitivity: Sensitivity = Sensitivity.PRIVATE


@dataclass(slots=True)
class Finding(Record):
    conclusion: str
    related_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    status: str = "draft"
    confidence: Confidence = Confidence.UNKNOWN
    sensitivity: Sensitivity = Sensitivity.PRIVATE
    # ISO date (YYYY, YYYY-MM or YYYY-MM-DD) the finding was reached; dates a findings log.
    recorded_on: str | None = None
    # What the finding does not establish: a copy rather than the original, an
    # identification it leaves open. Shown beside the conclusion, never inside it.
    limitations: str | None = None
    # Records the finding rests on directly, when no claim-level evidence exists.
    citation_ids: list[str] = field(default_factory=list)
    # A project's own grouping, e.g. "vital", "relationship" or "record".
    kind: str | None = None


@dataclass(slots=True)
class Study(Record):
    """A written research study: why it was undertaken, the account and its conclusion.

    ``body`` uses a small Markdown subset (headings, paragraphs, lists, emphasis,
    http(s) links and ``[[record-id|label]]`` references). ``related_ids`` lists
    the people, places, sources, findings and questions it concerns; a study
    is published only when every related record is public.
    """

    title: str
    summary: str | None = None
    rationale: str | None = None
    body: str | None = None
    conclusion: str | None = None
    related_ids: list[str] = field(default_factory=list)
    status: str = "draft"
    updated_on: str | None = None
    sensitivity: Sensitivity = Sensitivity.PRIVATE


@dataclass(slots=True)
class ImportProvenance(Record):
    """Durable, non-raw audit metadata for one adapter ingestion batch."""

    adapter: str
    observations: list[dict[str, Any]] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    sensitivity: Sensitivity = Sensitivity.PRIVATE


MODEL_TYPES: dict[str, type[Record]] = {
    cls.__name__: cls
    for cls in (Place, Event, Person, Relationship, Source, Citation, Claim,
                Evidence, Hypothesis, ResearchQuestion, Finding, Study, ImportProvenance)
}
PLACE_PRECISIONS = ("exact", "building", "street", "settlement", "parish", "district", "county", "region", "country", "approximate")


def record_from_dict(kind: str, data: dict[str, Any]) -> Record:
    """Rehydrate a record produced by :meth:`Record.to_dict`."""
    try:
        cls = MODEL_TYPES[kind]
    except KeyError as error:
        raise ValueError(f"unsupported record type: {kind}") from error
    converted = dict(data)
    for key in ("confidence", "sensitivity", "status"):
        if key in converted and converted[key] is not None:
            if key == "confidence":
                converted[key] = Confidence(converted[key])
            elif key == "sensitivity":
                converted[key] = AccessLevel(converted[key])
            elif cls is Claim:
                converted[key] = ClaimStatus(converted[key])
    if "living" in converted and isinstance(converted["living"], str):
        converted["living"] = LivingStatus(converted["living"])
    if "external_ids" in converted:
        converted["external_ids"] = [ExternalIdentifier(**item) for item in converted["external_ids"]]
    if "names" in converted:
        converted["names"] = [Name(**{**item, "confidence": Confidence(item.get("confidence", "unknown"))}) for item in converted["names"]]
    return cls(**converted)
