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
# What each standard grade usually rests on, printed under its meaning in the
# guide. Generic on purpose: a project's own grades say this in their own words.
CONFIDENCE_BASIS = {
    "documented": "a record that names both people and the relationship between them, or states the fact directly.",
    "probable": "several records that agree, such as a matching name, age and place, though none states it outright.",
    "possible": "a detail or two that fit, such as a name or an age, with other candidates not yet ruled out.",
    "disproved": "a record that conflicts with it, such as a birth after the supposed parent's death.",
    "unknown": "a tree, export or other compilation, not yet compared with the records it drew on.",
}
CLAIM_STATUS = {
    "asserted": ("Asserted", "Stated by a source or tree; not yet weighed against other evidence."),
    "supported": ("Supported", "Assessed evidence supports this claim."),
    "disputed": ("Disputed", "Evidence conflicts; the competing readings are recorded."),
    "rejected": ("Rejected", "Assessed evidence rules this claim out."),
}
# A citation's record, in the standard (Evidence Explained) terms: its form,
# and whether whoever supplied its information knew it first-hand.
SOURCE_QUALITY = {
    "original": ("Original record", "The record in its first form, made at or near the time by someone in a position to know, or an image of it such as a photograph, scan or microfilm of the page."),
    "derivative": ("Derivative record", "Made from another record: a transcription, abstract, extract, translation or index. Each copying can add errors, so the record it was made from is worth finding."),
    "authored": ("Authored work", "A writer's account built from other records, such as a published family history, a biography or a compiled tree. Its conclusions are only as sound as the records behind them."),
}
INFORMATION = {
    "primary": ("Primary information", "Supplied by someone with first-hand knowledge of what it records, such as a minister recording a baptism he performed."),
    "secondary": ("Secondary information", "Supplied by someone repeating what others told them or recalling what they did not witness, such as a death record's age or birthplace."),
    "undetermined": ("Undetermined information", "The record does not show who supplied the information, so whether it was first-hand cannot be said."),
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


def assessment_label(value: Any, grades: Mapping[str, Mapping[str, str]] | None) -> str:
    """A finding's before or after value: the project's grade wording, else the standard one."""
    return grade_label({"grade": value}, grades) or confidence_label(value)


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


def quality_parts(row: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """(field, guide anchor, words) for each standard term a citation states."""
    parts = [(name, f"{name}-{row[name]}", terms[row[name]][0]) for name, terms in (("quality", SOURCE_QUALITY), ("information", INFORMATION))
             if row.get(name) in terms]
    if len(parts) == 2:  # "Original record · primary information"
        parts[1] = (parts[1][0], parts[1][1], parts[1][2][0].lower() + parts[1][2][1:])
    return parts


def quality_label(row: Mapping[str, Any]) -> str:
    """E.g. "Original record · primary information"; empty when neither is stated."""
    return " · ".join(words for _, _, words in quality_parts(row))


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


def guide_basis(anchor: str, grades: Mapping[str, Mapping[str, str]] | None = None) -> str | None:
    """What a guide entry's grade usually rests on: the toolkit's words for a
    standard grade, a project grade's own ``basis`` (never borrowed from the
    grade it counts as, which may be weighed differently)."""
    if anchor.startswith("confidence-"):
        return CONFIDENCE_BASIS.get(anchor[len("confidence-"):])
    if anchor.startswith("grade-"):
        return (grades or {}).get(anchor[len("grade-"):], {}).get("basis")
    return None


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
    rows += [(f"quality-{key}", label, meaning, "Record quality") for key, (label, meaning) in SOURCE_QUALITY.items()]
    rows += [(f"information-{key}", label, meaning, "Record quality") for key, (label, meaning) in INFORMATION.items()]
    rows.append(("record-quality", "Quality is not confidence", "These terms describe the record a citation points to, never how far a claim is believed. An original record with primary information can still be misread, mistaken or about someone else; the claim's own label says how far it has been assessed. A citation without them has not had them stated.", "Record quality"))
    rows += [(f"status-{key}", RESEARCH_STATUS[key], meaning, "Research status") for key, meaning in RESEARCH_MEANINGS.items()]
    rows.append(("research-status", "Other statuses", "A project's own wording for the state of a question, hypothesis, finding or study, printed as recorded.", "Research status"))
    rows.append(("not-yet-identified", "Not yet identified", "Printed on an open question when the researcher has not yet recorded what evidence would answer it, or which record to check next. It marks a gap in the plan, not a search that found nothing.", "Research status"))
    rows.append(("finding-kind", "Finding type", "The researcher's own grouping for a finding, such as vital, relationship or record. It says what a finding is about, not how far it is believed.", "Research status"))
    rows.append(("pedigree", "Step, adoptive, foster, non-biological", "The supplied nature of a parent link. A link without one is a recorded parent whose nature was not stated.", "Relationship roles"))
    rows.append(("recorded-sibling", "Recorded sibling", "A sibling or half-sibling link recorded in its own right, not only inferred from parents in common. It carries its own label, and a sibling who also shares recorded parents is listed once, with that label.", "Relationship roles"))
    rows.append(("alternatives", "Competing parent records", "More recorded parents than one person can have by birth. Each is kept with its own label until research resolves it.", "Relationship roles"))
    rows.append(("for-and-against", "For and against", "The researcher's recorded points for and against a hypothesis, printed as written. They are not a tally: one strong point can outweigh several weak ones, and the number on each side says nothing about which hypothesis is right. Open hypotheses about the same people are set side by side, in no order of merit; the site never picks between them, and a hypothesis's own label says how far it has been assessed.", "Hypotheses"))
    return rows


# Plurals the "add s" rule gets wrong, for every count the site prints.
PLURALS = {"person": "people", "study": "studies", "family": "families", "child": "children", "search": "searches",
           "match": "matches", "spouse or partner": "spouses or partners", "is": "are", "has": "have"}


def plural(n: int, word: str, many: str | None = None) -> str:
    """ "1 person", "2 people", "1,204 evidence assessments": the count and the right form of the word."""
    return f"{n:,} {word if n == 1 else many or PLURALS.get(word) or word + 's'}"
# One badge system: each label's guide entry decides its family, so a pill is
# coloured and marked by what it links to. Glyphs mark evidence strength only;
# a type or a research status says what something is, not how far it is believed.
BADGE_GLYPHS = {"documented": "✓", "probable": "~", "possible": "?", "unassessed": "○", "conflict": "✕", "tree": "◇", "kind": "", "status": ""}
CONFIDENCE_FAMILY = {"documented": "documented", "probable": "probable", "possible": "possible", "disproved": "conflict", "unknown": "unassessed"}
STATUS_FAMILY = {"supported": "documented", "asserted": "unassessed", "disputed": "conflict", "rejected": "conflict"}


def badge_family(anchor: str, grades: Mapping[str, Mapping[str, str]] | None = None) -> str:
    """The family (colour and glyph) of the badge linking to a guide entry."""
    if anchor == "confidence-tree-link":
        return "unassessed"
    if anchor.startswith("confidence-"):
        return CONFIDENCE_FAMILY.get(anchor[len("confidence-"):], "unassessed")
    if anchor.startswith("grade-"):
        return CONFIDENCE_FAMILY.get(str((grades or {}).get(anchor[len("grade-"):], {}).get("confidence")), "unassessed")
    if anchor.startswith("status-"):
        return STATUS_FAMILY.get(anchor[len("status-"):], "status")
    if anchor == "tree-marked":
        return "tree"
    return "kind" if anchor.startswith(("quality-", "information-")) or anchor == "finding-kind" else "status"


def assessment_anchor(value: Any, grades: Mapping[str, Mapping[str, str]] | None = None) -> str:
    """The guide entry for a stored confidence or grade, such as a finding's before or after value."""
    return f"grade-{value}" if grades and value in grades else f"confidence-{str(value or 'unknown').casefold()}"
