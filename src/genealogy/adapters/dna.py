"""DNA boundary that admits only narrowly defined derived summaries."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .base import Adapter, AdapterBatch, AdapterRecord
from ._mapping import record_id, text
from ..privacy import PrivacyViolation
from ..models import Confidence, Evidence, Sensitivity


class DnaAdapter(Adapter):
    name = "dna"
    capabilities = frozenset({"ingest", "derived-dna-summary", "provenance"})
    _ALLOWED_KEYS = frozenset({
        "id", "externalid", "sensitivity", "summary", "matchcount", "sharedcm",
        "relationshipestimate", "subjectid", "predicate", "value", "claimid",
        "citationid", "assessment", "supports", "confidence", "url",
    })
    _FORBIDDEN_KEY_PARTS = ("raw", "genotype", "segment", "snip", "snp", "vcf", "bam", "fastq", "sequence", "allele")

    def ingest(self, payload: Any) -> AdapterBatch:
        rows = [payload] if isinstance(payload, Mapping) else payload
        batch = AdapterBatch(adapter=self.name)
        for number, row in enumerate(rows, start=1):
            if not isinstance(row, Mapping):
                raise TypeError("DNA summaries must be mappings")
            self._validate_derived_summary(row)
            data = dict(row)
            value = str(data.pop("id", data.pop("external_id", number)))
            data.pop("url", None)  # do not circulate account- or kit-specific links by default
            sensitivity = Sensitivity(data.pop("sensitivity", Sensitivity.RESTRICTED))
            if sensitivity is Sensitivity.RAW_DNA:
                raise PrivacyViolation("raw DNA is rejected")
            batch.records.append(AdapterRecord(
                self.external_id(value), "dna_summary", data, sensitivity, raw=dict(row),
                provenance={"adapter": self.name, "row": number, "kind": "derived_summary"},
            ))
            claim_id = text(data.get("claim_id"))
            citation_id = text(data.get("citation_id"))
            if claim_id and citation_id:
                assessment = text(data.get("assessment")) or text(data.get("summary")) or "derived DNA summary"
                confidence_value = text(data.get("confidence")) or Confidence.UNKNOWN.value
                batch.add_entity(Evidence(
                    id=record_id(self.name, "evidence", value), claim_id=claim_id, citation_id=citation_id,
                    assessment=assessment, supports=data.get("supports", True) is not False,
                    confidence=Confidence(confidence_value), sensitivity=sensitivity,
                ))
            elif claim_id or citation_id:
                batch.warnings.append(f"DNA summary {value} was retained as provenance but not evidence: both claim_id and citation_id are required")
        return batch

    @classmethod
    def _validate_derived_summary(cls, value: Any, path: str = "payload") -> None:
        """Reject raw material recursively, regardless of key casing or nesting."""
        if isinstance(value, Mapping):
            for name, child in value.items():
                normalised = re.sub(r"[^a-z0-9]", "", str(name).casefold())
                if any(part in normalised for part in cls._FORBIDDEN_KEY_PARTS):
                    raise PrivacyViolation("raw DNA, genotypes, or segments are rejected; provide a derived summary")
                if path == "payload" and normalised not in cls._ALLOWED_KEYS:
                    raise PrivacyViolation(f"DNA summary field is not in the derived-summary allowlist: {name}")
                cls._validate_derived_summary(child, f"{path}.{name}")
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for index, child in enumerate(value):
                cls._validate_derived_summary(child, f"{path}[{index}]")
