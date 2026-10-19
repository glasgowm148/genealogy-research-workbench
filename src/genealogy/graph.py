"""Relationship and life-event traversal over a neutral research case."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .case import ResearchCase, validate_case
from .models import Event, Person, Relationship


@dataclass(frozen=True, slots=True)
class Generation:
    depth: int
    person_ids: tuple[str, ...]


class RelationshipGraph:
    """Query recorded family structure without platform-specific identifiers.

    A ``parent`` relationship uses ``subject_id=child`` and
    ``object_id=parent``. Spouse, partner, sibling and associate relationships
    are treated as symmetric for neighbourhood queries.
    """

    SYMMETRIC_KINDS = frozenset({"spouse", "partner", "sibling", "associate"})

    def __init__(self, case: ResearchCase) -> None:
        errors = validate_case(case)
        if errors:
            raise ValueError("cannot index invalid research case:\n" + "\n".join(f"- {error}" for error in errors))
        self.case = case
        self.people = {
            person.id: person
            for person in case.records(Person)
            if isinstance(person, Person)
        }
        self.relationships = tuple(
            relationship
            for relationship in case.records(Relationship)
            if isinstance(relationship, Relationship)
        )
        self.events = {
            event.id: event
            for event in case.records(Event)
            if isinstance(event, Event)
        }

    def person(self, person_id: str) -> Person:
        try:
            return self.people[person_id]
        except KeyError as error:
            raise KeyError(f"person not found: {person_id}") from error

    def parents(self, person_id: str) -> tuple[Person, ...]:
        self.person(person_id)
        return self._people(
            edge.object_id
            for edge in self.relationships
            if edge.kind.casefold() == "parent" and edge.subject_id == person_id
        )

    def children(self, person_id: str) -> tuple[Person, ...]:
        self.person(person_id)
        return self._people(
            edge.subject_id
            for edge in self.relationships
            if edge.kind.casefold() == "parent" and edge.object_id == person_id
        )

    def partners(self, person_id: str) -> tuple[Person, ...]:
        self.person(person_id)
        return self._people(self._symmetric_neighbours(person_id, {"spouse", "partner"}))

    def neighbours(self, person_id: str, kinds: set[str] | None = None) -> tuple[Person, ...]:
        """Return directly related people, optionally limited by relation kind."""
        self.person(person_id)
        wanted = {kind.casefold() for kind in kinds} if kinds else None
        related: list[str] = []
        for edge in self.relationships:
            kind = edge.kind.casefold()
            if wanted is not None and kind not in wanted:
                continue
            if edge.subject_id == person_id:
                related.append(edge.object_id)
            if edge.object_id == person_id and (kind in self.SYMMETRIC_KINDS or kind == "parent"):
                related.append(edge.subject_id)
        return self._people(related)

    def ancestors(self, person_id: str, max_depth: int | None = None) -> tuple[Generation, ...]:
        return self._generations(person_id, self.parents, max_depth)

    def descendants(self, person_id: str, max_depth: int | None = None) -> tuple[Generation, ...]:
        return self._generations(person_id, self.children, max_depth)

    def connected_component(self, person_id: str) -> tuple[Person, ...]:
        self.person(person_id)
        visited = {person_id}
        pending = [person_id]
        while pending:
            current = pending.pop(0)
            for person in self.neighbours(current):
                if person.id not in visited:
                    visited.add(person.id)
                    pending.append(person.id)
        return self._people(visited)

    def events_for(self, person_id: str) -> tuple[Event, ...]:
        person = self.person(person_id)
        event_ids = set(person.event_ids)
        event_ids.update(
            event.id
            for event in self.events.values()
            if person_id in event.participant_ids
        )
        return tuple(sorted(
            (self.events[event_id] for event_id in event_ids if event_id in self.events),
            key=lambda event: (event.date or "", event.id),
        ))

    def _symmetric_neighbours(self, person_id: str, kinds: set[str]) -> list[str]:
        related = []
        for edge in self.relationships:
            if edge.kind.casefold() not in kinds:
                continue
            if edge.subject_id == person_id:
                related.append(edge.object_id)
            elif edge.object_id == person_id:
                related.append(edge.subject_id)
        return related

    def _generations(
        self,
        person_id: str,
        step: Callable[[str], tuple[Person, ...]],
        max_depth: int | None,
    ) -> tuple[Generation, ...]:
        self.person(person_id)
        if max_depth is not None and (type(max_depth) is not int or max_depth < 0):
            raise ValueError("max_depth must be a non-negative integer or null")
        visited = {person_id}
        current = (self.people[person_id],)
        generations: list[Generation] = []
        depth = 0
        while current and (max_depth is None or depth < max_depth):
            depth += 1
            next_people: dict[str, Person] = {}
            for person in current:
                for related in step(person.id):
                    if related.id not in visited:
                        visited.add(related.id)
                        next_people[related.id] = related
            if not next_people:
                break
            ordered = tuple(next_people[key] for key in sorted(next_people))
            generations.append(Generation(depth, tuple(person.id for person in ordered)))
            current = ordered
        return tuple(generations)

    def _people(self, ids: Iterable[str]) -> tuple[Person, ...]:
        unique = {person_id for person_id in ids if person_id in self.people}
        return tuple(self.people[person_id] for person_id in sorted(unique))
