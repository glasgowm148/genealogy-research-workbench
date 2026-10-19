"""Offline GEDCOM 5.5/5.5.1/7 reader; supplied assertions remain unassessed.

The reader keeps provider structure that changes meaning (surname parts,
adoptive/step parent links, source quality, identifiers) and reports, rather
than silently drops, records it cannot interpret. Original lines stay in the
caller's private copy of the file.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import re
from typing import Any

from .base import Adapter, AdapterBatch, AdapterRecord
from ._gedcom_text import decode_gedcom
from ._mapping import place_and_event, record_id, reject_raw_material, supplied_coordinates
from ..models import Citation, Claim, Confidence, Evidence, Event, ExternalIdentifier, LivingStatus, Name, Person, Place, Relationship, Sensitivity, Source

_LINE = re.compile(r"\s*(\d{1,3})\s+(?:(@[^@\s]+@)\s+)?([A-Za-z0-9_]+)(?:[ \t](.*))?")
_TEXT_TAGS = {"NOTE", "SNOTE", "TEXT", "CONT", "CONC", "TITL", "PUBL", "AUTH", "PAGE"}

INDIVIDUAL_EVENTS = {
    "BIRT": "birth", "CHR": "christening", "BAPM": "baptism", "BLES": "blessing", "ADOP": "adoption",
    "BARM": "bar mitzvah", "BASM": "bat mitzvah", "CONF": "confirmation", "FCOM": "first communion",
    "CHRA": "adult christening", "ORDN": "ordination", "GRAD": "graduation", "EDUC": "education",
    "RETI": "retirement", "EMIG": "emigration", "IMMI": "immigration", "NATU": "naturalisation",
    "CENS": "census", "RESI": "residence", "OCCU": "occupation", "TITL": "title", "PROB": "probate",
    "WILL": "will", "DEAT": "death", "BURI": "burial", "CREM": "cremation", "EVEN": "event", "FACT": "fact",
}
FAMILY_EVENTS = {
    "MARR": "marriage", "MARB": "marriage banns", "MARC": "marriage contract", "MARL": "marriage licence",
    "MARS": "marriage settlement", "ENGA": "engagement", "DIV": "divorce", "DIVF": "divorce filed",
    "ANUL": "annulment", "EVEN": "event", "FACT": "fact", "RESI": "residence", "CENS": "census",
}
# Interpreted elsewhere, or administrative structure with nothing to publish.
_HANDLED_INDI = {"NAME", "SEX", "FAMC", "FAMS", "NOTE", "SNOTE", "SOUR", "RESN", "_UID", "UID", "REFN", "EXID",
                 "_FSFTID", "AFN", "RIN", "CHAN", "CREA", "WWW", "_LIVING", "_ALIVE", "SUBM", "ALIA", "ASSO", "_PRIV"}
_HANDLED_FAM = {"HUSB", "WIFE", "CHIL", "NOTE", "SNOTE", "SOUR", "RESN", "_UID", "UID", "REFN", "EXID", "RIN",
                "CHAN", "CREA", "SUBM", "NCHI"}
_IDENTIFIER_TAGS = {"_UID": "uid", "UID": "uid", "REFN": "refn", "EXID": "exid", "_FSFTID": "familysearch", "AFN": "afn", "WWW": "url"}
_PEDIGREE = {
    "birth": "birth", "natural": "birth", "biological": "birth", "adopted": "adopted", "adoptive": "adopted",
    "foster": "foster", "step": "step", "stepchild": "step", "sealing": "sealing", "sealed": "sealing",
}
_QUALITY = {
    "0": "0 — unreliable or estimated evidence", "1": "1 — questionable reliability",
    "2": "2 — secondary evidence", "3": "3 — direct and primary evidence",
}


@dataclass
class _Node:
    tag: str
    value: str = ""
    identifier: str | None = None
    children: list[_Node] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    line: int = 0

    def all(self, tag: str) -> list[_Node]:
        return [child for child in self.children if child.tag == tag]

    def first(self, tag: str) -> str | None:
        nodes = self.all(tag)
        return nodes[0].content() or None if nodes else None

    def node(self, tag: str) -> _Node | None:
        nodes = self.all(tag)
        return nodes[0] if nodes else None

    def content(self) -> str:
        value = self.value
        for child in self.children:
            if child.tag == "CONT":
                value += "\n" + child.content()
            elif child.tag == "CONC":
                value += child.content()
        return value

    def pointer(self) -> str | None:
        value = self.value.strip()
        return value[1:-1] if len(value) > 2 and value.startswith("@") and value.endswith("@") else None


def _unescape(value: str) -> str:
    # GEDCOM 5.5 doubles a literal "@" in line values; pointers are not values.
    return value if re.fullmatch(r"@[^@\s]+@", value.strip()) else value.replace("@@", "@")


def _parse(payload: str, warnings: list[str]) -> list[_Node]:
    """Parse lines; text accidentally wrapped without CONT is kept as continuation.

    Some exporters (including WikiTree's) emit raw newlines inside long notes.
    Such a line cannot be a GEDCOM line, so it is appended to the preceding text
    node and reported. A malformed line that does not follow text still fails.
    """
    roots: list[_Node] = []
    stack: list[_Node] = []
    identifiers: set[str] = set()
    repaired: list[int] = []
    for number, raw in enumerate(payload.lstrip("﻿").splitlines(), 1):
        if not raw.strip():
            continue
        match = _LINE.fullmatch(raw)
        level = int(match[1]) if match else None
        tag = match[3] if match else ""
        structural = bool(match) and level <= len(stack)
        tag_like = tag.isupper() or tag.startswith("_") or not tag.isalpha()
        current = stack[-1] if stack else None
        texty = current is not None and bool(current.value or current.tag in _TEXT_TAGS)
        if not (structural and (tag_like or not texty)):
            if not texty:
                if match and level is not None and level > len(stack):
                    raise ValueError(f"invalid GEDCOM level jump at line {number}")
                raise ValueError(f"invalid GEDCOM line {number}: expected level, tag and optional value")
            owner = stack[-2] if current.tag in ("CONT", "CONC") and len(stack) > 1 else current
            owner.children.append(_Node("CONT", raw, line=number))
            stack[0].lines.append(raw)
            repaired.append(number)
            continue
        identifier = match[2].strip("@") if match[2] else None
        if identifier:
            if level or identifier in identifiers:
                raise ValueError(f"duplicate or nested GEDCOM record identifier at line {number}")
            identifiers.add(identifier)
        reject_raw_material({tag: match[4] or ""})
        node = _Node(tag.upper(), _unescape(match[4] or ""), identifier, line=number)
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
    if repaired:
        sample = ", ".join(str(item) for item in repaired[:8])
        warnings.append(f"{len(repaired)} GEDCOM lines were not valid GEDCOM lines and were kept as continued text of the preceding note or value (lines {sample}{', …' if len(repaired) > 8 else ''})")
    return roots


def _pedigree(value: str | None) -> str | None:
    if not value:
        return None
    normalised = " ".join(value.strip().casefold().split())
    if not normalised or normalised in {"unknown", "?"}:
        return None
    return _PEDIGREE.get(normalised, normalised)


def _name_parts(node: _Node) -> tuple[str, str | None, str | None]:
    raw = node.content()
    given = node.first("GIVN")
    surname = node.first("SURN")
    slashed = re.search(r"/([^/]*)/?", raw)
    if surname is None and slashed and slashed[1].strip():
        surname = slashed[1].strip()
    if given is None:
        before = raw.split("/", 1)[0].strip()
        given = before or None
    value = " ".join(raw.replace("/", " ").split())
    if not value:
        value = " ".join(part for part in (node.first("NPFX"), given, surname, node.first("NSFX")) if part)
    return value, given, surname


class GedcomAdapter(Adapter):
    name = "gedcom"
    capabilities = frozenset({"ingest", "gedcom", "people", "relationships", "events", "places", "citations"})

    def ingest(self, payload: Any) -> AdapterBatch:
        warnings: list[str] = []
        if isinstance(payload, bytes):
            payload, _, warnings = decode_gedcom(payload)
        if not isinstance(payload, str):
            raise TypeError("GEDCOM payload must be text or bytes")
        roots = _parse(payload, warnings)
        batch = AdapterBatch(adapter=self.name, warnings=warnings)
        by_id = {node.identifier: node for node in roots if node.identifier}
        people = {key for key, node in by_id.items() if node.tag == "INDI"}
        sources = {key for key, node in by_id.items() if node.tag == "SOUR"}
        notes = {key: node.content() for key, node in by_id.items() if node.tag in ("NOTE", "SNOTE")}
        protected = {key for key, node in by_id.items() if _restricted(node)}
        unsupported: Counter[str] = Counter()
        self._unsupported = unsupported
        # Child-to-family link qualifiers can be written on INDI.FAMC or FAM.CHIL.
        famc: dict[tuple[str, str], dict[str, str | None]] = {}
        for identifier, node in by_id.items():
            if node.tag != "INDI":
                continue
            for link in node.all("FAMC"):
                family = link.pointer()
                if family:
                    pedi = _pedigree(link.first("PEDI"))
                    famc[(identifier, family)] = {
                        "HUSB": _pedigree(link.first("_FREL")) or pedi, "WIFE": _pedigree(link.first("_MREL")) or pedi,
                        "status": (link.first("STAT") or "").strip().upper() or None,
                    }
            for adoption in node.all("ADOP"):
                family_link = adoption.node("FAMC")
                family = family_link.pointer() if family_link else None
                if family:
                    who = (family_link.first("ADOP") or "BOTH").strip().upper()
                    entry = famc.setdefault((identifier, family), {"HUSB": None, "WIFE": None, "status": None})
                    for role in ("HUSB", "WIFE"):
                        if who in ("BOTH", role) and entry[role] is None:
                            entry[role] = "adopted"
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
                repo_node = node.node("REPO")
                if repo_node and repo_node.pointer() in by_id:
                    repository = by_id[repo_node.pointer()].first("NAME") or repository
                call_number = repo_node.first("CALN") if repo_node else None
                if call_number:
                    repository = f"{repository} (call number {call_number})" if repository and not repository.startswith("@") else f"Call number {call_number}"
                if repository and repository.startswith("@"):
                    repository = None
                batch.add_entity(Source(id=record_id(self.name, "source", identifier), title=node.first("TITL") or node.first("ABBR") or identifier,
                    source_type="gedcom-source", repository=repository, author=node.first("AUTH"), publication=node.first("PUBL"),
                    access_note=node.first("TEXT"), external_ids=[self.external_id(identifier)], sensitivity=sensitivity))
            elif node.tag == "INDI":
                self._individual(batch, node, identifier, sources, notes)
            elif node.tag == "FAM":
                self._family(batch, node, identifier, people, sources, notes, famc)
            related = {item.value.strip("@") for item in node.children if item.tag in {"HUSB", "WIFE", "CHIL"}}
            if not _restricted(node) and not related.intersection(protected):
                # Shared places already in the batch also belong to this record.
                eligible = [entity.id for entity in batch.entities[entity_start:]
                            if not (isinstance(entity, Relationship) and entity.confidence is Confidence.DISPROVED)]
                for entity in batch.entities[entity_start:]:
                    if isinstance(entity, Event) and entity.place_id:
                        eligible.append(entity.place_id)
                batch.records[-1].provenance["publishable_entity_ids"] = list(dict.fromkeys(eligible))
        if unsupported:
            summary = ", ".join(f"{tag}×{count}" for tag, count in unsupported.most_common(12))
            more = len(unsupported) - 12
            batch.warnings.append(f"Unsupported GEDCOM structures were kept only in the private original file: {summary}{f' and {more} more' if more > 0 else ''}")
        return batch

    def _individual(self, batch: AdapterBatch, node: _Node, identifier: str, sources: set[str], notes: dict[str, str]) -> None:
        person = Person(id=record_id(self.name, "person", identifier), external_ids=[self.external_id(identifier)], sensitivity=Sensitivity.PRIVATE)
        for number, name in enumerate(node.all("NAME")):
            value, given, surname = _name_parts(name)
            kind = (name.first("TYPE") or ("birth" if number == 0 else "alias")).strip().lower()
            if value:
                person.names.append(Name(value=value, kind=kind, given=given, surname=surname))
            for variant in name.children:
                if variant.tag in {"ROMN", "FONE", "TRAN"} and variant.content():
                    person.names.append(Name(value=" ".join(variant.content().replace("/", " ").split()), kind="transcription", language=variant.first("LANG")))
                elif variant.tag in {"_MARN", "_MARNM"} and variant.content():
                    person.names.append(Name(value=" ".join(filter(None, (given, variant.content().strip()))), kind="married", given=given, surname=variant.content().strip()))
                elif variant.tag in {"_AKA", "_AKAN"} and variant.content():
                    person.names.append(Name(value=" ".join(variant.content().replace("/", " ").split()), kind="alias"))
                elif variant.tag == "NICK" and variant.content():
                    person.names.append(Name(value=variant.content().strip(), kind="nickname"))
        for alias in node.all("ALIA"):
            if alias.value and not alias.pointer():
                person.names.append(Name(value=" ".join(alias.value.replace("/", " ").split()), kind="alias"))
        person.notes = self._notes(node, notes)
        # A recorded death, burial or cremation is the export's own death evidence.
        if any(item.value.strip().upper() != "N" for tag in ("DEAT", "BURI", "CREM") for item in node.all(tag)):
            person.living = LivingStatus.DECEASED
        living = node.first("_LIVING") or node.first("_ALIVE")
        if living and living.strip().upper() in {"Y", "YES", "TRUE", "1"}:
            person.living = LivingStatus.LIVING
        for child in node.children:
            system = _IDENTIFIER_TAGS.get(child.tag)
            value = child.content().strip()
            if system and value:
                label = child.first("TYPE")
                url = value if system == "url" and re.match(r"https?://", value) else None
                person.external_ids.append(ExternalIdentifier(system=f"gedcom:{system}" + (f":{label.strip()}" if label else ""), value=value, url=url))
        batch.add_entity(person)
        self._events(batch, node, identifier, [person.id], sources, notes, INDIVIDUAL_EVENTS, person)
        sex = node.first("SEX")
        if sex and sex.strip():
            batch.add_entity(Claim(id=record_id(self.name, "claim", f"{identifier}:sex"), subject_id=person.id, predicate="sex", value=sex.strip(), sensitivity=Sensitivity.PRIVATE))
        self._citations(batch, node, person.id, identifier, sources)
        for number, name in enumerate(node.all("NAME"), 1):
            self._citations(batch, name, person.id, f"{identifier}:name:{number}", sources)
        self._count_unsupported("INDI", node, _HANDLED_INDI | INDIVIDUAL_EVENTS.keys())

    def _family(self, batch: AdapterBatch, node: _Node, identifier: str, people: set[str], sources: set[str], notes: dict[str, str], famc: dict) -> None:
        roles = [(item.tag, item.pointer()) for item in node.children if item.tag in {"HUSB", "WIFE"}]
        children = list(dict.fromkeys(item.pointer() for item in node.all("CHIL")))
        for relative in dict.fromkeys([*(value for _, value in roles), *children]):
            if relative and relative != "VOID" and relative not in people:
                batch.warnings.append(f"GEDCOM family {identifier} references missing person {relative}; omitted")
        partners = [(role, value) for role, value in roles if value in people]
        if len(partners) > 2:
            batch.warnings.append(f"GEDCOM family {identifier} lists {len(partners)} partners; only the first two are linked as a couple")
        child_nodes = {item.pointer(): item for item in node.all("CHIL")}
        for number, child in enumerate(children):
            if child not in people:
                continue
            link = famc.get((child, identifier), {})
            child_node = child_nodes.get(child)
            for index, (role, parent) in enumerate(partners):
                pedigree = link.get(role)
                if child_node is not None:
                    pedigree = _pedigree(child_node.first("_FREL" if role == "HUSB" else "_MREL")) or pedigree
                disproved = link.get("status") == "DISPROVEN"
                relation = Relationship(id=record_id(self.name, "relationship", f"{identifier}:parent:{child}:{index}"), subject_id=record_id(self.name, "person", child), object_id=record_id(self.name, "person", parent), kind="parent",
                                        confidence=Confidence.DISPROVED if disproved else Confidence.UNKNOWN, pedigree=pedigree,
                                        tree_status=(link.get("status") or "").casefold() or None, sensitivity=Sensitivity.PRIVATE)
                batch.add_entity(relation)
                self._citations(batch, node, relation.id, f"{identifier}:parent:{number}:{index}", sources)
        if len(partners) >= 2:
            relation = Relationship(id=record_id(self.name, "relationship", f"{identifier}:spouse"), subject_id=record_id(self.name, "person", partners[0][1]), object_id=record_id(self.name, "person", partners[1][1]), kind="spouse", sensitivity=Sensitivity.PRIVATE)
            batch.add_entity(relation)
            self._citations(batch, node, relation.id, f"{identifier}:spouse", sources)
        self._events(batch, node, identifier, [record_id(self.name, "person", value) for _, value in partners], sources, notes, FAMILY_EVENTS)
        self._count_unsupported("FAM", node, _HANDLED_FAM | FAMILY_EVENTS.keys())

    def _count_unsupported(self, record: str, node: _Node, handled: set[str]) -> None:
        for child in node.children:
            if child.tag not in handled:
                self._unsupported[f"{record}.{child.tag}"] += 1

    @staticmethod
    def _notes(node: _Node, notes: dict[str, str]) -> str | None:
        values = []
        for item in [*node.all("NOTE"), *node.all("SNOTE")]:
            pointer = item.pointer()
            values.append(notes.get(pointer, "") if pointer else item.content())
        return "\n\n".join(value for value in values if value) or None

    def _events(self, batch: AdapterBatch, node: _Node, identifier: str, participants: list[str], sources: set[str], notes: dict[str, str], tags: dict[str, str], person: Person | None = None) -> None:
        counts: dict[str, int] = {}
        for item in node.children:
            if item.tag not in tags or (item.value.strip().upper() == "N" and not item.children):
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
            supplied = item.content() if item.value.strip().upper() not in {"Y", "N", ""} else None
            event.description = "\n\n".join(value for value in (supplied, item.first("TYPE"), self._notes(item, notes)) if value) or None
            places = item.all("PLAC")
            if places:
                maps = places[0].all("MAP")
                if maps:
                    try:
                        coords = supplied_coordinates(maps[0].first("LATI"), maps[0].first("LONG"))
                    except ValueError as error:
                        batch.warnings.append(f"GEDCOM {identifier} {kind} place has invalid supplied coordinates ({error}); coordinates omitted")
                        coords = (None, None)
                    if coords != (None, None):
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
            source = item.pointer()
            if source:
                if source not in sources:
                    if source != "VOID":
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
            quality = (item.first("QUAY") or "").strip()
            assessment = "Unassessed GEDCOM source citation"
            if quality:
                assessment += f"; the export's own quality grade QUAY {_QUALITY.get(quality, quality)} is retained, not independently checked"
            batch.extend_entities([
                Citation(id=citation_id, source_id=source_id, locator=item.first("PAGE"), quotation=quotation, sensitivity=Sensitivity.PRIVATE),
                Claim(id=claim_id, subject_id=subject, predicate="documented-in", value=source_id, citation_ids=[citation_id], rationale="Imported source association; not independently assessed", sensitivity=Sensitivity.PRIVATE),
                Evidence(id=record_id(self.name, "evidence", f"{prefix}:source:{number}"), claim_id=claim_id, citation_id=citation_id, assessment=assessment, sensitivity=Sensitivity.PRIVATE),
            ])


def _restricted(node: _Node) -> bool:
    return node.tag in ("RESN", "_PRIV") or any(_restricted(child) for child in node.children)
