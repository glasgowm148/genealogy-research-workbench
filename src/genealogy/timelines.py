"""Timeline views derived from platform-neutral event records."""

from __future__ import annotations

from html import escape
import json
from typing import Any, Mapping
from .dates import date_sort_key, display_date, machine_date


def timeline_items(project: Mapping[str, Any]) -> list[dict[str, Any]]:
    places = {str(item.get("id")): item for item in project.get("places", [])}
    items: list[dict[str, Any]] = []
    for event in project.get("events", []):
        item = dict(event)
        place = places.get(str(event.get("place_id")))
        if place:
            item["place_name"] = place.get("name")
        items.append(item)
    return sorted(items, key=lambda item: (date_sort_key(item.get("date")), str(item.get("id", ""))))


def render_timeline(project: Mapping[str, Any]) -> str:
    lines = ["# Timeline", ""]
    for event in timeline_items(project):
        place = f" — {event['place_name']}" if event.get("place_name") else ""
        lines.append(f"- {event.get('date', 'undated')}: {event.get('type') or event.get('kind', 'event')}{place}")
    if len(lines) == 2:
        lines.append("- No events recorded.")
    return "\n".join(lines) + "\n"


def _date_cell(item: Mapping[str, Any]) -> str:
    """The date as a reader writes it, with the recorded value kept in the markup."""
    raw = str(item.get("date") or "")
    if not raw:
        return "undated"
    words, machine = display_date(raw, item.get("date_precision")), machine_date(raw, item.get("date_precision"))
    stored = f' data-date="{escape(raw, quote=True)}"'
    return (f'<time datetime="{machine}"{stored}>{escape(words)}</time>' if machine else f'<span{stored}>{escape(words)}</span>')


def render_timeline_html(project: Mapping[str, Any]) -> str:
    """Render an accessible offline timeline with kind and text filters."""
    items = timeline_items(project)
    title = escape(str(project.get("project", {}).get("title", "Genealogy research")))
    kinds = sorted({str(item.get("kind") or item.get("type") or "event") for item in items})
    options = "".join(f'<option value="{escape(kind, quote=True)}">{escape(kind)}</option>' for kind in kinds)
    rows = []
    for item in items:
        kind = str(item.get("kind") or item.get("type") or "event")
        participants = ", ".join(str(value) for value in item.get("participant_ids", []))
        description = str(item.get("description") or "")
        search = escape(" ".join((kind, participants, description, str(item.get("place_name") or ""))).casefold(), quote=True)
        rows.append(
            f'<tr data-kind="{escape(kind, quote=True)}" data-search="{search}">'
            f'<td>{_date_cell(item)}</td>'
            f'<td>{escape(kind)}</td><td>{escape(str(item.get("place_name") or "—"))}</td>'
            f'<td>{escape(participants) or "—"}</td><td>{escape(description) or "—"}</td></tr>'
        )
    embedded = json.dumps(items, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} — timeline</title><style>body{{margin:0;background:#fbfaf6;color:#17212b;font:16px/1.5 system-ui,sans-serif}}main{{max-width:76rem;margin:auto;padding:2rem}}.controls{{display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:1rem}}label{{font-weight:700}}input,select{{display:block;padding:.55rem;min-width:14rem}}.table-wrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;background:white}}th,td{{padding:.65rem;text-align:left;vertical-align:top;border-bottom:1px solid #d7d3c8}}thead th{{background:#eef2ed}}</style></head><body><main><h1>{title}: timeline</h1><div class="controls"><label>Search<input id="search" type="search"></label><label>Event kind<select id="kind"><option value="">All</option>{options}</select></label></div><p id="count" aria-live="polite"></p><div class="table-wrap"><table><thead><tr><th>Date</th><th>Event</th><th>Place</th><th>Participants</th><th>Description</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="5">No events recorded.</td></tr>'}</tbody></table></div><script type="application/json" id="timeline-data">{embedded}</script><script>(()=>{{const search=document.querySelector('#search'),kind=document.querySelector('#kind'),rows=[...document.querySelectorAll('tbody tr[data-kind]')],count=document.querySelector('#count');function apply(){{const q=search.value.trim().toLocaleLowerCase(),k=kind.value;let shown=0;for(const row of rows){{const visible=(!q||row.dataset.search.includes(q))&&(!k||row.dataset.kind===k);row.hidden=!visible;if(visible)shown++}}count.textContent=`${{shown}} of ${{rows.length}} events shown`}}search.addEventListener('input',apply);kind.addEventListener('change',apply);apply()}})();</script></main></body></html>"""
