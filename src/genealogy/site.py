"""Cohesive offline website derived exclusively from the public export contract."""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from . import exports
from .case import ResearchCase
from .config import ProjectConfig
from .dates import date_sort_key
from .maps import geojson

ROUTES = {
    "index.html": ("overview", "Overview"), "catalogue.html": ("people", "People"),
    "tree.html": ("tree", "Family tree"), "timeline.html": ("timeline", "Timeline"),
    "places.html": ("map", "Places"), "sources.html": ("sources", "Sources"),
    "research.html": ("research", "Research"), "compare.html": ("compare", "Compare"),
    "connections.html": ("connections", "Connections"), "sitemap.html": ("sitemap", "Site index"),
}
MANIFEST = ".genealogy-site-manifest.json"


def _text(value: Any) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def _key(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _anchor(value: str) -> str:
    return "r-" + _key(value)


def _url(value: Any) -> str | None:
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc and not parsed.username and not parsed.password:
            return value
    except ValueError:
        pass
    return None


def _json(value: Any) -> str:
    # Script elements are raw-text even when their type is application/json.
    return json.dumps(value, ensure_ascii=False, sort_keys=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _owned(name: str) -> bool:
    return name in ROUTES or name in {"assets/site.css", "assets/site.js", "assets/favicon.svg", "assets/world.svg", "data/site.json", "data/site.csv", "data/places.geojson", "data/routes.json"} or bool(re.fullmatch(r"people/p-[0-9a-f]{64}\.html", name))


def build_site(case: ResearchCase, config: ProjectConfig, directory: Path) -> dict[str, Path]:
    """Build portable HTML and data, removing only previously generated stale pages.

    The public export gate decides all record eligibility. The original case is
    deliberately never consulted again after that call. No network is used.
    """
    project = exports.project_for_public_export(case, config)
    directory = Path(directory)
    people = {p["id"]: p for p in project["people"]}
    places = {p["id"]: p for p in project["places"]}
    sources = {s["id"]: s for s in project["sources"]}
    citations = {c["id"]: c for c in project["citations"]}
    people_urls = {pid: "people/p-" + _key(pid) + ".html" for pid in people}
    events_by_person: dict[str, list[dict[str, Any]]] = defaultdict(list)
    events_by_place: dict[str, list[dict[str, Any]]] = defaultdict(list)
    relationships_by_person: dict[str, list[dict[str, Any]]] = defaultdict(list)
    claims_by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    evidence_by_claim: dict[str, list[dict[str, Any]]] = defaultdict(list)
    citations_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    research_by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    event_owners: dict[str, set[str]] = defaultdict(set)
    for person in people.values():
        for eid in person.get("event_ids", []):
            event_owners[eid].add(person["id"])
    events_sorted = sorted(project["events"], key=lambda e: (date_sort_key(e.get("date")), e["id"]))
    for event_row in events_sorted:
        for pid in set(event_row.get("participant_ids", [])) | event_owners[event_row["id"]]:
            events_by_person[pid].append(event_row)
        if event_row.get("place_id"):
            events_by_place[event_row["place_id"]].append(event_row)
    for row in project["relationships"]:
        for pid in {row["subject_id"], row["object_id"]}:
            relationships_by_person[pid].append(row)
    for row in project["claims"]:
        claims_by_subject[row["subject_id"]].append(row)
    for row in project["evidence"]:
        evidence_by_claim[row["claim_id"]].append(row)
    for row in project["citations"]:
        citations_by_source[row["source_id"]].append(row)
    for collection in ("questions", "findings", "hypotheses"):
        for row in project[collection]:
            for rid in set(row.get("related_ids", [])):
                research_by_subject[rid].append(row)
    record_routes: dict[str, str] = {}
    for collection, rows in project.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            route = people_urls.get(row["id"])
            if not route:
                route = {"events": "timeline.html", "places": "places.html", "sources": "sources.html", "citations": "sources.html", "relationships": "tree.html"}.get(collection, "research.html")
                route += "#" + _anchor(row["id"])
            record_routes[row["id"]] = route

    def person_name(pid: str) -> str:
        p = people.get(pid, {})
        return next((n["value"] for n in p.get("names", []) if n.get("value")), pid)

    def ref(rid: str, prefix: str = "", label: str | None = None) -> str:
        title = label or person_name(rid)
        route = record_routes.get(rid)
        return f'<a href="{prefix}{_text(route)}">{_text(title)}</a>' if route else _text(title)

    def empty(items: list[str], message: str = "No public records recorded.") -> str:
        return '<ul class="record-list">' + "".join(items) + "</ul>" if items else f'<p class="empty-state">{_text(message)}</p>'

    def metadata(row: dict[str, Any]) -> str:
        return ' <span class="badge">' + _text(" · ".join(str(row[k]) for k in ("status", "confidence") if row.get(k))) + "</span>" if row.get("status") or row.get("confidence") else ""

    def citation(row: dict[str, Any], prefix: str = "", *, canonical: bool = False) -> str:
        src = sources.get(row["source_id"], {})
        parts = [ref(row["source_id"], prefix, src.get("title", row["source_id"]))]
        for key in ("locator", "quotation", "transcription", "accessed_on"):
            if row.get(key):
                parts.append(f'<p><strong>{_text(key.replace("_", " ").capitalize())}:</strong> {_text(row[key])}</p>')
        return ('<article id="' + _anchor(row["id"]) + '">' if canonical else "<article>") + "".join(parts) + "</article>"

    def event(row: dict[str, Any], prefix: str = "", *, canonical: bool = True) -> str:
        place = places.get(row.get("place_id"), {})
        return (f'<li id="{_anchor(row["id"])}" data-event-id="{_text(row["id"])}">' if canonical else "<li>") + f'<strong>{_text(row.get("date") or "Date unknown")} · {_text(row["kind"])}</strong>' + (f' — {ref(place["id"], prefix, place["name"])}' if place else "") + (f'<p>{_text(row["description"])}</p>' if row.get("description") else "") + '<p>' + ", ".join(ref(pid, prefix) for pid in row.get("participant_ids", [])) + "</p></li>"

    def relationship(row: dict[str, Any], prefix: str = "") -> str:
        return f'<li id="{_anchor(row["id"])}">{ref(row["subject_id"], prefix)} — {_text(row["kind"])} → {ref(row["object_id"], prefix)}{metadata(row)}' + ("<p>Claims: " + ", ".join(ref(cid, prefix) for cid in row["claim_ids"]) + "</p>" if row.get("claim_ids") else "") + "</li>"

    def claim(row: dict[str, Any], prefix: str = "") -> str:
        supporting = evidence_by_claim[row["id"]]
        parts = [f'<article class="record-card card" id="{_anchor(row["id"])}"><h3>{_text(row["predicate"])}: {_text(row["value"])}</h3>{metadata(row)}', f'<p>Subject: {ref(row["subject_id"], prefix)}</p>']
        if row.get("rationale"):
            parts.append(f'<p>{_text(row["rationale"])}</p>')
        parts.append("<h4>Citations</h4>" + empty(["<li>" + citation(citations[cid], prefix) + "</li>" for cid in row.get("citation_ids", []) if cid in citations]))
        parts.append("<h4>Evidence assessments</h4>" + empty([f'<li id="{_anchor(e["id"])}"><strong>{"Supports" if e["supports"] else "Challenges"}</strong>: {_text(e["assessment"])}{metadata(e)} — {ref(e["citation_id"], prefix, "Citation")}</li>' for e in supporting]))
        return "".join(parts) + "</article>"

    options = '<option value="">Choose a person</option>' + "".join(f'<option value="{_text(pid)}">{_text(person_name(pid))}</option>' for pid in people)
    catalogue_rows = []
    for pid, person in people.items():
        events = events_by_person[pid]
        summary = "; ".join(f'{e["kind"]}: {e.get("date") or "date unknown"}' for e in events)
        catalogue_rows.append(f'<tr data-person-id="{_text(pid)}" data-search-text="{_text(person_name(pid) + " " + pid + " " + summary)}"><td>{ref(pid)}</td><td>{_text(summary or "No events recorded.")}</td><td>{_text(pid)}</td></tr>')
    pages: dict[str, str] = {}
    counts = [(len(project[key]), label) for key, label in (("people", "people"), ("events", "events"), ("sources", "sources"), ("questions", "research questions"))]
    pages["index.html"] = '<p class="eyebrow">An evidence-led family history</p><h1>' + _text(config.name) + '</h1><p>Explore people, family connections and historical records. Claims, citations and evidence assessments remain distinct throughout this collection.</p><div class="stats stat-grid">' + "".join(f'<div class="stat-card"><strong>{n}</strong><span>{label}</span></div>' for n, label in counts) + '</div><h2>Start exploring</h2><p><a class="button" href="catalogue.html">Browse the people</a> <a href="tree.html">Explore family connections</a></p><h2>Research findings</h2>' + empty([f'<li>{ref(f["id"], label=f["conclusion"])}{metadata(f)}</li>' for f in project["findings"]])
    pages["catalogue.html"] = '<h1>People catalogue</h1><label>Search people <input type="search" data-search placeholder="Name, ID or event"></label><p id="site-status" role="status"></p><div data-catalogue>' + ('<div class="table-wrap"><table><thead><tr><th>Person</th><th>Recorded events</th><th>Record ID</th></tr></thead><tbody>' + "".join(catalogue_rows) + '</tbody></table></div>' if catalogue_rows else '<p class="empty-state">No public people are available.</p>') + '</div>'
    pages["tree.html"] = '<h1>Family tree and branches</h1><p>Arrows follow the stored relationship direction; confidence describes the recorded assessment.</p><label>Explore from <select id="tree-root">' + options + '</select></label><div id="tree-output"></div><h2>Recorded family connections</h2>' + empty([relationship(r) for r in project["relationships"]], "No public family connections recorded.")
    pages["timeline.html"] = '<h1>Timeline</h1><p>Recorded dates are preserved, including approximate and incomplete dates.</p><div data-timeline>' + empty([event(e) for e in events_sorted], "No public dated events recorded.").replace('class="record-list"', 'class="record-list timeline"', 1) + '</div>'
    points, place_rows = [], []
    for p in project["places"]:
        coords = p.get("latitude") is not None and p.get("longitude") is not None
        details = f'{p["latitude"]}, {p["longitude"]}' if coords else "Coordinates not supplied"
        if coords:
            x, y = (p["longitude"] + 180) * 960 / 360, (90 - p["latitude"]) * 480 / 180
            points.append(f'<a href="#{_anchor(p["id"])}"><circle cx="{x:.3f}" cy="{y:.3f}" r="5"><title>{_text(p["name"])}</title></circle></a>')
        related = events_by_place[p["id"]]
        place_rows.append(f'<li id="{_anchor(p["id"])}"><h2>{_text(p["name"])}</h2><p>{_text(details)}</p>' + empty([event(e, canonical=False) for e in related], "No events linked to this place.") + '</li>')
    pages["places.html"] = '<h1>Places</h1><p>This offline coordinate overview uses supplied coordinates only. No geocoding or external map service is used. Basemap: <a href="https://www.naturalearthdata.com/">Natural Earth</a> (public domain).</p><div id="map-output"><svg class="place-map" viewBox="0 0 960 480" role="img" aria-label="Places with supplied coordinates"><rect width="960" height="480" fill="#e8efec"/><image href="assets/world.svg" width="960" height="480"/><path d="M0 240H960M480 0V480" stroke="#a8b9af"/>' + "".join(points) + '</svg></div>' + ("<p>No coordinates supplied.</p>" if not points else "") + empty(place_rows)
    source_cards = []
    for src in sources.values():
        link = _url(src.get("url"))
        fields = "".join(f'<p><strong>{_text(k.replace("_", " ").capitalize())}:</strong> {_text(src[k])}</p>' for k in ("source_type", "repository", "access_note", "licence") if src.get(k))
        source_cards.append(f'<article class="record-card card" data-source-id="{_text(src["id"])}" id="{_anchor(src["id"])}"><h2>{_text(src["title"])}</h2>{fields}' + (f'<p><a href="{_text(link)}" rel="noreferrer">Open original source</a></p>' if link else "") + '<h3>Citations</h3>' + empty(["<li>" + citation(c, canonical=True) + "</li>" for c in citations_by_source[src["id"]]]) + '</article>')
    pages["sources.html"] = '<h1>Sources and citations</h1><p>Consult original records when assessing a claim. A citation identifies the specific record or passage.</p><div data-sources>' + ("".join(source_cards) or '<p class="empty-state">No public sources recorded.</p>') + '</div>'
    research = ['<h1>Research notebook</h1><h2>Claims</h2>', "".join(claim(c) for c in project["claims"]) or '<p>No public claims recorded.</p>']
    for collection, heading, field in (("hypotheses", "Hypotheses", "statement"), ("questions", "Research questions", "question"), ("findings", "Findings", "conclusion")):
        research.append(f'<h2>{heading}</h2>' + empty([f'<li id="{_anchor(r["id"])}"><h3>{_text(r[field])}</h3>{metadata(r)}<p>' + ", ".join(ref(rid) for rid in r.get("related_ids", [])) + '</p><p>' + ", ".join(ref(eid, label="Evidence assessment") for eid in r.get("evidence_ids", [])) + '</p></li>' for r in project[collection]]))
    pages["research.html"] = "".join(research)
    for route, heading, hook in (("compare.html", "Compare people", "compare"), ("connections.html", "Find a connection", "connection")):
        pages[route] = f'<h1>{heading}</h1><p>Select two people to explore this public collection. Interactive results require JavaScript.</p><div class="tool-controls"><label>First person <select data-{hook}-a>{options}</select></label><label>Second person <select data-{hook}-b>{options}</select></label></div><div id="{hook}-result" role="status"></div><h2>Browse dossiers</h2>' + empty([f'<li>{ref(pid)}</li>' for pid in people])
    for pid, person in people.items():
        related_events = events_by_person[pid]
        subject_ids = {pid, *(e["id"] for e in related_events)}
        related_rels = relationships_by_person[pid]
        subject_ids.update(r["id"] for r in related_rels)
        personal_claims = [c for subject in sorted(subject_ids) for c in claims_by_subject[subject]]
        name_items = [f'<li>{_text(n["value"])} — {_text(n.get("kind", "unknown"))}{metadata(n)}</li>' for n in person.get("names", [])]
        external = []
        for identifier in person.get("external_ids", []):
            label = _text(identifier["system"] + ": " + identifier["value"])
            url = _url(identifier.get("url"))
            external.append("<li>" + (f'<a href="{_text(url)}" rel="noreferrer">{label}</a>' if url else label) + "</li>")
        content = f'<p class="eyebrow">Person dossier</p><h1>{_text(person_name(pid))}</h1><p class="record-id">{_text(pid)}</p><h2>Names</h2>' + empty(name_items)
        if person.get("notes"):
            content += '<h2>Biography and notes</h2><p class="preserve-lines">' + _text(person["notes"]) + '</p>'
        content += '<h2>Family connections</h2>' + empty([relationship(r, "../") for r in related_rels]) + '<h2>Events</h2>' + empty([event(e, "../") for e in related_events]) + '<h2>Claims, citations and evidence</h2>' + ("".join(claim(c, "../") for c in personal_claims) or '<p>No public claims recorded for this person.</p>')
        content += '<h2>Research</h2>' + empty([f'<li>{ref(r["id"], "../", r.get("question") or r.get("conclusion") or r.get("statement"))}{metadata(r)}</li>' for r in research_by_subject[pid]]) + '<h2>External identifiers</h2>' + empty(external)
        pages[people_urls[pid]] = content
    data_links = '<ul><li><a href="data/site.json">Public research JSON</a></li><li><a href="data/site.csv">Public research CSV</a></li><li><a href="data/places.geojson">Place GeoJSON</a></li><li><a href="data/routes.json">Route index JSON</a></li></ul>'
    pages["sitemap.html"] = '<h1>Site index and downloads</h1><h2>Explore</h2><ul>' + "".join(f'<li><a href="{path}">{title}</a></li>' for path, (_, title) in ROUTES.items()) + '</ul><h2>People</h2>' + empty([f'<li>{ref(pid)}</li>' for pid in people]) + '<h2>Machine-readable data</h2>' + data_links
    outputs: dict[str, str] = {"data/site.json": exports.to_json(project), "data/site.csv": exports.to_csv(project), "data/places.geojson": json.dumps(geojson(project), ensure_ascii=False, indent=2) + "\n", "data/routes.json": json.dumps(sorted(pages), indent=2) + "\n"}
    branding = config.raw.get("site", {})
    description = branding.get("description", "A public collection of people, records and research.") if isinstance(branding, dict) else "A public collection of people, records and research."
    person_titles = {url: person_name(pid) for pid, url in people_urls.items()}
    person_ids_by_path = {url: pid for pid, url in people_urls.items()}
    for path, content in pages.items():
        prefix = "../" if path.startswith("people/") else ""
        view, title = ROUTES[path] if path in ROUTES else ("person", person_titles[path])
        person_attribute = f' data-person-id="{_text(person_ids_by_path[path])}"' if path in person_ids_by_path else ""
        nav = "".join(f'<a data-view="{v}" href="{prefix}{p}"' + (' aria-current="page"' if path == p else '') + f'>{t}</a>' for p, (v, t) in ROUTES.items())
        # Dossiers need only the menu enhancement. Embedding the whole case in
        # each person page would make disk use quadratic in the person count.
        interactive = view in {"people", "tree", "timeline", "map", "compare", "connections", "sources"}
        payload = {**project, "site": {"people_urls": {pid: prefix + url for pid, url in people_urls.items()}}} if interactive else {"project": project["project"]}
        outputs[path] = f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="{_text(description)}"><title>{_text(title)} — {_text(config.name)}</title><link rel="icon" href="{prefix}assets/favicon.svg"><meta name="theme-color" content="#193f33"><link rel="stylesheet" href="{prefix}assets/site.css"><script defer src="{prefix}assets/site.js"></script><noscript><style>.site-sidebar nav{{display:grid!important}}#menu-toggle{{display:none!important}}</style></noscript></head><body data-view="{view}"{person_attribute}><a class="skip-link" href="#main-content">Skip to content</a><div class="site-shell"><aside class="site-sidebar" id="site-sidebar"><a class="site-brand brand" href="{prefix}index.html">{_text(config.name)}</a><p class="site-tagline">People · records · evidence</p><nav aria-label="Main navigation">{nav}</nav></aside><div class="site-content"><header class="site-header"><button id="menu-toggle" aria-controls="site-sidebar" aria-expanded="false">Menu</button><span>{_text(config.name)}</span></header><main id="main-content">{content}</main><footer class="site-footer"><p>Public research edition · <a href="{prefix}sitemap.html">Site index and downloads</a></p><p>Missing information is unknown; confidence and status remain attached to recorded claims.</p></footer></div></div><script type="application/json" id="site-data">{_json(payload)}</script></body></html>'
    asset_root = Path(__file__).with_name("web")
    for filename in ("site.css", "site.js", "favicon.svg", "world.svg"):
        asset = asset_root / filename
        if asset.is_file():
            outputs["assets/" + filename] = asset.read_text(encoding="utf-8")
        else:
            raise FileNotFoundError(f"website asset missing: {asset}")
    # Validate every destination before writing anything, including symlink escapes.
    destinations = {name: exports.safe_output_path(directory, name) for name in outputs}
    manifest_path = exports.safe_output_path(directory, MANIFEST)
    previous: list[str] = []
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            previous = loaded if isinstance(loaded, list) else []
        except (ValueError, OSError):
            previous = []
    stale = [exports.safe_output_path(directory, name) for name in previous if isinstance(name, str) and _owned(name) and name not in outputs]
    for name, destination in destinations.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(outputs[name], encoding="utf-8")
    for destination in stale:
        if destination.is_file():
            destination.unlink()
    manifest_path.write_text(json.dumps(sorted(outputs), indent=2) + "\n", encoding="utf-8")
    return destinations
