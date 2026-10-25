"""Read helpers for tests that inspect a project after CLI commands (database mode)."""

from __future__ import annotations

from pathlib import Path
import shutil

from genealogy.cli import initialize_project
from genealogy.exports import project_for_public_export
from genealogy.store import open_project
from genealogy.store.native import dumps, export_document, logical_digest
from genealogy.store.projection import public_case


def private_view(directory: Path):
    """(complete private case, config) as local tools see it."""
    with open_project(directory) as project:
        case, _ = public_case(project, everything=True)
        return case, project.config


def public_view(directory: Path, year: int | None = None) -> dict:
    """The public export representation every public output is built from."""
    with open_project(directory) as project:
        case, _ = public_case(project, build_year=year)
        return project_for_public_export(case, project.config)


def native_text(directory: Path) -> str:
    with open_project(directory) as project:
        return dumps(export_document(project.store))


def digest(directory: Path) -> str:
    with open_project(directory) as project:
        return logical_digest(project.store)


def fresh_project(directory: Path, name: str | None = None) -> None:
    """Start again: the database never discards research, so tests use a new project."""
    shutil.rmtree(directory, ignore_errors=True)
    initialize_project(directory, name)
