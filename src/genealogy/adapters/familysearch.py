"""Constrained mapping for FamilySearch-shaped records supplied by a caller."""

import re

from ._mapping import MappingAdapter, as_rows, person_entities, record_id, text, value_for
from ..models import Record, Relationship, Sensitivity


def normalise_familysearch_pid(value: str, *, example: str = "9ABC-DEF") -> str:
    """Validate and canonicalise a FamilySearch Family Tree person ID."""
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{4}-[A-Z0-9]{3}", value):
        raise ValueError(f"'{value}' does not look like a FamilySearch PID such as {example}.")
    return value


class FamilySearchAdapter(MappingAdapter):
    name = "familysearch"
    entity_type = "person"
    capabilities = frozenset({"ingest", "row-mapping", "people", "relationships", "events", "places"})

    def normalise_row(self, external_value: str, data: dict, entity_type: str, sensitivity: Sensitivity) -> list[Record]:
        if entity_type != "person":
            return super().normalise_row(external_value, data, entity_type, sensitivity)
        display = data.get("display") if isinstance(data.get("display"), dict) else {}
        names = as_rows(data.get("names"))
        name = names[0] if names else {}
        facts = as_rows(data.get("facts"))
        birth = next((fact for fact in facts if "birth" in str(fact.get("type", "")).casefold()), {})
        death = next((fact for fact in facts if "death" in str(fact.get("type", "")).casefold()), {})
        entities = person_entities(
            self.name, external_value, data, sensitivity,
            given=value_for(display, "givenName", "given_name") or value_for(name, "given", "givenName"),
            surname=value_for(display, "surname") or value_for(name, "surname"),
            display_name=value_for(display, "name") or value_for(data, "display_name", "name"),
            birth_date=_fact_text(birth, "date", "formal") or value_for(data, "birth_date"),
            birth_place=_fact_text(birth, "place", "place_name") or value_for(data, "birth_place"),
            birth_place_id=_fact_place_id(birth),
            death_date=_fact_text(death, "date", "formal") or value_for(data, "death_date"),
            death_place=_fact_text(death, "place", "place_name") or value_for(data, "death_place"),
            death_place_id=_fact_place_id(death),
        )
        parents = data.get("parents", [])
        if isinstance(parents, dict):
            parents = [parents]
        parent_ids = [text(item.get("id") if isinstance(item, dict) else item) for item in parents if isinstance(item, (dict, str, int))]
        parent_ids.extend(text(value_for(data, name)) for name in ("father_id", "mother_id"))
        for number, parent_id in enumerate(filter(None, parent_ids), start=1):
            entities.append(Relationship(id=record_id(self.name, "relationship", f"{external_value}:parent:{number}"), subject_id=record_id(self.name, "person", external_value), object_id=record_id(self.name, "person", parent_id), kind="parent", sensitivity=sensitivity))
        return entities


def _fact_text(fact: dict, *names: str) -> str | None:
    value = value_for(fact, *names)
    if isinstance(value, dict):
        return text(value.get("formal") or value.get("original") or value.get("name") or value.get("value"))
    return text(value)


def _fact_place_id(fact: dict) -> str | None:
    place = fact.get("place")
    if isinstance(place, dict):
        return text(value_for(place, "id", "originalId", "placeId"))
    return None
