"""Optional boundary adapters; none is required by the core model."""

from collections.abc import Mapping
from typing import Any

from .base import Adapter, AdapterBatch, AdapterRecord
from .dna import DnaAdapter
from .familysearch import FamilySearchAdapter, normalise_familysearch_pid
from .gedcom import GedcomAdapter
from .onetree import OneTreeAdapter
from .sources import ArchiveAdapter, OcrAdapter, SpreadsheetAdapter, TabularAdapter
from .wikitree import (
    WikiTreeAdapter, collect_family_profile_names, extract_biography,
    hydrate_family_envelope, iter_relation_profiles, merge_family_profile,
    normalise_wikitree_profile_id, save_wikitree_family_case, wikitree_family_case,
)
from .wikitree_http import (
    WikiTreeApiError,
    WikiTreeClientError,
    WikiTreeHttpClient,
    WikiTreeRequestError,
    WikiTreeResponseError,
    WikiTreeWafChallengeError,
)


ADAPTER_TYPES = {
    "archives": ArchiveAdapter,
    "dna": DnaAdapter,
    "familysearch": FamilySearchAdapter,
    "gedcom": GedcomAdapter,
    "ocr": OcrAdapter,
    "one-tree": OneTreeAdapter,
    "spreadsheets": SpreadsheetAdapter,
    "tabular": TabularAdapter,
    "wikitree": WikiTreeAdapter,
}


def adapter_registry() -> dict[str, type[Adapter]]:
    """Return the built-in, network-free adapter types by configured name."""
    return dict(ADAPTER_TYPES)


def resolve_adapter(configured_name: str | Mapping[str, Any]) -> Adapter:
    """Instantiate an adapter named in project configuration.

    Both ``one_tree`` and ``one-tree`` resolve to the same optional adapter.
    Configuration values may be a name or a mapping containing ``name``/``adapter``.
    """
    if isinstance(configured_name, Mapping):
        configured_name = configured_name.get("adapter", configured_name.get("name", ""))
    if not isinstance(configured_name, str):
        raise TypeError("configured adapter name must be a string or mapping")
    name = configured_name.strip().casefold().replace("_", "-")
    try:
        return ADAPTER_TYPES[name]()
    except KeyError as error:
        available = ", ".join(sorted(ADAPTER_TYPES))
        raise ValueError(f"unknown adapter {configured_name!r}; available: {available}") from error

__all__ = [
    "Adapter", "AdapterBatch", "AdapterRecord", "ArchiveAdapter", "DnaAdapter",
    "FamilySearchAdapter", "GedcomAdapter", "OcrAdapter", "OneTreeAdapter",
    "SpreadsheetAdapter", "TabularAdapter", "WikiTreeAdapter", "adapter_registry",
    "WikiTreeApiError", "WikiTreeClientError", "WikiTreeHttpClient",
    "WikiTreeRequestError", "WikiTreeResponseError", "WikiTreeWafChallengeError",
    "collect_family_profile_names", "extract_biography", "hydrate_family_envelope",
    "iter_relation_profiles", "merge_family_profile", "normalise_familysearch_pid",
    "normalise_wikitree_profile_id",
    "save_wikitree_family_case", "wikitree_family_case",
    "resolve_adapter",
]
