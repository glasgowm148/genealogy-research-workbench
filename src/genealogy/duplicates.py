"""Possible duplicate people: pairs a researcher may want to compare.

A pair is a lead, never a conclusion: two records with one name may describe
one person or two people who shared a name. Nothing here merges anything.
"""
from __future__ import annotations

from collections import defaultdict
import re
from typing import Any, Iterable
import unicodedata

YEARS_APART = 2  # birth years at most this far apart count as close
LIMIT = 500  # pairs listed; past this the page says how many more were found
PER_PAGE = 100  # pairs per page, so a long list stays a set of small pages


def fold(text: str) -> str:
    """Case and diacritics folded: "Ádá" and "ada" match."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).casefold()


def given_token(name: dict[str, Any]) -> str:
    """The first given name, folded: from ``given`` when recorded, else the full name without the surname."""
    surname = set(re.findall(r"[\w'’-]+", fold(str(name.get("surname") or ""))))
    if name.get("given"):
        tokens = re.findall(r"[\w'’-]+", fold(str(name["given"])))
    else:
        tokens = [t for t in re.findall(r"[\w'’-]+", fold(str(name.get("value") or ""))) if t not in surname]
    return tokens[0] if tokens else ""


def possible_pairs(people: Iterable[tuple[str, str, str, int | None, set[str]]],
                   related: set[frozenset[str]]) -> set[tuple[str, str]]:
    """Pairs ``(a, b)``, ``a < b``, from rows ``(id, surname key, given key, birth year, place ids)``.

    Same surname and first given name, and birth years within two, or (when
    either lacks a birth year) an event place in common. Pairs with a recorded
    relationship are left out. People are bucketed by name and each bucket is
    walked in birth-year order, so the work grows with the people and the pairs
    found, not with every possible pair.
    """
    buckets: dict[tuple[str, str], list[tuple[str, int | None, set[str]]]] = defaultdict(list)
    for pid, surname, given, year, places in people:
        if surname and given:
            buckets[(surname, given)].append((pid, year, places))
    found: set[tuple[str, str]] = set()

    def add(a: str, b: str) -> None:
        if a != b and frozenset((a, b)) not in related:
            found.add((a, b) if a < b else (b, a))

    for members in buckets.values():
        if len(members) < 2:
            continue
        dated = sorted((year, pid) for pid, year, _ in members if year is not None)
        for i, (year, a) in enumerate(dated):
            j = i + 1
            while j < len(dated) and dated[j][0] - year <= YEARS_APART:
                add(a, dated[j][1])
                j += 1
        at_place: dict[str, list[str]] = defaultdict(list)
        for pid, _, places in members:
            for place in places:
                at_place[place].append(pid)
        for pid, year, places in members:
            if year is None:
                for place in places:
                    for other in at_place[place]:
                        add(pid, other)
    return found
