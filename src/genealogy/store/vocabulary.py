"""Documented mappings from recorded workflow words to the core's statuses.

The original word is always kept beside the normalised status (``status_original``),
so a mapping never loses what the researcher wrote. Words not listed map to the
fallback given, never to a stronger status.

Research grades are *not* mapped here: a project's own grade labels are kept as
recorded (``assessment_revision.grade`` with its ``vocabulary``), and only a
mapping the project declares (``[grades]`` in genealogy.toml) relates a label to
a standard confidence. Labels are never equated because their names sound alike.
"""

from __future__ import annotations

FINDING_STATUSES = ("draft", "current", "qualified", "withdrawn", "superseded")
FINDING_MAP = {
    "draft": "draft", "proposed": "draft", "pending": "draft",
    "current": "current", "confirmed": "current", "supported": "current", "reviewed": "current",
    "approved": "current", "published": "current", "accepted": "current",
    "qualified": "qualified", "provisional": "qualified", "partial": "qualified", "uncertain": "qualified",
    "withdrawn": "withdrawn", "retracted": "withdrawn", "rejected": "withdrawn",
    "superseded": "superseded", "replaced": "superseded", "corrected": "superseded",
}

QUESTION_STATUSES = ("open", "in_progress", "parked", "answered", "withdrawn")
QUESTION_MAP = {
    "open": "open", "new": "open", "todo": "open", "pending": "open", "unresolved": "open",
    "in_progress": "in_progress", "in progress": "in_progress", "active": "in_progress",
    "parked": "parked", "deferred": "parked", "blocked": "parked", "on_hold": "parked", "waiting": "parked",
    "answered": "answered", "resolved": "answered", "closed": "answered", "done": "answered", "complete": "answered",
    "completed": "answered",
    "withdrawn": "withdrawn", "obsolete": "withdrawn", "superseded": "withdrawn",
}

PROPOSAL_STATUSES = ("draft", "proposed", "approved", "applied", "verified", "rejected", "deferred", "superseded")
PROPOSAL_MAP = {
    "draft": "draft", "prepared": "draft", "generated": "draft",
    "proposed": "proposed", "open": "proposed", "pending": "proposed", "queued": "proposed", "ready": "proposed",
    "needs_review": "proposed",
    "approved": "approved",
    "applied": "applied", "saved": "applied", "live": "applied", "done": "applied", "completed": "applied",
    "verified": "verified",
    "rejected": "rejected", "declined": "rejected",
    "deferred": "deferred", "parked": "deferred", "blocked": "deferred", "held": "deferred", "hold": "deferred",
    "superseded": "superseded", "obsolete": "superseded", "replaced": "superseded",
}

#: Allowed proposal transitions. Proposing, approving, applying remotely and
#: verifying the remote state are separate steps.
PROPOSAL_TRANSITIONS = {
    "draft": {"proposed", "superseded", "rejected", "deferred"},
    "proposed": {"approved", "rejected", "deferred", "superseded", "draft"},
    "approved": {"applied", "deferred", "superseded", "proposed"},
    "applied": {"verified", "proposed"},
    "verified": {"superseded"},
    "rejected": {"proposed", "superseded"},
    "deferred": {"proposed", "superseded", "rejected"},
    "superseded": set(),
}

SEARCH_OUTCOMES = ("positive", "negative", "partial", "unknown")


def normalise(value: str | None, mapping: dict[str, str], fallback: str) -> tuple[str, str | None]:
    """Return (normalised status, original word or None when it was already canonical)."""
    if value is None or not str(value).strip():
        return fallback, None
    word = str(value).strip()
    key = word.casefold().replace("-", "_")
    normalised = mapping.get(key) or mapping.get(key.replace("_", " ")) or fallback
    return normalised, (None if word == normalised else word)
