"""Portable, dependency-free research project exports."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .case import ResearchCase, grade_errors, validate_case
from .catalogue import catalogue_data, render_catalogue, render_catalogue_html
from .config import ProjectConfig
from .maps import geojson, render_map_html
from .privacy import PrivacyPolicy
from .timelines import render_timeline, render_timeline_html, timeline_items

COLLECTIONS = ("people", "names", "events", "places", "relationships", "claims", "sources", "citations", "evidence", "hypotheses", "questions", "findings", "studies", "searches")
CASE_COLLECTIONS = {
    "Person": "people", "Name": "names", "Event": "events", "Place": "places",
    "Relationship": "relationships", "Claim": "claims", "Source": "sources",
    "Citation": "citations", "Evidence": "evidence", "Hypothesis": "hypotheses",
    "ResearchQuestion": "questions", "Finding": "findings", "Study": "studies",
    "Search": "searches",
}


def to_json(project: Mapping[str, Any]) -> str:
    return json.dumps(project, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def records(project: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    for collection in COLLECTIONS:
        for record in project.get(collection, []):
            if isinstance(record, Mapping):
                yield {"record_type": collection, **record}


def to_ndjson(project: Mapping[str, Any]) -> str:
    return "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records(project))


def to_csv(project: Mapping[str, Any]) -> str:
    rows = list(records(project))
    fields = sorted({key for row in rows for key in row}) or ["record_type"]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value for key, value in row.items()})
    return output.getvalue()


def render(project: Mapping[str, Any], format_name: str) -> str:
    if format_name == "json":
        return to_json(project)
    if format_name == "ndjson":
        return to_ndjson(project)
    if format_name == "csv":
        return to_csv(project)
    if format_name == "geojson":
        return json.dumps(geojson(project), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if format_name == "gedcom":
        return to_gedcom(project)
    raise ValueError(f"Unsupported export format: {format_name}")


def project_for_public_export(case: ResearchCase, config: ProjectConfig) -> dict[str, Any]:
    """Return the only project representation intended for public outputs."""
    errors = validate_case(case) + grade_errors(case, config.grades)
    if errors:
        raise ValueError("cannot export invalid research case:\n" + "\n".join(f"- {error}" for error in errors))
    policy = PrivacyPolicy(
        allow_living=config.boolean("privacy", "allow_living", False),
        allow_licensed=config.boolean("privacy", "allow_licensed", False),
        allow_restricted=config.boolean("privacy", "allow_restricted", False),
    )
    safe = policy.filter_public(case)
    # Case titles and summaries may themselves describe protected people.  Use
    # only the explicitly public project name from configuration.
    project: dict[str, Any] = {"project": {"title": config.name}}
    for source_kind, destination in CASE_COLLECTIONS.items():
        project[destination] = safe.get(source_kind, [])
    return project


def safe_output_path(directory: Path, filename: str) -> Path:
    """Resolve a configured view filename without allowing an escape from directory."""
    if not isinstance(filename, str) or not filename:
        raise ValueError("configured output filename must be a non-empty string")
    relative = Path(filename)
    if relative.is_absolute() or not relative.name or any(part == ".." for part in relative.parts):
        raise ValueError("configured output filename must be a safe relative path")
    root = directory.resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("configured output filename escapes the output directory")
    return candidate


def write_public_export(
    case: ResearchCase,
    config: ProjectConfig,
    directory: Path,
    filename: str,
    format_name: str,
) -> Path:
    """Privacy-filter a case and write it below a caller-owned directory."""
    destination = safe_output_path(directory, filename)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render(project_for_public_export(case, config), format_name), encoding="utf-8")
    return destination


def build_public_views(case: ResearchCase, config: ProjectConfig, directory: Path) -> dict[str, Path]:
    """Build configured public views from a case through the mandatory privacy gate."""
    project = project_for_public_export(case, config)
    results: dict[str, Path] = {}
    for section, default_name, content in configured_views(project, config):
        if config.boolean(section, "enabled", True):
            destination = safe_output_path(directory, config_value(config, section, "output", default_name))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
            results[section] = destination
    return results


def configured_views(
    project: Mapping[str, Any],
    config: ProjectConfig,
) -> tuple[tuple[str, str, str], ...]:
    """Render the view formats selected by project configuration."""
    catalogue_format = config_value(config, "catalogue", "format", "markdown").casefold()
    timeline_format = config_value(config, "timelines", "format", "markdown").casefold()
    map_format = config_value(config, "maps", "format", "geojson").casefold()
    catalogue_renderers = {
        "markdown": ("catalogue.md", lambda: render_catalogue(project)),
        "html": ("catalogue.html", lambda: render_catalogue_html(project)),
        "json": ("catalogue.json", lambda: json.dumps(catalogue_data(project), indent=2, ensure_ascii=False) + "\n"),
    }
    timeline_renderers = {
        "markdown": ("timeline.md", lambda: render_timeline(project)),
        "html": ("timeline.html", lambda: render_timeline_html(project)),
        "json": ("timeline.json", lambda: json.dumps(timeline_items(project), indent=2, ensure_ascii=False) + "\n"),
    }
    map_renderers = {
        "geojson": ("places.geojson", lambda: json.dumps(geojson(project), indent=2, ensure_ascii=False) + "\n"),
        "html": ("places.html", lambda: render_map_html(project)),
    }
    selected = (
        ("catalogue", catalogue_format, catalogue_renderers),
        ("timelines", timeline_format, timeline_renderers),
        ("maps", map_format, map_renderers),
    )
    views: list[tuple[str, str, str]] = []
    for section, format_name, renderers in selected:
        if not config.boolean(section, "enabled", True):
            continue
        try:
            default_name, renderer = renderers[format_name]
        except KeyError as error:
            allowed = ", ".join(sorted(renderers))
            raise ValueError(f"unsupported {section}.format {format_name!r}; choose {allowed}") from error
        views.append((section, default_name, renderer()))
    return tuple(views)


def config_value(config: ProjectConfig, section: str, key: str, default: str) -> str:
    value = getattr(config, section).get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"{section}.{key} must be a string")
    return value


_GEDCOM_EVENTS = {
    "birth": "BIRT", "christening": "CHR", "baptism": "BAPM", "death": "DEAT", "burial": "BURI", "cremation": "CREM",
    "residence": "RESI", "occupation": "OCCU", "census": "CENS", "emigration": "EMIG", "immigration": "IMMI",
    "naturalisation": "NATU", "probate": "PROB", "will": "WILL", "adoption": "ADOP", "confirmation": "CONF",
    "graduation": "GRAD", "education": "EDUC", "retirement": "RETI", "ordination": "ORDN",
}
_GEDCOM_FAMILY_EVENTS = {"marriage": "MARR", "marriage banns": "MARB", "marriage contract": "MARC", "marriage licence": "MARL",
                         "marriage settlement": "MARS", "engagement": "ENGA", "divorce": "DIV", "divorce filed": "DIVF", "annulment": "ANUL"}
_GEDCOM_PEDIGREE = {"birth": "birth", "adopted": "adopted", "foster": "foster", "sealing": "sealing"}


def _gedcom_lines(level: int, tag: str, value: Any = None) -> list[str]:
    """One GEDCOM line, with CONT for newlines, CONC for long text and @ escaped."""
    if value is None or value == "":
        return [f"{level} {tag}"]
    text_lines = str(value).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output: list[str] = []
    for index, line in enumerate(text_lines):
        line = line.replace("@", "@@")
        chunks = [line[i:i + 200] for i in range(0, len(line), 200)] or [""]
        for part, chunk in enumerate(chunks):
            if index == 0 and part == 0:
                output.append(f"{level} {tag} {chunk}".rstrip())
            else:
                output.append(f"{level + 1} {'CONC' if part else 'CONT'} {chunk}".rstrip())
    return output


def to_gedcom(project: Mapping[str, Any]) -> str:
    """Write the already-public projection as UTF-8 GEDCOM 5.5.1.

    Only records present in ``project`` are written, so the privacy gate has
    already run. Relationship confidence is not representable in GEDCOM; the
    public JSON remains the complete account of assessments.
    """
    people = sorted(project.get("people", []), key=lambda row: row["id"])
    pointers = {row["id"]: f"I{number}" for number, row in enumerate(people, 1)}
    events = {row["id"]: row for row in project.get("events", [])}
    places = {row["id"]: row for row in project.get("places", [])}
    sources = sorted(project.get("sources", []), key=lambda row: row["id"])
    source_pointers = {row["id"]: f"S{number}" for number, row in enumerate(sources, 1)}
    citations = {row["id"]: row for row in project.get("citations", [])}
    sex = {row["subject_id"]: str(row.get("value") or "").strip().upper()[:1] for row in project.get("claims", []) if row.get("predicate") == "sex"}
    cited: dict[str, list[dict[str, Any]]] = {}
    for claim in project.get("claims", []):
        if claim.get("predicate") == "documented-in":
            cited.setdefault(claim["subject_id"], []).extend(citations[cid] for cid in claim.get("citation_ids", []) if cid in citations)
    # Families: a couple, or the set of recorded parents of a child.
    families: dict[tuple[str, ...], dict[str, Any]] = {}

    def family(partners: tuple[str, ...]) -> dict[str, Any]:
        return families.setdefault(tuple(sorted(partners)), {"children": {}, "events": []})

    parents: dict[str, list[dict[str, Any]]] = {}
    for row in project.get("relationships", []):
        if row.get("confidence") == "disproved" or row["subject_id"] not in pointers or row["object_id"] not in pointers:
            continue
        if row["kind"] in ("parent", "father", "mother"):
            parents.setdefault(row["subject_id"], []).append(row)
        elif row["kind"] in ("spouse", "partner"):
            family((row["subject_id"], row["object_id"]))
    rank = {"documented": 0, "probable": 1, "possible": 2, "unknown": 3}
    for child, rows in parents.items():
        # One family for the (at most two) best-assessed birth/unstated parents;
        # every other recorded parent link keeps its own one-parent family.
        primary = sorted((row for row in rows if row.get("pedigree") in (None, "birth")),
                         key=lambda row: (rank.get(row.get("confidence"), 3), row["object_id"]))[:2]
        groups = [primary] if primary else []
        groups += [[row] for row in rows if row not in primary]
        for group in groups:
            pedigrees = {row.get("pedigree") for row in group}
            family(tuple(row["object_id"] for row in group))["children"][child] = pedigrees.pop() if len(pedigrees) == 1 else None
    for row in events.values():
        tag = _GEDCOM_FAMILY_EVENTS.get(row.get("kind", ""))
        participants = tuple(sorted(pid for pid in row.get("participant_ids", []) if pid in pointers))
        if tag and len(participants) == 2:
            family(participants)["events"].append((tag, row))
    family_pointers = {key: f"F{number}" for number, key in enumerate(sorted(families), 1)}

    def event_lines(level: int, tag: str, row: Mapping[str, Any]) -> list[str]:
        lines = _gedcom_lines(level, tag, None if row.get("date") or row.get("place_id") else "Y")
        if row.get("date"):
            lines += _gedcom_lines(level + 1, "DATE", row["date"])
        place = places.get(row.get("place_id"))
        if place:
            lines += _gedcom_lines(level + 1, "PLAC", place["name"])
            if place.get("latitude") is not None and place.get("longitude") is not None:
                lat, lon = float(place["latitude"]), float(place["longitude"])
                lines += [f"{level + 2} MAP",
                          f"{level + 3} LATI {'N' if lat >= 0 else 'S'}{abs(lat):g}", f"{level + 3} LONG {'E' if lon >= 0 else 'W'}{abs(lon):g}"]
        lines += citation_lines(level + 1, row["id"])
        return lines

    def citation_lines(level: int, subject: str) -> list[str]:
        lines: list[str] = []
        for item in cited.get(subject, []):
            if item["source_id"] in source_pointers:
                lines.append(f"{level} SOUR @{source_pointers[item['source_id']]}@")
                if item.get("locator"):
                    lines += _gedcom_lines(level + 1, "PAGE", item["locator"])
        return lines

    title = str(project.get("project", {}).get("title") or "Public family history")
    lines = ["0 HEAD", "1 SOUR genealogy-research-workbench", "2 NAME Genealogy Research Workbench", "1 GEDC", "2 VERS 5.5.1",
             "2 FORM LINEAGE-LINKED", "1 CHAR UTF-8", *(_gedcom_lines(1, "NOTE", f"Public, privacy-filtered export of {title}. Relationships are recorded assertions; see the site's JSON for assessments."))]
    for person in people:
        pid = person["id"]
        lines.append(f"0 @{pointers[pid]}@ INDI")
        for name in person.get("names", []):
            given, surname = name.get("given"), name.get("surname")
            value = f"{given or ''} /{surname}/".strip() if surname else name.get("value", "")
            lines += _gedcom_lines(1, "NAME", value)
            if name.get("kind") in ("married", "aka", "alias", "nickname", "birth", "immigrant", "maiden", "religious"):
                lines += _gedcom_lines(2, "TYPE", {"alias": "aka", "nickname": "aka"}.get(name["kind"], name["kind"]))
        if sex.get(pid) in ("M", "F", "U", "X"):
            lines.append(f"1 SEX {sex[pid]}")
        for eid in sorted(set(person.get("event_ids", [])) | {e["id"] for e in events.values() if pid in e.get("participant_ids", []) and e.get("kind") in _GEDCOM_EVENTS}):
            row = events.get(eid)
            tag = _GEDCOM_EVENTS.get(row.get("kind", "")) if row else None
            if tag:
                lines += event_lines(1, tag, row)
        for key, pointer in family_pointers.items():
            if pid in families[key]["children"]:
                lines.append(f"1 FAMC @{pointer}@")
                supplied = families[key]["children"][pid]
                pedigree = _GEDCOM_PEDIGREE.get(str(supplied or ""))
                if pedigree:
                    lines.append(f"2 PEDI {pedigree}")
                elif supplied:
                    # GEDCOM 5.5.1 has no step/non-biological PEDI; use the common extension.
                    for parent in key:
                        lines += _gedcom_lines(2, "_MREL" if sex.get(parent) == "F" else "_FREL", supplied)
            if pid in key:
                lines.append(f"1 FAMS @{pointer}@")
        lines += citation_lines(1, pid)
    for key, pointer in family_pointers.items():
        lines.append(f"0 @{pointer}@ FAM")
        ordered = sorted(key, key=lambda value: (sex.get(value) != "M", value))
        for index, partner in enumerate(ordered):
            lines.append(f"1 {'HUSB' if index == 0 and sex.get(partner) != 'F' else 'WIFE'} @{pointers[partner]}@")
        for child in sorted(families[key]["children"]):
            lines.append(f"1 CHIL @{pointers[child]}@")
        for tag, row in families[key]["events"]:
            lines += event_lines(1, tag, row)
    for source in sources:
        lines.append(f"0 @{source_pointers[source['id']]}@ SOUR")
        lines += _gedcom_lines(1, "TITL", source.get("title"))
        for field, tag in (("author", "AUTH"), ("publication", "PUBL"), ("repository", "NOTE")):
            if source.get(field):
                lines += _gedcom_lines(1, tag, source[field] if field != "repository" else f"Repository: {source[field]}")
    lines.append("0 TRLR")
    return "\n".join(lines) + "\n"
