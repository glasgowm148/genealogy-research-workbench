"""The project database: one authoritative SQLite file per research project.

Public entry points:

* :func:`open_project` / :class:`Project`: configuration, database and asset roots;
* :class:`Research`: the typed domain services, the only supported writers;
* :mod:`.native`, :mod:`.backup`: complete export, backup and verified restore;
* :func:`public_case`: the single public projection behind every public output;
* :func:`build_from_database`: the staged, reproducible website build;
* :mod:`.gedcom_export`, :mod:`.wikitree_sync`, :mod:`.proposals`: interchange,
  external-tree comparison and reviewable change proposals.
"""

from .core import Store, Tx, create_store, migrate_store, open_store
from .errors import (
    ConstraintError, IncompatibleSchemaError, LockedError, NotFoundError, StaleRevisionError, StoreError,
)
from .project import Project, StorageSettings, has_database, open_project
from .projection import Omissions, public_case
from .schema import SCHEMA_VERSION
from .services import NameInput, Research, stable_id

__all__ = [
    "ConstraintError", "IncompatibleSchemaError", "LockedError", "NameInput", "NotFoundError", "Omissions", "Project",
    "Research", "SCHEMA_VERSION", "StaleRevisionError", "Store", "StorageSettings", "StoreError", "Tx", "create_store",
    "has_database", "migrate_store", "open_project", "open_store", "public_case", "stable_id",
]
