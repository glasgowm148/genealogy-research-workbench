"""The page shell: sidebar sections, breadcrumb and build stamp."""
from __future__ import annotations

from html import escape
import re
from typing import Any, Iterable

# The sidebar's sections, in order, each with its pages; a page that is not
# built (an optional route switched off) is left out. A route listed in no
# section is shown under the last one, so a new page is never unreachable.
NAV_GROUPS = (
    ("people", "People", ("catalogue.html", "branches.html", "duplicates.html")),
    ("family", "Family", ("tree.html", "timeline.html", "connections.html", "compare.html")),
    ("places", "Places", ("places.html", "statistics.html")),
    ("records", "Records", ("sources.html", "evidence.html")),
    ("research", "Research", ("research.html", "studies.html", "findings.html", "progress.html")),
    ("about", "About", ("sitemap.html", "about-data.html", "changes.html", "corrections.html")),
)
# Sidebar wording where a page's own title would only repeat its section's name.
NAV_LABELS = {"catalogue.html": "People catalogue", "places.html": "Map and places", "research.html": "Research notebook",
              "sitemap.html": "Site index"}
# One stroked path per section, styled by .nav-icon; kept short because every page carries them.
ICONS = {
    "home": "M3 9.5 10 4l7 5.5V17h-4.5v-4.5h-5V17H3z",
    "people": "M7.5 9a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM2.5 16c0-2.8 2.2-4.5 5-4.5s5 1.7 5 4.5M13 4.3a2.5 2.5 0 0 1 0 4.4m1.5 3.1c1.8.4 3 1.9 3 4.2",
    "family": "M10 17.5V11m0 0L5 7m5 4 5-4M5 7a2 2 0 1 0 0-4 2 2 0 0 0 0 4zm10 0a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
    "places": "M10 18s5.5-5 5.5-9.5a5.5 5.5 0 0 0-11 0C4.5 13 10 18 10 18zm0-7.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
    "records": "M5 2.5h7l3 3v12H5zm7 0v3h3m-7.5 4h5m-5 3h5m-5 3h3",
    "research": "M10 5.5C8.5 4 6 3.5 3 3.5v12c3 0 5.5.5 7 2 1.5-1.5 4-2 7-2v-12c-3 0-5.5.5-7 2zm0 0v12",
    "about": "M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16zm0-9.5V14m0-7.5v.1",
    "search": "M8.5 14a5.5 5.5 0 1 0 0-11 5.5 5.5 0 0 0 0 11zm4-1.5L17 17",
}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def icon(name: str) -> str:
    return f'<svg class="nav-icon" viewBox="0 0 20 20" aria-hidden="true"><path d="{ICONS[name]}"/></svg>'


def readable_date(value: str) -> str:
    """An ISO date (YYYY, YYYY-MM or YYYY-MM-DD) as "27 Sep 2026", "Sep 2026" or "2026"."""
    match = re.fullmatch(r"(\d{4})(?:-(\d\d)(?:-(\d\d))?)?", value)
    if not match or (match[2] and not 1 <= int(match[2]) <= 12):
        return value
    return " ".join(([str(int(match[3]))] if match[3] else []) + ([MONTHS[int(match[2]) - 1]] if match[2] else []) + [match[1]])


def build_stamp(findings: Iterable[dict[str, Any]], studies: Iterable[dict[str, Any]]) -> str:
    # Dated from the research itself, never the clock, so a rebuild of the same
    # research is identical. ISO strings of any precision compare in date order.
    dates = [str(f["recorded_on"]) for f in findings if f.get("recorded_on")] + [str(s["updated_on"]) for s in studies if s.get("updated_on")]
    dates = [d for d in dates if re.fullmatch(r"\d{4}(?:-\d\d){0,2}", d)]
    if not dates:
        return ""
    newest = max(dates)
    return (f'<p class="build-stamp" title="The newest recorded finding or study update">Catalogue · '
            f'<time datetime="{escape(newest)}">{escape(readable_date(newest))}</time></p>')


def section_route(path: str, view: str, routes: dict[str, tuple[str, str]]) -> str | None:
    """The route a page belongs to: itself, or for a person, study, place or paged list, the route listing it."""
    if path in routes:
        return path
    view = {"person": "people", "study": "studies"}.get(view, view)
    return next((route for route, (v, _) in routes.items() if v == view), None)


def groups(routes: dict[str, tuple[str, str]]) -> list[tuple[str, str, list[str]]]:
    listed = {route for _, _, members in NAV_GROUPS for route in members}
    built = [(key, label, [r for r in members if r in routes]) for key, label, members in NAV_GROUPS]
    built[-1][2].extend(r for r in routes if r not in listed and r != "index.html")
    return [group for group in built if group[2]]


def sidebar_nav(path: str, prefix: str, view: str, routes: dict[str, tuple[str, str]]) -> str:
    # Only the current section lists its pages, which keeps every page small;
    # each section's link opens its first page, and the site index lists them all.
    current = section_route(path, view, routes)
    home = ' aria-current="page"' if path == "index.html" else ""
    parts = [f'<a class="nav-home" data-view="overview" href="{prefix}index.html"{home}>{icon("home")}Home</a>']
    for key, label, members in groups(routes):
        if current not in members:
            parts.append(f'<a class="nav-group" data-group="{key}" href="{prefix}{members[0]}">{icon(key)}{label}</a>')
            continue
        items = "".join(f'<li><a data-view="{routes[r][0]}" href="{prefix}{r}"'
                        + (' aria-current="page"' if r == path else ' aria-current="true"' if r == current else "")
                        + f'>{escape(NAV_LABELS.get(r, routes[r][1]))}</a></li>' for r in members)
        parts.append(f'<div class="nav-section"><a class="nav-group" data-group="{key}" href="{prefix}{members[0]}">{icon(key)}{label}</a>'
                     f'<ul>{items}</ul></div>')
    shortcuts = ([f'<a href="{prefix}connections.html">Find a connection <span aria-hidden="true">→</span></a>'] if "connections.html" in routes else []) + [
        f'<a href="{prefix}sitemap.html">Site map</a>']
    return "".join(parts) + '<p class="nav-shortcuts">' + "".join(shortcuts) + "</p>"


def breadcrumb(path: str, prefix: str, view: str, title: str, routes: dict[str, tuple[str, str]]) -> str:
    """Home / section / page: a person's page reads Home / People / their name."""
    crumbs = [f'<a href="{prefix}index.html">Home</a>'] if path != "index.html" else []
    current = section_route(path, view, routes)
    if path in routes and path != "index.html":
        # A section page sits under its section's name, which is not a page of its own.
        label = next((label for _, label, members in groups(routes) if path in members), "")
        if label and label != title:
            crumbs.append(f"<span>{escape(label)}</span>")
    elif current and path not in routes:
        crumbs.append(f'<a href="{prefix}{current}">{escape(routes[current][1])}</a>')
    crumbs.append(f'<span aria-current="page">{escape(title if path != "index.html" else "Home")}</span>')
    return '<nav class="site-breadcrumb" aria-label="Breadcrumb"><ol>' + "".join(f"<li>{c}</li>" for c in crumbs) + "</ol></nav>"
