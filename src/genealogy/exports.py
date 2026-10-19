"""Portable, dependency-free research project exports."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .case import ResearchCase, validate_case
from .catalogue import catalogue_data, render_catalogue, render_catalogue_html
from .config import ProjectConfig
from .maps import geojson, render_map_html
from .privacy import PrivacyPolicy
from .timelines import render_timeline, render_timeline_html, timeline_items

COLLECTIONS = ("people", "names", "events", "places", "relationships", "claims", "sources", "citations", "evidence", "hypotheses", "questions", "findings")
CASE_COLLECTIONS = {
    "Person": "people", "Name": "names", "Event": "events", "Place": "places",
    "Relationship": "relationships", "Claim": "claims", "Source": "sources",
    "Citation": "citations", "Evidence": "evidence", "Hypothesis": "hypotheses",
    "ResearchQuestion": "questions", "Finding": "findings",
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
    raise ValueError(f"Unsupported export format: {format_name}")


def project_for_public_export(case: ResearchCase, config: ProjectConfig) -> dict[str, Any]:
    """Return the only project representation intended for public outputs."""
    errors = validate_case(case)
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
