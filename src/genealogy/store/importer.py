"""Load workbench records into the project database, idempotently and traceably.

Two inputs use this path:

* **Legacy JSON research cases** (``genealogy upgrade``): every case file under
  ``project.case_directory`` is loaded with its record ids kept, so existing
  sites keep their routes. Several cases that hold the same record id refer to
  *one* entity: identical copies are loaded once, differing copies are kept as
  ``legacy_item`` conflicts for review, never silently overwritten. Original case
  files are left untouched.
* **Genealogy files** (``genealogy import``): GEDCOM and OneTree adapter batches.
  People are matched to earlier imports by durable identifiers (GEDCOM ``UID``,
  ``_UID``, ``REFN``, ``EXID``, WikiTree IDs); file-local cross-reference ids are
  used only within the same named import lineage and reported. An imported row
  that was never edited locally follows a changed input; a locally edited row
  is kept and the incoming difference is recorded as a conflict. The original
  file is retained as an immutable asset and unsupported structures are kept
  verbatim as ``legacy_item`` rows.

Every created row gets an ``import_origin`` naming the input and pointer.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
import hashlib
import json
import re
from typing import Any

from ..models import (
    Citation, Claim, Event, Evidence, Finding, Haplogroup, Hypothesis, ImportProvenance, Person, Place, Record,
    Relationship, ResearchQuestion, Search, Source, Study,
)
from .core import Tx
from .services import NameInput, Research, stable_id

DATE_KIND = {"exact": "exact", "about": "about", "before": "before", "after": "after", "range": "range",
             "between": "between", "estimated": "estimated", "calculated": "calculated", "unknown": "unknown",
             "year": "exact", "month": "exact", "day": "exact"}
PEDIGREE = {"birth": "biological", "biological": "biological", "natural": "biological", "adopted": "adoptive",
            "adoptive": "adoptive", "step": "step", "foster": "foster", "sealing": "sealing", "guardian": "guardian"}
VITAL_PREDICATES = {"birth", "death", "baptism", "christening", "burial", "marriage", "sex", "age"}
NEGATIVE_RESULT = re.compile(r"^\s*(nothing|none|no\s|not found|no result|found nothing)", re.IGNORECASE)
DURABLE_SYSTEMS = re.compile(r"^(wikitree|one-tree|familysearch|gedcom:(uid|_uid|refn|exid|afn|rfn).*)$", re.IGNORECASE)
#: Adapter systems whose identifiers are another system's ids (OneTree rows are WikiTree profiles).
CANONICAL_SYSTEM = {"one-tree": "wikitree"}


def _iso(value: str | None) -> str | None:
    if value and re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", value):
        return value
    return None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class RecordLoader:
    """Writes neutral :mod:`genealogy.models` records through the domain services."""

    def __init__(self, research: Research, tx: Tx, *, batch_id: str | None, input_path: str, origin: str,
                 input_sha256: str | None = None, id_for: Callable[[str], str] | None = None,
                 private_details: bool = False):
        self.research = research
        self.store = research.store
        self.tx = tx
        self.batch_id = batch_id
        self.input_path = input_path
        self.input_sha256 = input_sha256
        self.origin = origin  # 'research' for cases, 'imported' for genealogy files
        self.id_for = id_for or (lambda value: value)
        self.report: dict[str, int] = {}
        self.conflicts: list[str] = []
        # Imported notes, descriptions, access notes and quotations stay private
        # even when the record they belong to is publishable.
        self.private_details = private_details

    def private_note(self, entity_id: str, text: str | None, kind: str) -> str | None:
        if not self.private_details or not text:
            return text
        self.research.add_note(self.tx, id=stable_id("not", entity_id, kind), kind=kind, text=text,
                               links=[(entity_id, "about")])
        return None

    # ------------------------------------------------------------ helpers
    def count(self, key: str) -> None:
        self.report[key] = self.report.get(key, 0) + 1

    def trace(self, entity_id: str, pointer: str, content_sha256: str | None = None) -> None:
        if not self.store.one("SELECT 1 FROM import_origin WHERE entity_id=? AND import_batch_id=? AND input_path=? "
                              "AND pointer=?", (entity_id, self.batch_id, self.input_path, pointer)):
            self.tx.insert("import_origin", {"entity_id": entity_id, "import_batch_id": self.batch_id,
                                             "input_path": self.input_path, "pointer": pointer,
                                             "input_sha256": self.input_sha256, "content_sha256": content_sha256})

    def conflict(self, record: Record, reason: str) -> None:
        item_id = stable_id("leg", self.input_path, record.id, "conflict", _json(record.to_dict()))
        if not self.store.get("legacy_item", item_id):
            self.tx.insert("legacy_item", {
                "id": item_id, "import_batch_id": self.batch_id, "input_path": self.input_path,
                "pointer": f"{type(record).__name__}/{record.id}/{item_id[-8:]}", "disposition": "conflict",
                "reason": reason, "payload_json": _json(record.to_dict()),
                "entity_id": self.id_for(record.id) if self.store.entity_type(self.id_for(record.id)) else None})
            self.conflicts.append(f"{record.id}: {reason}")
        self.count("conflicts kept for review")

    def ids(self, values: Iterable[str]) -> list[str]:
        return [self.id_for(value) for value in values if value]

    def existing(self, record: Record) -> str | None:
        return self.store.entity_type(self.id_for(record.id))

    # ------------------------------------------------------------ loading
    def load(self, records: Iterable[Record]) -> dict[str, int]:
        ordered = sorted(records, key=lambda record: ORDER.get(type(record).__name__, 99))
        self.person_events = {record.id: set(record.event_ids) for record in ordered if isinstance(record, Person)}
        for record in ordered:
            handler = getattr(self, f"_{type(record).__name__}", None)
            if handler is None:
                self.count(f"unsupported {type(record).__name__}")
                continue
            digest = hashlib.sha256(_json(record.to_dict()).encode("utf-8")).hexdigest()
            if self.existing(record):
                self._same_or_conflict(record, digest)
                continue
            handler(record)
            if self.store.entity_type(self.id_for(record.id)):
                self.trace(self.id_for(record.id), f"{type(record).__name__}/{record.id}", digest)
                self.count(type(record).__name__)
        return self.report

    def _same_or_conflict(self, record: Record, digest: str) -> None:
        """An id already loaded: identical content is the same entity; anything else is kept for review."""
        if self.store.one("SELECT 1 FROM import_origin WHERE entity_id=? AND content_sha256=?",
                          (self.id_for(record.id), digest)):
            self.count(f"{type(record).__name__} already present")
            return
        self.conflict(record, "the same id was loaded earlier with different content; the earlier content was kept")

    def _access(self, record: Record) -> str:
        value = getattr(record, "sensitivity", "private")
        return getattr(value, "value", value) or "private"

    def _Place(self, record: Place) -> None:
        self.research.create_place(self.tx, id=self.id_for(record.id), name=record.name,
                                   parent_id=self.id_for(record.parent_id) if record.parent_id else None,
                                   latitude=record.latitude, longitude=record.longitude, precision=record.precision,
                                   region=record.region, access=self._access(record))
        for ident in record.external_ids:
            self.research.map_external(self.tx, self.id_for(record.id), ident.system, ident.value, url=ident.url,
                                       status="alias")

    def _Person(self, record: Person) -> None:
        living = getattr(record.living, "value", record.living)
        if living is True:
            living = "living"
        elif living is False:
            living = "deceased"
        names = [NameInput(full_name=name.value, given=name.given, surname=name.surname, kind=name.kind,
                           preferred=index == 0, language=name.language,
                           confidence=None if getattr(name.confidence, "value", name.confidence) == "unknown"
                           else getattr(name.confidence, "value", name.confidence))
                 for index, name in enumerate(record.names) if name.value]
        person_id = self.research.create_person(self.tx, id=self.id_for(record.id), names=names,
                                                living=living or "unknown",
                                                summary=None if self.private_details else record.notes,
                                                access=self._access(record))
        self.private_note(person_id, record.notes, "imported_note")
        for ident in record.external_ids:
            system = CANONICAL_SYSTEM.get(ident.system, ident.system)
            status = "current" if DURABLE_SYSTEMS.match(system) else "alias"
            if status == "current" and self.research.find_external(system, ident.value, statuses=("current",)):
                status = "candidate"
            self.research.map_external(self.tx, person_id, system, ident.value, url=ident.url, status=status,
                                       verified=ident.verified)
        for former in record.former_ids:
            self.research.map_external(self.tx, person_id, "workbench-case", former, status="former")
        if record.haplogroup_id:
            self.pending_branches.append((person_id, self.id_for(record.haplogroup_id), record.haplogroup_note))

    pending_branches: list[tuple[str, str, str | None]]

    def _Haplogroup(self, record: Haplogroup) -> None:
        self.research.add_haplogroup(self.tx, id=self.id_for(record.id), name=record.name,
                                     parent_id=self.id_for(record.parent_id) if record.parent_id else None,
                                     date_text=record.date, note=record.note, access=self._access(record))

    def _Source(self, record: Source) -> None:
        source_id = self.research.register_source(
            self.tx, id=self.id_for(record.id), title=record.title, kind=record.source_type, author=record.author,
            publication=record.publication, url=record.url, licence=record.licence,
            access_note=None if self.private_details else record.access_note, access=self._access(record))
        self.private_note(source_id, record.access_note, "imported_source_text")
        if record.repository:
            repository_id = stable_id("rep", record.repository)
            if not self.store.get("repository", repository_id):
                self.research.add_repository(self.tx, id=repository_id, name=record.repository)
            self.research.add_holding(self.tx, id=stable_id("hld", source_id), source_id=source_id,
                                      repository_id=repository_id)
        for ident in record.external_ids:
            self.research.map_external(self.tx, source_id, ident.system, ident.value, url=ident.url, status="alias")

    def _Citation(self, record: Citation) -> None:
        record_id = None
        if record.abstract or record.quotation or record.transcription or record.quality or record.information:
            source = self.store.get("source", self.id_for(record.source_id))
            record_id = self.research.add_record(
                self.tx, id=stable_id("rec", self.id_for(record.id)),
                title=" — ".join(filter(None, [source["title"] if source else None, record.locator])) or record.id,
                source_id=self.id_for(record.source_id), locator=record.locator, summary=record.abstract,
                information=record.information, access=self._access(record),
                extra={"citation_quality": record.quality} if record.quality else None)
            for kind, text, note in (("transcription", record.transcription, None),
                                     ("transcription", record.quotation, "verbatim quotation")):
                if text:
                    self.research.add_transcription(self.tx, id=stable_id("trn", record_id, note or kind), record_id=record_id,
                                                    text=text, kind=kind, uncertainty=note,
                                                    access="private" if self.private_details else self._access(record))
        self.research.add_citation(self.tx, id=self.id_for(record.id), source_id=self.id_for(record.source_id),
                                   record_id=record_id, locator=record.locator, accessed_on=record.accessed_on,
                                   access=self._access(record))

    def _Event(self, record: Event) -> None:
        # A person's own event list marks them as a principal; other participants keep a plain role.
        participants = [(pid, "principal" if not self.person_events.get(raw) or record.id in self.person_events[raw]
                         else "participant")
                        for raw, pid in zip(record.participant_ids, self.ids(record.participant_ids))
                        if self.store.entity_type(pid) == "person"]
        precision = record.date_precision or "unknown"
        self.research.add_event(
            self.tx, id=self.id_for(record.id), kind=record.kind, participants=participants,
            date_original=record.date, date_kind=DATE_KIND.get(precision, "unknown"),
            date_start=_iso(record.date), place_id=self.id_for(record.place_id) if record.place_id else None,
            description=None if self.private_details else record.description, access=self._access(record),
            extra={"date_precision": precision} if precision not in DATE_KIND or DATE_KIND[precision] != precision else None)
        self.private_note(self.id_for(record.id), record.description, "imported_description")
        if record.external_ids:
            for ident in record.external_ids:
                self.research.map_external(self.tx, self.id_for(record.id), ident.system, ident.value, status="alias")

    def _assess(self, claim_id: str, *, status: str | None, confidence: str | None, grade: str | None,
                estimate: int | None = None, reasoning: str | None = None, tree_status: str | None = None) -> None:
        confidence = None if confidence in (None, "unknown") else confidence
        if not any((status not in (None, "asserted"), confidence, grade, estimate, reasoning, tree_status)):
            return
        self.research.assess(self.tx, claim_id, new=True, status=status, grade=grade,
                             vocabulary="project-grades" if grade else ("workbench" if status or confidence else None),
                             confidence=confidence, estimate_percent=estimate,
                             estimate_kind="subjective" if estimate is not None else None, reasoning=reasoning,
                             attachment_status=tree_status)

    def _Relationship(self, record: Relationship) -> None:
        kind = record.kind.casefold()
        role = {"husband": "spouse", "wife": "spouse", "brother": "sibling", "sister": "sibling",
                "half-sibling": "sibling"}.get(kind, kind)
        if role not in ("father", "mother", "parent", "spouse", "partner", "sibling"):
            self.conflict(record, f"relationship kind {record.kind!r} has no core equivalent; kept for review")
            return
        claim_id = self.research.relationship_claim(
            self.tx, id=self.id_for(record.id), child_id=self.id_for(record.subject_id),
            relative_id=self.id_for(record.object_id), role=role,
            relation_type=PEDIGREE.get(str(record.pedigree or "").casefold()) if record.pedigree else None,
            origin=self.origin, access=self._access(record),
            extra={"recorded_kind": record.kind, "pedigree": record.pedigree} if role != kind or record.pedigree else None)
        self._assess(claim_id, status=None, confidence=getattr(record.confidence, "value", record.confidence),
                     grade=record.grade, estimate=record.estimate, reasoning=record.rationale,
                     tree_status=record.tree_status)
        self.pending_claim_links.extend((claim_id, self.id_for(cid)) for cid in record.claim_ids)

    pending_claim_links: list[tuple[str, str]]

    def _Claim(self, record: Claim) -> None:
        predicate = record.predicate
        kind = "vital" if predicate.casefold() in VITAL_PREDICATES else "attribute"
        subject = self.id_for(record.subject_id)
        subject_type = self.store.entity_type(subject)
        claim_id = self.research.create_claim(
            self.tx, id=self.id_for(record.id), kind=kind if subject_type == "person" else "other", predicate=predicate,
            proposition=f"{predicate}: {record.value}", value_text=record.value,
            subject_person_id=subject if subject_type == "person" else None, origin=self.origin,
            access=self._access(record), extra=None if subject_type == "person" else {"subject_id": subject})
        if subject_type == "person" and predicate == "sex" and record.value:
            value = {"m": "male", "male": "male", "f": "female", "female": "female", "u": "unknown"}.get(
                record.value.strip().casefold())
            if value:
                self.tx.update("person", subject, {"sex": value})
        for citation in self.ids(record.citation_ids):
            self.research.add_evidence(self.tx, id=stable_id("evd", claim_id, citation), claim_id=claim_id,
                                       citation_id=citation, extra={"cited_by_claim": True})
        self._assess(claim_id, status=getattr(record.status, "value", record.status),
                     confidence=getattr(record.confidence, "value", record.confidence), grade=record.grade,
                     reasoning=record.rationale)

    def _Evidence(self, record: Evidence) -> None:
        self.research.add_evidence(
            self.tx, id=self.id_for(record.id), claim_id=self.id_for(record.claim_id),
            citation_id=self.id_for(record.citation_id), stance="supports" if record.supports else "opposes",
            interpretation=record.assessment, limitation=record.limitation,
            extra={key: value for key, value in {"confidence": getattr(record.confidence, "value", record.confidence),
                                                  "grade": record.grade}.items() if value not in (None, "unknown")} or None)

    def _links(self, record: Record, *groups: tuple[str, Iterable[str]]) -> list[tuple[str, str]]:
        links: list[tuple[str, str]] = []
        for role, values in groups:
            for value in self.ids(values):
                if self.store.entity_type(value):
                    links.append((value, role))
                else:
                    self.pending_links.append((self.id_for(record.id), value, role))
        return links

    pending_links: list[tuple[str, str, str]]

    def _Hypothesis(self, record: Hypothesis) -> None:
        self.research.add_hypothesis(
            self.tx, id=self.id_for(record.id), statement=record.statement, status=record.status,
            supports="\n".join(record.supports) or None, objections="\n".join(record.objections) or None,
            access=self._access(record),
            links=self._links(record, ("related", record.related_ids), ("evidence", record.evidence_ids)),
            extra={key: value for key, value in {"confidence": getattr(record.confidence, "value", record.confidence),
                                                  "grade": record.grade}.items() if value not in (None, "unknown")} or None)

    def _ResearchQuestion(self, record: ResearchQuestion) -> None:
        self.research.add_question(self.tx, id=self.id_for(record.id), question=record.question, status=record.status,
                                   priority=record.priority, resolves=record.resolves, next_action=record.next_record,
                                   access=self._access(record), links=self._links(record, ("related", record.related_ids)))

    def _Finding(self, record: Finding) -> None:
        extra = {key: value for key, value in {
            "confidence": getattr(record.confidence, "value", record.confidence), "changes": record.changes or None,
        }.items() if value not in (None, "unknown")}
        self.research.add_finding(
            self.tx, id=self.id_for(record.id), statement=record.conclusion, recorded_on=record.recorded_on,
            kind=record.kind, status=record.status, limitations=record.limitations, access=self._access(record),
            links=self._links(record, ("related", record.related_ids), ("evidence", record.evidence_ids),
                              ("citation", record.citation_ids)), extra=extra or None)

    def _Study(self, record: Study) -> None:
        study_id = self.research.add_study(
            self.tx, id=self.id_for(record.id), title=record.title, kind=record.kind, summary=record.summary,
            rationale=record.rationale, body=record.body, conclusion=record.conclusion,
            limitations=record.limitations, status=record.status, updated_on=record.updated_on,
            access=self._access(record), links=self._links(record, ("related", record.related_ids)),
            extra={key: value for key, value in {"links": record.links or None,
                                                  "next_records": record.next_records or None}.items() if value} or None)
        for group in record.groups:
            self.research.add_group(self.tx, id=stable_id("grp", study_id, group.get("id")), study_id=study_id,
                                    title=group.get("title") or group.get("id") or "Group", note=group.get("note"),
                                    members=[m for m in self.ids(group.get("member_ids", [])) if self.store.entity_type(m)],
                                    access=self._access(record),
                                    extra={"original_id": group.get("id"),
                                           **{k: v for k, v in group.items() if k not in ("id", "title", "note", "member_ids")}})

    def _Search(self, record: Search) -> None:
        outcome = "negative" if NEGATIVE_RESULT.match(record.result or "") else ("positive" if record.citation_ids else "unknown")
        self.research.log_search(
            self.tx, id=self.id_for(record.id), scope=record.search, result=record.result, outcome=outcome,
            searched_on=record.searched_on, limitation=record.limitation, access=self._access(record),
            links=self._links(record, ("related", record.related_ids), ("citation", record.citation_ids)))

    def _ImportProvenance(self, record: ImportProvenance) -> None:
        batch_id = self.id_for(record.id)
        self.tx.insert("import_batch", {"id": batch_id, "adapter": record.adapter, "input_label": "legacy case provenance",
                                        "imported_at": self.store.clock(),
                                        "report_json": _json({"observations": record.observations,
                                                              "entity_ids": record.entity_ids})})

    def existing_import_batch(self, record: Record) -> bool:  # pragma: no cover - documentation helper
        return bool(self.store.get("import_batch", self.id_for(record.id)))

    def finish(self) -> None:
        """Resolve references to records loaded later in the same batch."""
        for person_id, haplogroup_id, note in self.pending_branches:
            if self.store.entity_type(haplogroup_id) == "haplogroup":
                self.research.add_dna_observation(self.tx, id=stable_id("dna", person_id, haplogroup_id),
                                                  kind="branch_assignment", person_id=person_id,
                                                  haplogroup_id=haplogroup_id, summary=note or "Placed on this branch",
                                                  access=self.store.get("person", person_id)["access"])
        for claim_id, linked in self.pending_claim_links:
            if self.store.entity_type(linked):
                self.tx.upsert_link(claim_id, linked, "supporting_claim")
                self.research.add_dependency(self.tx, dependent_id=claim_id, premise_id=linked,
                                             note="relationship rests on this claim")
        for source, target, role in self.pending_links:
            if self.store.entity_type(target):
                self.tx.upsert_link(source, target, role)
            else:
                item_id = stable_id("leg", self.input_path, source, target, role)
                if not self.store.get("legacy_item", item_id):
                    self.tx.insert("legacy_item", {"id": item_id, "import_batch_id": self.batch_id,
                                                   "input_path": self.input_path, "pointer": f"link/{source}/{target}",
                                                   "disposition": "unresolved", "reason": f"{role} link to an unknown id",
                                                   "payload_json": _json({"from": source, "to": target, "role": role}),
                                                   "entity_id": source})


ORDER = {name: index for index, name in enumerate((
    "ImportProvenance", "Place", "Haplogroup", "Person", "Source", "Citation", "Event", "Claim", "Relationship",
    "Evidence", "Hypothesis", "ResearchQuestion", "Finding", "Search", "Study"))}


def new_loader(research: Research, tx: Tx, **kwargs: Any) -> RecordLoader:
    loader = RecordLoader(research, tx, **kwargs)
    loader.pending_branches = []
    loader.pending_claim_links = []
    loader.pending_links = []
    return loader
