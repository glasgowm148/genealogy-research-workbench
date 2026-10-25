"""Field-aware three-way comparison of a WikiTree profile. No network, no writes.

Inputs are three states of one profile's fields:

1. ``base``: the last accepted or observed remote state (``remote_baseline``);
2. ``local``: the locally proposed state (from reviewed research or a draft);
3. ``remote``: a freshly captured remote state (``external_observation``).

Each field is classified as ``unchanged``, ``local`` (only the local proposal
changed it), ``remote`` (only WikiTree changed it; the change is preserved),
``same`` (both made the same change) or ``conflict``. The *proposal* contains
only the local changes that do not conflict, applied on top of the fresh remote
state, so a remote edit the proposal did not mean to touch is never reverted.

Missing values, deletions, redirects (merged profiles) and retired attachments
are reported explicitly. Applying a proposal on WikiTree is a separate,
human-authorised step outside the workbench; verification compares a later
capture with the proposal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

MISSING = object()
DEFAULT_FIELDS = (
    "FirstName", "MiddleName", "LastNameAtBirth", "LastNameCurrent", "Nicknames", "Gender", "BirthDate",
    "BirthLocation", "DeathDate", "DeathLocation", "Father", "Mother", "Spouses", "Privacy", "IsLiving",
    "DataStatus", "Bio",
)


def _value(state: Mapping[str, Any] | None, name: str) -> Any:
    if state is None or name not in state:
        return MISSING
    return state[name]


def _show(value: Any) -> Any:
    return "(missing)" if value is MISSING else value


@dataclass(slots=True)
class FieldDiff:
    field: str
    base: Any
    local: Any
    remote: Any
    state: str
    result: Any

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "base": _show(self.base), "local": _show(self.local),
                "remote": _show(self.remote), "state": self.state,
                "result": None if self.state == "conflict" else _show(self.result)}


@dataclass(slots=True)
class Comparison:
    profile: str
    fields: list[FieldDiff] = field(default_factory=list)
    redirect_to: str | None = None
    remote_missing: bool = False
    notes: list[str] = field(default_factory=list)

    def by_state(self, state: str) -> list[FieldDiff]:
        return [item for item in self.fields if item.state == state]

    @property
    def conflicts(self) -> list[FieldDiff]:
        return self.by_state("conflict")

    def proposal(self) -> dict[str, Any]:
        """Local, non-conflicting changes only: what a reviewed update would set."""
        return {item.field: _show(item.local) for item in self.fields if item.state == "local"}

    def merged(self) -> dict[str, Any]:
        """The fresh remote state with the non-conflicting local changes applied."""
        return {item.field: _show(item.result) for item in self.fields if item.state != "conflict"}

    def to_dict(self) -> dict[str, Any]:
        return {"profile": self.profile, "redirect_to": self.redirect_to, "remote_missing": self.remote_missing,
                "summary": {state: len(self.by_state(state)) for state in ("unchanged", "local", "remote", "same", "conflict")},
                "fields": [item.to_dict() for item in self.fields if item.state != "unchanged"],
                "proposal": self.proposal(), "notes": self.notes}


def compare(profile: str, base: Mapping[str, Any] | None, local: Mapping[str, Any], remote: Mapping[str, Any] | None,
            *, fields: tuple[str, ...] = DEFAULT_FIELDS) -> Comparison:
    comparison = Comparison(profile=profile)
    if remote is None:
        comparison.remote_missing = True
        comparison.notes.append("No fresh remote capture: the profile may have been deleted or not captured. "
                                "Nothing can be proposed until it is captured again.")
        return comparison
    redirect = remote.get("redirect_to") or (remote.get("Name") if remote.get("Name") not in (None, profile) else None)
    if redirect:
        comparison.redirect_to = redirect
        comparison.notes.append(f"{profile} now redirects to {redirect} (a merge or rename on WikiTree). Map the local "
                                "person to the new id explicitly; a redirect does not prove the local identity.")
    for name in fields:
        b, l, r = _value(base, name), _value(local, name), _value(remote, name)
        if l is MISSING:
            # The local proposal does not speak about this field: keep remote.
            state, result = ("unchanged" if r == b else "remote"), r
        elif l == r:
            state, result = ("unchanged" if l == b else "same"), r
        elif l == b:
            state, result = "remote", r
        elif r == b:
            state, result = "local", l
        else:
            state, result = "conflict", None
        if state == "remote" and r is MISSING:
            comparison.notes.append(f"{name} was removed on WikiTree since the baseline; the removal is kept.")
        comparison.fields.append(FieldDiff(name, b, l, r, state, result))
    if base is None:
        comparison.notes.append("No accepted baseline: every difference between local and remote is a conflict to "
                                "review, because it cannot be told who changed what.")
    return comparison


def verify_applied(proposal: Mapping[str, Any], capture: Mapping[str, Any]) -> dict[str, Any]:
    """After a human applied the update on WikiTree, compare a new capture with the proposal."""
    mismatched = {name: {"proposed": value, "captured": capture.get(name, "(missing)")}
                  for name, value in proposal.items() if capture.get(name) != value}
    return {"verified": not mismatched, "mismatched": mismatched}
