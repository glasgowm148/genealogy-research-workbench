"""Offline GEDCOM 5.5/7 reader; supplied assertions remain unassessed."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from .base import Adapter, AdapterBatch, AdapterRecord
from ._mapping import place_and_event, record_id, reject_raw_material, supplied_coordinates
from ..models import Citation, Claim, Evidence, Event, ExternalIdentifier, Name, Person, Place, Relationship, Sensitivity, Source


@dataclass
class _Node:
    tag: str
    value: str = ""
    identifier: str | None = None
    children: list[_Node] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

    def all(self, tag: str) -> list[_Node]:
        return [child for child in self.children if child.tag == tag]

    def first(self, tag: str) -> str | None:
        nodes = self.all(tag)
        return nodes[0].content() or None if nodes else None

    def content(self) -> str:
        value = self.value
        for child in self.children:
            if child.tag == "CONT":
                value += "\n" + child.content()
            elif child.tag == "CONC":
                value += child.content()
        return value


def _parse(payload: str) -> list[_Node]:
    roots: list[_Node] = []
    stack: list[_Node] = []
    identifiers: set[str] = set()
    for number, raw in enumerate(payload.lstrip("\ufeff").splitlines(), 1):
        if not raw.strip():
            continue
        match = re.fullmatch(r"\s*(\d+)\s+(?:(@[^@\s]+@)\s+)?([A-Za-z0-9_]+)(?:[ \t](.*))?", raw)
        if not match:
            raise ValueError(f"invalid GEDCOM line {number}: expected level, tag and optional value")
        level = int(match[1])
        if level > len(stack):
            raise ValueError(f"invalid GEDCOM level jump at line {number}")
        identifier = match[2].strip("@") if match[2] else None
        if identifier:
            if level or identifier in identifiers:
                raise ValueError(f"duplicate or nested GEDCOM record identifier at line {number}")
            identifiers.add(identifier)
        reject_raw_material({match[3]: match[4] or ""})
        node = _Node(match[3].upper(), match[4] or "", identifier)
        stack = stack[:level]
        if stack:
            stack[-1].children.append(node)
            stack[0].lines.append(raw)
        else:
            roots.append(node)
            node.lines.append(raw)
        stack.append(node)
    if not roots or not any(node.tag in {"INDI", "FAM", "SOUR"} and node.identifier for node in roots):
        raise ValueError("GEDCOM contains no identified INDI, FAM or SOUR records")
    return roots


class GedcomAdapter(Adapter):
    name = "gedcom"
    capabilities = frozenset({"ingest", "gedcom", "people", "relationships", "events", "places", "citations"})

    def ingest(self, payload: Any) -> AdapterBatch:
        if isinstance(payload, bytes):
            try:
                payload = payload.decode("utf-8-sig")
            except UnicodeDecodeError as error:
                raise ValueError("GEDCOM must be UTF-8; convert legacy ANSEL/ANSI files before import") from error
        if not isinstance(payload, str):
            raise TypeError("GEDCOM payload must be text or UTF-8 bytes")
        roots = _parse(payload)
        batch = AdapterBatch(adapter=self.name)
        by_id = {node.identifier: node for node in roots if node.identifier}
        people = {key for key, node in by_id.items() if node.tag == "INDI"}
        sources = {key for key, node in by_id.items() if node.tag == "SOUR"}
        notes = {key: node.content() for key, node in by_id.items() if node.tag == "NOTE"}
        protected = {key for key, node in by_id.items() if _restricted(node)}
        for identifier, node in by_id.items():
            entity_start = len(batch.entities)
            sensitivity = Sensitivity.PRIVATE
            batch.records.append(AdapterRecord(
                self.external_id(identifier), {"INDI": "person", "FAM": "family", "SOUR": "source"}.get(node.tag, "record"),
                {"gedcom_lines": node.lines}, sensitivity, raw=list(node.lines),
                provenance={"adapter": self.name, "gedcom_record": identifier, "format": "GEDCOM", "restriction": node.first("RESN"), "publishable_entity_ids": []},
            ))
            if node.tag == "SOUR":
                repository = node.first("REPO")
                if repository and repository.strip("@") in by_id:
                    repository = by_id[repository.strip("@")].first("NAME") or repository
                batch.add_entity(Source(id=record_id(self.name, "source", identifier), title=node.first("TITL") or node.first("ABBR") or identifier,
                    source_type="gedcom-source", repository=repository, access_note=node.first("TEXT"),
                    external_ids=[self.external_id(identifier)], sensitivity=sensitivity))
            elif node.tag == "INDI":
                person = Person(id=record_id(self.name, "person", identifier), external_ids=[self.external_id(identifier)], sensitivity=sensitivity)
                for number, name in enumerate(node.all("NAME")):
                    value = name.content().replace("/", "").strip()
                    kind = (name.first("TYPE") or ("birth" if number == 0 else "alias")).lower()
                    if value:
                        person.names.append(Name(value=value, kind=kind))
                    for variant in name.children:
                        if variant.tag in {"ROMN", "FONE"} and variant.content():
                            person.names.append(Name(value=variant.content().replace("/", "").strip(), kind="transcription", language=variant.first("LANG")))
                person.notes = self._notes(node, notes)
                death = node.all("DEAT")
                if any(item.value.upper() != "N" for item in death):
                    person.living = False
                living = node.first("_LIVING") or node.first("_ALIVE")
                if living and living.upper() in {"Y", "YES", "TRUE", "1"}:
                    person.living = True
                batch.add_entity(person)
                self._events(batch, node, identifier, [person.id], sources, notes, person)
                sex = node.first("SEX")
                if sex:
                    batch.add_entity(Claim(id=record_id(self.name, "claim", f"{identifier}:sex"), subject_id=person.id, predicate="sex", value=sex, sensitivity=sensitivity))
                self._citations(batch, node, person.id, identifier, sources)
                for number, name in enumerate(node.all("NAME"), 1):
                    self._citations(batch, name, person.id, f"{identifier}:name:{number}", sources)
            elif node.tag == "FAM":
                partners = [item.value.strip("@") for item in node.children if item.tag in {"HUSB", "WIFE"}]
                children = [item.value.strip("@") for item in node.all("CHIL")]
                for relative in dict.fromkeys([*partners, *children]):
                    if relative not in people:
                        batch.warnings.append(f"GEDCOM family {identifier} references missing person {relative}; omitted")
                partners = [item for item in partners if item in people]
                for number, child in enumerate(children):
                    if child not in people:
                        continue
                    for index, parent in enumerate(partners):
                        relation = Relationship(id=record_id(self.name, "relationship", f"{identifier}:parent:{child}:{index}"), subject_id=record_id(self.name, "person", child), object_id=record_id(self.name, "person", parent), kind="parent", sensitivity=sensitivity)
                        batch.add_entity(relation)
                        self._citations(batch, node, relation.id, f"{identifier}:parent:{number}:{index}", sources)
                if len(partners) >= 2:
                    relation = Relationship(id=record_id(self.name, "relationship", f"{identifier}:spouse"), subject_id=record_id(self.name, "person", partners[0]), object_id=record_id(self.name, "person", partners[1]), kind="spouse", sensitivity=sensitivity)
                    batch.add_entity(relation)
                    self._citations(batch, node, relation.id, f"{identifier}:spouse", sources)
                self._events(batch, node, identifier, [record_id(self.name, "person", item) for item in partners], sources, notes)
            related = {item.value.strip("@") for item in node.children if item.tag in {"HUSB", "WIFE", "CHIL"}}
            if not _restricted(node) and not related.intersection(protected):
                # Shared places already in the batch also belong to this record.
                eligible = [entity.id for entity in batch.entities[entity_start:]]
                for entity in batch.entities[entity_start:]:
                    if isinstance(entity, Event) and entity.place_id:
                        eligible.append(entity.place_id)
                batch.records[-1].provenance["publishable_entity_ids"] = list(dict.fromkeys(eligible))
        return batch

    @staticmethod
    def _notes(node: _Node, notes: dict[str, str]) -> str | None:
        values = []
        for item in node.all("NOTE"):
            value = item.content()
            values.append(notes.get(value.strip("@"), value) if value.startswith("@") and value.endswith("@") else value)
        return "\n\n".join(values) or None

    def _events(self, batch: AdapterBatch, node: _Node, identifier: str, participants: list[str], sources: set[str], notes: dict[str, str], person: Person | None = None) -> None:
        tags = {"BIRT": "birth", "DEAT": "death", "BURI": "burial", "CREM": "cremation", "MARR": "marriage", "DIV": "divorce", "RESI": "residence", "OCCU": "occupation", "BAPM": "baptism", "CHR": "christening", "CENS": "census", "EVEN": "event"}
        counts: dict[str, int] = {}
        for item in node.children:
            if item.tag not in tags or (item.tag == "DEAT" and item.value.upper() == "N"):
                continue
            kind = tags[item.tag]
            counts[kind] = counts.get(kind, 0) + 1
            event_key = identifier if counts[kind] == 1 else f"{identifier}:{counts[kind]}"
            values = place_and_event(self.name, participants[0] if participants else "", event_key, kind, item.first("DATE"), item.first("PLAC"), Sensitivity.PRIVATE)
            event = next((value for value in values if isinstance(value, Event)), None)
            if event is None:
                event = Event(id=record_id(self.name, "event", f"{event_key}:{kind}"), kind=kind, sensitivity=Sensitivity.PRIVATE)
                values.append(event)
            event.participant_ids = participants
            event.description = "\n\n".join(value for value in (item.content() if item.value not in {"Y", "N", ""} else None, item.first("TYPE"), self._notes(item, notes)) if value) or None
            places = item.all("PLAC")
            if places:
                maps = places[0].all("MAP")
                if maps:
                    coords = supplied_coordinates(maps[0].first("LATI"), maps[0].first("LONG"))
                    for value in values:
                        if isinstance(value, Place):
                            value.latitude, value.longitude = coords
                            # Coordinate-bearing observations cannot collide with an
                            # unlocated place of the same supplied name.
                            value.id += f":{coords[0]}:{coords[1]}"
                            event.place_id = value.id
            batch.extend_entities(values)
            if person:
                person.event_ids.append(event.id)
            self._citations(batch, item, event.id, f"{event_key}:{kind}", sources)

    def _citations(self, batch: AdapterBatch, node: _Node, subject: str, prefix: str, sources: set[str]) -> None:
        for number, item in enumerate(node.all("SOUR"), 1):
            source = item.value.strip("@")
            if item.value.startswith("@"):
                if source not in sources:
                    batch.warnings.append(f"GEDCOM {prefix} references missing source {source}; citation omitted")
                    continue
                source_id = record_id(self.name, "source", source)
            else:
                source_id = record_id(self.name, "source", f"{prefix}:inline:{number}")
                batch.add_entity(Source(id=source_id, title=item.content() or "Untitled supplied source", source_type="gedcom-inline-source", sensitivity=Sensitivity.PRIVATE))
            citation_id = record_id(self.name, "citation", f"{prefix}:{number}")
            claim_id = record_id(self.name, "claim", f"{prefix}:source:{number}")
            data = item.all("DATA")
            quotation = item.first("TEXT") or (data[0].first("TEXT") if data else None)
            batch.extend_entities([
                Citation(id=citation_id, source_id=source_id, locator=item.first("PAGE"), quotation=quotation, sensitivity=Sensitivity.PRIVATE),
                Claim(id=claim_id, subject_id=subject, predicate="documented-in", value=source_id, citation_ids=[citation_id], rationale="Imported source association; not independently assessed", sensitivity=Sensitivity.PRIVATE),
                Evidence(id=record_id(self.name, "evidence", f"{prefix}:source:{number}"), claim_id=claim_id, citation_id=citation_id, assessment="Unassessed GEDCOM source citation", sensitivity=Sensitivity.PRIVATE),
            ])


def _restricted(node: _Node) -> bool:
    return node.tag == "RESN" or any(_restricted(child) for child in node.children)
