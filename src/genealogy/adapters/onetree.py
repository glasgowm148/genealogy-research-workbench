"""Offline mapping for OneTree profile exports and explicit relationship rows."""

from collections.abc import Mapping, Sequence
import json
from datetime import date
import re
from typing import Any

from ._mapping import MappingAdapter, input_sensitivity, person_entities, record_id, reject_raw_material, supplied_coordinates, text, value_for
from .base import AdapterBatch, AdapterRecord
from ..models import Claim, Confidence, ExternalIdentifier, Name, Person, Place, Record, Relationship, Sensitivity


class OneTreeAdapter(MappingAdapter):
    name = "one-tree"
    entity_type = "relationship"
    capabilities = frozenset({"ingest", "row-mapping", "relationships", "people", "events", "places"})

    def ingest(self, payload: Any) -> AdapterBatch:
        """Accept JSON, profile lists/dictionaries, data wrappers and people/edges."""
        if isinstance(payload, (str, bytes)):
            try:
                payload = json.loads(payload)
            except (ValueError, UnicodeDecodeError) as error:
                raise ValueError("OneTree input must be valid JSON") from error
        reject_raw_material(payload)
        wrapped = isinstance(payload, Mapping) and "data" in payload
        explicit_collection = isinstance(payload, Mapping) and "people" in payload
        source_rows = payload["data"] if wrapped else payload
        if explicit_collection:
            rows = self._rows(payload["people"])
            rows += [(fallback, {**row, "entity_type": "relationship"}) for fallback, row in self._rows(payload.get("relationships", []))]
        else:
            rows = self._rows(source_rows)
        if not rows and self.name != "one-tree":
            return AdapterBatch(adapter=self.name)
        if not rows:
            raise ValueError("OneTree input contains no profiles or relationships")
        id_to_profile: dict[str, str] = {}
        prepared = []
        known_people: set[str] = set()
        for number, (fallback, row) in enumerate(rows, 1):
            entity_type = text(value_for(row, "entity_type")) or ("relationship" if self._is_relation(row) else "person")
            # Provider Name/profile IDs are identities; generic lowercase name
            # is display text and may be shared by several explicit IDs.
            external = onetree_external_id(row, fallback)
            if self.name != "one-tree":
                # WikiTree subclass accepts case-insensitive provider Name.
                external = text(value_for(row, "name", "profile_id", "profile")) or external
            if not external:
                raise ValueError(f"OneTree row {number} needs an id or profile name")
            if entity_type not in {"person", "relationship"}:
                raise ValueError(f"unsupported OneTree entity_type: {entity_type}")
            if entity_type == "person":
                if external in known_people:
                    raise ValueError(f"duplicate OneTree person id: {external}")
                known_people.add(external)
                for candidate in (value_for(row, "id"), value_for(row, "profile_id"), fallback, external):
                    candidate = text(candidate)
                    if candidate:
                        previous = id_to_profile.get(candidate)
                        if previous and previous != external:
                            raise ValueError(f"ambiguous OneTree provider identifier: {candidate}")
                        id_to_profile[candidate] = external
            prepared.append((external, dict(row), entity_type))
        batch = AdapterBatch(adapter=self.name)
        # A legacy isolated relationship row is a supported interchange API. Full
        # imports, however, must never fabricate missing profile endpoints.
        relation_only = not known_people and not explicit_collection and len(prepared) == 1
        protected_people = {
            external for external, row, kind in prepared
            if kind == "person" and not _publishable(row)
        }
        for number, (external, data, entity_type) in enumerate(prepared, 1):
            sensitivity = _provider_sensitivity(data, Sensitivity.PRIVATE)
            observation = AdapterRecord(self.external_id(external, text(value_for(data, "url"))), entity_type, data, sensitivity,
                raw=dict(data), provenance={"adapter": self.name, "row": number, "wrapper": wrapped, "publishable_entity_ids": [],
                    "provider_confidence": {key: value for key, value in data.items() if "confidence" in key.casefold() or key.casefold() == "datastatus"}})
            batch.records.append(observation)
            entities = self.normalise_row(external, data, entity_type, sensitivity, id_to_profile)
            for entity in entities:
                if isinstance(entity, Place) and sensitivity != Sensitivity.PRIVATE:
                    old_id = entity.id
                    entity.id += f":{sensitivity.value}"
                    for associated in entities:
                        if getattr(associated, "place_id", None) == old_id:
                            associated.place_id = entity.id
                if isinstance(entity, Relationship) and not relation_only and self.name == "one-tree":
                    endpoints = [entity.subject_id.removeprefix(f"{self.name}:person:"), entity.object_id.removeprefix(f"{self.name}:person:")]
                    missing = [item for item in endpoints if item not in known_people]
                    if missing:
                        batch.warnings.append(f"OneTree {external} references missing person {', '.join(missing)}; relationship omitted")
                        continue
                batch.add_entity(entity)
                if _publishable(data):
                    if not isinstance(entity, Relationship) or not any(value.removeprefix(f"{self.name}:person:") in protected_people for value in (entity.subject_id, entity.object_id)):
                        observation.provenance["publishable_entity_ids"].append(entity.id)
        return batch

    @staticmethod
    def _rows(value: Any) -> list[tuple[Any, Mapping[str, Any]]]:
        if isinstance(value, Mapping):
            # A profile-id dictionary is distinguishable from a single row by
            # every value being a profile mapping.
            if value and all(isinstance(item, Mapping) for item in value.values()):
                return list(value.items())
            return [(None, value)] if value else []
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            if not all(isinstance(row, Mapping) for row in value):
                raise TypeError("OneTree payload rows must be mappings")
            return [(None, row) for row in value]
        raise TypeError("OneTree input must be a profile mapping or list of mappings")

    @staticmethod
    def _is_relation(data: Mapping[str, Any]) -> bool:
        return bool(value_for(data, "subject_id", "person_id", "child_id", "from_id", "object_id", "relative_id", "parent_id", "to_id"))

    def normalise_row(self, external_value: str, data: dict, entity_type: str, sensitivity: Sensitivity, id_to_profile: Mapping[str, str] | None = None) -> list[Record]:
        id_to_profile = id_to_profile or {}
        if entity_type == "person":
            entity_data = _with_living_from_death(data)
            entities = person_entities(self.name, external_value, entity_data, sensitivity,
                birth_place=value_for(data, "birth_place", "birth_location"), death_place=value_for(data, "death_place", "death_location"),
                surname=value_for(data, "surname", "last_name_at_birth", "last_name"))
            person = entities[0]
            numeric_id = text(value_for(data, "id"))
            if numeric_id and numeric_id != external_value:
                person.external_ids.append(ExternalIdentifier(system=f"{self.name}:numeric", value=numeric_id))
            current_surname = text(value_for(data, "last_name_current"))
            given = text(value_for(data, "given_name", "first_name"))
            if given and current_surname:
                variant = f"{given} {current_surname}"
                if not any(item.value == variant for item in person.names):
                    person.names.append(Name(value=variant, kind="married"))
            variants = value_for(data, "aliases", "name_variants") or []
            if isinstance(variants, str):
                variants = [variants]
            for variant in variants:
                value = text(variant) or (text(variant.get("value")) if isinstance(variant, Mapping) else None)
                if value:
                    person.names.append(Name(value=value, kind="alias"))
            bio = value_for(data, "bio", "biography", "notes")
            if isinstance(bio, Mapping):
                person.notes = text(value_for(bio, "wiki", "text", "plain"))
            sex = text(value_for(data, "sex", "gender"))
            if sex:
                entities.append(Claim(id=record_id(self.name, "claim", f"{external_value}:sex"), subject_id=person.id, predicate="sex", value=sex, sensitivity=sensitivity))
            for kind in ("birth", "death"):
                latitude = value_for(data, f"{kind}_latitude", f"{kind}_lat")
                longitude = value_for(data, f"{kind}_longitude", f"{kind}_lon", f"{kind}_lng")
                if latitude is not None or longitude is not None:
                    coords = supplied_coordinates(latitude, longitude)
                    event = next((item for item in entities if getattr(item, "kind", None) == kind), None)
                    if event and event.place_id:
                        place = next(item for item in entities if isinstance(item, Place) and item.id == event.place_id)
                        place.latitude, place.longitude = coords
                        place.id += f":{coords[0]}:{coords[1]}"
                        event.place_id = place.id
            for role in ("father", "mother"):
                related = _relative_id(value_for(data, role, f"{role}_id"), id_to_profile)
                if related:
                    entities.append(Relationship(id=record_id(self.name, "relationship", f"{external_value}:{role}"), subject_id=person.id, object_id=record_id(self.name, "person", related), kind="parent", confidence=_confidence(value_for(data, f"{role}_confidence")), sensitivity=sensitivity))
            for collection, relation_kind in (("spouses", "spouse"), ("children", "parent")):
                relatives = value_for(data, collection, collection.rstrip("s"))
                if relatives is None:
                    continue
                if isinstance(relatives, Mapping):
                    relatives = list(relatives.values()) if not value_for(relatives, "id", "name", "profile_id") else [relatives]
                if not isinstance(relatives, list):
                    relatives = [relatives]
                for number, relative in enumerate(relatives, 1):
                    related = _relative_id(relative, id_to_profile)
                    if related:
                        subject, object_ = (person.id, record_id(self.name, "person", related))
                        if collection == "children":
                            subject, object_ = object_, subject
                        entities.append(Relationship(id=record_id(self.name, "relationship", f"{external_value}:{collection}:{number}"), subject_id=subject, object_id=object_, kind=relation_kind, confidence=_confidence(value_for(relative, "confidence") if isinstance(relative, Mapping) else None), sensitivity=sensitivity))
            return entities
        subject = text(value_for(data, "subject_id", "person_id", "child_id", "from_id"))
        object_ = text(value_for(data, "object_id", "relative_id", "parent_id", "to_id"))
        kind = text(value_for(data, "relationship", "relationship_type", "kind", "type"))
        if not (subject and object_ and kind):
            raise ValueError(f"OneTree relationship {external_value} needs subject, object and kind")
        return [Relationship(id=record_id(self.name, "relationship", external_value), subject_id=record_id(self.name, "person", _profile_value(subject, id_to_profile)), object_id=record_id(self.name, "person", _profile_value(object_, id_to_profile)), kind=kind.casefold(), confidence=_confidence(value_for(data, "confidence")), sensitivity=sensitivity)]


def _confidence(value: Any) -> Confidence:
    # An imported confidence label is a provider assertion, never independent proof.
    try:
        result = Confidence(str(value).lower())
        return Confidence.UNKNOWN if result is Confidence.DOCUMENTED else result
    except ValueError:
        return Confidence.UNKNOWN


def _relative_id(value: Any, id_to_profile: Mapping[str, str]) -> str:
    if isinstance(value, Mapping):
        value = onetree_external_id(value)
    value = text(value)
    return "" if value in {None, "0", ""} else _profile_value(value, id_to_profile)


def _profile_value(value: str | None, id_to_profile: Mapping[str, str]) -> str:
    return id_to_profile.get(value or "", value or "")


def _with_living_from_death(data: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(data)
    death = text(value_for(data, "death_date", "deathdate"))
    if value_for(data, "living", "is_living") is None and _actual_death_date(death):
        result["living"] = False
    return result


def _publishable(data: Mapping[str, Any]) -> bool:
    explicit = value_for(data, "sensitivity", "access_level")
    if explicit is not None and explicit != "public":
        return False
    for field in ("restricted", "licensed", "licensed_source", "raw_dna", "raw_sensitive", "private"):
        if value_for(data, field):
            return False
    privacy = value_for(data, "privacy")
    if privacy is not None:
        try:
            return int(str(privacy)) >= 50
        except ValueError:
            return False
    return True


def _provider_sensitivity(data: Mapping[str, Any], fallback: Sensitivity) -> Sensitivity:
    return input_sensitivity(data, fallback, provider_privacy=True)


def onetree_external_id(data: Mapping[str, Any], fallback: Any = None) -> str | None:
    """Select provider identities before generic IDs, keeping display names distinct."""
    provider = text(data.get("Name")) or text(value_for(data, "profile_id", "profile"))
    return provider or text(value_for(data, "id", "external_id")) or text(fallback) or text(value_for(data, "name"))


def _actual_death_date(value: str | None) -> bool:
    """Recognise supported dates conservatively; placeholder text is no death evidence."""
    if not value:
        return False
    value = value.strip().upper()
    value = re.sub(r"^(ABT|ABOUT|BEF|BEFORE|AFT|AFTER|EST|CAL)\s+", "", value)
    iso = re.fullmatch(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", value)
    if iso:
        year = int(iso[1])
        month = int(iso[2] or 0)
        day = int(iso[3] or 0)
    else:
        gedcom = re.fullmatch(r"(?:(\d{1,2})\s+)?(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+(\d{4})", value)
        if not gedcom:
            return False
        year = int(gedcom[3])
        month = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split().index(gedcom[2]) + 1
        day = int(gedcom[1] or 0)
    if day and not month:
        return False
    try:
        supplied = date(year, month or 1, day or 1)
    except ValueError:
        return False
    return supplied <= date.today()
