"""Constrained helpers for mapping supplied rows to neutral research records."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .base import Adapter, AdapterBatch, AdapterRecord
from ..models import Event, ExternalIdentifier, LivingStatus, Name, Person, Place, Record, Sensitivity, Source, contains_raw_dna_material


def key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def value_for(data: Mapping[str, Any], *names: str) -> Any:
    normalised: dict[str, Any] = {}
    for name, value in data.items():
        normalised.setdefault(key(str(name)), value)
    for name in names:
        value = normalised.get(key(name))
        if value not in (None, ""):
            return value
    return None


def text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def input_sensitivity(
    data: Mapping[str, Any],
    fallback: Sensitivity,
    *,
    provider_privacy: bool = False,
) -> Sensitivity:
    """Combine access signals conservatively; protected flags cannot be downgraded."""
    levels: list[Sensitivity] = []
    explicit = value_for(data, "sensitivity", "access_level")
    if explicit is not None:
        try:
            levels.append(Sensitivity(explicit))
        except ValueError as error:
            raise ValueError(f"unknown input sensitivity: {explicit!r}") from error
    if provider_privacy:
        privacy = value_for(data, "privacy")
        if privacy is not None:
            try:
                levels.append(Sensitivity.PUBLIC if int(str(privacy)) >= 50 else Sensitivity.RESTRICTED)
            except (TypeError, ValueError) as error:
                raise ValueError(f"provider Privacy must be numeric: {privacy!r}") from error
    for key_name, level in (
        ("raw_dna", Sensitivity.RAW_DNA),
        ("raw_sensitive", Sensitivity.RAW_DNA),
        ("licensed", Sensitivity.LICENSED),
        ("licensed_source", Sensitivity.LICENSED),
        ("restricted", Sensitivity.RESTRICTED),
        ("private", Sensitivity.PRIVATE),
    ):
        flag = value_for(data, key_name)
        if flag is not None:
            if type(flag) is not bool:
                raise ValueError(f"input privacy flag {key_name} must be a boolean")
            if flag:
                levels.append(level)
    if not levels:
        return fallback
    rank = {
        Sensitivity.PUBLIC: 0,
        Sensitivity.RESTRICTED: 1,
        Sensitivity.LICENSED: 2,
        Sensitivity.PRIVATE: 3,
        Sensitivity.RAW_DNA: 4,
    }
    return max(levels, key=rank.__getitem__)


def as_rows(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def record_id(adapter: str, kind: str, external_value: str) -> str:
    return f"{adapter}:{kind}:{external_value}"


def place_id(adapter: str, name: str) -> str:
    digest = hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()[:16]
    return record_id(adapter, "place", digest)


def place_and_event(
    adapter: str,
    person_id: str,
    external_value: str,
    kind: str,
    date: Any,
    place_name: Any,
    sensitivity: Sensitivity,
    external_place_id: Any = None,
    latitude: Any = None,
    longitude: Any = None,
) -> list[Record]:
    date_text, location = text(date), text(place_name)
    if not date_text and not location:
        return []
    event_id = record_id(adapter, "event", f"{external_value}:{kind}")
    entities: list[Record] = []
    location_id = None
    if location:
        provider_place_id = text(external_place_id)
        location_id = (
            record_id(adapter, "place", provider_place_id)
            if provider_place_id
            else place_id(adapter, location)
        )
        lat, lon = supplied_coordinates(latitude, longitude)
        if lat is not None or lon is not None:
            location_id += f":{lat}:{lon}"
        external_ids = (
            [ExternalIdentifier(system=adapter, value=provider_place_id)]
            if provider_place_id
            else []
        )
        entities.append(Place(
            id=location_id,
            name=location,
            latitude=lat, longitude=lon,
            external_ids=external_ids,
            sensitivity=sensitivity,
        ))
    entities.append(Event(id=event_id, kind=kind, date=date_text, date_precision="supplied" if date_text else "unknown", place_id=location_id, participant_ids=[person_id], sensitivity=sensitivity))
    return entities


def person_entities(adapter: str, external_value: str, data: Mapping[str, Any], sensitivity: Sensitivity, *, given: Any = None, surname: Any = None, display_name: Any = None, birth_date: Any = None, birth_place: Any = None, birth_place_id: Any = None, death_date: Any = None, death_place: Any = None, death_place_id: Any = None) -> list[Record]:
    """Make a person and only the common, explicit birth/death facts."""
    person_id = record_id(adapter, "person", external_value)
    given = text(given) or text(value_for(data, "given_name", "first_name", "firstname"))
    surname = text(surname) or text(value_for(data, "surname", "last_name", "lastname", "last_name_at_birth"))
    display_name = text(display_name) or text(value_for(data, "display_name", "full_name", "name"))
    joined = " ".join(part for part in (given, surname) if part)
    person = Person(id=person_id, names=[Name(value=joined or display_name, kind="birth" if joined else "preferred")] if joined or display_name else [], external_ids=[ExternalIdentifier(system=adapter, value=external_value)], living=_living(value_for(data, "living", "is_living")), sensitivity=sensitivity)
    birth = place_and_event(adapter, person_id, external_value, "birth", birth_date or value_for(data, "birth_date", "birthdate"), birth_place or value_for(data, "birth_place", "birthplace"), sensitivity, birth_place_id or value_for(data, "birth_place_id", "birthplaceid"))
    death = place_and_event(adapter, person_id, external_value, "death", death_date or value_for(data, "death_date", "deathdate"), death_place or value_for(data, "death_place", "deathplace"), sensitivity, death_place_id or value_for(data, "death_place_id", "deathplaceid"))
    person.event_ids = [item.id for item in [*birth, *death] if isinstance(item, Event)]
    person.notes = text(value_for(data, "notes", "biography", "bio"))
    return [person, *birth, *death]


def _living(value: Any) -> LivingStatus:
    if isinstance(value, bool):
        return LivingStatus.LIVING if value else LivingStatus.DECEASED
    if isinstance(value, str):
        normalised = value.strip().casefold()
        if normalised in {"living", "true", "yes", "1"}:
            return LivingStatus.LIVING
        if normalised in {"deceased", "dead", "false", "no", "0"}:
            return LivingStatus.DECEASED
    return LivingStatus.UNKNOWN


class MappingAdapter(Adapter):
    """Base for rows whose source format is already a mapping or CSV row."""

    entity_type = "record"
    default_sensitivity = Sensitivity.PRIVATE
    capabilities = frozenset({"ingest", "row-mapping", "provenance"})

    def ingest(self, payload: Any) -> AdapterBatch:
        rows: Iterable[Mapping[str, Any]] = [payload] if isinstance(payload, Mapping) else payload
        batch = AdapterBatch(adapter=self.name)
        for number, row in enumerate(rows, start=1):
            if not isinstance(row, Mapping):
                raise TypeError("adapter payload rows must be mappings")
            raw = dict(row)
            data = dict(row)
            value = text(data.pop("id", data.pop("external_id", number))) or str(number)
            url = text(data.get("url"))
            type_name = text(data.pop("entity_type", self.entity_type)) or self.entity_type
            sensitivity = input_sensitivity(data, self.default_sensitivity)
            batch.records.append(AdapterRecord(self.external_id(value, url), type_name, data, sensitivity, raw=raw, provenance={"adapter": self.name, "row": number}))
            batch.extend_entities(self.normalise_row(value, data, type_name, sensitivity))
        return batch

    def normalise_row(self, external_value: str, data: Mapping[str, Any], entity_type: str, sensitivity: Sensitivity) -> list[Record]:
        if entity_type == "person":
            return person_entities(self.name, external_value, data, sensitivity)
        if entity_type == "source":
            title = text(value_for(data, "title", "source_title", "name"))
            if title:
                return [Source(id=record_id(self.name, "source", external_value), title=title, source_type=text(value_for(data, "source_type", "type")) or "unknown", repository=text(value_for(data, "repository", "archive")), url=text(value_for(data, "source_url", "url")), external_ids=[ExternalIdentifier(system=self.name, value=external_value)], sensitivity=sensitivity)]
        return []


def supplied_coordinates(latitude: Any, longitude: Any) -> tuple[float | None, float | None]:
    """Validate supplied decimal coordinates, including GEDCOM N/S/E/W prefixes."""
    def convert(value: Any, axis: str, bound: float) -> float | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            raise ValueError(f"invalid supplied {axis}")
        value = str(value).strip().upper()
        direction = value[0] if value and value[0] in "NSEW" else None
        if direction:
            if direction not in ("NS" if axis == "latitude" else "EW"):
                raise ValueError(f"invalid supplied {axis} direction")
            value = value[1:].strip()
        try:
            number = float(value)
        except ValueError as error:
            raise ValueError(f"invalid supplied {axis}") from error
        if direction:
            number = abs(number) * (-1 if direction in "SW" else 1)
        if not math.isfinite(number) or abs(number) > bound:
            raise ValueError(f"supplied {axis} is outside its valid range")
        return number
    return convert(latitude, "latitude", 90), convert(longitude, "longitude", 180)


def reject_raw_material(value: Any) -> None:
    """Reject genetic payloads before normalisation can discard unknown fields.

    Boolean access markers remain supported for compatibility; case boundaries
    reject records bearing the resulting RAW_DNA access level.
    """
    if isinstance(value, Mapping):
        for name, child in value.items():
            marker = key(str(name))
            if marker in {"rawdna", "rawsensitive"} and type(child) is bool:
                continue
            if contains_raw_dna_material({str(name): None}) or marker == "dna":
                raise ValueError("raw DNA material cannot be imported into a case")
            reject_raw_material(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            reject_raw_material(child)
