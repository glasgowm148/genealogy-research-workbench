"""GEDCOM 7.0 and 5.5.1 export from the project database, with a loss report.

GEDCOM is an interchange format here, never the backup or the authority. The
mapping (documented in ``docs/gedcom.md``):

* Each person gets a stable ``UID`` (GEDCOM 7) or ``_UID`` (5.5.1), a UUID
  derived from the project and person ids, so identity survives re-export even
  though ``@I1@``-style cross-reference ids are file-local. WikiTree and other
  external ids become ``EXID`` + ``TYPE`` (7.0) or ``REFN`` + ``TYPE`` (5.5.1).
* Mother and father claims are assessed separately. A ``FAM`` couple record is
  written only where the database holds an explicit spouse/partner claim and
  both parents' claims for that child are current and not disproved. Every other
  parent claim becomes a single-parent ``FAM``; competing fathers therefore
  appear as two ``FAMC`` links, never as an invented couple.
* ``FAMC.STAT`` is written only as ``DISPROVEN`` (assessed confidence
  ``disproved``) or ``PROVEN`` (``documented``); probable and possible are not
  GEDCOM statuses and are carried by the extension below or a ``NOTE``.
* The assessment (the project's status word, grade and any subjective
  estimate) is exported with the documented extension ``_GRWB_ASSESS`` under
  ``FAMC`` and events in 7.0, declared in ``HEAD.SCHMA``, and as a ``NOTE`` in
  5.5.1. Declaring it does not mean another program keeps it.
* Citation ``PAGE`` is the locator; ``DATA.TEXT`` is the current transcription,
  never the researcher's interpretation. ``QUAY`` is not written: the
  workbench keeps record quality and belief in a conclusion separate.
* Competing events (two births) are each exported; the preferred one (best
  current assessment) first.

Records, mentions, identity claims, findings, questions, searches, revisions,
dependencies, approvals and workflow have no GEDCOM equivalent and are counted
in the loss report. Use the native export for a complete copy.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import re
from typing import Any, Iterable
import uuid

from .core import Store

EXTENSION_URI = "https://github.com/glasgowm148/genealogy-research-workbench/blob/main/docs/gedcom.md#_grwb_assess"
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
EVENT_TAGS = {"birth": "BIRT", "death": "DEAT", "burial": "BURI", "baptism": "BAPM", "christening": "CHR",
              "cremation": "CREM", "marriage": "MARR", "residence": "RESI", "census": "CENS", "probate": "PROB",
              "will": "WILL", "emigration": "EMIG", "immigration": "IMMI", "occupation": "OCCU",
              "naturalization": "NATU", "graduation": "GRAD", "retirement": "RETI", "divorce": "DIV"}
FAMILY_EVENTS = {"marriage", "divorce"}
PEDI = {"biological": "BIRTH", "adoptive": "ADOPTED", "foster": "FOSTER", "sealing": "SEALING"}
NAME_TYPES = {"birth": "BIRTH", "married": "MARRIED", "alias": "AKA", "aka": "AKA", "immigrant": "IMMIGRANT",
              "maiden": "MAIDEN", "professional": "PROFESSIONAL"}


@dataclass(slots=True)
class LossReport:
    version: str
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def add(self, key: str, amount: int = 1) -> None:
        if amount:
            self.counts[key] = self.counts.get(key, 0) + amount

    def to_dict(self) -> dict[str, Any]:
        return {"gedcom_version": self.version, "omitted_or_simplified": dict(sorted(self.counts.items())),
                "notes": self.notes}


def gedcom_date(start: str | None, end: str | None, kind: str, original: str | None, version: str) -> tuple[str | None, str | None]:
    """(DATE payload, PHRASE) for a stored date; unparseable wording keeps its words."""
    def one(value: str | None) -> str | None:
        if not value:
            return None
        match = re.fullmatch(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", value)
        if not match:
            return None
        year, month, day = match.groups()
        parts = [str(int(day))] if day else []
        if month:
            parts.append(MONTHS[int(month) - 1])
        parts.append(year)
        return " ".join(parts)
    first, last = one(start), one(end)
    payload = None
    if first:
        payload = {"exact": first, "about": f"ABT {first}", "estimated": f"EST {first}", "calculated": f"CAL {first}",
                   "inferred": f"EST {first}", "before": f"BEF {first}", "after": f"AFT {first}",
                   "between": f"BET {first} AND {last}" if last else f"AFT {first}",
                   "range": f"FROM {first} TO {last}" if last else f"FROM {first}"}.get(kind, first)
    if payload and original and original.strip() != (start or ""):
        return payload, original.strip()
    if payload:
        return payload, None
    if original:
        return ("", original.strip()) if version.startswith("7") else (f"({original.strip()})", None)
    return None, None


class GedcomWriter:
    def __init__(self, store: Store, *, version: str = "7.0", allowed: set[str] | None = None,
                 project_name: str = "Genealogy project", export_date: str | None = None,
                 workbench_version: str = "unknown"):
        if version not in ("7.0", "5.5.1"):
            raise ValueError("GEDCOM version must be 7.0 or 5.5.1")
        self.store = store
        self.version = version
        self.allowed = allowed
        self.project_name = project_name
        self.export_date = export_date
        self.workbench_version = workbench_version
        self.lines: list[str] = []
        self.report = LossReport(version)
        self.project_id = store.meta("project_id") or "project"

    # --------------------------------------------------------------- output
    def emit(self, level: int, tag: str, value: str | None = None) -> None:
        if value is None or value == "":
            self.lines.append(f"{level} {tag}")
            return
        text = str(value).replace("\r\n", "\n").replace("\r", "\n")
        if self.version == "7.0" and text.startswith("@") and not re.fullmatch(r"@[A-Z0-9_]+@", text):
            text = "@" + text
        first, *rest = text.split("\n")
        self._line(level, tag, first)
        for line in rest:
            self._line(level + 1, "CONT", line)

    def _line(self, level: int, tag: str, value: str) -> None:
        if self.version == "5.5.1" and len(value) > 200:
            self.lines.append(f"{level} {tag} {value[:200]}")
            for start in range(200, len(value), 200):
                self.lines.append(f"{level + 1} CONC {value[start:start + 200]}")
            return
        self.lines.append(f"{level} {tag} {value}" if value else f"{level} {tag}")

    def ok(self, entity_id: str | None) -> bool:
        return entity_id is not None and (self.allowed is None or entity_id in self.allowed)

    def uid(self, entity_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"genealogy-research-workbench:{self.project_id}:{entity_id}"))

    # --------------------------------------------------------------- data
    def current(self, claim_id: str) -> dict[str, Any] | None:
        return self.store.one("SELECT r.* FROM assessment a JOIN assessment_revision r ON r.assessment_id=a.id AND "
                              "r.revision=a.current_revision WHERE a.claim_id=? AND a.scope_id='project'", (claim_id,))

    def assessment_words(self, revision: dict[str, Any] | None) -> str | None:
        if not revision:
            return None
        parts = [part for part in (revision.get("status"), revision.get("grade") and f"grade {revision['grade']}",
                                   revision.get("confidence") and f"confidence {revision['confidence']}") if part]
        if revision.get("estimate_percent") is not None:
            parts.append(f"{revision['estimate_kind'] or 'subjective'} estimate {revision['estimate_percent']}%")
        return "; ".join(parts) or None

    def write_assessment(self, level: int, revision: dict[str, Any] | None) -> None:
        words = self.assessment_words(revision)
        if not words:
            return
        if self.version == "7.0":
            self.emit(level, "_GRWB_ASSESS", words)
        else:
            self.emit(level, "NOTE", f"Assessment: {words}")
        if revision and revision.get("estimate_percent") is not None:
            self.report.add("estimates carried only as text or extension")

    def citations(self, level: int, rows: Iterable[dict[str, Any]], xref: dict[str, str]) -> None:
        for row in rows:
            citation = self.store.get("citation", row["citation_id"]) if row.get("citation_id") else None
            if citation is None or not self.ok(citation["id"]) or citation["source_id"] not in xref:
                continue
            self.emit(level, "SOUR", xref[citation["source_id"]])
            locator = citation["locator"]
            if locator:
                self.emit(level + 1, "PAGE", locator)
            text = None
            if citation["record_id"]:
                text = self.store.one(
                    "SELECT r.text FROM transcription t JOIN transcription_revision r ON r.transcription_id=t.id AND "
                    "r.revision=t.current_revision WHERE t.record_id=? AND r.status='current' AND t.kind='transcription' "
                    "ORDER BY t.id LIMIT 1", (citation["record_id"],))
            if text and text["text"] and (self.allowed is None or citation["access"] == "public"):
                self.emit(level + 1, "DATA")
                self.emit(level + 2, "TEXT", text["text"])

    def event_block(self, level: int, event: dict[str, Any], xref: dict[str, str]) -> None:
        tag = EVENT_TAGS.get(event["kind"].casefold(), "EVEN")
        self.emit(level, tag)
        if tag == "EVEN":
            self.emit(level + 1, "TYPE", event["kind"])
        payload, phrase = gedcom_date(event["date_start"], event["date_end"], event["date_kind"],
                                      event["date_original"], self.version)
        if payload is not None:
            self.emit(level + 1, "DATE", payload)
            if phrase and self.version == "7.0":
                self.emit(level + 2, "PHRASE", phrase)
            elif phrase:
                self.report.add("date wording kept only by its interpreted form (5.5.1)")
        place = self.store.get("place", event["place_id"]) if event["place_id"] else None
        if place and self.ok(place["id"]):
            self.emit(level + 1, "PLAC", place["name"])
            if place["latitude"] is not None:
                self.emit(level + 2, "MAP")
                self.emit(level + 3, "LATI", f"{'N' if place['latitude'] >= 0 else 'S'}{abs(place['latitude'])}")
                self.emit(level + 3, "LONG", f"{'E' if place['longitude'] >= 0 else 'W'}{abs(place['longitude'])}")
                if place["precision"]:
                    self.report.add("place precision not representable")
        elif event["place_wording"]:
            self.emit(level + 1, "PLAC", event["place_wording"])
        if event["description"] and self.allowed is None:
            self.emit(level + 1, "NOTE", event["description"])
        claims = self.store.all("SELECT * FROM claim WHERE event_id=? ORDER BY id", (event["id"],))
        for claim in claims:
            self.write_assessment(level + 1, self.current(claim["id"]))
            self.citations(level + 1, self.store.all("SELECT * FROM claim_evidence WHERE claim_id=? ORDER BY id",
                                                     (claim["id"],)), xref)

    # --------------------------------------------------------------- writing
    def write(self) -> str:
        store = self.store
        people = [row for row in store.all("SELECT * FROM person ORDER BY id") if self.ok(row["id"])]
        person_x = {row["id"]: f"@I{index}@" for index, row in enumerate(people, 1)}
        sources = [row for row in store.all("SELECT * FROM source ORDER BY id") if self.ok(row["id"])]
        source_x = {row["id"]: f"@S{index}@" for index, row in enumerate(sources, 1)}
        claims = [row for row in store.all("SELECT * FROM claim WHERE kind='relationship' ORDER BY id")
                  if self.ok(row["id"]) and row["subject_person_id"] in person_x and row["object_person_id"] in person_x]
        assessments = {row["id"]: self.current(row["id"]) for row in claims}

        # ---------- families: explicit couples first, then single parents
        spouses = {frozenset((row["subject_person_id"], row["object_person_id"])): row for row in claims
                   if row["predicate"] in ("spouse", "partner")}
        parent_claims: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in claims:
            if row["predicate"] in ("father", "mother", "parent"):
                parent_claims[row["subject_person_id"]].append(row)
        families: dict[tuple, dict[str, Any]] = {}

        def family(key: tuple, partners: list[str], couple: dict[str, Any] | None) -> dict[str, Any]:
            if key not in families:
                families[key] = {"partners": partners, "couple": couple, "children": []}
            return families[key]

        def disproved(row: dict[str, Any]) -> bool:
            return (assessments.get(row["id"]) or {}).get("confidence") == "disproved"

        for child, rows in sorted(parent_claims.items()):
            used: set[str] = set()
            live = [row for row in rows if not disproved(row)]
            for first in live:
                for second in live:
                    if first["id"] >= second["id"] or first["id"] in used or second["id"] in used:
                        continue
                    pair = frozenset((first["object_person_id"], second["object_person_id"]))
                    roles = {first["predicate"], second["predicate"]}
                    # Two fathers (or two mothers) are competing candidates, never a couple.
                    if len(pair) == 2 and pair in spouses and roles not in ({"father"}, {"mother"}):
                        partners = sorted(pair)
                        family(("couple", *partners), partners, spouses[pair])["children"].append((child, [first, second]))
                        used.update((first["id"], second["id"]))
            for row in rows:
                if row["id"] not in used:
                    family(("single", row["object_person_id"]), [row["object_person_id"]], None)["children"].append((child, [row]))
        for pair, row in sorted(spouses.items(), key=lambda item: item[1]["id"]):
            family(("couple", *sorted(pair)), sorted(pair), row)
        family_x = {key: f"@F{index}@" for index, key in enumerate(sorted(families), 1)}
        famc: dict[str, list[tuple[str, list[dict[str, Any]]]]] = defaultdict(list)
        fams: dict[str, list[str]] = defaultdict(list)
        for key, data in families.items():
            for partner in data["partners"]:
                fams[partner].append(family_x[key])
            for child, rows in data["children"]:
                famc[child].append((family_x[key], rows))

        # ---------- header
        self.emit(0, "HEAD")
        self.emit(1, "GEDC")
        self.emit(2, "VERS", self.version)
        if self.version == "5.5.1":
            self.emit(2, "FORM", "LINEAGE-LINKED")
            self.emit(1, "CHAR", "UTF-8")
        else:
            self.emit(1, "SCHMA")
            self.emit(2, "TAG", f"_GRWB_ASSESS {EXTENSION_URI}")
        self.emit(1, "SOUR", "GENEALOGY-RESEARCH-WORKBENCH")
        self.emit(2, "VERS", self.workbench_version)
        self.emit(2, "NAME", "Genealogy Research Workbench")
        if self.export_date:
            payload, _ = gedcom_date(self.export_date[:10], None, "exact", None, self.version)
            if payload:
                self.emit(1, "DATE", payload)
        if self.version == "5.5.1":
            self.emit(1, "SUBM", "@U1@")
        self.emit(1, "NOTE", f"{self.project_name}. Exported from a genealogy-research-workbench database; "
                             "see the accompanying loss report for what GEDCOM cannot carry.")

        # ---------- people
        for row in people:
            self.emit(0, f"{person_x[row['id']]} INDI")
            for name in store.all("SELECT * FROM person_name WHERE person_id=? ORDER BY preferred DESC, sort_order, id",
                                  (row["id"],)):
                value = name["full_name"]
                if name["surname"] and name["surname"] in value:
                    value = value.replace(name["surname"], f"/{name['surname']}/", 1)
                self.emit(1, "NAME", value)
                if name["given"]:
                    self.emit(2, "GIVN", name["given"])
                if name["surname"]:
                    self.emit(2, "SURN", name["surname"])
                kind = NAME_TYPES.get((name["kind"] or "").casefold())
                if kind:
                    self.emit(2, "TYPE", kind)
                elif name["kind"] and name["kind"] != "unknown":
                    self.emit(2, "TYPE", "OTHER")
                    if self.version == "7.0":
                        self.emit(3, "PHRASE", name["kind"])
            sex = {"male": "M", "female": "F", "unknown": "U", "other": "X" if self.version == "7.0" else "U"}.get(row["sex"] or "")
            if sex:
                self.emit(1, "SEX", sex)
            events = store.all("SELECT e.* FROM event e JOIN event_participant p ON p.event_id=e.id WHERE p.person_id=? "
                               "AND p.role='principal' ORDER BY e.kind, e.date_start, e.id", (row["id"],))
            kinds = defaultdict(int)
            for event in events:
                if not self.ok(event["id"]) or event["kind"].casefold() in FAMILY_EVENTS:
                    continue
                kinds[event["kind"]] += 1
                self.event_block(1, event, source_x)
            for kind, count in kinds.items():
                if count > 1:
                    self.report.add("people with competing events of one kind (all exported)")
            if self.version == "7.0":
                self.emit(1, "UID", self.uid(row["id"]))
            else:
                self.emit(1, "_UID", self.uid(row["id"]).replace("-", "").upper())
            for ident in store.all("SELECT * FROM external_id WHERE entity_id=? ORDER BY system, value", (row["id"],)):
                if ident["status"] not in ("current", "former", "redirect") or ident["system"].startswith("xref:"):
                    continue
                if self.version == "7.0":
                    self.emit(1, "EXID", ident["value"])
                    self.emit(2, "TYPE", ident["url"].rsplit("/", 1)[0] + "/" if ident["url"] and ident["system"] == "wikitree"
                              else f"https://github.com/glasgowm148/genealogy-research-workbench/exid/{ident['system']}"
                              + (f"/{ident['status']}" if ident["status"] != "current" else ""))
                else:
                    self.emit(1, "REFN", ident["value"])
                    self.emit(2, "TYPE", ident["system"] + ("" if ident["status"] == "current" else f" ({ident['status']})"))
            for xref, rows in famc[row["id"]]:
                self.emit(1, "FAMC", xref)
                relation = next((r["relation_type"] for r in rows if r["relation_type"]), None)
                if relation in PEDI:
                    self.emit(2, "PEDI", PEDI[relation])
                elif relation in ("step", "guardian", "in_law"):
                    self.emit(2, "PEDI", "OTHER")
                    if self.version == "7.0":
                        self.emit(3, "PHRASE", relation)
                confidences = {(assessments.get(r["id"]) or {}).get("confidence") for r in rows}
                if confidences == {"disproved"}:
                    self.emit(2, "STAT", "DISPROVEN")
                elif confidences == {"documented"}:
                    self.emit(2, "STAT", "PROVEN")
                for r in rows:
                    if len(rows) > 1:
                        self.emit(2, "NOTE", f"{r['predicate'].capitalize()} claim assessed separately")
                    self.write_assessment(2, assessments.get(r["id"]))
            for xref in sorted(set(fams[row["id"]])):
                self.emit(1, "FAMS", xref)
            if row["summary"] and self.allowed is None:
                self.emit(1, "NOTE", row["summary"])

        # ---------- families
        sex = {row["id"]: row["sex"] for row in people}
        for key in sorted(families):
            data = families[key]
            self.emit(0, f"{family_x[key]} FAM")
            partners = data["partners"]
            if len(partners) == 2:
                first, second = partners
                if sex.get(first) == "female" and sex.get(second) != "female":
                    first, second = second, first
                self.emit(1, "HUSB", person_x[first])
                self.emit(1, "WIFE", person_x[second])
            else:
                parent = partners[0]
                roles = {r["predicate"] for _, rows in data["children"] for r in rows}
                self.emit(1, "WIFE" if roles == {"mother"} or (roles == {"parent"} and sex.get(parent) == "female")
                          else "HUSB", person_x[parent])
            for child, _ in sorted(data["children"], key=lambda item: item[0]):
                self.emit(1, "CHIL", person_x[child])
            if data["couple"]:
                for event in store.all("SELECT e.* FROM event e WHERE e.kind IN ('marriage','divorce') AND e.id IN "
                                       "(SELECT event_id FROM event_participant WHERE person_id=?) AND e.id IN "
                                       "(SELECT event_id FROM event_participant WHERE person_id=?) ORDER BY e.id",
                                       tuple(partners)):
                    if self.ok(event["id"]):
                        self.event_block(1, event, source_x)
                self.write_assessment(1, assessments.get(data["couple"]["id"]))

        # ---------- sources
        for row in sources:
            self.emit(0, f"{source_x[row['id']]} SOUR")
            self.emit(1, "TITL", row["title"])
            if row["author"]:
                self.emit(1, "AUTH", row["author"])
            if row["publication"]:
                self.emit(1, "PUBL", row["publication"])
        if self.version == "5.5.1":
            self.emit(0, "@U1@ SUBM")
            self.emit(1, "NAME", self.project_name)
        self.emit(0, "TRLR")

        # ---------- what GEDCOM could not carry
        for table, label in (("record", "records (occurrences)"), ("mention", "record mentions"),
                             ("documentary_relation", "documentary relationship statements"),
                             ("finding", "findings"), ("question", "research questions"), ("search", "searches"),
                             ("hypothesis", "hypotheses"), ("study", "studies"), ("dependency", "dependencies"),
                             ("approval", "publication approvals"), ("proposal", "workflow proposals"),
                             ("dna_observation", "DNA observations"), ("external_observation", "external tree observations")):
            self.report.add(f"{label} (not in GEDCOM)", store.one(f"SELECT count(*) AS n FROM {table}")["n"])
        self.report.add("identity claims (not in GEDCOM)",
                        store.one("SELECT count(*) AS n FROM claim WHERE kind='identity'")["n"])
        history = store.one("SELECT count(*) AS n FROM assessment_revision r JOIN assessment a ON a.id=r.assessment_id "
                            "WHERE r.revision < a.current_revision")["n"]
        self.report.add("earlier assessment revisions (history not in GEDCOM)", history)
        self.report.add("single-parent families written for unpaired parent claims",
                        sum(1 for key in families if key[0] == "single"))
        if self.allowed is not None:
            self.report.notes.append("Public export: built from the public projection; withheld people and records are absent, "
                                     "not flagged.")
        self.report.notes.append("Cross-reference ids (@I1@) are file-local; use UID/_UID for identity across exports.")
        if self.version == "7.0":
            self.report.notes.append(f"_GRWB_ASSESS is documented at {EXTENSION_URI}; other programs may drop it.")
        return "\n".join(self.lines) + "\n"


def export_gedcom(store: Store, *, version: str = "7.0", allowed: set[str] | None = None, project_name: str = "",
                  export_date: str | None = None, workbench_version: str = "unknown") -> tuple[str, dict[str, Any]]:
    writer = GedcomWriter(store, version=version, allowed=allowed, project_name=project_name or "Genealogy project",
                          export_date=export_date, workbench_version=workbench_version)
    text = writer.write()
    return text, writer.report.to_dict()
