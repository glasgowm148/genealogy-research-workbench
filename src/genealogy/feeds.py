"""Deterministic Atom feeds for dated research.

A feed never carries a build timestamp: ``updated`` comes from the newest
entry, so rebuilding unchanged research produces an identical file. Dates may
be ``YYYY``, ``YYYY-MM``, ``YYYY-MM-DD`` or a full RFC 3339 timestamp.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
import re
from typing import Iterable

ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"


@dataclass(frozen=True)
class FeedEntry:
    id: str
    title: str
    link: str
    updated: str
    published: str | None = None
    summary: str | None = None
    category: tuple[str, str] | None = None  # (term, label)


def timestamp(value: str) -> str:
    """``1851`` → ``1851-01-01T00:00:00Z``; full timestamps pass through."""
    value = str(value)
    if re.fullmatch(r"\d{4}", value):
        value += "-01-01"
    elif re.fullmatch(r"\d{4}-\d{2}", value):
        value += "-01"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value + "T00:00:00Z"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value):
        return value
    raise ValueError(f"Not a feed date: {value!r}")


def _x(value: object) -> str:
    return escape(str(value), quote=True)


def atom_feed(*, title: str, feed_id: str, alternate: str, author: str, entries: Iterable[FeedEntry],
              updated: str, self_url: str | None = None, subtitle: str | None = None) -> str:
    """Render an Atom 1.0 feed. Entries are written in the order given."""
    head = f"<title>{_x(title)}</title>"
    if subtitle:
        head += f"<subtitle>{_x(subtitle)}</subtitle>"
    if self_url:
        head += f'<link rel="self" type="application/atom+xml" href="{_x(self_url)}"/>'
    head += (f'<link rel="alternate" type="text/html" href="{_x(alternate)}"/>'
             f"<id>{_x(feed_id)}</id><updated>{timestamp(updated)}</updated>"
             f"<author><name>{_x(author)}</name></author>")
    body = []
    for entry in entries:
        item = (f"<entry><title>{_x(entry.title)}</title>"
                f'<link rel="alternate" type="text/html" href="{_x(entry.link)}"/>'
                f"<id>{_x(entry.id)}</id>")
        if entry.published:
            item += f"<published>{timestamp(entry.published)}</published>"
        item += f"<updated>{timestamp(entry.updated)}</updated>"
        if entry.category:
            term, label = entry.category
            item += f'<category term="{_x(term)}" label="{_x(label)}"/>'
        if entry.summary:
            item += f'<summary type="text">{_x(entry.summary)}</summary>'
        body.append(item + "</entry>")
    return (f'<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="{ATOM_NAMESPACE}">'
            + head + "".join(body) + "</feed>\n")
