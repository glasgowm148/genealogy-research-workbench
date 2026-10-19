"""Constrained mapping for WikiTree-shaped records supplied by a caller."""

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import unquote, urlparse

from ._mapping import person_entities, record_id, text, value_for
from .base import AdapterBatch
from .onetree import OneTreeAdapter, _profile_value, _with_living_from_death
from ..case import CaseStore, ResearchCase
from ..models import Person, Record, Relationship, Sensitivity


def normalise_wikitree_profile_id(value: str, *, example: str = "Example-123") -> str:
    """Accept a WikiTree profile ID or URL and return its stable profile ID."""
    value = value.strip()
    if not value:
        raise ValueError("WikiTree ID cannot be empty.")
    if "://" in value:
        parsed = urlparse(value)
        hostname = (parsed.hostname or "").casefold()
        if hostname != "wikitree.com" and not hostname.endswith(".wikitree.com"):
            raise ValueError("The URL is not a WikiTree URL.")
        match = re.search(r"/wiki/([^/?#]+)", parsed.path)
        if not match:
            raise ValueError("Could not find a WikiTree ID in the URL.")
        value = unquote(match.group(1))
    value = value.replace(" ", "_")
    if not re.fullmatch(r"[^\s/]+-\d+", value):
        raise ValueError(f"'{value}' does not look like a WikiTree ID such as {example}.")
    return value


class WikiTreeAdapter(OneTreeAdapter):
    name = "wikitree"
    entity_type = "person"
    capabilities = frozenset({"ingest", "row-mapping", "people", "relationships", "events", "places"})

    def ingest(self, payload: Any) -> AdapterBatch:
        """Accept direct rows and common API ``items``/``resultByKey`` envelopes."""
        if isinstance(payload, Mapping):
            for key in ("items", "resultByKey", "profiles"):
                rows = payload.get(key)
                if isinstance(rows, Mapping):
                    return super().ingest({"data": rows})
                if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
                    expanded = _api_item_rows(rows) if key == "items" else list(rows)
                    return super().ingest(expanded)
        if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
            flattened: list[Any] = []
            for item in payload:
                if isinstance(item, Mapping) and any(key in item for key in ("items", "resultByKey", "profiles")):
                    nested = self.ingest(item)
                    flattened.extend(record.raw for record in nested.records)
                else:
                    flattened.append(item)
            return super().ingest(flattened)
        return super().ingest(payload)

    def normalise_row(
        self,
        external_value: str,
        data: dict,
        entity_type: str,
        sensitivity: Sensitivity,
        id_to_profile: Mapping[str, str] | None = None,
    ) -> list[Record]:
        id_to_profile = id_to_profile or {}
        if entity_type != "person":
            return super().normalise_row(external_value, data, entity_type, sensitivity)
        data = _with_living_from_death(data)
        identifier = text(value_for(data, "name", "profile_id", "profile")) or external_value
        entities = person_entities(
            self.name, identifier, data, sensitivity,
            given=value_for(data, "first_name", "firstname", "real_name"),
            surname=value_for(data, "last_name_at_birth", "lastnameatbirth", "last_name_current", "lastnamecurrent"),
            birth_date=value_for(data, "birth_date", "birthdate"), birth_place=value_for(data, "birth_location", "birthlocation"),
            death_date=value_for(data, "death_date", "deathdate"), death_place=value_for(data, "death_location", "deathlocation"),
        )
        for role, relation_kind in (("father", "parent"), ("mother", "parent")):
            related = text(value_for(data, role, f"{role}_id"))
            if related:
                related = _profile_value(related, id_to_profile)
                entities.append(Relationship(
                    id=record_id(self.name, "relationship", f"{identifier}:{role}"),
                    subject_id=record_id(self.name, "person", identifier), object_id=record_id(self.name, "person", related),
                    kind=relation_kind, sensitivity=sensitivity,
                ))
        spouses = value_for(data, "spouse", "spouses")
        if isinstance(spouses, str):
            spouses = [spouses]
        if isinstance(spouses, list):
            for number, spouse in enumerate(spouses, start=1):
                spouse_id = text(spouse.get("id") if isinstance(spouse, dict) else spouse)
                if spouse_id:
                    entities.append(Relationship(
                        id=record_id(self.name, "relationship", f"{identifier}:spouse:{number}"),
                        subject_id=record_id(self.name, "person", identifier), object_id=record_id(self.name, "person", spouse_id),
                        kind="spouse", sensitivity=sensitivity,
                    ))
        return entities


DEFAULT_RELATION_COLLECTIONS = ("Parents", "Children", "Siblings", "Spouses")


def iter_relation_profiles(
    person: Mapping[str, Any],
    relation_names: Sequence[str] = DEFAULT_RELATION_COLLECTIONS,
):
    """Yield profile mappings from WikiTree relationship containers."""
    for relation in relation_names:
        raw = person.get(relation, {})
        values = raw.values() if isinstance(raw, Mapping) else raw if isinstance(raw, list) else []
        yield from (value for value in values if isinstance(value, Mapping))


def collect_family_profile_names(
    relatives_envelope: Mapping[str, Any],
    requested_id: str,
    relation_names: Sequence[str] = DEFAULT_RELATION_COLLECTIONS,
) -> list[str]:
    """Collect a subject and immediate relatives' stable WikiTree names."""
    items = relatives_envelope.get("items")
    if not isinstance(items, list) or not items or not isinstance(items[0], Mapping):
        raise ValueError("WikiTree relatives envelope has no item")
    item = items[0]
    person = item.get("person")
    if not isinstance(person, Mapping):
        raise ValueError("WikiTree relatives envelope has no subject person")
    names = {requested_id}
    subject_name = person.get("Name") or item.get("user_name")
    if subject_name:
        names.add(str(subject_name))
    names.update(
        str(name)
        for profile in iter_relation_profiles(person, relation_names)
        if (name := profile.get("Name"))
    )
    return sorted(names)


def merge_family_profile(
    stub: Mapping[str, Any],
    full_profiles: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Hydrate a relation stub while preserving relation-specific metadata."""
    name = stub.get("Name")
    if not name or str(name) not in full_profiles:
        return dict(stub)
    merged = dict(full_profiles[str(name)])
    for key, value in stub.items():
        if str(key).startswith("marriage_") or key == "do_not_display":
            merged[str(key)] = value
    return merged


def hydrate_family_envelope(
    relatives_envelope: dict[str, Any],
    full_profiles: Mapping[str, Mapping[str, Any]],
    requested_id: str,
    relation_names: Sequence[str] = DEFAULT_RELATION_COLLECTIONS,
) -> dict[str, Any]:
    """Replace subject and immediate-relative stubs with full profiles."""
    items = relatives_envelope.get("items")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise ValueError("WikiTree relatives envelope has no mutable item")
    item = items[0]
    stub_subject = item.get("person")
    if not isinstance(stub_subject, Mapping):
        raise ValueError("WikiTree relatives envelope has no subject person")
    subject_name = stub_subject.get("Name") or item.get("user_name") or requested_id
    subject = dict(full_profiles.get(str(subject_name), stub_subject))
    for relation in relation_names:
        raw = stub_subject.get(relation, {})
        if isinstance(raw, Mapping):
            subject[relation] = {
                str(relation_id): merge_family_profile(stub, full_profiles)
                for relation_id, stub in raw.items()
                if isinstance(stub, Mapping)
            }
        elif isinstance(raw, list):
            subject[relation] = [
                merge_family_profile(stub, full_profiles)
                for stub in raw if isinstance(stub, Mapping)
            ]
        else:
            subject[relation] = {}
    item["person"] = subject
    return relatives_envelope


def extract_biography(profile: Mapping[str, Any]) -> str | None:
    """Read WikiTree biography text across the common API shapes."""
    biography = profile.get("Bio", profile.get("bio"))
    if isinstance(biography, str):
        return biography.strip() or None
    if isinstance(biography, Mapping):
        for key in ("wiki", "Wiki", "bio", "html"):
            value = biography.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return json.dumps(dict(biography), ensure_ascii=False, indent=2, sort_keys=True)
    return None


def wikitree_family_case(
    payload: Any,
    *,
    case_id: str,
    title: str | None = None,
) -> ResearchCase:
    """Normalise a supplied WikiTree family capture into a valid local case.

    A getRelatives capture can contain scalar references to profiles that were
    not returned. Those references remain in the provider observation, but
    cannot become neutral relationships until both people are present.
    """
    batch = WikiTreeAdapter().ingest(payload)
    person_ids = {
        entity.id for entity in batch.entities if isinstance(entity, Person)
    }
    if not person_ids:
        raise ValueError("WikiTree family capture contains no people")
    batch.entities = [
        entity
        for entity in batch.entities
        if not isinstance(entity, Relationship)
        or entity.subject_id in person_ids and entity.object_id in person_ids
    ]
    case = ResearchCase(
        id=case_id,
        title=title or f"WikiTree family capture {case_id}",
    )
    batch.add_to_case(case)
    return case


def save_wikitree_family_case(
    payload: Any,
    directory: str | Path,
    *,
    case_id: str,
    title: str | None = None,
) -> Path:
    """Persist a supplied family capture through the neutral case contract."""
    return CaseStore(directory).save(
        wikitree_family_case(payload, case_id=case_id, title=title)
    )


def _api_item_rows(items: Sequence[Any]) -> list[Mapping[str, Any]]:
    """Flatten getRelatives-style item/person envelopes and their family maps."""
    rows: list[Mapping[str, Any]] = []
    seen_profiles: set[str] = set()
    seen_relationships: set[tuple[str, str, str]] = set()

    def identity(profile: Mapping[str, Any], fallback: Any = None) -> str | None:
        return text(value_for(profile, "name", "profile_id", "id")) or text(fallback)

    def add_profile(profile: Mapping[str, Any], fallback: Any = None) -> str | None:
        identifier = identity(profile, fallback)
        if identifier and identifier not in seen_profiles:
            seen_profiles.add(identifier)
            rows.append(profile)
        return identifier

    def related_profiles(value: Any) -> list[tuple[Any, Mapping[str, Any]]]:
        if isinstance(value, Mapping):
            if identity(value):
                return [(None, value)]
            return [(key, item) for key, item in value.items() if isinstance(item, Mapping)]
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return [(None, item) for item in value if isinstance(item, Mapping)]
        return []

    for item in items:
        if not isinstance(item, Mapping):
            continue
        subject = item.get("person") if isinstance(item.get("person"), Mapping) else item
        subject_id = add_profile(subject)
        if not subject_id:
            continue
        for container, kind, reverse in (
            ("Parents", "parent", False),
            ("Children", "parent", True),
            ("Siblings", "sibling", False),
            ("Spouses", "spouse", False),
        ):
            for fallback, related in related_profiles(value_for(subject, container)):
                related_id = add_profile(related, fallback)
                if not related_id:
                    continue
                left, right = (related_id, subject_id) if reverse else (subject_id, related_id)
                signature = (left, right, kind)
                if signature in seen_relationships:
                    continue
                seen_relationships.add(signature)
                rows.append({
                    "id": f"api:{left}:{kind}:{right}",
                    "entity_type": "relationship",
                    "subject_id": left,
                    "object_id": right,
                    "kind": kind,
                    "sensitivity": "private",
                })
    return rows
