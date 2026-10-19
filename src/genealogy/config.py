"""TOML configuration for a reusable genealogy project."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib
from typing import Any, ClassVar, Mapping


DEFAULT_PROJECT_NAME = "Genealogy research project"


def exact_bool(value: Any, *, setting: str) -> bool:
    """Accept TOML booleans only; truthy strings are unsafe configuration."""
    if type(value) is not bool:
        raise ValueError(f"{setting} must be a boolean")
    return value


def _table(data: Mapping[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"[{name}] must be a table")
    return dict(value)


def safe_relative_path(value: Any, *, setting: str) -> str:
    """Validate a project-owned path without resolving filesystem links."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{setting} must be a non-empty relative path")
    path = Path(value)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ValueError(f"{setting} must stay within the project directory")
    return value


@dataclass(slots=True)
class ProjectConfig:
    DEFAULT_NAME: ClassVar[str] = DEFAULT_PROJECT_NAME
    project_id: str | None = None
    name: str = DEFAULT_PROJECT_NAME
    case_directory: str = "cases"
    default_case: str | None = None
    privacy: dict[str, Any] = field(default_factory=dict)
    catalogue: dict[str, Any] = field(default_factory=dict)
    maps: dict[str, Any] = field(default_factory=dict)
    timelines: dict[str, Any] = field(default_factory=dict)
    adapters: dict[str, Any] = field(default_factory=dict)
    exports: dict[str, Any] = field(default_factory=dict)
    research: dict[str, Any] = field(default_factory=dict)
    paths: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, path: str | Path = "genealogy.toml") -> "ProjectConfig":
        with Path(path).open("rb") as handle:
            data = tomllib.load(handle)
        project = _table(data, "project")
        config = cls(
            project_id=project.get("id"),
            name=project.get("name", DEFAULT_PROJECT_NAME),
            case_directory=project.get("case_directory", "cases"),
            default_case=project.get("default_case"),
            privacy=_table(data, "privacy"),
            catalogue=_table(data, "catalogue"),
            maps=_table(data, "maps"),
            timelines=_table(data, "timelines"),
            adapters=_table(data, "adapters"),
            exports=_table(data, "exports"),
            research=_table(data, "research"),
            paths=_table(data, "paths"),
            raw=data,
        )
        config.validate()
        return config

    def boolean(self, section: str, key: str, default: bool) -> bool:
        values = getattr(self, section)
        value = values.get(key, default)
        return exact_bool(value, setting=f"{section}.{key}")

    def validate(self) -> None:
        safe_relative_path(self.case_directory, setting="project.case_directory")
        for key in ("allow_living", "allow_licensed", "allow_restricted"):
            if key in self.privacy:
                exact_bool(self.privacy[key], setting=f"privacy.{key}")
        for section in ("catalogue", "maps", "timelines"):
            values = getattr(self, section)
            if "enabled" in values:
                exact_bool(values["enabled"], setting=f"{section}.enabled")
        if "directory" in self.exports:
            safe_relative_path(self.exports["directory"], setting="exports.directory")
        for format_name in ("json", "ndjson", "csv", "geojson"):
            if format_name in self.exports:
                safe_relative_path(self.exports[format_name], setting=f"exports.{format_name}")

    def to_dict(self) -> dict[str, Any]:
        # Preserve project-defined extension sections so a toolkit upgrade does
        # not erase a consumer project's configuration vocabulary.
        data = {key: value for key, value in self.raw.items()}
        project = dict(data.get("project", {}))
        project.update({"id": self.project_id, "name": self.name,
                        "case_directory": self.case_directory,
                        "default_case": self.default_case})
        data["project"] = project
        data.update({"privacy": self.privacy, "catalogue": self.catalogue,
                     "maps": self.maps, "timelines": self.timelines,
                     "adapters": self.adapters, "exports": self.exports,
                     "research": self.research, "paths": self.paths})
        return data
