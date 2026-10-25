"""Reviewable change proposals for bulk and agent-driven edits.

A proposal is a JSON document (``genealogy-change-proposal`` version 1) listing
operations, each stating the revision it was prepared against::

    {"format": "genealogy-change-proposal", "format_version": 1,
     "title": "Reassess the Currituck sons", "actor": "agent:review-bot",
     "operations": [
       {"op": "assess", "claim": "clm-1", "expected_revision": 2,
        "set": {"status": "probable", "estimate_percent": 80, "estimate_kind": "subjective",
                "reasoning": "..."}},
       {"op": "update", "table": "finding", "id": "fnd-1", "expected_revision": 1,
        "set": {"status": "qualified"}},
       {"op": "add_finding", "set": {"statement": "...", "links": [["per-1", "related"]]}},
       {"op": "withdraw_finding", "id": "fnd-2", "expected_revision": 3, "reason": "..."}
     ]}

``genealogy proposal check`` lists stale operations with the current values so
the author can rebase; ``proposal diff`` shows what would change; ``proposal
apply`` re-checks every expectation inside one transaction and applies all or
nothing, recording the proposal and its approval in the workflow tables.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .core import Store
from .errors import ConstraintError, StaleRevisionError, StoreError
from .services import Research

FORMAT = "genealogy-change-proposal"
UPDATABLE = {
    "person": {"sex", "living", "living_basis", "label", "summary", "access"},
    "place": {"name", "latitude", "longitude", "precision", "region", "coordinate_basis", "access"},
    "source": {"title", "kind", "author", "publication", "url", "originality", "licence", "access_note", "access"},
    "record": {"title", "record_type", "locator", "date_original", "date_start", "date_end", "date_kind",
               "place_wording", "summary", "information", "access"},
    "citation": {"locator", "accessed_on", "note", "access"},
    "claim": {"proposition", "relation_type", "value_text", "access", "publication_status"},
    "finding": {"statement", "status", "qualification", "limitations", "access", "publication_status", "kind"},
    "question": {"question", "status", "priority", "resolves", "next_action", "resume_condition", "closed_on", "access"},
    "search": {"result", "outcome", "limitation", "access"},
    "study": {"title", "summary", "rationale", "body", "conclusion", "limitations", "status", "updated_on", "access"},
    "note": {"title", "text", "access"},
    "mention": {"role", "name_as_written", "details", "access"},
}
ADDERS = {"add_finding": "add_finding", "add_question": "add_question", "add_search": "log_search",
          "add_hypothesis": "add_hypothesis"}


class StaleProposalError(StoreError):
    def __init__(self, stale: list[dict[str, Any]]):
        self.stale = stale
        lines = "; ".join(f"{item['target']} expected r{item['expected']} found r{item['actual']}" for item in stale[:5])
        super().__init__(f"{len(stale)} operations are stale ({lines}). Nothing was applied; regenerate the proposal "
                         "against the current records (see 'genealogy proposal check').")


def load(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise ConstraintError(f"not a {FORMAT} document")
    if document.get("format_version") != 1:
        raise ConstraintError(f"unsupported proposal format_version {document.get('format_version')!r}; this workbench reads 1")
    operations = document.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ConstraintError("a proposal needs a non-empty operations list")
    for index, op in enumerate(operations):
        if not isinstance(op, dict) or op.get("op") not in {"assess", "update", "withdraw_finding", *ADDERS}:
            raise ConstraintError(f"operation {index}: unknown op {op.get('op') if isinstance(op, dict) else op!r}")
        if op["op"] == "update":
            allowed = UPDATABLE.get(op.get("table"))
            if allowed is None:
                raise ConstraintError(f"operation {index}: table {op.get('table')!r} cannot be updated by a proposal")
            extra = set(op.get("set", {})) - allowed
            if extra:
                raise ConstraintError(f"operation {index}: {op['table']} fields not updatable: {', '.join(sorted(extra))}")
        if op["op"] in ("update", "withdraw_finding", "assess") and "expected_revision" not in op:
            raise ConstraintError(f"operation {index}: expected_revision is required (0 for a new assessment)")
    return document


def _current(store: Store, research: Research, op: Mapping[str, Any]) -> tuple[str, int | None, Any]:
    if op["op"] == "assess":
        scope = op.get("scope", "project")
        current = research.current_assessment(op["claim"], scope)
        return f"assessment {op['claim']}@{scope}", (current["current_revision"] if current else 0), current
    table = "finding" if op["op"] == "withdraw_finding" else op["table"]
    row = store.get(table, op["id"])
    return f"{table} {op['id']}", (row["revision"] if row else None), row


def check(store: Store, document: Mapping[str, Any]) -> list[dict[str, Any]]:
    research = Research(store)
    stale = []
    for index, op in enumerate(document["operations"]):
        if op["op"] in ADDERS:
            continue
        target, actual, current = _current(store, research, op)
        if actual != op["expected_revision"]:
            stale.append({"operation": index, "target": target, "expected": op["expected_revision"], "actual": actual,
                          "current": current})
    return stale


def diff(store: Store, document: Mapping[str, Any]) -> list[str]:
    research = Research(store)
    lines = []
    for index, op in enumerate(document["operations"]):
        if op["op"] in ADDERS:
            lines.append(f"[{index}] {op['op']}: {json.dumps(op.get('set', {}), ensure_ascii=False, sort_keys=True)}")
            continue
        target, actual, current = _current(store, research, op)
        flag = "" if actual == op["expected_revision"] else f"  STALE (expected r{op['expected_revision']}, now r{actual})"
        lines.append(f"[{index}] {op['op']} {target}{flag}")
        if op["op"] == "withdraw_finding":
            lines.append(f"      status: {current and current['status']!r} -> 'withdrawn' ({op.get('reason')})")
        for key, value in op.get("set", {}).items():
            before = current.get(key) if current else None
            if before != value:
                lines.append(f"      {key}: {before!r} -> {value!r}")
    return lines


def apply(store: Store, document: Mapping[str, Any], *, actor: str, approved_by: str | None = None) -> dict[str, Any]:
    research = Research(store)
    load(document)
    digest = hashlib.sha256(json.dumps(document, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with store.write(actor=actor, tool="genealogy proposal apply", source=f"proposal sha256:{digest}",
                     reason=document.get("title")) as tx:
        stale = check(store, document)
        if stale:
            raise StaleProposalError(stale)
        created: list[str] = []
        for op in document["operations"]:
            values = dict(op.get("set", {}))
            if op["op"] == "assess":
                expected = op["expected_revision"]
                research.assess(tx, op["claim"], scope_id=op.get("scope", "project"),
                                expected_revision=None if expected == 0 else expected, new=expected == 0, **values)
            elif op["op"] == "update":
                tx.update(op["table"], op["id"], values, expected_revision=op["expected_revision"])
            elif op["op"] == "withdraw_finding":
                research.withdraw_finding(tx, op["id"], reason=op["reason"], expected_revision=op["expected_revision"])
            else:
                links = [tuple(item) for item in values.pop("links", [])]
                created.append(getattr(research, ADDERS[op["op"]])(tx, links=links, **values))
        proposal_id = research.create_proposal(tx, kind="bulk_change", status="proposed", rationale=document.get("title"),
                                               basis={"sha256": digest, "operations": len(document["operations"])},
                                               diff=document["operations"], authored=True, actor=document.get("actor"))
        revision = store.get("proposal", proposal_id)["revision"]
        research.transition_proposal(tx, proposal_id, "approved", expected_revision=revision, actor=approved_by or actor)
        research.transition_proposal(tx, proposal_id, "applied", expected_revision=revision + 1, actor=actor)
    return {"proposal": proposal_id, "applied": len(document["operations"]), "created": created}


__all__ = ["StaleProposalError", "StaleRevisionError", "apply", "check", "diff", "load"]
