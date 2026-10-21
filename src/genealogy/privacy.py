"""Fail-closed privacy checks for publishing and interchange."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .case import NESTED_REFERENCES, ResearchCase, reference_values, validate_case
from .markup import references
from .models import AccessLevel, LivingStatus, Person, Record, Sensitivity, Source, Study, access_level, is_raw_dna


class PrivacyViolation(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PrivacyPolicy:
    """Only explicitly public, non-living material can leave a case by default."""

    allow_living: bool = False
    allow_licensed: bool = False
    allow_restricted: bool = False

    def __post_init__(self) -> None:
        for name in ("allow_living", "allow_licensed", "allow_restricted"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")

    def permits(self, record: Record) -> bool:
        """Apply access and living rules cumulatively, never as alternatives."""
        sensitivity = access_level(getattr(record, "sensitivity", Sensitivity.PRIVATE))
        if sensitivity is None or sensitivity is AccessLevel.RAW_DNA:
            return False
        access_permitted = (
            sensitivity is AccessLevel.PUBLIC
            or (sensitivity is AccessLevel.RESTRICTED and self.allow_restricted)
            or (sensitivity is AccessLevel.LICENSED and self.allow_licensed)
        )
        if not access_permitted:
            return False
        if isinstance(record, Person) and not (
            type(record.living) is bool and record.living is False
            or isinstance(record.living, LivingStatus) and record.living is LivingStatus.DECEASED
        ):
            return self.allow_living
        return True

    def require(self, record: Record) -> None:
        if not self.permits(record):
            raise PrivacyViolation(f"publication rejected for {record.id}: protected or non-public record")

    def require_source(self, source: Source) -> None:
        if source.sensitivity is Sensitivity.RAW_DNA:
            raise PrivacyViolation("raw DNA is never accepted by the public export boundary")
        self.require(source)

    def filter_public(self, case: ResearchCase) -> dict[str, list[dict]]:
        """Produce an export-safe projection; it never leaks omitted records."""
        errors = validate_case(case)
        if errors:
            raise PrivacyViolation("invalid research case:\n" + "\n".join(f"- {error}" for error in errors))
        self.reject_raw_dna(record for records in case.record_sets.values() for record in records)
        allowed_ids = {record.id for records in case.record_sets.values() for record in records
                       if self.permits(record)}
        # A relationship, claim or evidence would disclose a protected record by
        # implication, even when its own access level says public.
        def dependencies(record: Record) -> set[str]:
            values: set[str] = set()
            for field in (
                "subject_id", "object_id", "source_id", "citation_id", "claim_id",
                "place_id", "parent_id",
            ):
                value = getattr(record, field, None)
                if value:
                    values.add(value)
            for field in (
                "citation_ids", "claim_ids", "participant_ids", "event_ids",
                "related_ids", "evidence_ids",
            ):
                values.update(value for value in getattr(record, field, []) if value)
            # A finding that regraded a withheld link or claim is withheld with
            # it, as is a study grouping a withheld person or citing withheld evidence.
            values.update(rid for nested in NESTED_REFERENCES for rid in reference_values(record, nested))
            if isinstance(record, Study):
                # A study naming a withheld record in its prose is withheld too.
                for text in (record.summary, record.rationale, record.body, record.conclusion):
                    values.update(references(text))
            return values
        # Remove dependent records to a fixed point.  This prevents an otherwise
        # public evidence record from exposing the id of a claim removed because
        # it concerned a protected person or source.
        visible_ids = set(allowed_ids)
        while True:
            next_ids = {
                record.id
                for records in case.record_sets.values()
                for record in records
                if record.id in visible_ids and dependencies(record).issubset(visible_ids)
            }
            if next_ids == visible_ids:
                break
            visible_ids = next_ids
        result: dict[str, list[dict]] = {}
        for kind, records in case.record_sets.items():
            allowed = [
                record.to_dict()
                for record in records
                if record.id in visible_ids and self.permits(record)
            ]
            if allowed:
                result[kind] = allowed
        return result

    def reject_raw_dna(self, records: Iterable[Record]) -> None:
        for record in records:
            if is_raw_dna(record):
                raise PrivacyViolation("raw DNA material cannot be imported into a case")
