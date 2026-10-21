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
    # Ids this person was known by before a merge or an id change. The site keeps
    # a page at each old address that sends readers to this one; references in
    # the case must still use the current id.
    former_ids: list[str] = field(default_factory=list)


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
    # The project's own grade for ``confidence``, defined under [grades] in
    # genealogy.toml (e.g. "strongly_supported"). ``confidence`` stays the
    # standard grade it counts as; the site prints the project's wording.
    grade: str | None = None
    # Why the link is shown (or was rejected), in a sentence. Without it the
    # site gives the first linked claim's rationale.
    rationale: str | None = None


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
    # Your reading of the record in your own words (a genealogical abstract):
    # what it states, as distinct from a verbatim quotation or transcription.
    abstract: str | None = None
    quotation: str | None = None
    transcription: str | None = None
    accessed_on: str | None = None
    sensitivity: Sensitivity = Sensitivity.PRIVATE
    # The record's form and its informant's knowledge, in the standard terms
    # (CITATION_QUALITIES, CITATION_INFORMATION below). They describe the
    # record, never how far the claim it supports is believed. None means not
    # stated.
    quality: str | None = None
    information: str | None = None


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
    grade: str | None = None  # see Relationship.grade


@dataclass(slots=True)
class Evidence(Record):
    claim_id: str
    citation_id: str
    assessment: str
    supports: bool = True
    confidence: Confidence = Confidence.UNKNOWN
    sensitivity: Sensitivity = Sensitivity.PRIVATE
    grade: str | None = None  # see Relationship.grade
    # What this record cannot show for the claim (no age stated, a later copy);
    # the reader sees it beside the assessment.
    limitation: str | None = None


@dataclass(slots=True)
class Hypothesis(Record):
    statement: str
    related_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    status: str = "open"
    confidence: Confidence = Confidence.UNKNOWN
    sensitivity: Sensitivity = Sensitivity.PRIVATE
    grade: str | None = None  # see Relationship.grade
    # The researcher's own points for and against, one plain sentence each.
    # Printed as recorded beside competing hypotheses; never counted or scored.
    supports: list[str] = field(default_factory=list)
    objections: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ResearchQuestion(Record):
    question: str
    related_ids: list[str] = field(default_factory=list)
    priority: str = "normal"
    status: str = "open"
    sensitivity: Sensitivity = Sensitivity.PRIVATE
    # What evidence would answer the question, and the next record to check.
    # Shown on open questions; a blank prints "Not yet identified", never a guess.
    resolves: str | None = None
    next_record: str | None = None


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
    # The relationships and claims this finding reassessed, each
    # {"record_id", "before", "after", "note"}: before and after are confidence
    # values or project grade keys; before is None for a newly recorded link.
    changes: list[dict[str, Any]] = field(default_factory=list)


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
    # The households or groups the study compares, each {"id", "title",
    # "member_ids", "note"}; membership says who is studied together, never
    # that they are kin. A study naming a withheld member is withheld.
    groups: list[dict[str, Any]] = field(default_factory=list)
    # How the groups connect, each {"from", "to", "status", "note",
    # "evidence_ids"}: from and to are group ids, status a confidence value
    # or project grade key, evidence_ids Evidence or Citation records.
    links: list[dict[str, Any]] = field(default_factory=list)
    # Records still to inspect, as plain text.
    next_records: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Search(Record):
    """One search made for the research log: where you looked and what you found.

    A search that found nothing is recorded like any other, so the next
    researcher need not repeat it. ``related_ids`` lists the people, places or
    sources searched for; ``citation_ids`` the records found, if any. A search
    is published only when every related and cited record is public.
    """

    search: str  # repository, collection, years and names searched
    result: str  # what was found, including "nothing"
    related_ids: list[str] = field(default_factory=list)
    searched_on: str | None = None  # ISO date (YYYY, YYYY-MM or YYYY-MM-DD)
    limitation: str | None = None  # what the search could not cover: gaps, indexes only
    citation_ids: list[str] = field(default_factory=list)
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
                Evidence, Hypothesis, ResearchQuestion, Finding, Study, Search, ImportProvenance)
}
# Evidence Explained terms: an original record, a derivative (copy, transcript,
# abstract or index) or an authored work; primary information from someone with
# first-hand knowledge, secondary information from hearsay, or undetermined.
CITATION_QUALITIES = ("original", "derivative", "authored")
CITATION_INFORMATION = ("primary", "secondary", "undetermined")
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
