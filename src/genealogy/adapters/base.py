"""Small, provenance-preserving interchange contract for adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import hashlib
import json
from typing import TYPE_CHECKING, Any, Iterable

from ..models import ExternalIdentifier, ImportProvenance, Place, Record, Sensitivity

if TYPE_CHECKING:
    from ..case import ResearchCase


@dataclass(slots=True)
class AdapterRecord:
    """An unaltered adapter observation alongside its external identity.

    ``payload`` is the useful, serialisable working view.  ``raw`` deliberately
    retains the supplied observation, and ``provenance`` records how it entered
    the workbench.  Normalised entities must never replace this audit trail.
    """

    external_id: ExternalIdentifier
    entity_type: str
    payload: dict[str, Any]
    sensitivity: Sensitivity = Sensitivity.PRIVATE
    raw: Any = None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AdapterBatch:
    adapter: str
    records: list[AdapterRecord] = field(default_factory=list)
    entities: list[Record] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    _entity_index: dict[str, Record] = field(default_factory=dict, init=False, repr=False)

    def __iter__(self) -> Iterable[AdapterRecord]:
        return iter(self.records)

    def add_entity(self, entity: Record) -> None:
        """Add one typed neutral entity, refusing malformed duplicates."""
        if not isinstance(entity, Record):
            raise TypeError("adapter entities must be neutral Record instances")
        if not entity.id:
            raise ValueError("adapter entity ids must not be empty")
        # Rebuild after callers append directly through the public list.
        if len(self._entity_index) != len(self.entities):
            self._entity_index = {item.id: item for item in self.entities}
        existing = self._entity_index.get(entity.id)
        if existing is not None:
            # A shared, deterministic place (or other exact entity) is one
            # entity, not an import error.  Conflicting same-id records remain
            # unsafe and are rejected.
            if isinstance(existing, Place) and isinstance(entity, Place) and existing.name.casefold() == entity.name.casefold():
                comparable = entity.to_dict()
                comparable["name"] = existing.name
                if existing.to_dict() == comparable:
                    return
            if type(existing) is type(entity) and existing.to_dict() == entity.to_dict():
                return
            raise ValueError(f"duplicate entity id in adapter batch: {entity.id}")
        self.entities.append(entity)
        self._entity_index[entity.id] = entity

    def extend_entities(self, entities: Iterable[Record]) -> None:
        for entity in entities:
            self.add_entity(entity)

    def add_to_case(self, case: "ResearchCase") -> int:
        """Atomically add this batch after checking cross-batch id collisions.

        The check occurs before mutating the case, so a malformed adapter result
        cannot leave a partially imported research case behind.
        """
        observations = [
            {
                "external_id": item.external_id.to_dict() if hasattr(item.external_id, "to_dict") else {
                    "system": item.external_id.system,
                    "value": item.external_id.value,
                    "url": item.external_id.url,
                    "verified": item.external_id.verified,
                },
                "entity_type": item.entity_type,
                "provenance": item.provenance,
                "sensitivity": item.sensitivity.value,
            }
            for item in self.records
        ]
        provenance: ImportProvenance | None = None
        if observations:
            digest_input = json.dumps(
                {"adapter": self.adapter, "observations": observations},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            provenance = ImportProvenance(
                id=f"import:{self.adapter}:{hashlib.sha256(digest_input).hexdigest()[:20]}",
                adapter=self.adapter,
                observations=observations,
                entity_ids=[entity.id for entity in self.entities],
            )
        candidates = [*self.entities, *([provenance] if provenance else [])]
        existing = {
            record.id: record
            for records in case.record_sets.values()
            for record in records
        }
        entity_ids = [entity.id for entity in candidates]
        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError("adapter batch contains duplicate entity ids")
        pending: list[Record] = []
        for entity in candidates:
            current = existing.get(entity.id)
            if current is None:
                pending.append(entity)
            elif type(current) is not type(entity) or current.to_dict() != entity.to_dict():
                raise ValueError(f"adapter entity id conflicts with case: {entity.id}")
        add_many = getattr(case, "add_many", None)
        if callable(add_many):
            add_many(pending)
        else:
            for entity in pending:
                case.add(entity)
        return sum(not isinstance(entity, ImportProvenance) for entity in pending)


class Adapter(ABC):
    """A boundary converter. Network access and credentials remain caller-owned."""

    name: str
    capabilities: frozenset[str] = frozenset({"ingest"})

    @abstractmethod
    def ingest(self, payload: Any) -> AdapterBatch:
        """Convert supplied service/file data into source-labelled raw records."""

    def external_id(self, value: str, url: str | None = None) -> ExternalIdentifier:
        return ExternalIdentifier(system=self.name, value=value, url=url)
