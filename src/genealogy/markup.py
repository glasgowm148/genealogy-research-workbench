"""A deliberately small, escaping Markdown subset for research prose.

Supported: ``#``–``####`` headings, paragraphs, ``-``/``*`` and ``1.`` lists,
``> `` quotations, ``**strong**``, ``*emphasis*``, ```code```, http(s) links
``[label](https://…)`` and record references ``[[record-id]]`` or
``[[record-id|label]]``. Everything else is text. Raw HTML is always escaped,
and a reference to a record that is not public renders only its label (or
"withheld record"), never the identifier.
"""
from __future__ import annotations

from html import escape
import re
from typing import Callable
from urllib.parse import urlsplit

Resolver = Callable[[str], "tuple[str, str] | None"]  # record id -> (href, default label)

_REFERENCE = re.compile(r"\[\[([^\[\]|]+)(?:\|([^\[\]]+))?\]\]")
_LINK = re.compile(r"\[([^\[\]]+)\]\(([^()\s]+)\)")
_CODE = re.compile(r"`([^`]+)`")
_STRONG = re.compile(r"\*\*(.+?)\*\*")
_EMPHASIS = re.compile(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?![\*\w])")


def _safe_url(value: str) -> str | None:
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme in ("http", "https") and parts.netloc and not parts.username and not parts.password:
        return value
    return None


def inline(text: str, resolve: Resolver) -> str:
    """Render one line of inline markup to escaped HTML."""
    tokens: list[str] = []

    def stash(html: str) -> str:
        tokens.append(html)
        return f"\x00{len(tokens) - 1}\x00"

    def reference(match: re.Match[str]) -> str:
        record_id, label = match[1].strip(), (match[2] or "").strip()
        target = resolve(record_id)
        if target is None:
            return stash(f'<span class="withheld-reference">{escape(label or "withheld record")}</span>')
        href, default = target
        return stash(f'<a href="{escape(href, quote=True)}">{escape(label or default)}</a>')

    def link(match: re.Match[str]) -> str:
        url = _safe_url(match[2])
        if not url:
            return stash(escape(match[1]))
        return stash(f'<a href="{escape(url, quote=True)}" rel="noreferrer">{escape(match[1])}</a>')

    text = _REFERENCE.sub(reference, text)
    text = _LINK.sub(link, text)
    text = _CODE.sub(lambda m: stash(f"<code>{escape(m[1])}</code>"), text)
    html = escape(text)
    html = _STRONG.sub(r"<strong>\1</strong>", html)
    html = _EMPHASIS.sub(r"<em>\1</em>", html)
    return re.sub("\x00(\\d+)\x00", lambda m: tokens[int(m[1])], html)


def render(source: str | None, resolve: Resolver, *, heading_offset: int = 1) -> str:
    """Render research prose; headings start at h(1 + heading_offset)."""
    if not source:
        return ""
    output: list[str] = []
    paragraph: list[str] = []
    items: list[str] = []
    list_tag = ""
    quote: list[str] = []

    def flush() -> None:
        nonlocal list_tag
        if paragraph:
            output.append("<p>" + "<br>".join(inline(line, resolve) for line in paragraph) + "</p>")
            paragraph.clear()
        if items:
            output.append(f"<{list_tag}>" + "".join(f"<li>{inline(item, resolve)}</li>" for item in items) + f"</{list_tag}>")
            items.clear()
            list_tag = ""
        if quote:
            output.append("<blockquote><p>" + "<br>".join(inline(line, resolve) for line in quote) + "</p></blockquote>")
            quote.clear()

    for raw in source.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.rstrip()
        heading = re.fullmatch(r"(#{1,4})\s+(.+)", line)
        bullet = re.fullmatch(r"\s*[-*]\s+(.+)", line)
        number = re.fullmatch(r"\s*\d+[.)]\s+(.+)", line)
        quoted = re.fullmatch(r">\s?(.*)", line)
        if not line.strip():
            flush()
        elif heading:
            flush()
            level = min(6, len(heading[1]) + heading_offset)
            output.append(f"<h{level}>{inline(heading[2], resolve)}</h{level}>")
        elif bullet or number:
            tag = "ul" if bullet else "ol"
            if paragraph or quote or (items and list_tag != tag):
                flush()
            list_tag = tag
            items.append((bullet or number)[1])
        elif quoted:
            if paragraph or items:
                flush()
            quote.append(quoted[1])
        else:
            if items or quote:
                flush()
            paragraph.append(line.strip())
    flush()
    return "".join(output)


def references(source: str | None) -> list[str]:
    """Record ids referenced with ``[[id]]`` in research prose."""
    return [match[1].strip() for match in _REFERENCE.finditer(source or "")]
