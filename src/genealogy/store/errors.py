"""Errors raised by the project database, each saying what to do next."""

from __future__ import annotations

from typing import Any


class StoreError(ValueError):
    """Base class: a ValueError so the CLI reports it as an ordinary error."""


class IncompatibleSchemaError(StoreError):
    """The database was written by a newer workbench, or needs migrating."""


class StaleRevisionError(StoreError):
    """An update was based on an older revision than the one now stored.

    ``current`` carries the stored row so the caller can rebase or regenerate
    the change instead of overwriting newer research.
    """

    def __init__(self, table: str, row_id: str, expected: int | None, actual: int | None, current: dict[str, Any] | None = None):
        self.table = table
        self.row_id = row_id
        self.expected = expected
        self.actual = actual
        self.current = current
        super().__init__(
            f"stale change to {table} {row_id}: it was based on revision {expected}, but revision {actual} is stored. "
            "Someone else changed it since; review the current record and regenerate the change."
        )


class NotFoundError(StoreError):
    pass


class LockedError(StoreError):
    pass


class ConstraintError(StoreError):
    """A uniqueness, reference or value rule rejected a change; nothing was written."""
