"""Adapters for archival descriptions and spreadsheets/OCR output."""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping
from typing import Any

from ._mapping import MappingAdapter, person_entities, value_for
from .base import AdapterBatch
from ..models import Record, Sensitivity


class ArchiveAdapter(MappingAdapter):
    name = "archives"
    entity_type = "source"
    capabilities = frozenset({"ingest", "row-mapping", "sources", "provenance"})


class TabularAdapter(MappingAdapter):
    """Accept row mappings or CSV text, including OCR-normalised rows."""

    name = "tabular"
    entity_type = "record"
    capabilities = frozenset({"ingest", "csv", "row-mapping", "people", "sources", "provenance"})

    def ingest(self, payload: Any) -> AdapterBatch:
        if isinstance(payload, str):
            return super().ingest(csv.DictReader(io.StringIO(payload)))
        return super().ingest(payload)

    def normalise_row(self, external_value: str, data: Mapping[str, Any], entity_type: str, sensitivity: Sensitivity) -> list[Record]:
        explicit = entity_type.casefold()
        if explicit == "person" or (explicit == "record" and value_for(data, "name", "full_name", "given_name", "first_name")):
            return person_entities(self.name, external_value, data, sensitivity)
        if explicit == "source" or value_for(data, "source_title", "repository", "archive"):
            return super().normalise_row(external_value, data, "source", sensitivity)
        return []


class SpreadsheetAdapter(TabularAdapter):
    """Tabular rows supplied by a spreadsheet reader chosen by the caller."""

    name = "spreadsheets"


class OcrAdapter(TabularAdapter):
    """Structured rows produced by an OCR workflow, retaining raw provenance."""

    name = "ocr"
