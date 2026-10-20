"""One reader-facing vocabulary for confidence, status and relationship roles.

Stored values never change; these functions only decide the words printed for
them. A label never claims more than its stored value: an imported tree link is
"unassessed" however confident the tree that supplied it was.
"""
from __future__ import annotations

from typing import Any, Mapping

CONFIDENCE = {
    "documented": ("Documented", "An assessed, cited record states this directly."),
    "probable": ("Probable", "Assessed evidence makes this likely, although no single record proves it."),
    "possible": ("Possible", "Some evidence fits. This remains a hypothesis to test."),
    "disproved": ("Disproved", "Assessed evidence contradicts this. It is kept so the reasoning stays visible."),
    "unknown": ("Unassessed", "Recorded, but not yet assessed against original sources."),
}
CLAIM_STATUS = {
    "asserted": ("Asserted", "Stated by a source or tree; not yet weighed against other evidence."),
    "supported": ("Supported", "Assessed evidence supports this claim."),
    "disputed": ("Disputed", "Evidence conflicts; the competing readings are recorded."),
    "rejected": ("Rejected", "Assessed evidence rules this claim out."),
}
PEDIGREE = {
    "birth": "birth", "adopted": "adoptive", "foster": "foster", "step": "step",
    "sealing": "sealing", "non-biological": "non-biological",
}
RESEARCH_STATUS = {
    "open": "Open", "draft": "Draft", "closed": "Closed", "resolved": "Resolved", "final": "Final",
    "abandoned": "Set aside", "superseded": "Superseded", "confirmed": "Confirmed", "rejected": "Rejected",
    "reviewed": "Reviewed", "published": "Published", "in progress": "In progress", "in-progress": "In progress",
}


def confidence_label(value: Any, *, relationship: bool = False) -> str:
    key = str(value or "unknown").casefold()
    if relationship and key == "unknown":
        return "Unassessed tree link"
    return CONFIDENCE.get(key, (str(value), ""))[0]


def confidence_meaning(value: Any) -> str:
    return CONFIDENCE.get(str(value or "unknown").casefold(), ("", "Recorded with this project's own wording."))[1]


def grade_label(row: Mapping[str, Any], grades: Mapping[str, Mapping[str, str]] | None) -> str | None:
    """The project's own wording for a record's grade, when it has one."""
    grade = row.get("grade")
    return str(grades[grade]["label"]) if grades and grade in grades else None


def relationship_label(row: Mapping[str, Any], grades: Mapping[str, Mapping[str, str]] | None = None) -> str:
    """E.g. "Unassessed tree link · tree-marked uncertain"."""
    parts = [grade_label(row, grades) or confidence_label(row.get("confidence"), relationship=True)]
    if isinstance(row.get("estimate"), int):
        parts[0] += f" ({row['estimate']}%)"
    if row.get("tree_status"):
        parts.append(f"tree-marked {row['tree_status']}")
    return " · ".join(parts)


def parent_role(row: Mapping[str, Any], sex: str | None) -> str:
    """Reader label for a parent link, e.g. "Father", "Step-mother", "Adoptive parent"."""
    base = {"m": "father", "male": "father", "f": "mother", "female": "mother"}.get(str(sex or "").casefold(), "parent")
    pedigree = str(row.get("pedigree") or "").casefold()
    if not pedigree or pedigree == "birth":
        return base.capitalize()
    qualifier = PEDIGREE.get(pedigree, pedigree)
    if qualifier == "step":
        return f"Step-{base}"
    return f"{qualifier.capitalize()} {base}"


def child_role(row: Mapping[str, Any], sex: str | None) -> str:
    base = {"m": "son", "male": "son", "f": "daughter", "female": "daughter"}.get(str(sex or "").casefold(), "child")
    pedigree = str(row.get("pedigree") or "").casefold()
    if not pedigree or pedigree == "birth":
        return base.capitalize()
    qualifier = PEDIGREE.get(pedigree, pedigree)
    return f"Step-{base}" if qualifier == "step" else f"{qualifier.capitalize()} {base}"


def status_label(value: Any) -> str:
    key = str(value or "").casefold()
    return CLAIM_STATUS.get(key, (RESEARCH_STATUS.get(key, str(value or "")), ""))[0]


RESEARCH_MEANINGS = {
    "open": "Still being researched; no answer has been reached.",
    "draft": "A provisional conclusion, recorded before review.",
    "reviewed": "A conclusion that has been checked against its evidence.",
    "final": "A settled conclusion, revisited only if new evidence appears.",
    "resolved": "The question has been answered; see the linked finding or study.",
    "closed": "No longer pursued; the reason is recorded with the question.",
}


def status_anchor(value: Any) -> str:
    """The guide entry for a stored claim or research status."""
    key = str(value or "").casefold()
    return f"status-{key}" if key in CLAIM_STATUS or key in RESEARCH_MEANINGS else "research-status"


def guide_entries(grades: Mapping[str, Mapping[str, str]] | None = None) -> list[tuple[str, str, str, str]]:
    """(anchor, label, meaning, group) rows for a reader's evidence guide.

    A project's own grades follow the standard ones, each with the standard
    grade it counts as.
    """
    rows = [(f"confidence-{key}", label, meaning, "Confidence") for key, (label, meaning) in CONFIDENCE.items()]
    rows.append(("confidence-tree-link", "Unassessed tree link", "A relationship copied from a family tree or export. It is a research lead until records are assessed.", "Confidence"))
    rows.append(("estimate", "Probable (70%) and similar", "A percentage is a researcher's assessed probability for that link, recorded with its reasoning. It is an estimate, not a measurement, and never comes from an imported tree.", "Confidence"))
    rows.append(("tree-marked", "Tree-marked …", "The supplying tree's own mark, such as uncertain or confident. It is shown as that tree's statement, never as this project's assessment.", "Confidence"))
    rows += [(f"grade-{key}", str(grade["label"]), f'{grade["meaning"]} Counted as {CONFIDENCE[grade["confidence"]][0].lower()} wherever the site groups or colours by confidence.',
              "This project's grades") for key, grade in (grades or {}).items()]
    rows += [(f"status-{key}", label, meaning, "Claim status") for key, (label, meaning) in CLAIM_STATUS.items()]
    rows += [(f"status-{key}", RESEARCH_STATUS[key], meaning, "Research status") for key, meaning in RESEARCH_MEANINGS.items()]
    rows.append(("research-status", "Other statuses", "A project's own wording for the state of a question, hypothesis, finding or study, printed as recorded.", "Research status"))
    rows.append(("pedigree", "Step, adoptive, foster, non-biological", "The supplied nature of a parent link. A link without one is a recorded parent whose nature was not stated.", "Relationship roles"))
    rows.append(("alternatives", "Competing parent records", "More recorded parents than one person can have by birth. Each is kept with its own label until research resolves it.", "Relationship roles"))
    return rows
