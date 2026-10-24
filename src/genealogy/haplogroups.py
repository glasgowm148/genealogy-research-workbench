"""DNA branches (Haplogroup records) as a tree: page addresses, reading order and the chain drawing.

Only what the public projection holds is used: a branch whose parent is
withheld is withheld with it, so every branch here descends from a root that
is also here. Nothing is calculated from the reported dates; they are text.
"""
from __future__ import annotations

from hashlib import sha256
from html import escape
import csv
import io
import re
from typing import Any
import unicodedata

CHAIN_DRAWN = 80  # branches drawn in a chain; the nested list beside it names every one
LIST_BYTES = 25_000  # dna.html's branch list and its people table each stop here; every branch page lists its own
ROW = 34  # px per branch in the chain
INDENT = 22  # px per generation of branches


def public_branch_csv(branches: dict[str, dict[str, Any]], people: dict[str, dict[str, Any]],
                      people_by_branch: dict[str, list[str]]) -> str:
    """Public reusable branch model; deliberately excludes DNA test data."""
    out = io.StringIO(newline="")
    fields = ("branch_id", "branch_name", "parent_branch_id", "reported_date",
              "person_id", "person_name", "attachment_note")
    writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for bid in sorted(branches, key=lambda key: (str(branches[key].get("name", "")).casefold(), key)):
        branch = branches[bid]
        ids = people_by_branch.get(bid) or [None]
        for pid in ids:
            person = people.get(pid, {}) if pid else {}
            name = next((n.get("value", "") for n in person.get("names", []) if n.get("value")), "")
            writer.writerow({"branch_id": bid, "branch_name": branch.get("name", ""),
                             "parent_branch_id": branch.get("parent_id") if branch.get("parent_id") in branches else "",
                             "reported_date": branch.get("date") or "", "person_id": pid or "",
                             "person_name": name, "attachment_note": person.get("haplogroup_note") or ""})
    return out.getvalue()


def slug(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.casefold()).strip("-")


def branch_urls(branches: dict[str, dict[str, Any]]) -> dict[str, str]:
    """``dna/<slug>.html`` from each branch's name ("R-FABLE1" -> dna/r-fable1.html); a clash or an
    empty slug takes a short hash of the id, assigned in id order so a rebuild gives the same address."""
    urls, used = {}, set()
    for bid in sorted(branches):
        name = slug(str(branches[bid]["name"]))
        if not name or name in used:
            name = f"{name or 'branch'}-{sha256(bid.encode('utf-8')).hexdigest()[:8]}"
        used.add(name)
        urls[bid] = f"dna/{name}.html"
    return urls


def children(branches: dict[str, dict[str, Any]]) -> dict[str | None, list[str]]:
    """Each branch's child branches in name order; ``None`` holds the roots."""
    below: dict[str | None, list[str]] = {}
    for bid, row in branches.items():
        parent = row.get("parent_id") if row.get("parent_id") in branches else None
        below.setdefault(parent, []).append(bid)
    for members in below.values():
        members.sort(key=lambda bid: (str(branches[bid]["name"]).casefold(), bid))
    return below


def reading_order(below: dict[str | None, list[str]], start: str | None = None, depth: int = 0) -> list[tuple[str, int]]:
    """Every branch under ``start`` (the roots when None), each followed by its own branches, with its depth."""
    order: list[tuple[str, int]] = []
    stack = [(bid, depth) for bid in reversed(below.get(start, []))]
    while stack:
        bid, level = stack.pop()
        order.append((bid, level))
        stack.extend((child, level + 1) for child in reversed(below.get(bid, [])))
    return order


def ancestors(branches: dict[str, dict[str, Any]], bid: str) -> list[str]:
    """The branches ``bid`` descends from, root first."""
    line, current = [], branches[bid].get("parent_id")
    while current in branches and current not in line:
        line.append(current)
        current = branches[current].get("parent_id")
    return line[::-1]


def chain_svg(order: list[tuple[str, int]], branches: dict[str, dict[str, Any]], href: dict[str, str],
              placed: dict[str, int], label: str, current: str | None = None) -> str:
    """The branches as a chain, root at the top and each branch under the one it descends from.

    Each branch is a link to its page; a filled mark is a branch with people
    placed on it. Drawn as plain SVG, so it needs no script.
    """
    drawn = order[:CHAIN_DRAWN]
    rows = {bid: index for index, (bid, _) in enumerate(drawn)}
    lines, marks, width = [], [], 0
    for index, (bid, level) in enumerate(drawn):
        x, y = 14 + level * INDENT, 18 + index * ROW
        parent = branches[bid].get("parent_id")
        if parent in rows:
            px = 14 + (level - 1) * INDENT
            lines.append(f"M{px} {18 + rows[parent] * ROW + 6}V{y}H{x - 6}")
        row = branches[bid]
        words = str(row["name"]) + (f" · {row['date']}" if row.get("date") else "")
        width = max(width, x + 16 + int(len(words) * 7.4))
        here = ' aria-current="page"' if bid == current else ""
        cls = "dna-node" + (" placed" if placed.get(bid) else "") + (" current" if bid == current else "")
        date = f'<tspan class="dna-date" dx="6">{escape(str(row["date"]))}</tspan>' if row.get("date") else ""
        marks.append(f'<a href="{escape(href[bid])}"{here} class="{cls}" aria-label="{escape(words.replace(" · ", ", "))}"><circle cx="{x}" cy="{y}" r="6"/>'
                     f'<text x="{x + 14}" y="{y + 4.5}">{escape(str(row["name"]))}{date}</text></a>')
    height = 18 + max(len(drawn) - 1, 0) * ROW + 18
    return (f'<svg class="dna-chain" role="group" aria-label="{escape(label)}" viewBox="0 0 {width} {height}" '
            f'width="{width}" height="{height}">'
            + (f'<path class="dna-links" d="{"".join(lines)}"/>' if lines else "") + "".join(marks) + "</svg>")
