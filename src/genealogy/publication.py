"""Explicit, conservative review of imported historical facts for publication."""
from __future__ import annotations

from datetime import date
import re
from urllib.parse import urlsplit

from .adapters.base import AdapterBatch
from .case import ResearchCase
from .models import AccessLevel, ClaimStatus, Confidence, ImportProvenance, LivingStatus


# An "about 1800" birth is treated as possibly up to this many years later.
APPROXIMATE_MARGIN_YEARS = 10
HISTORICAL_YEARS = 120

_MONTHS = {name: index for index, name in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1
)}


def _exact_date_year(value: str) -> int | None:
    """Recognize complete year/month/day forms, never a year inside free text."""
    iso = re.fullmatch(r"([0-9]{4})(?:-([0-9]{2})(?:-([0-9]{2}))?)?", value)
    textual = re.fullmatch(r"(?:([0-9]{1,2})\s*)?(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s*([0-9]{4})", value)
    if iso:
        year, month, day = int(iso[1]), int(iso[2] or 1), int(iso[3] or 1)
    elif textual:
        year, month, day = int(textual[3]), _MONTHS[textual[2]], int(textual[1] or 1)
    else:
        return None
    try:
        date(year, month, day)
    except ValueError:
        return None
    return year


def _birth_upper_year(value: str | None) -> int | None:
    """Conservative upper year for exact dates or explicitly bounded GEDCOM dates.

    Approximate dates (ABT/CAL/EST) are given a fixed margin of
    APPROXIMATE_MARGIN_YEARS; open-ended dates (AFT/FROM) have no upper bound.
    Unsupported calendars, placeholders and free text fail closed. The original
    imported date remains unchanged for display and provenance.
    """
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.upper().replace(".", " ").split())
    exact = _exact_date_year(normalized)
    if exact is not None:
        return exact
    approximate = re.fullmatch(r"(?:ABT|ABOUT|CAL|EST|CIRCA|CA|C) (.+)", normalized)
    if approximate:
        year = _exact_date_year(approximate[1])
        return year + APPROXIMATE_MARGIN_YEARS if year is not None else None
    upper = re.fullmatch(r"(?:BEF|TO) (.+)", normalized)
    if upper:
        return _exact_date_year(upper[1])
    interval = re.fullmatch(r"(?:BET (.+) AND (.+)|FROM (.+) TO (.+))", normalized)
    if interval:
        lower_text, upper_text = (interval[1], interval[2]) if interval[1] else (interval[3], interval[4])
        lower_year, upper_year = _exact_date_year(lower_text), _exact_date_year(upper_text)
        if lower_year is not None and upper_year is not None and lower_year <= upper_year:
            return upper_year
    return None


def birth_upper_year(value: str | None) -> int | None:
    """The latest year a supplied birth date allows, or None when it cannot be assessed.

    Exact dates give their year; ``BEF``/``BET … AND …``/``FROM … TO …`` their
    upper bound; ``ABT``/``EST``/``CAL`` the year plus APPROXIMATE_MARGIN_YEARS.
    Open-ended, placeholder and free-text values return None.
    """
    return _birth_upper_year(value)


def is_historical_birth(value: str | None, *, current_year: int | None = None) -> bool:
    """True when a supplied birth date is assuredly over HISTORICAL_YEARS ago.

    This is the publication heuristic used by the import review, available to
    project tools so every surface applies one rule. WikiTree-style ``1850-00-00``
    values should first be normalised with :func:`genealogy.dates.wikitree_date`.
    It never proves that a person has died.
    """
    upper = _birth_upper_year(value)
    return upper is not None and upper < (current_year or date.today().year) - HISTORICAL_YEARS


def review_deceased(case: ResearchCase, batch: AdapterBatch, *, reviewed_sources: bool = False) -> int:
    """Promote only adapter-vetted basic facts; retain original records privately.

    Import assertions remain assertions. Notes, quotations and transcriptions
    stay private. Bibliography and citation locators require reviewed_sources
    and must support an eligible public historical subject.
    """
    eligible_ids = {
        identifier for observation in batch.records
        for identifier in observation.provenance.get("publishable_entity_ids", [])
    }
    events = {record.id: record for record in case.records("Event")}
    people: set[str] = set()
    for person in case.records("Person"):
        if person.id not in eligible_ids or person.sensitivity not in (AccessLevel.PRIVATE, AccessLevel.PUBLIC):
            continue
        if person.living is True or person.living == LivingStatus.LIVING:
            continue
        historical = any(
            event.kind.casefold() in ("birth", "birt") and is_historical_birth(event.date)
            for event in (events[eid] for eid in person.event_ids if eid in events)
        )
        if person.living is False or person.living == LivingStatus.DECEASED or historical:
            people.add(person.id)
    public_events = {
        event.id for event in events.values()
        if event.id in eligible_ids and event.sensitivity in (AccessLevel.PRIVATE, AccessLevel.PUBLIC)
        and event.participant_ids and set(event.participant_ids).issubset(people)
    }
    public_places = {events[eid].place_id for eid in public_events if events[eid].place_id in eligible_ids}
    claims = {record.id: record for record in case.records("Claim")}
    citations = {record.id: record for record in case.records("Citation")}
    sources = {record.id: record for record in case.records("Source")}
    def vetted(record):
        return record.id in eligible_ids and record.sensitivity in (AccessLevel.PRIVATE, AccessLevel.PUBLIC)
    source_ids: set[str] = set()
    citation_ids: set[str] = set()
    claim_ids: set[str] = set()
    if reviewed_sources:
        for claim in claims.values():
            if not vetted(claim) or claim.subject_id not in people | public_events or claim.predicate != "documented-in":
                continue
            usable = [citations[cid] for cid in claim.citation_ids if cid in citations
                      and vetted(citations[cid]) and citations[cid].source_id in sources
                      and vetted(sources[citations[cid].source_id]) and not sources[citations[cid].source_id].licence]
            if usable and len(usable) == len(claim.citation_ids) and all(claim.value == citation.source_id for citation in usable):
                claim_ids.add(claim.id)
                citation_ids.update(citation.id for citation in usable)
                source_ids.update(citation.source_id for citation in usable)
    # The recorded sex of an eligible historical person is a basic tree fact,
    # published as the export's assertion so dossiers can say father/mother.
    claim_ids.update(
        claim.id for claim in claims.values()
        if claim.predicate == "sex" and claim.subject_id in people and vetted(claim) and not claim.citation_ids
    )
    originals = []
    for records in case.record_sets.values():
        for record in records:
            kind = type(record).__name__
            publish = (
                kind == "Source" and record.id in source_ids
                or kind == "Citation" and record.id in citation_ids
                or kind == "Claim" and record.id in claim_ids
                or kind == "Person" and record.id in people
                or kind == "Event" and record.id in public_events
                or kind == "Place" and record.id in public_places
                or kind == "Relationship" and record.id in eligible_ids
                and record.subject_id in people and record.object_id in people
                and record.confidence is not Confidence.DISPROVED
            )
            if not publish or record.sensitivity not in (AccessLevel.PRIVATE, AccessLevel.PUBLIC):
                continue
            originals.append({"record_type": kind, "record": record.to_dict()})
            record.sensitivity = AccessLevel.PUBLIC
            if kind == "Person":
                record.living = LivingStatus.DECEASED
                record.notes = None
                record.event_ids = [eid for eid in record.event_ids if eid in public_events]
            elif kind == "Event":
                record.description = None
            elif kind == "Source":
                record.access_note = None
                try:
                    url = urlsplit(record.url or "")
                    if url.scheme not in ("http", "https") or not url.netloc or url.username or url.password:
                        record.url = None
                except ValueError:
                    record.url = None
            elif kind == "Citation":
                record.quotation = None
                record.transcription = None
                record.accessed_on = None
            elif kind == "Claim":
                record.status = ClaimStatus.ASSERTED
                record.confidence = Confidence.UNKNOWN
                record.rationale = ("Imported tree assertion; not independently assessed" if record.predicate == "sex"
                                    else "Imported source association; not independently assessed")
            elif kind == "Relationship":
                record.claim_ids = []
                record.confidence = Confidence.UNKNOWN
            # Imported external links may contain private paths or arbitrary URL schemes.
            if hasattr(record, "external_ids"):
                record.external_ids = []
    if originals:
        case.add(ImportProvenance(
            id="import-review:deceased", adapter="publication-review",
            observations=originals, entity_ids=[item["record"]["id"] for item in originals],
        ))
    return len(people)
