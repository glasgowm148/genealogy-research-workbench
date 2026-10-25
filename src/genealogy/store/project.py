"""A research project on disk: its configuration, database and asset roots.

``[storage]`` in ``genealogy.toml`` (all optional, validated defaults)::

    [storage]
    database = "private/research.sqlite"   # the one authoritative database
    assets = "private/assets"              # managed, content-addressed files
    backups = "private/backups"            # default backup destination
    exports = "private/exports"            # complete native exports (private)

    [storage.asset_roots]                  # files referenced where they already are
    evidence = "evidence"

Paths are relative to the project directory and may not escape it, except an
asset root given as an absolute path, which is reported as external.

Machine-specific asset-root locations (an evidence drive, another checkout)
belong in ``genealogy.local.toml`` beside ``genealogy.toml``. Keep that file out
of version control; only its ``[storage.asset_roots]`` table is read, and it
overrides roots of the same name::

    [storage.asset_roots]
    evidence = "/Volumes/Research/evidence" The
database, native exports and backups are private: ``genealogy init`` writes a
``.gitignore`` for them and the site builder refuses to publish them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import ProjectConfig, safe_relative_path
from .core import Store, create_store, open_store

DEFAULT_STORAGE = {
    "database": "private/research.sqlite",
    "assets": "private/assets",
    "backups": "private/backups",
    "exports": "private/exports",
}
MANAGED_ROOT = "managed"
LOCAL_CONFIG = "genealogy.local.toml"


@dataclass(slots=True)
class StorageSettings:
    database: str = DEFAULT_STORAGE["database"]
    assets: str = DEFAULT_STORAGE["assets"]
    backups: str = DEFAULT_STORAGE["backups"]
    exports: str = DEFAULT_STORAGE["exports"]
    asset_roots: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_config(cls, config: ProjectConfig) -> "StorageSettings":
        raw = config.raw.get("storage", {})
        if not isinstance(raw, dict):
            raise ValueError("[storage] must be a table")
        unknown = set(raw) - {*DEFAULT_STORAGE, "asset_roots"}
        if unknown:
            raise ValueError(f"storage has unknown settings: {', '.join(sorted(unknown))}")
        values: dict[str, Any] = {}
        for key, default in DEFAULT_STORAGE.items():
            value = raw.get(key, default)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"storage.{key} must be a non-empty relative path")
            safe_relative_path(value, setting=f"storage.{key}")
            values[key] = value
        roots = raw.get("asset_roots", {})
        if not isinstance(roots, dict):
            raise ValueError("[storage.asset_roots] must be a table of name = path")
        for name, value in roots.items():
            if name == MANAGED_ROOT:
                raise ValueError(f"storage.asset_roots.{MANAGED_ROOT} is reserved for storage.assets")
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"storage.asset_roots.{name} must be a path")
            if not Path(value).is_absolute() and value != ".":
                safe_relative_path(value, setting=f"storage.asset_roots.{name}")
        values["asset_roots"] = dict(roots)
        directory = config.raw.get("_directory")
        local = Path(directory) / LOCAL_CONFIG if directory else None
        if local is not None and local.is_file():
            import tomllib
            with local.open("rb") as handle:
                data = tomllib.load(handle)
            unknown = set(data) - {"storage"} or set(data.get("storage", {})) - {"asset_roots"}
            if unknown:
                raise ValueError(f"{LOCAL_CONFIG} may only set [storage.asset_roots]; found {', '.join(sorted(unknown))}")
            for name, value in data.get("storage", {}).get("asset_roots", {}).items():
                if name == MANAGED_ROOT or not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{LOCAL_CONFIG}: storage.asset_roots.{name} must be a path (and not '{MANAGED_ROOT}')")
                values["asset_roots"][name] = value
        return cls(**values)


class Project:
    """An opened project: ``directory``, ``config``, ``settings`` and ``store``."""

    def __init__(self, directory: Path, config: ProjectConfig, settings: StorageSettings, store: Store):
        self.directory = directory
        self.config = config
        self.settings = settings
        self.store = store

    @property
    def database_path(self) -> Path:
        return self.directory / self.settings.database

    def root(self, name: str) -> Path:
        """The directory an asset root names."""
        if name == MANAGED_ROOT:
            return (self.directory / self.settings.assets).resolve()
        try:
            value = self.settings.asset_roots[name]
        except KeyError as error:
            raise ValueError(f"unknown asset root {name!r}; configure it under [storage.asset_roots]") from error
        path = Path(value)
        return path.resolve() if path.is_absolute() else (self.directory / path).resolve()

    def roots(self) -> dict[str, Path]:
        return {MANAGED_ROOT: self.root(MANAGED_ROOT), **{name: self.root(name) for name in self.settings.asset_roots}}

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "Project":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def workbench_version() -> str:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("genealogy-research-workbench")
    except PackageNotFoundError:
        return "unknown"


def load_config(directory: Path) -> ProjectConfig:
    path = Path(directory) / "genealogy.toml"
    if not path.is_file():
        raise ValueError(f"No project configuration at {path}; run 'genealogy init DIRECTORY' first")
    config = ProjectConfig.load(path)
    config.raw.setdefault("_directory", str(Path(directory).resolve()))
    return config


def open_project(directory: Path, *, readonly: bool = False, create: bool = False) -> Project:
    directory = Path(directory).resolve()
    config = load_config(directory)
    settings = StorageSettings.from_config(config)
    path = directory / settings.database
    if create and not path.exists():
        store = create_store(path, project_id=config.project_id or directory.name, workbench_version=workbench_version())
    else:
        store = open_store(path, readonly=readonly)
    return Project(directory, config, settings, store)


def has_database(directory: Path) -> bool:
    try:
        settings = StorageSettings.from_config(load_config(directory))
    except ValueError:
        return False
    return (Path(directory) / settings.database).is_file()
