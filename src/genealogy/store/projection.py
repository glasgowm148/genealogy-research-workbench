"""The one public projection of a project database.

Every public consumer (the website, its JSON/CSV/GeoJSON/GEDCOM downloads,
feeds, search indexes and sitemaps) is built from :func:`public_case`, which
reads the complete private database and returns an in-memory
:class:`~genealogy.case.ResearchCase` containing only what may be published,
plus a private :class:`Omissions` report saying what was left out and why.

Rules, applied before the site's own fail-closed export gate (which runs again):

* Only rows whose ``access`` is ``public`` are candidates. Unknown or
  ambiguous access is private.
* People must be deceased, or have no living indication and a birth more than
  ``living_birth_years`` before the build year; ``living`` people never appear.
* Claims, findings and other assertions marked ``withheld`` never appear;
  relationship claims appear only when both people do.
* Anything that names, cites or links an omitted entity is omitted with it
  (repeated to a fixed point by the export gate).
* Transcription text appears only from a public transcription whose current
  revision is not withdrawn.
* Files appear only under an active exact-file approval whose SHA-256 equals
  the file's current bytes; a changed file loses its approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import json
from pathlib import Path
import re
from typing import Any

from ..case import ResearchCase
from ..models import (
    Citation, Claim, ClaimStatus, Confidence, Event, Evidence, ExternalIdentifier, Finding, Haplogroup, Hypothesis,
    LivingStatus, Name, Person, Place, Relationship, ResearchQuestion, Search, Sensitivity, Source, Study,
)
from ..publication import HISTORICAL_YEARS, birth_upper_year
from .project import Project

CONFIDENCES = {c.value for c in Confidence}
DATE_PRECISION = {"exact": "exact", "about": "about", "before": "before", "after": "after", "between": "range",
                  "range": "range", "estimated": "about", "calculated": "about", "inferred": "about",
                  "unknown": "unknown"}
WITHHELD_STATUSES = ("withheld",)


@dataclass(slots=True)
class Omissions:
    """Private: what the public projection left out, by entity, with reasons."""

    items: list[dict[str, str]] = field(default_factory=list)
    withheld_terms: set[str] = field(default_factory=set)
    withheld_files: set[str] = field(default_factory=set)   # matched against output file names only
    published_assets: list[dict[str, Any]] = field(default_factory=list)

    def add(self, entity_id: str, kind: str, reason: str) -> None:
        self.items.append({"id": entity_id, "type": kind, "reason": reason})

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for item in self.items:
            key = f"{item['type']}: {item['reason']}"
            result[key] = result.get(key, 0) + 1
        return dict(sorted(result.items()))


def _extra(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("extra_json")
    return json.loads(value) if value else {}


def _safe_url(value: str | None) -> str | None:
    from urllib.parse import urlsplit
    if not value:
        return None
    try:
        url = urlsplit(value)
    except ValueError:
        return None
    if url.scheme not in ("http", "https") or not url.netloc or url.username or url.password:
        return None
    return value


def _iso(value: str | None) -> str | None:
    if value and re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", value):
        return value
    return None


def public_case(project: Project, *, build_year: int | None = None,
                everything: bool = False) -> tuple[ResearchCase, Omissions]:
    """The public projection; ``everything=True`` gives the complete private view for local tools.

    The private view keeps each row's own access level and is never passed to a
    public output (the site's export gate would remove its private rows anyway).
    """
    store = project.store
    config = project.config
    year = build_year or date.today().year
    living_years = int(config.privacy.get("living_birth_years", HISTORICAL_YEARS))
    grades = config.grades
    omissions = Omissions()
    case = ResearchCase(id=config.project_id or "project", title=config.name, summary="",
                        created_at="1970-01-01T00:00:00+00:00", updated_at="1970-01-01T00:00:00+00:00")
    public = Sensitivity.PUBLIC
    # External identifiers are published only for systems the project names
    # (default: WikiTree and FamilySearch); file-local and private ids never.
    public_systems = set(config.raw.get("publication", {}).get("external_id_systems", ["wikitree", "familysearch"]))

    def pub(row: dict[str, Any]) -> bool:
        return everything or row["access"] == "public"

    def sens(row: dict[str, Any]) -> Sensitivity:
        return Sensitivity(row["access"]) if everything else public

    def withheld_status(row: dict[str, Any]) -> bool:
        return not everything and row.get("publication_status") in WITHHELD_STATUSES

    def withhold(row: dict[str, Any], kind: str, reason: str) -> None:
        omissions.add(row["id"], kind, reason)
        omissions.withheld_terms.add(row["id"])

    # ------------------------------------------------------------ places
    places: dict[str, Place] = {}
    for row in store.all("SELECT * FROM place ORDER BY id"):
        if not pub(row):
            withhold(row, "place", f"access {row['access']}")
            continue
        places[row["id"]] = Place(id=row["id"], name=row["name"], parent_id=row["parent_id"], latitude=row["latitude"],
                                  longitude=row["longitude"], precision=row["precision"], region=row["region"],
                                  sensitivity=sens(row))
    for place in list(places.values()):
        if place.parent_id and place.parent_id not in places:
            place.parent_id = None
    case.add_many(list(places.values()))

    # ------------------------------------------------------------ people
    births: dict[str, str | None] = {}
    for row in store.all("SELECT p.person_id, e.date_start, e.date_original FROM event_participant p "
                         "JOIN event e ON e.id = p.event_id WHERE e.kind='birth' AND p.role='principal' "
                         "ORDER BY e.date_start"):
        births.setdefault(row["person_id"], row["date_start"] or row["date_original"])
    external = {}
    for row in store.all("SELECT * FROM external_id ORDER BY system, value"):
        external.setdefault(row["entity_id"], []).append(row)
    people: dict[str, Person] = {}
    for row in store.all("SELECT * FROM person ORDER BY id"):
        if not pub(row):
            withhold(row, "person", f"access {row['access']}")
            continue
        if row["living"] == "living" and not everything:
            withhold(row, "person", "living")
            continue
        if row["living"] != "deceased" and not everything:
            upper = birth_upper_year(births.get(row["id"]))
            if upper is None or upper >= year - living_years:
                withhold(row, "person", "living status unknown and birth not shown to be historical")
                continue
        names = [Name(value=n["full_name"], kind=n["kind"], given=n["given"], surname=n["surname"],
                      language=n["language"], confidence=Confidence(n["confidence"] or "unknown"))
                 for n in store.all("SELECT * FROM person_name WHERE person_id=? ORDER BY preferred DESC, sort_order, id",
                                    (row["id"],))]
        ids = [ExternalIdentifier(system=x["system"], value=x["value"], url=_safe_url(x["url"]), verified=bool(x["verified"]))
               for x in external.get(row["id"], [])
               if x["status"] == "current" and (everything or x["system"] in public_systems)]
        former = [x["value"] for x in external.get(row["id"], []) if x["status"] in ("former", "redirect")]
        people[row["id"]] = Person(id=row["id"], names=names or [Name(value=row["label"] or "Unnamed person")],
                                   external_ids=ids, living=LivingStatus(row["living"]) if everything else LivingStatus.DECEASED, notes=row["summary"],
                                   sensitivity=sens(row), former_ids=former)
    for row in store.all("SELECT id FROM person ORDER BY id"):
        if row["id"] not in people:
            omissions.withheld_terms.update(x["value"] for x in external.get(row["id"], []))
            for name in store.all("SELECT full_name FROM person_name WHERE person_id=?", (row["id"],)):
                if " " in name["full_name"].strip():   # a lone surname or forename is not identifying
                    omissions.withheld_terms.add(name["full_name"].strip())

    # ------------------------------------------------------------ sources
    sources: dict[str, Source] = {}
    repositories = {row["id"]: row for row in store.all("SELECT * FROM repository")}
    holdings = {row["source_id"]: row for row in store.all("SELECT * FROM source_holding ORDER BY id DESC")}
    for row in store.all("SELECT * FROM source ORDER BY id"):
        if not pub(row):
            withhold(row, "source", f"access {row['access']}")
            continue
        holding = holdings.get(row["id"])
        repository = repositories.get(holding["repository_id"]) if holding and holding["repository_id"] else None
        sources[row["id"]] = Source(id=row["id"], title=row["title"], source_type=row["kind"],
                                    repository=repository["name"] if repository else None, author=row["author"],
                                    publication=row["publication"], url=_safe_url(row["url"]) if not everything else row["url"],
                                    licence=row["licence"],
                                    access_note=row["access_note"], sensitivity=sens(row))
    case.add_many(list(sources.values()))

    records = {row["id"]: row for row in store.all("SELECT * FROM record ORDER BY id")}
    transcriptions: dict[str, str] = {}
    for row in store.all("SELECT t.record_id, t.access, r.text, r.status FROM transcription t JOIN transcription_revision r "
                         "ON r.transcription_id=t.id AND r.revision=t.current_revision ORDER BY t.id"):
        if pub(row) and (row["status"] == "current" or everything) and row["text"]:
            transcriptions.setdefault(row["record_id"], row["text"])
    copies = {row["id"]: row for row in store.all("SELECT * FROM source_copy")}
    citations: dict[str, Citation] = {}
    for row in store.all("SELECT * FROM citation ORDER BY id"):
        record = records.get(row["record_id"]) if row["record_id"] else None
        if not pub(row) or row["source_id"] not in sources or (record and not pub(record)):
            withhold(row, "citation", "citation, its record or its source is not public")
            continue
        source_row = store.get("source", row["source_id"])
        copy = copies.get(row["copy_id"]) if row["copy_id"] else None
        quality = source_row["originality"] if source_row["originality"] in ("original", "derivative", "authored") else None
        if copy and copy["form"] in ("transcript_site", "index", "abstract"):
            quality = "derivative"
        if record and _extra(record).get("citation_quality") in ("original", "derivative", "authored"):
            quality = _extra(record)["citation_quality"]
        citations[row["id"]] = Citation(
            id=row["id"], source_id=row["source_id"], locator=row["locator"] or (record["locator"] if record else None),
            abstract=record["summary"] if record else None,
            transcription=transcriptions.get(row["record_id"]) if row["record_id"] else None,
            accessed_on=row["accessed_on"], sensitivity=sens(row), quality=quality,
            information=(record["information"] if record and record["information"] in ("primary", "secondary", "undetermined") else None))
    case.add_many(list(citations.values()))
    citations_of_record: dict[str, list[str]] = {}
    for citation_id, citation in citations.items():
        row = store.get("citation", citation_id)
        if row["record_id"]:
            citations_of_record.setdefault(row["record_id"], []).append(citation_id)

    # ------------------------------------------------------------ events
    event_ids: dict[str, list[str]] = {}
    for row in store.all("SELECT * FROM event ORDER BY id"):
        roles = store.all("SELECT person_id, role FROM event_participant WHERE event_id=? ORDER BY sort_order, person_id", (row["id"],))
        participants = list(dict.fromkeys(p["person_id"] for p in roles))
        rejected = store.one("SELECT 1 FROM claim c JOIN assessment a ON a.claim_id=c.id AND a.scope_id='project' "
                             "JOIN assessment_revision r ON r.assessment_id=a.id AND r.revision=a.current_revision "
                             "WHERE c.event_id=? AND (r.confidence='disproved' OR c.publication_status='withheld')",
                             (row["id"],))
        if not pub(row) or (rejected and not everything) or any(p not in people for p in participants):
            withhold(row, "event", "not public, rejected, or concerns a withheld person")
            continue
        place_id = row["place_id"] if row["place_id"] in places else None
        description = row["description"]
        if not place_id and row["place_wording"]:
            description = f"{row['place_wording']}" + (f". {description}" if description else "")
        case.add(Event(id=row["id"], kind=row["kind"], date=_iso(row["date_start"]) or row["date_original"],
                       date_precision=_extra(row).get("date_precision") or DATE_PRECISION.get(row["date_kind"], "unknown"),
                       place_id=place_id, participant_ids=participants, description=description, sensitivity=sens(row),
                       external_ids=[ExternalIdentifier(system=x["system"], value=x["value"], url=x["url"])
                                     for x in external.get(row["id"], [])]))
        for item in roles:
            if item["role"] == "principal":
                event_ids.setdefault(item["person_id"], []).append(row["id"])
    public_event_ids = {event.id for event in case.records("Event")}
    for person_id, person in people.items():
        person.event_ids = event_ids.get(person_id, [])

    # ------------------------------------------------------------ DNA branches
    haplogroups: dict[str, Haplogroup] = {}
    for row in store.all("SELECT * FROM haplogroup ORDER BY id"):
        if pub(row):
            haplogroups[row["id"]] = Haplogroup(id=row["id"], name=row["name"], parent_id=row["parent_id"],
                                                date=row["date_text"], note=row["note"], sensitivity=sens(row))
        else:
            withhold(row, "haplogroup", f"access {row['access']}")
    for haplogroup in haplogroups.values():
        if haplogroup.parent_id not in haplogroups:
            haplogroup.parent_id = None
    for row in store.all("SELECT * FROM dna_observation WHERE kind='branch_assignment' AND access='public' "
                         "ORDER BY id"):
        if row["person_id"] in people and row["haplogroup_id"] in haplogroups:
            people[row["person_id"]].haplogroup_id = row["haplogroup_id"]
            people[row["person_id"]].haplogroup_note = row["summary"]
    case.add_many(list(people.values()))
    case.add_many(list(haplogroups.values()))

    # ------------------------------------------------------------ claims
    def grade_and_confidence(revision: dict[str, Any] | None) -> tuple[str | None, Confidence]:
        if not revision:
            return None, Confidence.UNKNOWN
        grade = revision.get("grade")
        if grade in grades:
            return grade, Confidence(grades[grade]["confidence"])
        if revision.get("confidence") in CONFIDENCES:
            return None, Confidence(revision["confidence"])
        return None, Confidence.UNKNOWN

    def current(claim_id: str) -> dict[str, Any] | None:
        return store.one("SELECT r.* FROM assessment a JOIN assessment_revision r ON r.assessment_id=a.id AND "
                         "r.revision=a.current_revision WHERE a.claim_id=? AND a.scope_id='project'", (claim_id,))

    def evidence_citations(claim_id: str) -> list[str]:
        """Citations the claim itself lists; separately assessed evidence becomes Evidence records."""
        cited: list[str] = []
        for row in store.all("SELECT * FROM claim_evidence WHERE claim_id=? ORDER BY id", (claim_id,)):
            if not _extra(row).get("cited_by_claim"):
                continue
            if row["citation_id"] in citations:
                cited.append(row["citation_id"])
            elif row["record_id"]:
                cited.extend(citations_of_record.get(row["record_id"], []))
        return list(dict.fromkeys(cited))

    public_claims: set[str] = set()
    for row in store.all("SELECT * FROM claim ORDER BY id"):
        if not pub(row) or withheld_status(row):
            withhold(row, "claim", "claim not public or withheld")
            continue
        revision = current(row["id"])
        grade, confidence = grade_and_confidence(revision)
        if row["kind"] == "relationship":
            if row["subject_person_id"] not in people or row["object_person_id"] not in people:
                withhold(row, "claim", "relationship concerns a withheld person")
                continue
            estimate = revision.get("estimate_percent") if revision else None
            case.add(Relationship(
                id=row["id"], subject_id=row["subject_person_id"], object_id=row["object_person_id"],
                kind=row["predicate"], confidence=confidence, claim_ids=[],
                sensitivity=sens(row), pedigree=None if row["relation_type"] in (None, "unknown") else row["relation_type"],
                tree_status=revision.get("attachment_status") if revision else None,
                estimate=estimate if isinstance(estimate, int) and 1 <= estimate <= 99 else None,
                grade=grade, rationale=revision.get("reasoning") if revision else None))
            public_claims.add(row["id"])
        elif row["kind"] in ("vital", "attribute", "other"):
            subject = row["subject_person_id"] or _extra(row).get("subject_id")
            if subject not in people and subject not in public_event_ids:
                withhold(row, "claim", "claim concerns a withheld person or record")
                continue
            status = ClaimStatus.REJECTED if confidence is Confidence.DISPROVED else (
                ClaimStatus.SUPPORTED if confidence in (Confidence.DOCUMENTED, Confidence.PROBABLE) else ClaimStatus.ASSERTED)
            case.add(Claim(id=row["id"], subject_id=subject, predicate=row["predicate"],
                           value=row["value_text"] or row["proposition"], citation_ids=evidence_citations(row["id"]),
                           status=status, confidence=confidence,
                           rationale=revision.get("reasoning") if revision else None, sensitivity=sens(row), grade=grade))
            public_claims.add(row["id"])
        else:
            withhold(row, "claim", "identity claims are research material, not published facts")
    for row in store.all("SELECT * FROM person WHERE sex IS NOT NULL AND sex <> 'unknown' ORDER BY id"):
        if row["id"] in people:
            case.add(Claim(id=f"{row['id']}--sex", subject_id=row["id"], predicate="sex", value=row["sex"],
                           status=ClaimStatus.ASSERTED, sensitivity=sens(row)))
    public_evidence: set[str] = set()
    for row in store.all("SELECT * FROM claim_evidence ORDER BY id"):
        extra = _extra(row)
        if row["claim_id"] in public_claims and row["citation_id"] in citations and not extra.get("cited_by_claim"):
            claim_row = store.get("claim", row["claim_id"])
            if claim_row["kind"] == "relationship":
                continue
            grade = extra.get("grade") if extra.get("grade") in grades else None
            confidence = Confidence(grades[grade]["confidence"]) if grade else Confidence(extra.get("confidence", "unknown"))
            case.add(Evidence(id=row["id"], claim_id=row["claim_id"], citation_id=row["citation_id"],
                              assessment=row["interpretation"] or "Cited for this claim.",
                              supports=row["stance"] != "opposes", sensitivity=sens(claim_row),
                              limitation=row["limitation"], confidence=confidence, grade=grade))
            public_evidence.add(row["id"])

    # ------------------------------------------------------------ research items
    def related(entity_id: str, role: str | None = None) -> list[str]:
        if role:
            rows = store.all("SELECT to_id FROM link WHERE from_id=? AND role=? ORDER BY sort_order, to_id", (entity_id, role))
        else:
            rows = store.all("SELECT to_id FROM link WHERE from_id=? ORDER BY sort_order, to_id", (entity_id,))
        return [row["to_id"] for row in rows]

    visible = set(people) | set(places) | set(sources) | set(citations) | public_claims | public_evidence | set(haplogroups)

    def confidence_of(row: dict[str, Any]) -> tuple[Confidence, str | None]:
        extra = _extra(row)
        grade = extra.get("grade") if extra.get("grade") in grades else None
        if grade:
            return Confidence(grades[grade]["confidence"]), grade
        return Confidence(extra.get("confidence", "unknown")), None

    def allowed(row: dict[str, Any], kind: str, links: list[str]) -> bool:
        if not pub(row) or withheld_status(row):
            withhold(row, kind, "not public or withheld")
            return False
        hidden = [rid for rid in links if rid not in visible]
        if hidden:
            withhold(row, kind, "names an entity that is not published")
            return False
        return True

    for row in store.all("SELECT * FROM hypothesis ORDER BY id"):
        links = related(row["id"])
        if allowed(row, "hypothesis", links):
            confidence, grade = confidence_of(row)
            case.add(Hypothesis(id=row["id"], statement=row["statement"], related_ids=related(row["id"], "related"),
                                evidence_ids=related(row["id"], "evidence"), status=row["status"],
                                confidence=confidence, grade=grade, sensitivity=sens(row),
                                supports=[s for s in (row["supports"] or "").split("\n") if s.strip()],
                                objections=[s for s in (row["objections"] or "").split("\n") if s.strip()]))
            visible.add(row["id"])
    for row in store.all("SELECT * FROM finding ORDER BY id"):
        links = related(row["id"])
        if not allowed(row, "finding", links):
            continue
        confidence, _ = confidence_of(row)
        extra = _extra(row)
        status = row["status_original"] or row["status"]
        case.add(Finding(id=row["id"], conclusion=row["statement"], related_ids=related(row["id"], "related"),
                         evidence_ids=related(row["id"], "evidence"), status=status,
                         confidence=confidence, recorded_on=_iso(row["recorded_on"]),
                         limitations=row["limitations"] or row["qualification"], kind=row["kind"],
                         citation_ids=related(row["id"], "citation"), sensitivity=sens(row),
                         changes=[change for change in extra.get("changes", []) if change.get("record_id") in visible]))
        visible.add(row["id"])
    for row in store.all("SELECT * FROM question ORDER BY id"):
        links = related(row["id"])
        if allowed(row, "question", links):
            case.add(ResearchQuestion(id=row["id"], question=row["question"], related_ids=links,
                                      priority=row["priority"], status=row["status_original"] or row["status"],
                                      resolves=row["resolves"],
                                      next_record=row["next_action"], sensitivity=sens(row)))
            visible.add(row["id"])
    for row in store.all("SELECT * FROM search ORDER BY id"):
        links = related(row["id"])
        if allowed(row, "search", links):
            scope = f"{row['repository']}: {row['scope']}" if row["repository"] else row["scope"]
            case.add(Search(id=row["id"], search=scope, result=row["result"],
                            related_ids=[rid for rid in links if rid not in citations],
                            searched_on=_iso(row["searched_on"]), limitation=row["limitation"],
                            citation_ids=[rid for rid in links if rid in citations], sensitivity=sens(row)))
            visible.add(row["id"])
    for row in store.all("SELECT * FROM study ORDER BY id"):
        links = related(row["id"])
        if not allowed(row, "study", links):
            continue
        groups = []
        for group in store.all("SELECT * FROM research_group WHERE study_id=? ORDER BY id", (row["id"],)):
            members = related(group["id"], "member")
            if pub(group) and all(member in people for member in members):
                extra = _extra(group)
                original = extra.pop("original_id", None) or group["id"]
                groups.append({**extra, "id": original, "title": group["title"], "member_ids": members,
                               "note": group["note"]})
        extra = _extra(row)
        case.add(Study(id=row["id"], title=row["title"], summary=row["summary"], rationale=row["rationale"],
                       body=row["body"], conclusion=row["conclusion"], related_ids=links, status=row["status"],
                       updated_on=_iso(row["updated_on"]), sensitivity=sens(row), groups=groups, kind=row["kind"],
                       limitations=row["limitations"], links=extra.get("links", []),
                       next_records=extra.get("next_records", [])))

    # ------------------------------------------------------------ files
    from .assets import asset_file, sha256_file
    for approval in store.all("SELECT * FROM approval WHERE kind='exact_file' AND status='active' ORDER BY target"):
        assets = store.all("SELECT * FROM asset WHERE sha256=? ORDER BY id", (approval["sha256"],))
        candidate = next((asset for asset in assets if asset_file(project, asset).is_file()), None)
        if candidate is None:
            omissions.add(approval["id"], "approval", "approved file is not registered or not present")
            continue
        path = asset_file(project, candidate)
        if sha256_file(path) != approval["sha256"]:
            omissions.add(approval["id"], "approval", "file bytes changed since approval")
            continue
        omissions.published_assets.append({"target": approval["target"], "path": str(path), "sha256": approval["sha256"]})
    approved_names = {Path(item["target"]).name for item in omissions.published_assets}
    for asset in store.all("SELECT * FROM asset WHERE access <> 'public' AND sha256 NOT IN (SELECT sha256 FROM "
                           "approval WHERE kind='exact_file' AND status='active') ORDER BY id"):
        omissions.withheld_terms.add(asset["sha256"])
        if asset["original_name"] and asset["original_name"] not in approved_names:
            omissions.withheld_files.add(asset["original_name"])
    public_names = {name.value for person in people.values() for name in person.names}
    omissions.withheld_terms -= public_names
    return case, omissions
