"""Human-readable catalogue generation for portable research projects."""

from __future__ import annotations

from html import escape
import json
from typing import Any, Mapping, Sequence
from .dates import date_sort_key


def display_name(person: Mapping[str, Any]) -> str:
    names = person.get("names", [])
    if isinstance(names, Sequence) and not isinstance(names, (str, bytes)):
        for name in names:
            if isinstance(name, Mapping):
                value = name.get("full") or name.get("value") or " ".join(str(name.get(key, "")) for key in ("given", "middle", "family")).strip()
                if value:
                    return str(value)
            elif name:
                return str(name)
    return str(person.get("name") or person.get("id", "Unnamed person"))


def render_catalogue(project: Mapping[str, Any]) -> str:
    """Return a stable Markdown catalogue; no platform terminology is assumed."""
    title = project.get("project", {}).get("title", "Genealogy research")
    lines = [f"# {title}", "", "## People", ""]
    people = sorted(project.get("people", []), key=lambda item: display_name(item).casefold())
    event_by_person: dict[str, list[Mapping[str, Any]]] = {}
    for event in project.get("events", []):
        for person_id in event.get("person_ids", []):
            event_by_person.setdefault(str(person_id), []).append(event)
        for person_id in event.get("participant_ids", []):
            event_by_person.setdefault(str(person_id), []).append(event)
    for person in people:
        lines.append(f"- **{display_name(person)}** (`{person.get('id', '')}`)")
        for event in event_by_person.get(str(person.get("id")), []):
            lines.append(f"  - {event.get('type') or event.get('kind', 'event')}: {event.get('date', 'undated')}")
    if not people:
        lines.append("- No people recorded.")
    lines.extend(["", "## Research questions", ""])
    for question in project.get("questions", []):
        lines.append(f"- {question.get('text') or question.get('question') or question.get('id')}")
    if not project.get("questions", []):
        lines.append("- None recorded.")
    lines.extend(["", "## Findings", ""])
    for finding in project.get("findings", []):
        lines.append(f"- {finding.get('conclusion') or finding.get('id')}")
    if not project.get("findings", []):
        lines.append("- None recorded.")
    return "\n".join(lines) + "\n"


def catalogue_data(project: Mapping[str, Any]) -> dict[str, Any]:
    """Build a stable, presentation-neutral catalogue index."""
    # Callers pass the privacy-filtered project representation.
    public_people = [p for p in project.get("people", []) if isinstance(p, Mapping)]
    people_by_id = {str(p.get("id", "")): p for p in public_people}
    people_ids = {str(p.get("id", "")) for p in public_people}
    places = {str(p.get("id")): p for p in project.get("places", []) if isinstance(p, Mapping)}
    events_by_person: dict[str, list[Mapping[str, Any]]] = {}
    events_by_id = {str(e.get("id")): e for e in project.get("events", []) if isinstance(e, Mapping)}
    for event in project.get("events", []):
        if not isinstance(event, Mapping):
            continue
        for person_id in event.get("participant_ids", event.get("person_ids", [])):
            if str(person_id) in people_ids:
                events_by_person.setdefault(str(person_id), []).append(event)
    for person in public_people:
        pid = str(person.get("id", ""))
        for event_id in person.get("event_ids", []):
            event = events_by_id.get(str(event_id))
            if event is not None and event not in events_by_person.setdefault(pid, []):
                events_by_person[pid].append(event)
    relatives: dict[str, list[dict[str, str]]] = {pid: [] for pid in people_ids}
    for relationship in project.get("relationships", []):
        if not isinstance(relationship, Mapping):
            continue
        subject, other = str(relationship.get("subject_id", "")), str(relationship.get("object_id", ""))
        if subject not in people_ids or other not in people_ids:
            continue
        kind = str(relationship.get("kind") or relationship.get("type") or "related")
        relatives[subject].append({"id": other, "name": display_name(people_by_id[other]), "relationship": kind})
        relatives[other].append({"id": subject, "name": display_name(people_by_id[subject]), "relationship": kind})
    claims_by_person: dict[str, list[Mapping[str, Any]]] = {}
    for claim in project.get("claims", []):
        if isinstance(claim, Mapping) and str(claim.get("subject_id", "")) in people_ids:
            claims_by_person.setdefault(str(claim.get("subject_id", "")), []).append(claim)
    people = []
    for person in sorted(public_people, key=lambda item: display_name(item).casefold()):
        person_id = str(person.get("id", ""))
        events = sorted((dict(event) for event in events_by_person.get(person_id, [])),
                        key=lambda item: (date_sort_key(item.get("date")), str(item.get("id", ""))))
        summary: dict[str, Any] = {}
        for event in events:
            kind = str(event.get("kind") or event.get("type") or "").casefold()
            if kind in ("birth", "birt", "death", "deat"):
                prefix = "birth" if kind in ("birth", "birt") else "death"
                summary[f"{prefix}_date"] = event.get("date")
                place = places.get(str(event.get("place_id", "")))
                if place:
                    summary[f"{prefix}_place"] = place.get("name") or place.get("title") or place.get("label")
        people.append({
            "id": person_id,
            "name": display_name(person),
            "events": events,
            "claims": [dict(claim) for claim in claims_by_person.get(person_id, [])],
            "external_ids": list(person.get("external_ids", [])),
            "relatives": relatives.get(person_id, []),
            **summary,
        })
    return {
        "project": dict(project.get("project", {})),
        "people": people,
        "places": [dict(place) for place in places.values()],
        "questions": list(project.get("questions", [])),
        "findings": list(project.get("findings", [])),
        "sources": list(project.get("sources", [])),
        "counts": {
            key: len(project.get(key, []))
            for key in (
                "people", "events", "places", "relationships", "claims",
                "sources", "citations", "evidence", "hypotheses", "questions", "findings",
            )
        },
    }


def render_catalogue_html(project: Mapping[str, Any]) -> str:
    """Render a searchable, self-contained and offline-safe HTML catalogue."""
    data = catalogue_data(project)
    title = escape(str(data["project"].get("title", "Genealogy research")))
    count_cards = "".join(
        f'<li><strong>{count}</strong><span>{escape(label.replace("_", " ").title())}</span></li>'
        for label, count in data["counts"].items()
    )
    people_rows = []
    for person in data["people"]:
        events = "; ".join(
            f'{event.get("date") or "undated"}: {event.get("kind") or event.get("type") or "event"}'
            for event in person["events"]
        )
        claims = "; ".join(
            f'{claim.get("predicate", "claim")}: {claim.get("value", "")}'
            for claim in person["claims"]
        )
        life = "; ".join(str(person.get(key, "")) for key in ("birth_date", "birth_place", "death_date", "death_place") if person.get(key))
        kin = "; ".join(f'{r.get("relationship", "related")}: {r.get("name", "")}' for r in person.get("relatives", []))
        search = escape(" ".join((person["name"], person["id"], events, claims, life, kin)).casefold(), quote=True)
        people_rows.append(
            f'<tr data-search="{search}"><th scope="row">{escape(person["name"])}</th>'
            f'<td><code>{escape(person["id"])}</code></td><td>{escape(life + ("; " if life and events else "") + events) or "—"}</td>'
            f'<td>{escape(claims + (("; " if claims and kin else "") + kin)) or "—"}</td></tr>'
        )
    question_items = "".join(
        f'<li>{escape(str(item.get("question") or item.get("text") or item.get("id", "")))}</li>'
        for item in data["questions"] if isinstance(item, Mapping)
    ) or "<li>None recorded.</li>"
    finding_items = "".join(
        f'<li>{escape(str(item.get("conclusion") or item.get("id", "")))}</li>'
        for item in data["findings"] if isinstance(item, Mapping)
    ) or "<li>None recorded.</li>"
    source_rows = "".join(
        f'<tr><th scope="row">{escape(str(item.get("title") or item.get("id", "")))}</th>'
        f'<td>{escape(str(item.get("repository") or "—"))}</td>'
        f'<td>{escape(str(item.get("source_type") or "unknown"))}</td></tr>'
        for item in data["sources"] if isinstance(item, Mapping)
    ) or '<tr><td colspan="3">No public sources recorded.</td></tr>'
    embedded = json.dumps(data, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — catalogue</title>
<style>:root{{--ink:#17212b;--muted:#5d6a76;--paper:#fbfaf6;--line:#d7d3c8;--accent:#315c4c}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.5 system-ui,sans-serif}}main{{max-width:76rem;margin:auto;padding:2rem}}h1,h2{{line-height:1.15}}.counts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(8rem,1fr));gap:.75rem;padding:0;list-style:none}}.counts li{{border:1px solid var(--line);border-radius:.5rem;padding:.8rem;background:white}}.counts strong,.counts span{{display:block}}.counts strong{{font-size:1.5rem;color:var(--accent)}}label{{font-weight:700}}input{{display:block;width:100%;max-width:34rem;margin:.4rem 0 1rem;padding:.65rem;border:1px solid var(--line);border-radius:.35rem}}.table-wrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;background:white}}th,td{{padding:.65rem;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}}thead th{{background:#eef2ed}}code{{font-size:.85em}}section{{margin-top:2.25rem}}.muted{{color:var(--muted)}}</style>
</head><body><main><header><p class="muted">Portable genealogy research catalogue</p><h1>{title}</h1></header>
<ul class="counts">{count_cards}</ul>
<section><h2>People</h2><label for="catalogue-filter">Filter people, events and claims</label><input id="catalogue-filter" type="search" autocomplete="off"><p id="result-count" class="muted" aria-live="polite"></p><div class="table-wrap"><table><thead><tr><th>Name</th><th>Record ID</th><th>Events</th><th>Claims</th></tr></thead><tbody id="people-body">{''.join(people_rows) or '<tr><td colspan="4">No people recorded.</td></tr>'}</tbody></table></div></section>
<section><h2>Research questions</h2><ul>{question_items}</ul></section><section><h2>Findings</h2><ul>{finding_items}</ul></section>
<section><h2>Sources</h2><div class="table-wrap"><table><thead><tr><th>Source</th><th>Repository</th><th>Type</th></tr></thead><tbody>{source_rows}</tbody></table></div></section>
<script id="catalogue-data" type="application/json">{embedded}</script><script>(()=>{{const input=document.querySelector('#catalogue-filter'),rows=[...document.querySelectorAll('#people-body tr[data-search]')],count=document.querySelector('#result-count');function apply(){{const q=input.value.trim().toLocaleLowerCase(),shown=rows.filter(row=>{{const visible=!q||row.dataset.search.includes(q);row.hidden=!visible;return visible}}).length;count.textContent=`${{shown}} of ${{rows.length}} people shown`}}input.addEventListener('input',apply);apply()}})();</script>
</main></body></html>"""
