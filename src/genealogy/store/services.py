"""Typed research operations: the only supported writers of project research.

Every method that changes data takes the open :class:`~genealogy.store.core.Tx`
of one short transaction, so several operations commit or roll back together.
Reads use the store directly. Callers (the CLI, importers, adapters, local
interfaces, project scripts) must not write tables themselves.

Semantics the services keep:

* A record and its mentions exist before anyone is identified; identifying a
  mention with a person is an *identity claim*, and competing candidates are
  separate claims, never a forced assignment.
* A relationship claim is one proposition (child, parent role, relation type);
  "parent's child" is a view derived from it, never a second editable row.
* One assessment per claim per scope. Each change adds a revision; earlier
  revisions remain as history. Updating needs the revision you read.
* Estimates are optional, explicitly typed (normally ``subjective``) and are
  never invented, defaulted to zero, maximised or averaged.
* A changed or withdrawn premise flags dependent conclusions for review; it
  never changes their confidence.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from ..models import contains_raw_dna_material
from .core import Store, Tx, new_id
from .errors import ConstraintError, NotFoundError, StaleRevisionError
from .vocabulary import (
    FINDING_MAP, PROPOSAL_MAP, PROPOSAL_TRANSITIONS, QUESTION_MAP, SEARCH_OUTCOMES, normalise,
)

ACCESS = ("public", "private", "restricted", "licensed", "raw_dna")
RELATIONSHIP_PREDICATES = ("father", "mother", "parent", "spouse", "partner", "sibling")
REVERSE_ROLE = {"father": "child", "mother": "child", "parent": "child", "spouse": "spouse", "partner": "partner",
                "sibling": "sibling"}


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads(value: str | None) -> Any:
    return None if value is None else json.loads(value)


def stable_id(prefix: str, *parts: Any) -> str:
    """A deterministic opaque id for idempotent imports (never parsed back)."""
    digest = hashlib.sha256("\x1f".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _access(value: str) -> str:
    if value not in ACCESS:
        raise ConstraintError(f"access must be one of {', '.join(ACCESS)}, not {value!r}")
    return value


@dataclass(slots=True)
class NameInput:
    full_name: str
    given: str | None = None
    surname: str | None = None
    kind: str = "unknown"
    original_wording: str | None = None
    preferred: bool = False
    basis: str | None = None
    confidence: str | None = None
    language: str | None = None


class Research:
    """Domain operations over one project's :class:`Store`."""

    def __init__(self, store: Store):
        self.store = store

    # ================================================================ identity
    def create_person(self, tx: Tx, *, id: str | None = None, names: Sequence[NameInput] = (), sex: str | None = None,
                      living: str = "unknown", living_basis: str | None = None, label: str | None = None,
                      record_defined: bool = False, summary: str | None = None, access: str = "private",
                      extra: Mapping[str, Any] | None = None) -> str:
        person_id = id or new_id("per")
        tx.insert("person", {
            "id": person_id, "sex": sex, "living": living, "living_basis": living_basis, "label": label,
            "record_defined": 1 if record_defined else 0, "summary": summary, "access": _access(access),
            "extra_json": _json(dict(extra)) if extra else None,
        })
        for index, name in enumerate(names):
            self.add_name(tx, person_id, name, sort_order=index)
        return person_id

    def add_name(self, tx: Tx, person_id: str, name: NameInput, *, sort_order: int = 0, id: str | None = None) -> str:
        if not name.full_name or not name.full_name.strip():
            raise ConstraintError("a name needs its full wording")
        name_id = id or stable_id("nam", person_id, name.full_name, name.kind, sort_order)
        if self.store.get("person_name", name_id):
            return name_id
        tx.insert("person_name", {
            "id": name_id, "person_id": person_id, "full_name": name.full_name.strip(), "given": name.given,
            "surname": name.surname, "kind": name.kind, "original_wording": name.original_wording,
            "preferred": 1 if name.preferred else 0, "sort_order": sort_order, "basis": name.basis,
            "confidence": name.confidence, "language": name.language,
        })
        return name_id

    def map_external(self, tx: Tx, entity_id: str, system: str, value: str, *, status: str = "current",
                     url: str | None = None, redirect_to: str | None = None, verified: bool = False,
                     observed_on: str | None = None, note: str | None = None) -> str:
        """Map an external identifier to a local entity, refusing silent double assignment.

        A ``current`` identifier may belong to one entity only. A competing
        assignment is recorded with status ``candidate``; nothing is merged.
        """
        if not value:
            raise ConstraintError("an external identifier needs a value")
        existing = self.store.one("SELECT * FROM external_id WHERE system=? AND value=? AND entity_id=?",
                                  (system, value, entity_id))
        if status == "current":
            other = self.store.one("SELECT entity_id FROM external_id WHERE system=? AND value=? AND status='current' "
                                   "AND entity_id<>?", (system, value, entity_id))
            if other:
                raise ConstraintError(
                    f"{system} {value} already identifies {other['entity_id']}; record a competing assignment "
                    "with status 'candidate' or merge the entities explicitly")
        if existing:
            changes = {key: val for key, val in {"status": status, "url": url, "redirect_to": redirect_to,
                                                  "observed_on": observed_on, "note": note}.items() if val is not None}
            if changes:
                tx.update("external_id", existing["id"], changes)
            return existing["id"]
        mapping_id = stable_id("xid", system, value, entity_id)
        tx.insert("external_id", {
            "id": mapping_id, "entity_id": entity_id, "system": system, "value": value, "url": url, "status": status,
            "redirect_to": redirect_to, "verified": 1 if verified else 0, "observed_on": observed_on, "note": note,
        })
        return mapping_id

    def find_external(self, system: str, value: str, *, statuses: Iterable[str] = ("current", "redirect", "former", "alias")) -> list[str]:
        wanted = tuple(statuses)
        marks = ",".join("?" for _ in wanted)
        rows = self.store.all(f"SELECT entity_id FROM external_id WHERE system=? AND value=? AND status IN ({marks}) "
                              "ORDER BY CASE status WHEN 'current' THEN 0 ELSE 1 END, entity_id", (system, value, *wanted))
        return list(dict.fromkeys(row["entity_id"] for row in rows))

    def add_route(self, tx: Tx, path: str, entity_id: str, kind: str = "current") -> None:
        existing = self.store.one("SELECT * FROM route_alias WHERE path=?", (path,))
        if existing:
            if existing["entity_id"] != entity_id:
                raise ConstraintError(f"route {path} already belongs to {existing['entity_id']}")
            return
        tx.insert("route_alias", {"path": path, "entity_id": entity_id, "kind": kind})

    # ================================================================== places
    def create_place(self, tx: Tx, *, name: str, id: str | None = None, parent_id: str | None = None,
                     latitude: float | None = None, longitude: float | None = None, precision: str | None = None,
                     region: str | None = None, coordinate_basis: str | None = None, access: str = "public",
                     extra: Mapping[str, Any] | None = None) -> str:
        place_id = id or new_id("plc")
        if self.store.get("place", place_id):
            return place_id
        tx.insert("place", {"id": place_id, "name": name, "parent_id": parent_id, "latitude": latitude,
                            "longitude": longitude, "precision": precision, "region": region,
                            "coordinate_basis": coordinate_basis, "access": _access(access),
                            "extra_json": _json(dict(extra)) if extra else None})
        return place_id

    # ================================================================= sources
    def add_repository(self, tx: Tx, *, name: str, id: str | None = None, location: str | None = None,
                       url: str | None = None) -> str:
        repository_id = id or new_id("rep")
        tx.insert("repository", {"id": repository_id, "name": name, "location": location, "url": url})
        return repository_id

    def register_source(self, tx: Tx, *, title: str, id: str | None = None, kind: str = "unknown",
                        author: str | None = None, publication: str | None = None, url: str | None = None,
                        originality: str | None = None, licence: str | None = None, access_note: str | None = None,
                        access: str = "private", extra: Mapping[str, Any] | None = None) -> str:
        if not title or not title.strip():
            raise ConstraintError("a source needs a title")
        source_id = id or new_id("src")
        tx.insert("source", {"id": source_id, "title": title.strip(), "kind": kind, "author": author,
                             "publication": publication, "url": url, "originality": originality, "licence": licence,
                             "access_note": access_note, "access": _access(access),
                             "extra_json": _json(dict(extra)) if extra else None})
        return source_id

    def add_holding(self, tx: Tx, *, source_id: str, repository_id: str | None = None,
                    catalogue_ref: str | None = None, note: str | None = None, id: str | None = None) -> str:
        holding_id = id or new_id("hld")
        tx.insert("source_holding", {"id": holding_id, "source_id": source_id, "repository_id": repository_id,
                                     "catalogue_ref": catalogue_ref, "note": note})
        return holding_id

    def add_copy(self, tx: Tx, *, source_id: str, form: str = "unknown", id: str | None = None,
                 holding_id: str | None = None, description: str | None = None, url: str | None = None,
                 inspected: bool = False, inspection_note: str | None = None, captured_on: str | None = None,
                 accessed_on: str | None = None, asset_id: str | None = None,
                 derived_from_copy_id: str | None = None, access: str = "private") -> str:
        """One captured or inspected copy. Never merged with another by catalogue reference."""
        copy_id = id or new_id("cpy")
        tx.insert("source_copy", {
            "id": copy_id, "source_id": source_id, "holding_id": holding_id, "form": form,
            "description": description, "url": url, "inspected": 1 if inspected else 0,
            "inspection_note": inspection_note, "captured_on": captured_on, "accessed_on": accessed_on,
            "asset_id": asset_id, "derived_from_copy_id": derived_from_copy_id, "access": _access(access)})
        return copy_id

    def add_record(self, tx: Tx, *, title: str, id: str | None = None, source_id: str | None = None,
                   copy_id: str | None = None, record_type: str | None = None, locator: str | None = None,
                   date_original: str | None = None, date_start: str | None = None, date_end: str | None = None,
                   date_kind: str = "unknown", place_id: str | None = None, place_wording: str | None = None,
                   summary: str | None = None, information: str | None = None, url: str | None = None,
                   access: str = "private", extra: Mapping[str, Any] | None = None) -> str:
        record_id = id or new_id("rec")
        tx.insert("record", {
            "id": record_id, "source_id": source_id, "copy_id": copy_id, "record_type": record_type, "title": title,
            "locator": locator, "date_original": date_original, "date_start": date_start, "date_end": date_end,
            "date_kind": date_kind, "place_id": place_id, "place_wording": place_wording, "summary": summary,
            "information": information, "url": url, "access": _access(access),
            "extra_json": _json(dict(extra)) if extra else None})
        return record_id

    def add_citation(self, tx: Tx, *, source_id: str, id: str | None = None, record_id: str | None = None,
                     copy_id: str | None = None, locator: str | None = None, accessed_on: str | None = None,
                     note: str | None = None, access: str = "private") -> str:
        citation_id = id or new_id("cit")
        tx.insert("citation", {"id": citation_id, "source_id": source_id, "record_id": record_id, "copy_id": copy_id,
                               "locator": locator, "accessed_on": accessed_on, "note": note, "access": _access(access)})
        return citation_id

    def add_transcription(self, tx: Tx, *, record_id: str, text: str | None = None, asset_id: str | None = None,
                          kind: str = "transcription", id: str | None = None, copy_id: str | None = None,
                          reader: str | None = None, read_on: str | None = None, uncertainty: str | None = None,
                          access: str = "private") -> str:
        transcription_id = id or new_id("trn")
        tx.insert("transcription", {"id": transcription_id, "record_id": record_id, "copy_id": copy_id, "kind": kind,
                                    "current_revision": 1, "access": _access(access)})
        tx.insert("transcription_revision", {
            "transcription_id": transcription_id, "revision": 1, "text": text, "asset_id": asset_id, "status": "current",
            "reader": reader, "read_on": read_on, "uncertainty": uncertainty, "change_set_id": tx.change_set_id})
        return transcription_id

    def revise_transcription(self, tx: Tx, transcription_id: str, *, expected_revision: int, text: str | None = None,
                             asset_id: str | None = None, reason: str, reader: str | None = None,
                             read_on: str | None = None, uncertainty: str | None = None) -> int:
        """A corrected reading: the earlier revision is kept as superseded; dependents are flagged."""
        current = self.store.require("transcription", transcription_id)
        if current["current_revision"] != expected_revision:
            raise StaleRevisionError("transcription", transcription_id, expected_revision, current["current_revision"], current)
        new_revision = current["current_revision"] + 1
        tx.conn.execute("UPDATE transcription_revision SET status='superseded' WHERE transcription_id=? AND revision=? "
                        "AND status='current'", (transcription_id, current["current_revision"]))
        tx.insert("transcription_revision", {
            "transcription_id": transcription_id, "revision": new_revision, "text": text, "asset_id": asset_id,
            "status": "current", "reader": reader, "read_on": read_on, "uncertainty": uncertainty, "reason": reason,
            "change_set_id": tx.change_set_id})
        tx.update("transcription", transcription_id, {"current_revision": new_revision})
        self.flag_dependents(tx, transcription_id, f"transcription revised to revision {new_revision}: {reason}")
        return new_revision

    def withdraw_transcription(self, tx: Tx, transcription_id: str, *, expected_revision: int, reason: str) -> int:
        """Withdraw the current reading. The text stays as history; dependents are flagged."""
        current = self.store.require("transcription", transcription_id)
        if current["current_revision"] != expected_revision:
            raise StaleRevisionError("transcription", transcription_id, expected_revision, current["current_revision"], current)
        previous = self.store.one("SELECT * FROM transcription_revision WHERE transcription_id=? AND revision=?",
                                  (transcription_id, expected_revision))
        new_revision = expected_revision + 1
        tx.conn.execute("UPDATE transcription_revision SET status='superseded' WHERE transcription_id=? AND revision=?",
                        (transcription_id, expected_revision))
        tx.insert("transcription_revision", {
            "transcription_id": transcription_id, "revision": new_revision, "text": previous["text"],
            "asset_id": previous["asset_id"], "status": "withdrawn", "reason": reason,
            "change_set_id": tx.change_set_id})
        tx.update("transcription", transcription_id, {"current_revision": new_revision})
        self.flag_dependents(tx, transcription_id, f"reading withdrawn: {reason}")
        return new_revision

    def add_mention(self, tx: Tx, *, record_id: str, role: str | None = None, name_as_written: str | None = None,
                    details: str | None = None, sort_order: int = 0, id: str | None = None, access: str = "private",
                    extra: Mapping[str, Any] | None = None) -> str:
        mention_id = id or new_id("men")
        tx.insert("mention", {"id": mention_id, "record_id": record_id, "role": role,
                              "name_as_written": name_as_written, "details": details, "sort_order": sort_order,
                              "access": _access(access), "extra_json": _json(dict(extra)) if extra else None})
        return mention_id

    def add_documentary_relation(self, tx: Tx, *, record_id: str, from_mention_id: str, to_mention_id: str,
                                 relation: str, wording: str | None = None, id: str | None = None) -> str:
        """What the document says ("Isaac, son"), independent of who the people were."""
        for mention_id in (from_mention_id, to_mention_id):
            mention = self.store.require("mention", mention_id)
            if mention["record_id"] != record_id:
                raise ConstraintError(f"mention {mention_id} belongs to another record")
        relation_id = id or new_id("drl")
        tx.insert("documentary_relation", {"id": relation_id, "record_id": record_id, "from_mention_id": from_mention_id,
                                           "to_mention_id": to_mention_id, "relation": relation, "wording": wording})
        return relation_id

    # ================================================================== events
    def add_event(self, tx: Tx, *, kind: str, id: str | None = None, participants: Sequence[tuple[str, str]] = (),
                  date_original: str | None = None, date_kind: str = "unknown", date_start: str | None = None,
                  date_end: str | None = None, calendar: str | None = None, date_basis: str | None = None,
                  place_id: str | None = None, place_wording: str | None = None, description: str | None = None,
                  record_id: str | None = None, access: str = "private", extra: Mapping[str, Any] | None = None) -> str:
        if date_kind in ("inferred", "calculated", "estimated") and not date_basis:
            raise ConstraintError(f"an {date_kind} date needs its basis (date_basis)")
        event_id = id or new_id("evt")
        tx.insert("event", {
            "id": event_id, "kind": kind, "date_original": date_original, "date_kind": date_kind,
            "date_start": date_start, "date_end": date_end, "calendar": calendar, "date_basis": date_basis,
            "place_id": place_id, "place_wording": place_wording, "description": description, "record_id": record_id,
            "access": _access(access), "extra_json": _json(dict(extra)) if extra else None})
        for index, (person_id, role) in enumerate(participants):
            tx.insert("event_participant", {"event_id": event_id, "person_id": person_id, "role": role,
                                            "sort_order": index})
        return event_id

    # ================================================================== claims
    def create_claim(self, tx: Tx, *, kind: str, predicate: str, proposition: str, id: str | None = None,
                     subject_person_id: str | None = None, object_person_id: str | None = None,
                     subject_mention_id: str | None = None, event_id: str | None = None,
                     relation_type: str | None = None, value_text: str | None = None, origin: str = "research",
                     access: str = "private", publication_status: str = "unreviewed",
                     extra: Mapping[str, Any] | None = None) -> str:
        if kind == "relationship" and predicate not in RELATIONSHIP_PREDICATES:
            raise ConstraintError(f"relationship predicate must be one of {', '.join(RELATIONSHIP_PREDICATES)}")
        if not proposition or not proposition.strip():
            raise ConstraintError("a claim needs its proposition in words")
        claim_id = id or new_id("clm")
        tx.insert("claim", {
            "id": claim_id, "kind": kind, "predicate": predicate, "subject_person_id": subject_person_id,
            "object_person_id": object_person_id, "subject_mention_id": subject_mention_id, "event_id": event_id,
            "relation_type": relation_type, "value_text": value_text, "proposition": proposition.strip(),
            "origin": origin, "access": _access(access), "publication_status": publication_status,
            "extra_json": _json(dict(extra)) if extra else None})
        return claim_id

    def relationship_claim(self, tx: Tx, *, child_id: str, relative_id: str, role: str,
                           relation_type: str | None = None, proposition: str | None = None, id: str | None = None,
                           origin: str = "research", access: str = "private",
                           publication_status: str = "unreviewed", extra: Mapping[str, Any] | None = None) -> str:
        """``relative_id`` is ``child_id``'s ``role`` (father, mother, parent, spouse, sibling)."""
        words = proposition or f"{relative_id} is the {role} of {child_id}"
        return self.create_claim(tx, kind="relationship", predicate=role, proposition=words, id=id,
                                 subject_person_id=child_id, object_person_id=relative_id,
                                 relation_type=relation_type, origin=origin, access=access,
                                 publication_status=publication_status, extra=extra)

    def identity_claim(self, tx: Tx, *, mention_id: str, person_id: str, proposition: str | None = None,
                       id: str | None = None, access: str = "private") -> str:
        """Propose that a record's participant is a particular person. Competing candidates coexist."""
        words = proposition or f"Mention {mention_id} refers to {person_id}"
        return self.create_claim(tx, kind="identity", predicate="identifies", proposition=words, id=id,
                                 subject_mention_id=mention_id, object_person_id=person_id, access=access)

    def add_evidence(self, tx: Tx, *, claim_id: str, citation_id: str | None = None, record_id: str | None = None,
                     mention_id: str | None = None, stance: str = "supports", interpretation: str | None = None,
                     information: str | None = None, independence_key: str | None = None,
                     limitation: str | None = None, id: str | None = None,
                     extra: Mapping[str, Any] | None = None) -> str:
        evidence_id = id or new_id("evd")
        tx.insert("claim_evidence", {
            "id": evidence_id, "claim_id": claim_id, "citation_id": citation_id, "record_id": record_id,
            "mention_id": mention_id, "stance": stance, "interpretation": interpretation, "information": information,
            "independence_key": independence_key, "limitation": limitation,
            "extra_json": _json(dict(extra)) if extra else None})
        return evidence_id

    def ensure_scope(self, tx: Tx, scope_id: str, *, name: str, researcher: str | None = None,
                     description: str | None = None) -> str:
        if not self.store.one("SELECT 1 FROM assessment_scope WHERE id=?", (scope_id,)):
            tx.insert("assessment_scope", {"id": scope_id, "name": name, "researcher": researcher,
                                           "description": description})
        return scope_id

    # ============================================================ assessments
    def assess(self, tx: Tx, claim_id: str, *, scope_id: str = "project", expected_revision: int | None = None,
               new: bool = False, status: str | None = None, grade: str | None = None,
               vocabulary: str | None = None, confidence: str | None = None, estimate_percent: int | None = None,
               estimate_kind: str | None = None, reasoning: str | None = None, limitations: str | None = None,
               research_status: str | None = None, working_selection: bool | None = None,
               attachment_status: str | None = None, assessed_on: str | None = None, review_due: str | None = None,
               basis: Sequence[str] | None = None, extra: Mapping[str, Any] | None = None) -> tuple[str, int]:
        """Add the current revision of the claim's assessment in ``scope_id``.

        For an existing assessment, ``expected_revision`` must be the revision
        the change was based on; otherwise :class:`StaleRevisionError` is
        raised and nothing is written. Pass ``new=True`` to state that no
        assessment is expected to exist yet.
        """
        self.store.require("claim", claim_id)
        if estimate_percent is not None:
            if isinstance(estimate_percent, bool) or not isinstance(estimate_percent, int):
                raise ConstraintError("estimate_percent must be a whole number from 0 to 100")
            if estimate_kind is None:
                raise ConstraintError("an estimate needs estimate_kind (normally 'subjective'); the workbench never "
                                      "implies a calibrated probability")
        existing = self.store.one("SELECT * FROM assessment WHERE claim_id=? AND scope_id=?", (claim_id, scope_id))
        if existing is None:
            if expected_revision not in (None, 0):
                raise StaleRevisionError("assessment", f"{claim_id}@{scope_id}", expected_revision, 0)
            assessment_id = stable_id("asm", claim_id, scope_id)
            tx.insert("assessment", {"id": assessment_id, "claim_id": claim_id, "scope_id": scope_id,
                                     "current_revision": 1})
            revision = 1
        else:
            if new or expected_revision is None or expected_revision != existing["current_revision"]:
                raise StaleRevisionError("assessment", existing["id"], expected_revision if not new else 0,
                                         existing["current_revision"], self.current_assessment(claim_id, scope_id))
            assessment_id = existing["id"]
            revision = existing["current_revision"] + 1
        tx.insert("assessment_revision", {
            "assessment_id": assessment_id, "revision": revision, "status": status, "grade": grade,
            "vocabulary": vocabulary, "confidence": confidence, "estimate_percent": estimate_percent,
            "estimate_kind": estimate_kind, "reasoning": reasoning, "limitations": limitations,
            "research_status": research_status,
            "working_selection": None if working_selection is None else (1 if working_selection else 0),
            "attachment_status": attachment_status, "assessed_on": assessed_on, "review_due": review_due,
            "basis_json": _json(list(basis)) if basis else None, "change_set_id": tx.change_set_id,
            "extra_json": _json(dict(extra)) if extra else None})
        if existing is not None:
            tx.update("assessment", assessment_id, {"current_revision": revision})
            self.flag_dependents(tx, assessment_id, f"assessment revised to revision {revision}")
        if scope_id == "project":
            self.flag_dependents(tx, claim_id, f"project assessment is now revision {revision}")
        return assessment_id, revision

    def current_assessment(self, claim_id: str, scope_id: str = "project") -> dict[str, Any] | None:
        row = self.store.one(
            "SELECT a.id AS assessment_id, a.scope_id, a.current_revision, r.* FROM assessment a "
            "JOIN assessment_revision r ON r.assessment_id = a.id AND r.revision = a.current_revision "
            "WHERE a.claim_id=? AND a.scope_id=?", (claim_id, scope_id))
        if row:
            row["basis"] = _loads(row.pop("basis_json"))
            row["extra"] = _loads(row.pop("extra_json"))
        return row

    def assessment_history(self, claim_id: str, scope_id: str = "project") -> list[dict[str, Any]]:
        rows = self.store.all(
            "SELECT r.* FROM assessment a JOIN assessment_revision r ON r.assessment_id = a.id "
            "WHERE a.claim_id=? AND a.scope_id=? ORDER BY r.revision", (claim_id, scope_id))
        for row in rows:
            row["basis"] = _loads(row.pop("basis_json"))
            row["extra"] = _loads(row.pop("extra_json"))
        return rows

    def relationship_views(self, person_id: str, scope_id: str = "project") -> list[dict[str, Any]]:
        """Both directions of every relationship claim touching a person, from one assessment each."""
        views: list[dict[str, Any]] = []
        claims = self.store.all("SELECT * FROM claim WHERE kind='relationship' AND (subject_person_id=? OR object_person_id=?) "
                                "ORDER BY id", (person_id, person_id))
        for claim in claims:
            current = self.current_assessment(claim["id"], scope_id)
            if claim["subject_person_id"] == person_id:
                relative, role = claim["object_person_id"], claim["predicate"]
            else:
                relative, role = claim["subject_person_id"], REVERSE_ROLE[claim["predicate"]]
            views.append({"person_id": person_id, "relative_id": relative, "role": role, "claim_id": claim["id"],
                          "relation_type": claim["relation_type"], "assessment": current})
        return views

    # ============================================================ dependencies
    def premise_revision(self, entity_id: str) -> int:
        kind = self.store.entity_type(entity_id)
        if kind is None:
            raise NotFoundError(f"no entity {entity_id!r}")
        if kind == "claim":
            row = self.store.one("SELECT current_revision FROM assessment WHERE claim_id=? AND scope_id='project'",
                                 (entity_id,))
            claim = self.store.get("claim", entity_id)
            # A claim's basis changes when it is reassessed or itself edited.
            return (row["current_revision"] if row else 0) * 1000 + claim["revision"]
        if kind in ("assessment", "transcription"):
            return self.store.get(kind, entity_id)["current_revision"]
        row = self.store.get(kind, entity_id)
        return row.get("revision", 1) if row else 1

    def add_dependency(self, tx: Tx, *, dependent_id: str, premise_id: str, note: str | None = None,
                       premise_revision: int | None = None, id: str | None = None) -> str:
        revision = self.premise_revision(premise_id) if premise_revision is None else premise_revision
        existing = self.store.one("SELECT * FROM dependency WHERE dependent_id=? AND premise_id=?",
                                  (dependent_id, premise_id))
        if existing:
            return existing["id"]
        dependency_id = id or stable_id("dep", dependent_id, premise_id)
        tx.insert("dependency", {"id": dependency_id, "dependent_id": dependent_id, "premise_id": premise_id,
                                 "premise_revision": revision, "note": note, "status": "current"})
        return dependency_id

    def flag_dependents(self, tx: Tx, premise_id: str, reason: str) -> int:
        """Mark conclusions resting on a changed premise for review. Confidence is never touched."""
        count = 0
        for dependency in self.store.all("SELECT * FROM dependency WHERE premise_id=? AND status<>'review_needed'",
                                         (premise_id,)):
            tx.update("dependency", dependency["id"], {"status": "review_needed", "flagged_reason": reason,
                                                       "flagged_at": self.store.clock()})
            count += 1
        return count

    def review_queue(self) -> list[dict[str, Any]]:
        return self.store.all("SELECT * FROM dependency WHERE status='review_needed' ORDER BY flagged_at, id")

    def acknowledge_dependency(self, tx: Tx, dependency_id: str, *, expected_revision: int, note: str | None = None) -> None:
        """The dependent conclusion was reviewed against the premise as it now stands."""
        dependency = self.store.require("dependency", dependency_id)
        tx.update("dependency", dependency_id, {
            "status": "current", "premise_revision": self.premise_revision(dependency["premise_id"]),
            "note": note or dependency["note"], "flagged_reason": None, "flagged_at": None,
        }, expected_revision=expected_revision)

    # ================================================================ research
    def _links(self, tx: Tx, from_id: str, links: Iterable[tuple[str, str] | str]) -> None:
        for index, item in enumerate(links):
            target, role = (item, "related") if isinstance(item, str) else item
            tx.upsert_link(from_id, target, role, sort_order=index)

    def link(self, tx: Tx, from_id: str, to_id: str, role: str = "related", note: str | None = None) -> None:
        tx.upsert_link(from_id, to_id, role, note=note)

    def add_finding(self, tx: Tx, *, statement: str, id: str | None = None, recorded_on: str | None = None,
                    kind: str | None = None, status: str | None = "draft", qualification: str | None = None,
                    limitations: str | None = None, supersedes_id: str | None = None, access: str = "private",
                    publication_status: str = "unreviewed", links: Iterable[tuple[str, str] | str] = (),
                    extra: Mapping[str, Any] | None = None) -> str:
        normalised, original = normalise(status, FINDING_MAP, "draft")
        finding_id = id or new_id("fnd")
        tx.insert("finding", {
            "id": finding_id, "recorded_on": recorded_on, "kind": kind, "statement": statement, "status": normalised,
            "status_original": original, "qualification": qualification, "limitations": limitations,
            "supersedes_id": supersedes_id, "access": _access(access), "publication_status": publication_status,
            "extra_json": _json(dict(extra)) if extra else None})
        self._links(tx, finding_id, links)
        if supersedes_id:
            previous = self.store.require("finding", supersedes_id)
            if previous["status"] not in ("withdrawn", "superseded"):
                tx.update("finding", supersedes_id, {"status": "superseded"})
            self.flag_dependents(tx, supersedes_id, f"finding superseded by {finding_id}")
        return finding_id

    def withdraw_finding(self, tx: Tx, finding_id: str, *, reason: str, expected_revision: int) -> None:
        tx.update("finding", finding_id, {"status": "withdrawn", "withdrawn_reason": reason},
                  expected_revision=expected_revision)
        self.flag_dependents(tx, finding_id, f"finding withdrawn: {reason}")

    def add_question(self, tx: Tx, *, question: str, id: str | None = None, status: str | None = "open",
                     priority: str = "normal", resolves: str | None = None, next_action: str | None = None,
                     resume_condition: str | None = None, opened_on: str | None = None, closed_on: str | None = None,
                     access: str = "private", links: Iterable[tuple[str, str] | str] = (),
                     extra: Mapping[str, Any] | None = None) -> str:
        normalised, original = normalise(status, QUESTION_MAP, "open")
        question_id = id or new_id("qst")
        tx.insert("question", {
            "id": question_id, "question": question, "status": normalised, "status_original": original,
            "priority": priority, "resolves": resolves, "next_action": next_action,
            "resume_condition": resume_condition, "opened_on": opened_on, "closed_on": closed_on,
            "access": _access(access), "extra_json": _json(dict(extra)) if extra else None})
        self._links(tx, question_id, links)
        return question_id

    def set_question_status(self, tx: Tx, question_id: str, status: str, *, expected_revision: int,
                            closed_on: str | None = None, next_action: str | None = None) -> None:
        normalised, original = normalise(status, QUESTION_MAP, "open")
        changes: dict[str, Any] = {"status": normalised, "status_original": original}
        if closed_on:
            changes["closed_on"] = closed_on
        if next_action:
            changes["next_action"] = next_action
        tx.update("question", question_id, changes, expected_revision=expected_revision)

    def log_search(self, tx: Tx, *, scope: str, result: str, outcome: str = "unknown", id: str | None = None,
                   searched_on: str | None = None, repository: str | None = None, limitation: str | None = None,
                   access: str = "private", links: Iterable[tuple[str, str] | str] = (),
                   extra: Mapping[str, Any] | None = None) -> str:
        """Record a search, including one that found nothing (outcome 'negative')."""
        if outcome not in SEARCH_OUTCOMES:
            raise ConstraintError(f"search outcome must be one of {', '.join(SEARCH_OUTCOMES)}")
        search_id = id or new_id("sch")
        tx.insert("search", {"id": search_id, "searched_on": searched_on, "repository": repository, "scope": scope,
                             "result": result, "outcome": outcome, "limitation": limitation, "access": _access(access),
                             "extra_json": _json(dict(extra)) if extra else None})
        self._links(tx, search_id, links)
        return search_id

    def add_hypothesis(self, tx: Tx, *, statement: str, kind: str = "other", id: str | None = None,
                       status: str = "open", supports: str | None = None, objections: str | None = None,
                       access: str = "private", links: Iterable[tuple[str, str] | str] = (),
                       extra: Mapping[str, Any] | None = None) -> str:
        hypothesis_id = id or new_id("hyp")
        tx.insert("hypothesis", {"id": hypothesis_id, "kind": kind, "statement": statement, "status": status,
                                 "supports": supports, "objections": objections, "access": _access(access),
                                 "extra_json": _json(dict(extra)) if extra else None})
        self._links(tx, hypothesis_id, links)
        return hypothesis_id

    def add_study(self, tx: Tx, *, title: str, id: str | None = None, kind: str | None = None,
                  summary: str | None = None, rationale: str | None = None, body: str | None = None,
                  body_asset_id: str | None = None, conclusion: str | None = None, limitations: str | None = None,
                  status: str = "draft", updated_on: str | None = None, access: str = "private",
                  links: Iterable[tuple[str, str] | str] = (), extra: Mapping[str, Any] | None = None) -> str:
        study_id = id or new_id("std")
        tx.insert("study", {"id": study_id, "title": title, "kind": kind, "summary": summary, "rationale": rationale,
                            "body": body, "body_asset_id": body_asset_id, "conclusion": conclusion,
                            "limitations": limitations, "status": status, "updated_on": updated_on,
                            "access": _access(access), "extra_json": _json(dict(extra)) if extra else None})
        self._links(tx, study_id, links)
        return study_id

    def add_group(self, tx: Tx, *, title: str, study_id: str | None = None, id: str | None = None,
                  kind: str | None = None, note: str | None = None, members: Iterable[str] = (),
                  access: str = "private", extra: Mapping[str, Any] | None = None) -> str:
        group_id = id or new_id("grp")
        tx.insert("research_group", {"id": group_id, "study_id": study_id, "title": title, "kind": kind, "note": note,
                                     "access": _access(access), "extra_json": _json(dict(extra)) if extra else None})
        self._links(tx, group_id, [(member, "member") for member in members])
        return group_id

    def add_note(self, tx: Tx, *, text: str | None = None, asset_id: str | None = None, kind: str = "note",
                 title: str | None = None, id: str | None = None, access: str = "private",
                 links: Iterable[tuple[str, str] | str] = ()) -> str:
        note_id = id or new_id("not")
        tx.insert("note", {"id": note_id, "kind": kind, "title": title, "text": text, "asset_id": asset_id,
                           "access": _access(access)})
        self._links(tx, note_id, links)
        return note_id

    # ===================================================================== DNA
    def add_haplogroup(self, tx: Tx, *, name: str, id: str | None = None, parent_id: str | None = None,
                       date_text: str | None = None, note: str | None = None, access: str = "private") -> str:
        haplogroup_id = id or new_id("hap")
        tx.insert("haplogroup", {"id": haplogroup_id, "name": name, "parent_id": parent_id, "date_text": date_text,
                                 "note": note, "access": _access(access)})
        return haplogroup_id

    def add_dna_observation(self, tx: Tx, *, kind: str, summary: str, id: str | None = None,
                            person_id: str | None = None, haplogroup_id: str | None = None,
                            tester_label: str | None = None, limitations: str | None = None,
                            provenance: str | None = None, observed_on: str | None = None,
                            asset_id: str | None = None, access: str = "private") -> str:
        """A DNA observation or interpretation; raw genotype or sequence data is refused."""
        if contains_raw_dna_material({"kind": kind, "summary": summary}) or access == "raw_dna":
            raise ConstraintError("raw DNA material cannot be stored in the project database; keep it in private files")
        observation_id = id or new_id("dna")
        tx.insert("dna_observation", {"id": observation_id, "kind": kind, "person_id": person_id,
                                      "haplogroup_id": haplogroup_id, "tester_label": tester_label, "summary": summary,
                                      "limitations": limitations, "provenance": provenance, "observed_on": observed_on,
                                      "asset_id": asset_id, "access": _access(access)})
        return observation_id

    # ============================================================= publication
    def add_approval(self, tx: Tx, *, kind: str, target: str, authority: str, id: str | None = None,
                     sha256: str | None = None, source_path: str | None = None, entity_id: str | None = None,
                     scope: str | None = None, approved_on: str | None = None, manifest: str | None = None) -> str:
        approval_id = id or stable_id("apr", kind, target, sha256 or "", entity_id or "")
        if self.store.get("approval", approval_id):
            return approval_id
        tx.insert("approval", {"id": approval_id, "kind": kind, "target": target, "sha256": sha256,
                               "source_path": source_path, "entity_id": entity_id, "scope": scope,
                               "approved_on": approved_on, "authority": authority, "manifest": manifest})
        return approval_id

    # ======================================================== external systems
    def record_observation(self, tx: Tx, *, system: str, external_value: str, fields: Mapping[str, Any],
                           captured_on: str | None = None, entity_id: str | None = None, asset_id: str | None = None,
                           import_batch_id: str | None = None) -> tuple[str, bool]:
        """Store a captured external state; an identical capture is not duplicated."""
        payload = _json(dict(fields))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        existing = self.store.one("SELECT id FROM external_observation WHERE system=? AND external_value=? AND "
                                  "fields_sha256=? AND coalesce(captured_on,'')=coalesce(?,'')",
                                  (system, external_value, digest, captured_on))
        if existing:
            return existing["id"], False
        observation_id = stable_id("obs", system, external_value, digest, captured_on or "")
        tx.insert("external_observation", {
            "id": observation_id, "system": system, "external_value": external_value, "entity_id": entity_id,
            "captured_on": captured_on, "fields_json": payload, "fields_sha256": digest, "asset_id": asset_id,
            "import_batch_id": import_batch_id})
        return observation_id, True

    def set_baseline(self, tx: Tx, *, system: str, external_value: str, observation_id: str,
                     accepted_on: str | None = None) -> None:
        tx.delete_where("remote_baseline", {"system": system, "external_value": external_value})
        tx.insert("remote_baseline", {"system": system, "external_value": external_value,
                                      "observation_id": observation_id, "accepted_on": accepted_on})

    def latest_observation(self, system: str, external_value: str) -> dict[str, Any] | None:
        row = self.store.one("SELECT * FROM external_observation WHERE system=? AND external_value=? "
                             "ORDER BY coalesce(captured_on,''), id DESC LIMIT 1", (system, external_value))
        if row:
            row["fields"] = json.loads(row["fields_json"])
        return row

    # ================================================================ workflow
    def create_proposal(self, tx: Tx, *, kind: str, id: str | None = None, system: str | None = None,
                        target: str | None = None, status: str | None = "draft", destination: str | None = None,
                        rationale: str | None = None, basis: Mapping[str, Any] | None = None,
                        diff: Any = None, draft_text: str | None = None, draft_asset_id: str | None = None,
                        authored: bool = True, access: str = "private", actor: str | None = None,
                        extra: Mapping[str, Any] | None = None) -> str:
        normalised, original = normalise(status, PROPOSAL_MAP, "draft")
        proposal_id = id or new_id("prp")
        tx.insert("proposal", {
            "id": proposal_id, "kind": kind, "system": system, "target": target, "status": normalised,
            "status_original": original, "destination": destination, "rationale": rationale,
            "basis_json": _json(dict(basis)) if basis else None, "diff_json": _json(diff),
            "draft_text": draft_text, "draft_asset_id": draft_asset_id, "authored": 1 if authored else 0,
            "access": _access(access), "extra_json": _json(dict(extra)) if extra else None})
        tx.insert("proposal_event", {"proposal_id": proposal_id, "at": self.store.clock(), "to_status": normalised,
                                     "actor": actor, "note": original, "change_set_id": tx.change_set_id})
        return proposal_id

    def transition_proposal(self, tx: Tx, proposal_id: str, to_status: str, *, expected_revision: int,
                            actor: str | None = None, note: str | None = None, at: str | None = None) -> None:
        proposal = self.store.require("proposal", proposal_id)
        if to_status not in PROPOSAL_TRANSITIONS:
            raise ConstraintError(f"unknown proposal status {to_status!r}")
        if to_status not in PROPOSAL_TRANSITIONS[proposal["status"]]:
            raise ConstraintError(f"a {proposal['status']} proposal cannot become {to_status}; allowed: "
                                  f"{', '.join(sorted(PROPOSAL_TRANSITIONS[proposal['status']])) or 'none'}")
        tx.update("proposal", proposal_id, {"status": to_status}, expected_revision=expected_revision)
        tx.insert("proposal_event", {"proposal_id": proposal_id, "at": at or self.store.clock(),
                                     "from_status": proposal["status"], "to_status": to_status, "actor": actor,
                                     "note": note, "change_set_id": tx.change_set_id})

    # ========================================================= merge and split
    PERSON_REFERENCES = (
        ("person_name", "person_id"), ("event_participant", "person_id"), ("claim", "subject_person_id"),
        ("claim", "object_person_id"), ("dna_observation", "person_id"), ("external_id", "entity_id"),
        ("link", "to_id"), ("link", "from_id"), ("route_alias", "entity_id"),
    )

    def merge_people(self, tx: Tx, *, survivor_id: str, retired_id: str, reason: str) -> str:
        """Move every reference from ``retired_id`` to ``survivor_id``; reversible with :meth:`undo_merge`.

        The retired person row is kept (labelled), its external ids become
        ``former`` mappings of the survivor, and each moved reference is listed
        in ``entity_merge.moved_json``.
        """
        self.store.require("person", survivor_id)
        retired = self.store.require("person", retired_id)
        from .schema import TABLE_KEYS
        moved: list[dict[str, Any]] = []
        for table, column in self.PERSON_REFERENCES:
            keys = TABLE_KEYS[table]
            for row in self.store.all(f"SELECT * FROM {table} WHERE {column}=?", (retired_id,)):
                where = " AND ".join(f"{key}=?" for key in keys)
                tx.conn.execute(f"UPDATE {table} SET {column}=? WHERE {where}", (survivor_id, *(row[k] for k in keys)))
                after_key = {key: (survivor_id if key == column else row[key]) for key in keys}
                item = {"table": table, "column": column, "key": after_key}
                if table == "external_id" and row["status"] == "current":
                    tx.conn.execute("UPDATE external_id SET status='former' WHERE id=?", (row["id"],))
                    item["status"] = "current"
                tx._audit(table, "|".join(str(row[k]) for k in keys), "update", row.get("revision"), row,
                          {**row, column: survivor_id})
                moved.append(item)
        merge_id = new_id("mrg")
        tx.insert("entity_merge", {"id": merge_id, "kind": "merge", "survivor_id": survivor_id,
                                   "retired_ids": _json([retired_id]),
                                   "moved_json": _json({"label": retired["label"], "rows": moved}),
                                   "reason": reason, "change_set_id": tx.change_set_id})
        tx.update("person", retired_id, {"label": f"merged into {survivor_id}"})
        return merge_id

    def undo_merge(self, tx: Tx, merge_id: str, *, reason: str) -> None:
        merge = self.store.require("entity_merge", merge_id)
        retired_id = json.loads(merge["retired_ids"])[0]
        moved = json.loads(merge["moved_json"])
        for item in moved["rows"]:
            where = " AND ".join(f"{key}=?" for key in item["key"])
            tx.conn.execute(f"UPDATE {item['table']} SET {item['column']}=? WHERE {where}",
                            (retired_id, *item["key"].values()))
            if item.get("status"):
                tx.conn.execute("UPDATE external_id SET status=? WHERE id=?", (item["status"], item["key"]["id"]))
            tx._audit(item["table"], "|".join(str(v) for v in item["key"].values()), "update", None,
                      {item["column"]: merge["survivor_id"]}, {item["column"]: retired_id})
        tx.update("person", retired_id, {"label": moved["label"]})
        tx.insert("entity_merge", {"id": new_id("mrg"), "kind": "split", "survivor_id": retired_id,
                                   "retired_ids": _json([]), "moved_json": merge["moved_json"],
                                   "reason": f"undo {merge_id}: {reason}", "change_set_id": tx.change_set_id})
