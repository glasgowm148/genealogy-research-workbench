"""Platform-neutral operations for evidence-led research cases.

The service deliberately accepts and returns core model objects.  Importers,
user interfaces, and remote services belong in adapters above this layer.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, TypeVar

from .case import NESTED_REFERENCES, CaseStore, ResearchCase, reference_values, validate_case
from .models import MODEL_TYPES, Claim, Evidence, Finding, Hypothesis, Record, ResearchQuestion


TRecord = TypeVar("TRecord", bound=Record)


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One record matched by :meth:`ResearchService.search_records`."""

    record: Record
    matched_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceCompleteness:
    """Counts that show whether conclusions are connected to evidence."""

    claims: int
    claims_with_citations: int
    claims_with_evidence: int
    findings: int
    findings_with_evidence: int

    @property
    def complete(self) -> bool:
        return (
            self.claims_with_citations == self.claims
            and self.claims_with_evidence == self.claims
            and self.findings_with_evidence == self.findings
        )


@dataclass(frozen=True, slots=True)
class UnresolvedWork:
    """Open work and evidence gaps, represented as stable record ids."""

    open_question_ids: tuple[str, ...]
    open_hypothesis_ids: tuple[str, ...]
    draft_finding_ids: tuple[str, ...]
    uncited_claim_ids: tuple[str, ...]
    unevidenced_claim_ids: tuple[str, ...]
    unsupported_finding_ids: tuple[str, ...]

    @property
    def is_clear(self) -> bool:
        return not any((
            self.open_question_ids, self.open_hypothesis_ids, self.draft_finding_ids,
            self.uncited_claim_ids, self.unevidenced_claim_ids,
            self.unsupported_finding_ids,
        ))


class ResearchService:
    """Case-oriented research commands backed by a local :class:`CaseStore`.

    Every write builds a fresh valid case and persists it through ``CaseStore``.
    The store's replace operation therefore remains the sole durable write path.
    """

    def __init__(self, store: CaseStore | str | Path) -> None:
        self.store = store if isinstance(store, CaseStore) else CaseStore(store)

    def create_case(self, case_id: str, title: str, summary: str = "") -> ResearchCase:
        """Create a new case without replacing an existing on-disk case."""
        path = self.store.path_for(case_id)
        if path.exists():
            raise ValueError(f"research case already exists: {case_id}")
        case = ResearchCase(id=case_id, title=title, summary=summary)
        return self._persist(case)

    def list_cases(self) -> list[ResearchCase]:
        """Load cases in id order; incomplete temporary files are ignored."""
        if not self.store.directory.exists():
            return []
        return [self.store.load(path.stem) for path in sorted(self.store.directory.glob("*.json"))]

    def get_case(self, case_id: str) -> ResearchCase:
        return self.store.load(case_id)

    def add_record(self, case_id: str, record: TRecord) -> TRecord:
        """Add any core record, for example a source needed by a later claim."""
        return self._add(case_id, record)

    def add_question(self, case_id: str, question: ResearchQuestion) -> ResearchQuestion:
        return self._add(case_id, question)

    def add_finding(self, case_id: str, finding: Finding) -> Finding:
        return self._add(case_id, finding)

    def add_hypothesis(self, case_id: str, hypothesis: Hypothesis) -> Hypothesis:
        return self._add(case_id, hypothesis)

    def add_claim(self, case_id: str, claim: Claim) -> Claim:
        return self._add(case_id, claim)

    def add_evidence(self, case_id: str, evidence: Evidence) -> Evidence:
        return self._add(case_id, evidence)

    def update_question(self, case_id: str, record_id: str, **changes: Any) -> ResearchQuestion:
        return self._update(case_id, ResearchQuestion, record_id, **changes)

    def update_finding(self, case_id: str, record_id: str, **changes: Any) -> Finding:
        return self._update(case_id, Finding, record_id, **changes)

    def update_hypothesis(self, case_id: str, record_id: str, **changes: Any) -> Hypothesis:
        return self._update(case_id, Hypothesis, record_id, **changes)

    def update_claim(self, case_id: str, record_id: str, **changes: Any) -> Claim:
        return self._update(case_id, Claim, record_id, **changes)

    def update_evidence(self, case_id: str, record_id: str, **changes: Any) -> Evidence:
        return self._update(case_id, Evidence, record_id, **changes)

    def query_records(
        self, case_id: str, *, kind: type[TRecord] | str | None = None,
        ids: Iterable[str] | None = None, related_to: str | None = None,
    ) -> list[TRecord | Record]:
        """Return records filtered by type, id, or an explicit relation reference."""
        case = self.get_case(case_id)
        if isinstance(kind, str) and kind not in MODEL_TYPES:
            raise ValueError(f"unsupported record type: {kind}")
        requested_ids = set(ids) if ids is not None else None
        records = case.records(kind) if kind is not None else [
            record for records in case.record_sets.values() for record in records
        ]
        return [record for record in records if (
            (requested_ids is None or record.id in requested_ids)
            and (related_to is None or related_to in self._references(record))
        )]

    def search_records(
        self, case_id: str, text: str, *, kind: type[Record] | str | None = None,
    ) -> list[SearchResult]:
        """Case-insensitively search text-bearing fields without adapter assumptions."""
        term = text.strip().casefold()
        if not term:
            raise ValueError("search text must not be blank")
        results: list[SearchResult] = []
        for record in self.query_records(case_id, kind=kind):
            fields = tuple(self._matching_paths(record.to_dict(), term))
            if fields:
                results.append(SearchResult(record, fields))
        return results

    def evidence_completeness(self, case_id: str) -> EvidenceCompleteness:
        case = self.get_case(case_id)
        claims = self._records(case, Claim)
        findings = self._records(case, Finding)
        evidence_by_claim = {item.claim_id for item in self._records(case, Evidence)}
        return EvidenceCompleteness(
            claims=len(claims),
            claims_with_citations=sum(bool(item.citation_ids) for item in claims),
            claims_with_evidence=sum(item.id in evidence_by_claim for item in claims),
            findings=len(findings),
            findings_with_evidence=sum(bool(item.evidence_ids) for item in findings),
        )

    def unresolved_work(self, case_id: str) -> UnresolvedWork:
        case = self.get_case(case_id)
        evidence_by_claim = {item.claim_id for item in self._records(case, Evidence)}
        return UnresolvedWork(
            open_question_ids=tuple(item.id for item in self._records(case, ResearchQuestion)
                                    if item.status.casefold() not in {"resolved", "closed"}),
            open_hypothesis_ids=tuple(item.id for item in self._records(case, Hypothesis)
                                      if item.status.casefold() not in {"resolved", "closed", "rejected"}),
            draft_finding_ids=tuple(item.id for item in self._records(case, Finding)
                                    if item.status.casefold() in {"draft", "open"}),
            uncited_claim_ids=tuple(item.id for item in self._records(case, Claim) if not item.citation_ids),
            unevidenced_claim_ids=tuple(item.id for item in self._records(case, Claim)
                                        if item.id not in evidence_by_claim),
            unsupported_finding_ids=tuple(item.id for item in self._records(case, Finding)
                                           if not item.evidence_ids),
        )

    def research_brief(self, case_id: str) -> str:
        """Render a durable, platform-neutral Markdown research handoff."""
        case = self.get_case(case_id)
        completeness = self.evidence_completeness(case_id)
        unresolved = self.unresolved_work(case_id)
        lines = [
            f"# {case.title}",
            "",
            case.summary or "No case summary recorded.",
            "",
            "## Evidence coverage",
            "",
            f"- Claims with citations: {completeness.claims_with_citations}/{completeness.claims}",
            f"- Claims with evidence assessments: {completeness.claims_with_evidence}/{completeness.claims}",
            f"- Findings with evidence: {completeness.findings_with_evidence}/{completeness.findings}",
            "",
            "## Open research questions",
            "",
        ]
        questions = {
            item.id: item for item in self._records(case, ResearchQuestion)
            if item.id in unresolved.open_question_ids
        }
        lines.extend(
            f"- **{record.id}** ({record.priority}): {record.question}"
            for record in questions.values()
        )
        if not questions:
            lines.append("- None.")
        lines.extend(["", "## Open hypotheses", ""])
        hypotheses = {
            item.id: item for item in self._records(case, Hypothesis)
            if item.id in unresolved.open_hypothesis_ids
        }
        lines.extend(f"- **{record.id}**: {record.statement}" for record in hypotheses.values())
        if not hypotheses:
            lines.append("- None.")
        lines.extend(["", "## Findings", ""])
        findings = self._records(case, Finding)
        lines.extend(
            f"- **{record.id}** [{record.status}; {record.confidence}]: {record.conclusion}"
            for record in findings
        )
        if not findings:
            lines.append("- None.")
        lines.extend(["", "## Evidence gaps", ""])
        gap_groups = (
            ("Claims without citations", unresolved.uncited_claim_ids),
            ("Claims without evidence assessments", unresolved.unevidenced_claim_ids),
            ("Findings without evidence", unresolved.unsupported_finding_ids),
        )
        for label, ids in gap_groups:
            lines.append(f"- {label}: {', '.join(ids) if ids else 'none'}")
        return "\n".join(lines) + "\n"

    def _add(self, case_id: str, record: TRecord) -> TRecord:
        case = self._copy_case(case_id)
        case.add(record)
        self._persist(case)
        return record

    def _update(self, case_id: str, kind: type[TRecord], record_id: str, **changes: Any) -> TRecord:
        if "id" in changes and changes["id"] != record_id:
            raise ValueError("record ids cannot be changed")
        case = self._copy_case(case_id)
        records = case.records(kind)
        for index, record in enumerate(records):
            if record.id == record_id:
                updated = replace(record, **changes)
                records[index] = updated
                case.updated_at = datetime.now(UTC).isoformat()
                self._persist(case)
                return updated
        raise KeyError(f"{kind.__name__} not found: {record_id}")

    def _copy_case(self, case_id: str) -> ResearchCase:
        return ResearchCase.from_dict(self.get_case(case_id).to_dict())

    def _persist(self, case: ResearchCase) -> ResearchCase:
        errors = validate_case(case)
        if errors:
            raise ValueError("invalid research operation:\n" + "\n".join(f"- {error}" for error in errors))
        self.store.save(case)
        return case

    @staticmethod
    def _records(case: ResearchCase, kind: type[TRecord]) -> list[TRecord]:
        return [record for record in case.records(kind) if isinstance(record, kind)]

    @staticmethod
    def _references(record: Record) -> tuple[str, ...]:
        references: list[str] = []
        for name in (
            "parent_id", "place_id", "subject_id", "object_id", "source_id", "claim_id",
            "citation_id", "event_ids", "participant_ids", "claim_ids", "citation_ids",
            "related_ids", "evidence_ids", "entity_ids",
        ):
            value = getattr(record, name, None)
            if isinstance(value, str):
                references.append(value)
            elif isinstance(value, list):
                references.extend(item for item in value if isinstance(item, str))
        references.extend(rid for nested in NESTED_REFERENCES for rid in reference_values(record, nested))
        return tuple(references)

    @staticmethod
    def _matching_paths(value: Any, term: str, prefix: str = "") -> Iterable[str]:
        if isinstance(value, str):
            if term in value.casefold():
                yield prefix or "$"
            return
        if isinstance(value, dict):
            for name, child in value.items():
                path = f"{prefix}.{name}" if prefix else str(name)
                yield from ResearchService._matching_paths(child, term, path)
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                yield from ResearchService._matching_paths(child, term, f"{prefix}[{index}]")
