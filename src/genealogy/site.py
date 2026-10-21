"""Cohesive offline website derived exclusively from the public export contract."""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re
from typing import Any
import unicodedata
from urllib.parse import quote, urlsplit
from xml.sax.saxutils import escape as xml_escape

from . import exports
from .case import ResearchCase
from .config import ProjectConfig, site_contact
from .dates import date_sort_key, year_of
from .feeds import FeedEntry, atom_feed
from .markup import references as prose_references, render as render_prose
from .labels import (assessment_label, child_role, confidence_label, grade_label, guide_entries, parent_role, quality_parts, relationship_label,
                     status_anchor, status_label)
from .maps import geojson
from .labels import CLAIM_STATUS, guide_basis  # the evidence guide's basis and example lines

# Lists longer than this are not written out in full: the interactive views
# load them from the shared data script, and readers without JavaScript
# browse the paged pages instead. Keeps every page small at thousands of people.
INLINE_LIMIT = 300
LATEST_FINDINGS = 30  # the findings log opens with the newest; older ones are on archive pages
LATEST_SEARCHES = 50  # research.html lists the newest searches; each dossier lists all of its own
FINDINGS_PER_PAGE = 50
CATALOGUE_PER_PAGE = 100  # people per catalogue page on a large site, in name order
PLACES_PER_PAGE = 100  # places per region page on a large site
SOURCES_PER_PAGE = 100  # sources per page on a large site, in title order
STUDIES_PER_PAGE = 100  # studies on a large site's studies page (newest) and on each title page
CITED_FOR_LIMIT = 20  # people, findings or family links listed under a source's "Cited for"
STUDY_GROUPS_DRAWN = 20  # groups drawn in a study's connection diagram; all are listed
CHRONOLOGY_LANES = 30  # people drawn in a study's chronology; the rest are counted, not drawn
CHRONOLOGY_BYTES = 36_000  # lanes stop once the drawing reaches this, so a busy study page stays small
PLACE_LIST_LIMIT = 200  # people, sub-places, surnames or studies listed on a place's page; the rest are counted
PLACE_PEOPLE_BYTES = 40_000  # a place's people list also stops here, and each of its other lists at a third of it
STATISTICS_ROWS = 25  # rows per statistics table; the rest are counted, so the page stays small on a large site
UNPLACED_REGION = "Places without a broader jurisdiction"
ROUTES = {
    "index.html": ("overview", "Overview"), "catalogue.html": ("people", "People"),
    "tree.html": ("tree", "Family tree"), "branches.html": ("branches", "Families & branches"),
    "timeline.html": ("timeline", "Timeline"), "places.html": ("map", "Places"), "sources.html": ("sources", "Sources"),
    "studies.html": ("studies", "Studies"), "research.html": ("research", "Research"),
    "findings.html": ("findings", "Latest findings"), "compare.html": ("compare", "Compare"),
    "connections.html": ("connections", "Connections"), "evidence.html": ("evidence", "Reading the evidence"),
    "sitemap.html": ("sitemap", "Site index"),
    "statistics.html": ("statistics", "Statistics"),
}
# Pages built only when the project configures them; still owned when switched
# off, so a rebuild removes them.
OPTIONAL_ROUTES = {"corrections.html": ("corrections", "Corrections")}
DATA_FILES = {"data/site.json", "data/site.csv", "data/places.geojson", "data/routes.json", "data/site-data.js",
              "data/public-tree.ged", "sitemap.xml", "findings.xml", "data/redirects.json", "_redirects"}
# The fields the browser script reads. ``data/site.json`` keeps every public
# field; the shared script carries only these, so it stays small to download
# and parse on a large site.
BROWSER_FIELDS = {
    "people": ("id", "names", "event_ids", "notes"),
    "events": ("id", "kind", "date", "place_id", "participant_ids", "description"),
    "places": ("id", "name", "latitude", "longitude", "precision"),
    "relationships": ("id", "subject_id", "object_id", "kind", "confidence", "grade", "estimate", "tree_status", "pedigree"),
    # A claim's citations, with each record's stated quality, let the catalogue
    # find people whose supported claims rest on an original record.
    "claims": ("id", "subject_id", "predicate", "value", "status", "citation_ids"),
    "citations": ("id", "source_id", "quality", "information"),
    "sources": ("id", "title", "author", "publication", "source_type", "repository"),
    # Never a study's body or reasoning: long prose, read on the study's own page.
    "studies": ("id", "title", "summary", "status", "updated_on", "related_ids"),
}
OUTSTANDING = ("open", "draft")  # research statuses the notebook lists first as work still to do
BROAD_PRECISIONS = {"parish", "district", "county", "region", "country", "approximate"}
ASSETS = ("site.css", "site.js", "favicon.svg", "world.svg")
MANIFEST = ".genealogy-site-manifest.json"
PARENT_KINDS = {"parent", "father", "mother", "biological_parent", "adoptive_parent", "parent_child"}
PARTNER_KINDS = {"spouse", "partner", "husband", "wife", "marriage"}
SIBLING_KINDS = {"sibling", "brother", "sister", "half_sibling", "half-sibling"}
FAMILY_EVENTS = {"marriage", "marriage banns", "marriage contract", "marriage licence", "marriage settlement",
                 "engagement", "divorce", "divorce filed", "annulment"}


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


def browser_data(project: dict[str, Any], people_urls: dict[str, str], source_urls: dict[str, str] | None = None,
                 grades: dict[str, dict[str, str]] | None = None, study_urls: dict[str, str] | None = None,
                 name_variants: dict[str, str] | None = None) -> dict[str, Any]:
    """The public records the interactive pages need, without empty values."""
    def slim(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
        out = {key: row[key] for key in fields if row.get(key) is not None and row.get(key) != [] and row.get(key) != ""}
        if "names" in out:
            out["names"] = [{key: n[key] for key in ("value", "surname") if n.get(key)} for n in out["names"]]
        return out
    data: dict[str, Any] = {key: [slim(row, fields) for row in project.get(key, [])] for key, fields in BROWSER_FIELDS.items()}
    # A citation stating neither term tells the script nothing; an imported tree
    # can hold tens of thousands of them.
    data["citations"] = [row for row in data["citations"] if row.get("quality") or row.get("information")]
    data["project"] = project["project"]
    data["site"] = {"people_urls": people_urls}
    if source_urls:
        data["site"]["source_urls"] = source_urls
    if study_urls:
        data["site"]["study_urls"] = study_urls
    if grades:
        data["site"]["grades"] = {key: grade["label"] for key, grade in grades.items()}
    if name_variants:
        data["site"]["name_variants"] = name_variants
    # The catalogue's recorded-sex filter: the first sex claim not rejected, as
    # the dossier shows it, folded to "F" or "M" where it says so; one short
    # value per person rather than the claims themselves.
    sex: dict[str, str] = {}
    for row in project.get("claims", []):
        if row.get("predicate") == "sex" and row.get("status") != "rejected":
            sex.setdefault(row["subject_id"], str(row.get("value") or "").strip())
    for row in data["people"]:
        value = sex.get(row["id"], "")
        if value:
            row["sex"] = {"f": "F", "female": "F", "m": "M", "male": "M"}.get(value.casefold(), value)
    return data


def _owned(name: str) -> bool:
    return (name in ROUTES or name in OPTIONAL_ROUTES or name in DATA_FILES or name in {f"assets/{asset}" for asset in ASSETS}
            or bool(re.fullmatch(r"(?:people/p|studies/s|places/pl)-[0-9a-f]{64}\.html|(?:findings|catalogue|sources|studies)/page-[1-9][0-9]*\.html"
                                 r"|timeline/(?:[1-9][0-9]*0s|undated)\.html|places/[a-z0-9-]+\.html|sources/type-[a-z0-9-]+\.html", name)))


def _slug(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.casefold()).strip("-")


def _decade(row: dict[str, Any]) -> str:
    """The timeline page an event is on: ``1870s``, or ``undated`` without a year."""
    year = year_of(row.get("date"))
    return f"{year // 10 * 10}s" if year else "undated"


def _base_url(config: ProjectConfig) -> str | None:
    site = config.raw.get("site", {})
    value = site.get("base_url") if isinstance(site, dict) else None
    if value is None:
        return None
    url = _url(value)
    if not url:
        raise ValueError("site.base_url must be an absolute http(s) URL without credentials")
    return url.rstrip("/") + "/"


def build_site(case: ResearchCase, config: ProjectConfig, directory: Path) -> dict[str, Path]:
    """Build portable HTML and data, removing only previously generated stale pages.

    The public export gate decides all record eligibility. The original case is
    deliberately never consulted again after that call. No network is used.
    """
    project = exports.project_for_public_export(case, config)
    base_url = _base_url(config)
    contact = site_contact(config.raw.get("site", {}))
    routes = {**ROUTES, **({"corrections.html": OPTIONAL_ROUTES["corrections.html"]} if contact.keys() & {"email", "url"} else {})}
    directory = Path(directory)
    people = {p["id"]: p for p in project["people"]}
    # Only the surname groups some public person is recorded under are
    # published: a group listed for withheld people alone stays out of the data.
    name_variants = config.name_variants
    public_groups = {name_variants.get(str(n["surname"]).casefold()) for p in people.values() for n in p.get("names", []) if n.get("surname")}
    name_variants = {spelling: canonical for spelling, canonical in name_variants.items() if canonical in public_groups}
    places = {p["id"]: p for p in project["places"]}
    sources = {s["id"]: s for s in project["sources"]}
    citations = {c["id"]: c for c in project["citations"]}
    people_urls = {pid: "people/p-" + _key(pid) + ".html" for pid in people}
    # The address each public person's former id had, after a merge or an id
    # change, and the page it now leads to. A withheld person's former ids are
    # never seen here: the person is not in the projection.
    moved = {"people/p-" + _key(former) + ".html": people_urls[pid] for pid, p in people.items() for former in p.get("former_ids", [])}
    studies = {s["id"]: s for s in project.get("studies", [])}
    study_urls = {sid: "studies/s-" + _key(sid) + ".html" for sid in studies}
    events_by_person: dict[str, list[dict[str, Any]]] = defaultdict(list)
    events_by_place: dict[str, list[dict[str, Any]]] = defaultdict(list)
    relationships_by_person: dict[str, list[dict[str, Any]]] = defaultdict(list)
    claims_by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    evidence_by_claim: dict[str, list[dict[str, Any]]] = defaultdict(list)
    citations_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    research_by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    parents_of: dict[str, list[dict[str, Any]]] = defaultdict(list)
    children_of: dict[str, list[dict[str, Any]]] = defaultdict(list)
    partners_of: dict[str, list[tuple[dict[str, Any], str]]] = defaultdict(list)
    siblings_of: dict[str, list[tuple[dict[str, Any], str]]] = defaultdict(list)
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
        kind = str(row["kind"]).casefold()
        if kind in PARENT_KINDS:
            parents_of[row["subject_id"]].append(row)
            children_of[row["object_id"]].append(row)
        elif kind in PARTNER_KINDS:
            partners_of[row["subject_id"]].append((row, row["object_id"]))
            partners_of[row["object_id"]].append((row, row["subject_id"]))
        elif kind in SIBLING_KINDS and row["subject_id"] != row["object_id"]:
            siblings_of[row["subject_id"]].append((row, row["object_id"]))
            siblings_of[row["object_id"]].append((row, row["subject_id"]))
    sex = {}
    for row in project["claims"]:
        claims_by_subject[row["subject_id"]].append(row)
        if row.get("predicate") == "sex" and row.get("status") != "rejected":
            sex.setdefault(row["subject_id"], str(row.get("value") or "").strip())
    for row in project["evidence"]:
        evidence_by_claim[row["claim_id"]].append(row)
    for row in project["citations"]:
        citations_by_source[row["source_id"]].append(row)
    # What each citation supports, for "Cited for" on its source: a claim cites
    # it directly or through an evidence assessment. Built once, not per source.
    claims_by_citation: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in project["claims"]:
        for cid in [*row.get("citation_ids", []), *(e["citation_id"] for e in evidence_by_claim[row["id"]])]:
            claims_by_citation[cid][row["id"]] = row
    findings_by_citation: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in project["findings"]:
        for cid in dict.fromkeys(row.get("citation_ids", [])):
            findings_by_citation[cid].append(row)
    relationships_by_claim: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in project["relationships"]:
        for cid in dict.fromkeys(row.get("claim_ids", [])):
            relationships_by_claim[cid].append(row)
    relationships_by_id = {r["id"]: r for r in project["relationships"]}
    events_by_id = {e["id"]: e for e in project["events"]}
    studies_by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in studies.values():
        for rid in dict.fromkeys([*row.get("related_ids", []), *(r for text in (row.get("summary"), row.get("rationale"), row.get("body"), row.get("conclusion")) for r in prose_references(text))]):
            studies_by_subject[rid].append(row)
        # A person the study groups is one it concerns, even when not in related_ids.
        for rid in dict.fromkeys(pid for g in row.get("groups", []) for pid in g.get("member_ids", [])):
            if not studies_by_subject[rid] or studies_by_subject[rid][-1] is not row:
                studies_by_subject[rid].append(row)
    for collection in ("questions", "findings", "hypotheses"):
        for row in project[collection]:
            for rid in set(row.get("related_ids", [])):
                research_by_subject[rid].append(row)
    # The findings that reassessed each relationship or claim, oldest first
    # (undated first, then in case order), as the latest-change check reads them.
    relationships_by_id = {r["id"]: r for r in project["relationships"]}
    claims_by_id = {c["id"]: c for c in project["claims"]}
    changes_of: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for row in sorted(project["findings"], key=lambda f: str(f.get("recorded_on") or "")):
        for change in row.get("changes", []):
            changes_of[change["record_id"]].append((row, change))
    # A long findings log keeps each finding on a stable archive page, numbered
    # from the earliest; on a large site that page, not the notebook, is its address.
    dated = sorted((f for f in project["findings"] if f.get("recorded_on")), key=lambda f: (f["recorded_on"], f["id"]), reverse=True)
    undated = [f for f in project["findings"] if not f.get("recorded_on")]
    archive_page = ({row["id"]: (len(dated) - 1 - index) // FINDINGS_PER_PAGE + 1 for index, row in enumerate(dated)}
                    if len(dated) > LATEST_FINDINGS else {})
    compact_findings = len(project["findings"]) > INLINE_LIMIT
    compact_people = len(people) > INLINE_LIMIT
    compact_relationships = len(project["relationships"]) > INLINE_LIMIT
    compact_claims = len(project["claims"]) > INLINE_LIMIT
    compact_events = len(project["events"]) > INLINE_LIMIT
    compact_places = len(project["places"]) > INLINE_LIMIT
    compact_sources = len(project["sources"]) > INLINE_LIMIT
    compact_studies = len(studies) > INLINE_LIMIT
    sources_ordered = sorted(sources, key=lambda sid: (str(sources[sid]["title"]).casefold(), sid))
    source_page_url = lambda n: "sources.html" if n == 1 else f"sources/page-{n}.html"
    source_pages = ({sid: source_page_url(index // SOURCES_PER_PAGE + 1) for index, sid in enumerate(sources_ordered)}
                    if compact_sources else {})
    # Places group by their broadest jurisdiction as written ("Town, County,
    # Country" -> "Country"); nothing is looked up or inferred. On a large site
    # each region has its own pages.
    regions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in project["places"]:
        parts = [part.strip() for part in str(p["name"]).split(",") if part.strip()]
        regions[parts[-1] if len(parts) > 1 else UNPLACED_REGION].append(p)
    for members in regions.values():
        members.sort(key=lambda row: (str(row["name"]).casefold(), row["id"]))
    region_order = sorted(regions, key=lambda r: (r == UNPLACED_REGION, -len(regions[r]), r.casefold()))
    region_pages: dict[str, list[str]] = {}
    place_pages: dict[str, str] = {}
    if compact_places:
        used: set[str] = set()
        for region in region_order:
            slug = "other" if region == UNPLACED_REGION else _slug(region) or "region"
            if slug in used:
                slug = f"{slug}-{_key(region)[:8]}"
            used.add(slug)
            members = regions[region]
            region_pages[region] = [f"places/{slug}.html" if n == 0 else f"places/{slug}--{n + 1}.html"
                                    for n in range(0, max(1, -(-len(members) // PLACES_PER_PAGE)))]
            for index, row in enumerate(members):
                place_pages[row["id"]] = region_pages[region][index // PLACES_PER_PAGE]
    # A place with a public event or a sub-place (``parent_id``) has a page of
    # its own, named from its id like a person's so its address never moves.
    # Other places keep only their entry on the places or region page.
    sub_places: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in project["places"]:
        if p.get("parent_id") in places and p["parent_id"] != p["id"]:
            sub_places[p["parent_id"]].append(p)
    for members in sub_places.values():
        members.sort(key=lambda row: (str(row["name"]).casefold(), row["id"]))
    place_urls = {pid: "places/pl-" + _key(pid) + ".html" for pid in places if events_by_place.get(pid) or sub_places.get(pid)}
    # On a large site a relationship or claim lives on its subject's page,
    # where it is already shown with the same anchor.
    home_of = {}
    if compact_relationships:
        home_of.update({r["id"]: people_urls[r["subject_id"]] for r in project["relationships"] if r["subject_id"] in people_urls})
    if compact_claims:
        home_of.update({c["id"]: people_urls[c["subject_id"]] for c in project["claims"] if c["subject_id"] in people_urls})
        home_of.update({e["id"]: home_of[e["claim_id"]] for e in project["evidence"] if e["claim_id"] in home_of})
    record_routes: dict[str, str] = {}
    for collection, rows in project.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            route = people_urls.get(row["id"]) or study_urls.get(row["id"]) or place_urls.get(row["id"])
            if not route:
                route = {"events": "timeline.html", "places": "places.html", "sources": "sources.html", "citations": "sources.html", "relationships": "tree.html"}.get(collection, "research.html")
                route = home_of.get(row["id"], route)
                if collection == "events" and compact_events:
                    route = f"timeline/{_decade(row)}.html"
                if collection == "places" and compact_places:
                    route = place_pages[row["id"]]
                if collection in ("sources", "citations") and compact_sources:
                    route = source_pages[row["id"] if collection == "sources" else row["source_id"]]
                if collection == "findings" and compact_findings:
                    route = f"findings/page-{archive_page[row['id']]}.html" if row["id"] in archive_page else "findings.html"
                route += "#" + _anchor(row["id"])
            record_routes[row["id"]] = route
    # The research log: each search is listed, newest first (undated last), on
    # the dossier of every person it was made for, and is addressed on the first
    # of those. One made for no public person is addressed on research.html,
    # anchored only while it is among the newest listed there.
    searches_newest = sorted(project["searches"], key=lambda s: (str(s.get("searched_on") or ""), s["id"]), reverse=True)
    searches_by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in searches_newest:
        for rid in dict.fromkeys(row.get("related_ids", [])):
            searches_by_subject[rid].append(row)
    searches_logged = {row["id"] for row in searches_newest[:LATEST_SEARCHES]}
    for row in searches_newest:
        home = next((people_urls[rid] for rid in row.get("related_ids", []) if rid in people_urls), None)
        record_routes[row["id"]] = (home or "research.html") + ("#" + _anchor(row["id"]) if home or row["id"] in searches_logged else "")

    def person_name(pid: str) -> str:
        p = people.get(pid, {})
        return next((n["value"] for n in p.get("names", []) if n.get("value")), pid)

    def surname(pid: str) -> str:
        p = people.get(pid, {})
        return next((n["surname"] for n in p.get("names", []) if n.get("surname")), "")

    def canonical_surname(pid: str) -> str:
        """The surname a person is grouped and filtered under: [names.variants] folds other spellings into one."""
        recorded = surname(pid)
        return name_variants.get(recorded.casefold(), recorded)

    def lifespan(pid: str) -> str:
        """Recorded birth/death years, e.g. "b. 1840 – d. 1908"; approximate years keep "c."."""
        parts = []
        for kind, label in (("birth", "b."), ("death", "d.")):
            event = next((e for e in events_by_person[pid] if e["kind"] == kind and e.get("date")), None)
            year = year_of(event["date"]) if event else None
            if year:
                qualifier = re.match(r"\s*(ABOUT|ABT|EST|CAL|CIRCA|CA|C|BEF|BEFORE|AFT|AFTER|BET|FROM|INT)\b\.?", event["date"].upper())
                marker = {"BEF": "bef. ", "BEFORE": "bef. ", "AFT": "aft. ", "AFTER": "aft. "}.get(qualifier[1], "c. ") if qualifier else ""
                parts.append(f"{label} {marker}{year}")
        return " – ".join(parts)

    def ref(rid: str, prefix: str = "", label: str | None = None) -> str:
        title = label or person_name(rid)
        route = record_routes.get(rid)
        return f'<a href="{prefix}{_text(route)}">{_text(title)}</a>' if route else _text(title)

    def shift(change: dict[str, Any]) -> str:
        """E.g. "Possible → Documented", in the project's own grade wording where it has one."""
        after = assessment_label(change["after"], config.grades)
        return f'{assessment_label(change["before"], config.grades)} → {after}' if change.get("before") else f"Recorded as {after}"

    def change_notes(rid: str, prefix: str = "") -> str:
        """Beside a link or claim: each finding that changed its assessment, linked to that finding."""
        notes = []
        for finding, change in changes_of.get(rid, []):
            after = assessment_label(change["after"], config.grades)
            words = f'Changed from {assessment_label(change["before"], config.grades)} to {after}' if change.get("before") else f"Recorded as {after}"
            words += f', {finding["recorded_on"]}' if finding.get("recorded_on") else ""
            notes.append(f'<p class="meta assessment-change"><a href="{prefix}{_text(record_routes[finding["id"]])}">{_text(words)}</a></p>')
        return "".join(notes)

    def changed_label(rid: str) -> str:
        if rid in relationships_by_id:
            r = relationships_by_id[rid]
            return f'{person_name(r["subject_id"])} — {r["kind"]} → {person_name(r["object_id"])}'
        c = claims_by_id.get(rid, {})
        return f'{c.get("predicate", "")}: {c.get("value", "")}' if c else rid

    def empty(items: list[str], message: str = "No public records recorded.") -> str:
        return '<ul class="record-list">' + "".join(items) + "</ul>" if items else f'<p class="empty-state">{_text(message)}</p>'

    def metadata(row: dict[str, Any], prefix: str = "", *, relationship: bool = False) -> str:
        """A labelled badge linked to the guide; stored values stay in data attributes."""
        if not (relationship or row.get("status") or row.get("confidence")):
            return ""
        confidence = str(row.get("confidence") or "unknown")
        graded = grade_label(row, config.grades)
        if relationship:
            words = relationship_label(row, config.grades)
            anchor = f'grade-{row["grade"]}' if graded else "confidence-tree-link" if confidence == "unknown" else f"confidence-{confidence}"
        else:
            words = " · ".join(value for value in (status_label(row.get("status")) if row.get("status") else "",
                                                   graded or (confidence_label(row["confidence"]) if row.get("confidence") else "")) if value)
            anchor = (status_anchor(row["status"]) if row.get("status") and not row.get("confidence") else
                      f'grade-{row["grade"]}' if graded else f"confidence-{confidence}")
        stored = "".join(f' data-{name.replace("_", "-")}="{_text(row[name])}"' for name in ("status", "confidence", "grade", "tree_status") if row.get(name))
        return f' <a class="badge evidence-badge" href="{prefix}evidence.html#{_text(anchor)}"{stored}>{_text(words)}</a>'

    def record_quality(row: dict[str, Any], prefix: str = "") -> str:
        """A citation's stated form and information, each linked to its guide entry; stored values stay in data attributes."""
        # Plain links, styled as badges by the wrapping .record-quality: a source page lists a hundred citations.
        return " · ".join(f'<a href="{prefix}evidence.html#{_text(anchor)}" data-{name}="{_text(row[name])}">{_text(words)}</a>'
                          for name, anchor, words in quality_parts(row))

    def citation(row: dict[str, Any], prefix: str = "", *, canonical: bool = False) -> str:
        src = sources.get(row["source_id"], {})
        parts = [ref(row["source_id"], prefix, src.get("title", row["source_id"]))]
        if quality_parts(row):
            parts.append(f'<p class="record-quality">{record_quality(row, prefix)}</p>')
        for key in ("locator", "abstract", "quotation", "transcription", "accessed_on"):
            if row.get(key):
                parts.append(f'<p><strong>{_text(key.replace("_", " ").capitalize())}:</strong> {_text(row[key])}</p>')
        return ('<article id="' + _anchor(row["id"]) + '">' if canonical else "<article>") + "".join(parts) + "</article>"

    def record_link(cid: str, prefix: str = "") -> str:
        """A citation as its source title and locator, linked to the citation."""
        found = citations[cid]
        label = sources.get(found["source_id"], {}).get("title", found["source_id"])
        if found.get("locator"):
            label += f' ({found["locator"]})'
        return ref(cid, prefix, label)

    def finding_details(row: dict[str, Any], prefix: str = "") -> str:
        """A finding's type, stated limits and the records it rests on."""
        parts = []
        if row.get("limitations"):
            parts.append(f'<p class="finding-limitations"><strong>Limits:</strong> {_text(row["limitations"])}</p>')
        cited = [f"<li>{record_link(cid, prefix)}</li>" for cid in row.get("citation_ids", []) if cid in citations]
        if cited:
            parts.append('<p class="meta">Records:</p><ul class="finding-records">' + "".join(cited) + "</ul>")
        changed = [f'<li>{ref(c["record_id"], prefix, changed_label(c["record_id"]))} <span class="badge change" data-after="{_text(c["after"])}"'
                   + (f' data-before="{_text(c["before"])}"' if c.get("before") else "") + f'>{_text(shift(c))}</span>'
                   + (f' <span class="meta">{_text(c["note"])}</span>' if c.get("note") else "") + "</li>" for c in row.get("changes", [])]
        if changed:
            parts.append('<p class="meta">Changed:</p><ul class="finding-changes">' + "".join(changed) + "</ul>")
        return "".join(parts)

    def question_next(row: dict[str, Any], prefix: str = "") -> str:
        """An open question's plan; a blank says so rather than leaving the reader to guess."""
        if str(row.get("status", "open")).casefold() not in OUTSTANDING:
            return ""
        gap = f'<a class="not-identified" href="{prefix}evidence.html#not-yet-identified">Not yet identified</a>'
        return ('<dl class="question-next">' + "".join(f'<dt>{label}</dt><dd>{_text(row[key]) if row.get(key) else gap}</dd>'
                for key, label in (("resolves", "What would answer this"), ("next_record", "Next record to check"))) + '</dl>')

    def finding_kind(row: dict[str, Any]) -> str:
        return f' <span class="badge finding-kind" data-kind="{_text(row["kind"])}">{_text(str(row["kind"]).replace("-", " ").replace("_", " ").capitalize())}</span>' if row.get("kind") else ""

    def event(row: dict[str, Any], prefix: str = "", *, canonical: bool = True) -> str:
        place = places.get(row.get("place_id"), {})
        return (f'<li id="{_anchor(row["id"])}" data-event-id="{_text(row["id"])}">' if canonical else "<li>") + f'<strong>{_text(row.get("date") or "Date unknown")} · {_text(row["kind"])}</strong>' + (f' — {ref(place["id"], prefix, place["name"])}' if place else "") + (f'<p>{_text(row["description"])}</p>' if row.get("description") else "") + '<p>' + ", ".join(ref(pid, prefix) for pid in row.get("participant_ids", [])) + "</p></li>"

    def relationship(row: dict[str, Any], prefix: str = "") -> str:
        role = f' <span class="meta">({_text(row["pedigree"])})</span>' if row.get("pedigree") else ""
        return f'<li id="{_anchor(row["id"])}">{ref(row["subject_id"], prefix)} — {_text(row["kind"])}{role} → {ref(row["object_id"], prefix)}{metadata(row, prefix, relationship=True)}{change_notes(row["id"], prefix)}' + ("<p>Claims: " + ", ".join(ref(cid, prefix) for cid in row["claim_ids"]) + "</p>" if row.get("claim_ids") else "") + "</li>"

    def claim(row: dict[str, Any], prefix: str = "") -> str:
        supporting = evidence_by_claim[row["id"]]
        parts = [f'<article class="record-card card" id="{_anchor(row["id"])}"><h3>{_text(row["predicate"])}: {_text(row["value"])}</h3>{metadata(row, prefix)}{change_notes(row["id"], prefix)}', f'<p>Subject: {ref(row["subject_id"], prefix)}</p>']
        if row.get("rationale"):
            parts.append(f'<p>{_text(row["rationale"])}</p>')
        # One row per assessment, in the claim's citation order; a cited record
        # nobody has assessed yet still gets a row, so the gap is visible.
        cited = [cid for cid in row.get("citation_ids", []) if cid in citations]
        pairs = [(cid, e) for cid in cited for e in ([e for e in supporting if e["citation_id"] == cid] or [None])]
        pairs += [(e["citation_id"], e) for e in supporting if e["citation_id"] not in cited]
        rows = []
        for cid, e in pairs:
            found = citations.get(cid, {})
            record = ref(cid, prefix, sources.get(found.get("source_id"), {}).get("title", found.get("source_id", cid)))
            if found.get("locator"):
                record += f'<br><span class="meta">{_text(found["locator"])}</span>'
            if quality_parts(found):
                record += f'<br><span class="record-quality">{record_quality(found, prefix)}</span>'
            says = (_text(found["abstract"]) if found.get("abstract") else
                    f'<q>{_text(found.get("quotation") or found["transcription"])}</q>' if found.get("quotation") or found.get("transcription") else "—")
            assessed = (f'<strong>{"Supports" if e["supports"] else "Challenges"}</strong>: {_text(e["assessment"])}{metadata(e, prefix)}'
                        if e else '<span class="meta">Not yet assessed</span>')
            limit = _text(e["limitation"]) if e and e.get("limitation") else "—"
            rows.append((f'<tr id="{_anchor(e["id"])}">' if e else "<tr>") + f'<td data-label="Record">{record}</td><td data-label="What it says">{says}</td>'
                        f'<td data-label="Assessment">{assessed}</td><td data-label="Limitation">{limit}</td></tr>')
        parts.append('<div class="table-wrap"><table class="evidence-table"><caption>Records and assessments</caption><thead><tr><th scope="col">Record</th>'
                     '<th scope="col">What it says</th><th scope="col">Assessment</th><th scope="col">Limitation</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>"
                     if rows else '<p class="empty-state">No public records cited.</p>')
        return "".join(parts) + "</article>"

    def link_reason(row: dict[str, Any], prefix: str) -> str:
        """Why a family link is shown: its own rationale, else its first linked
        claim's, and the records those claims cite. Nothing is supplied for a blank."""
        linked = [claims_by_id[cid] for cid in row.get("claim_ids", []) if cid in claims_by_id]
        reason = row.get("rationale") or next((c["rationale"] for c in linked if c.get("rationale")), None)
        cited = list(dict.fromkeys(cid for c in linked for cid in [*c.get("citation_ids", []), *(e["citation_id"] for e in evidence_by_claim[c["id"]])]
                                   if cid in citations))
        more = len(cited) - 5
        return ((f'<p class="meta link-reason"><strong>Reason:</strong> {_text(reason)}</p>' if reason else "")
                + (f'<p class="meta link-records">Supporting records: ' + ", ".join(record_link(cid, prefix) for cid in cited[:5])
                   + (f" and {more:,} more" if more > 0 else "") + "</p>" if cited else ""))

    def person_item(pid: str, role: str, row: dict[str, Any] | None, prefix: str, extra: str = "") -> str:
        span = lifespan(pid)
        return (f'<li><span class="family-role">{_text(role)}</span> {ref(pid, prefix)}' + (f' <span class="meta">{_text(span)}</span>' if span else "")
                + (metadata(row, prefix, relationship=True) + change_notes(row["id"], prefix) + link_reason(row, prefix) if row else "") + extra + "</li>")

    def rejected(row: dict[str, Any]) -> bool:
        """A link assessed evidence contradicts: disproved, or a project grade counted as disproved.
        The family section, its competing-parents notice and the opening sentence all use this."""
        return row.get("confidence") == "disproved" or config.grades.get(str(row.get("grade")), {}).get("confidence") == "disproved"

    def kin(pid: str) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], str]], list[dict[str, Any]]]:
        """Parent, partner and child links in the order the family section lists them."""
        birth = lambda p: date_sort_key(next((e.get("date") for e in events_by_person[p] if e["kind"] == "birth"), None))
        return (sorted(parents_of[pid], key=lambda r: (person_name(r["object_id"]), r["id"])),
                sorted(partners_of[pid], key=lambda item: (person_name(item[1]), item[0]["id"])),
                sorted(children_of[pid], key=lambda r: (birth(r["subject_id"]), person_name(r["subject_id"]))))

    def family(pid: str) -> str:
        """Parents, partners, children and siblings, each with its own recorded label.
        Rejected links leave those lists for one list of their own, kept with their reasons."""
        prefix = "../"
        all_parents, all_partners, all_children = kin(pid)
        parents = [r for r in all_parents if not rejected(r)]
        set_apart = [person_item(r["object_id"], parent_role(r, sex.get(r["object_id"])), r, prefix) for r in all_parents if rejected(r)]
        sections = []
        items = [person_item(r["object_id"], parent_role(r, sex.get(r["object_id"])), r, prefix) for r in parents]
        by_birth = [r for r in parents if str(r.get("pedigree") or "birth") == "birth"]
        fathers = {r["object_id"] for r in by_birth if sex.get(r["object_id"], "").casefold() in ("m", "male")}
        mothers = {r["object_id"] for r in by_birth if sex.get(r["object_id"], "").casefold() in ("f", "female")}
        competing = ""
        if len(fathers) > 1 or len(mothers) > 1 or len({r["object_id"] for r in by_birth}) > 2:
            competing = ('<p class="note" data-competing-parents>Competing parent records: more parents are recorded than one person can have by birth. '
                         'Each link keeps its own label until research resolves it. <a href="../evidence.html#alternatives">About alternatives</a></p>')
        sections.append("<h3>Parents</h3>" + competing + empty(items, "No public parents recorded."))
        partner_items = []
        for row, other in all_partners:
            shared = [e for e in events_by_person[pid] if e["kind"] in FAMILY_EVENTS and other in e.get("participant_ids", [])]
            extra = "".join(f'<p class="meta">{_text(e["kind"].capitalize())}: {_text(e.get("date") or "date unknown")}' + (f' · {_text(places[e["place_id"]]["name"])}' if e.get("place_id") in places else "") + "</p>" for e in shared)
            (set_apart if rejected(row) else partner_items).append(person_item(other, "Spouse or partner", row, prefix, extra))
        sections.append("<h3>Spouses and partners</h3>" + empty(partner_items, "No public spouses or partners recorded."))
        child_items = []
        for r in all_children:
            (set_apart if rejected(r) else child_items).append(person_item(r["subject_id"], child_role(r, sex.get(r["subject_id"])), r, prefix))
        sections.append("<h3>Children</h3>" + empty(child_items, "No public children recorded."))
        siblings: dict[str, set[str]] = defaultdict(set)
        for parent in {r["object_id"] for r in parents}:
            for r in children_of[parent]:
                if r["subject_id"] != pid and not rejected(r):
                    siblings[r["subject_id"]].add(parent)
        # A recorded sibling link is symmetric like a partner link; a rejected
        # one is set apart with the other rejected links.
        recorded: dict[str, dict[str, Any]] = {}
        for row, other in sorted(siblings_of[pid], key=lambda item: item[0]["id"]):
            if rejected(row):
                half = "half" in str(row["kind"]).casefold() or "half" in str(row.get("pedigree") or "").casefold()
                set_apart.append(person_item(other, "Recorded half-sibling" if half else "Recorded sibling", row, prefix))
            else:
                recorded.setdefault(other, row)
        sibling_items = []
        for sibling in sorted(set(siblings) | set(recorded), key=lambda s: (date_sort_key(next((e.get("date") for e in events_by_person[s] if e["kind"] == "birth"), None)), person_name(s))):
            shared, row = siblings.get(sibling, set()), recorded.get(sibling)
            in_common = "two recorded parents in common" if len(shared) >= 2 else "shares a recorded parent"
            if row is None:
                role = f"Sibling ({in_common})" if len(shared) >= 2 else "Shares a recorded parent"
            else:
                half = "half" in str(row["kind"]).casefold() or "half" in str(row.get("pedigree") or "").casefold()
                role = (f"{'Half-sibling' if half else 'Sibling'} (recorded link; {in_common})" if shared
                        else "Recorded half-sibling" if half else "Recorded sibling")
            sibling_items.append(person_item(sibling, role, row, prefix))
        sections.append("<h3>Siblings</h3>" + empty(sibling_items, "No public siblings recorded."))
        if set_apart:
            sections.append('<h3>Rejected and superseded links</h3><p class="meta">Assessed evidence contradicts these links. '
                            'They are kept, with their reasons, so the reasoning stays visible.</p><ul class="record-list rejected-links">' + "".join(set_apart) + "</ul>")
        return '<section class="family-summary" aria-labelledby="family-heading"><h2 id="family-heading">Family</h2>' + "".join(sections) + "</section>"

    # A large site's person menus are filled by the script from the shared data.
    options = '<option value="">Choose a person</option>' + ("" if compact_people else "".join(f'<option value="{_text(pid)}">{_text(person_name(pid))}</option>' for pid in people))
    browse_people = (f'<p>All {len(people):,} people are listed in the <a href="catalogue.html">catalogue</a>; each has a page of their own.</p>'
                     if compact_people else empty([f'<li>{ref(pid)}</li>' for pid in people]))
    def catalogue_row(pid: str, prefix: str = "") -> str:
        summary = "; ".join(f'{e["kind"]}: {e.get("date") or "date unknown"}' for e in events_by_person[pid])
        span = lifespan(pid)
        return (f'<tr data-person-id="{_text(pid)}" data-surname="{_text(canonical_surname(pid))}" data-search-text="{_text(person_name(pid) + " " + pid + " " + summary)}"><td>{ref(pid, prefix)}'
                + (f'<br><span class="meta">{_text(span)}</span>' if span else "") + f'</td><td>{_text(surname(pid) or "—")}</td><td>{_text(summary or "No events recorded.")}</td><td>{_text(pid)}</td></tr>')

    def catalogue_table(pids: list[str], prefix: str = "") -> str:
        return ('<div class="table-wrap"><table><thead><tr><th>Person</th><th>Surname</th><th>Recorded events</th><th>Record ID</th></tr></thead><tbody>'
                + "".join(catalogue_row(pid, prefix) for pid in pids) + '</tbody></table></div>')

    pages: dict[str, str] = {}
    # Pages other than the fixed routes: (view, title).
    extra_titles: dict[str, tuple[str, str]] = {}
    open_questions = [q for q in project["questions"] if str(q.get("status", "open")).casefold() == "open"]
    counts = [(len(project["people"]), "people"), (len(project["events"]), "events"), (len(project["sources"]), "sources"), (len(open_questions), "open questions")]
    pages["index.html"] = '<p class="eyebrow">An evidence-led family history</p><h1>' + _text(config.name) + '</h1><p>Explore people, family connections and historical records. Claims, citations and evidence assessments remain distinct throughout this collection. <a href="evidence.html">How to read the evidence labels</a>.</p><div class="stats stat-grid">' + "".join(f'<div class="stat-card"><strong>{n}</strong><span>{label}</span></div>' for n, label in counts) + '</div><h2>Start exploring</h2><p><a class="button" href="catalogue.html">Browse the people</a> <a href="tree.html">Explore family connections</a></p><h2>Research findings</h2>' + empty([f'<li>{ref(f["id"], label=f["conclusion"])}{metadata(f)}</li>' for f in sorted(project["findings"], key=lambda f: (str(f.get("recorded_on") or ""), f["id"]), reverse=True)[:10]]) + (f'<p><a href="findings.html">All {len(project["findings"]):,} findings</a></p>' if len(project["findings"]) > 10 else "")
    catalogue_search = '<h1>People catalogue</h1><label>Search people <input type="search" data-search placeholder="Name, ID or event"></label><p id="site-status" role="status"></p>'
    if compact_people:
        # The first page is written out; the script searches and pages everyone
        # from the shared data, and each later page has its own address.
        ordered = sorted(people, key=lambda pid: (person_name(pid).casefold(), pid))
        chunks = [ordered[i:i + CATALOGUE_PER_PAGE] for i in range(0, len(ordered), CATALOGUE_PER_PAGE)]
        page_url = lambda n: "catalogue.html" if n == 1 else f"catalogue/page-{n}.html"

        def catalogue_pages(prefix: str, current: int) -> str:
            return ('<nav class="catalogue-pages" aria-label="Catalogue pages" data-catalogue-pages><h2>Browse by name</h2><ol>'
                    + "".join(f'<li><a href="{prefix}{page_url(n)}"' + (' aria-current="page"' if n == current else "")
                              + f'>{_text(person_name(chunk[0]))} – {_text(person_name(chunk[-1]))}</a></li>' for n, chunk in enumerate(chunks, 1))
                    + "</ol></nav>")
        pages["catalogue.html"] = (catalogue_search + f'<div data-catalogue data-total="{len(people)}">' + catalogue_table(chunks[0]) + '</div>'
                                   + catalogue_pages("", 1))
        for n, chunk in enumerate(chunks[1:], 2):
            pages[page_url(n)] = (f'<h1>People catalogue, page {n} of {len(chunks)}</h1><p>{len(people):,} people in name order. '
                                  '<a href="../catalogue.html">Search the catalogue</a>.</p>' + catalogue_table(chunk, "../") + catalogue_pages("../", n))
            extra_titles[page_url(n)] = ("people", f"People catalogue, page {n}")
    else:
        pages["catalogue.html"] = catalogue_search + '<div data-catalogue>' + (catalogue_table(list(people)) if people else '<p class="empty-state">No public people are available.</p>') + '</div>'
    pages["tree.html"] = '<h1>Family tree and branches</h1><p>Arrows follow the stored relationship direction; each label describes the recorded assessment, not proof. <a href="evidence.html">Reading the evidence</a>.</p><label>Explore from <select id="tree-root">' + options + '</select></label><div id="tree-output"></div><h2>Recorded family connections</h2>' + (
        f'<p>{len(project["relationships"]):,} recorded family connections. Each person\'s page lists their parents, partners, children and siblings with these labels, and <a href="branches.html">Families &amp; branches</a> groups them.</p>'
        if compact_relationships else empty([relationship(r) for r in project["relationships"]], "No public family connections recorded."))
    timeline_list = lambda rows, prefix="": empty([event(e, prefix) for e in rows], "No public dated events recorded.").replace('class="record-list"', 'class="record-list timeline"', 1)
    if compact_events:
        # One page per decade; an event keeps its page as others are added.
        by_decade: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in events_sorted:
            by_decade[_decade(row)].append(row)
        decades = sorted((d for d in by_decade if d != "undated"), key=lambda d: int(d[:-1])) + (["undated"] if "undated" in by_decade else [])
        label = lambda d: "Events without a recorded year" if d == "undated" else d
        centuries: dict[str, list[str]] = defaultdict(list)
        for d in decades:
            centuries["Without a year" if d == "undated" else f"{int(d[:-1]) // 100 * 100}s"].append(d)
        index = "".join(f'<h2>{_text(century)}</h2><ul class="decade-list">' + "".join(
            f'<li><a href="timeline/{d}.html">{_text(label(d))}</a> <span class="meta">{len(by_decade[d]):,} event{"" if len(by_decade[d]) == 1 else "s"}</span></li>'
            for d in members) + "</ul>" for century, members in centuries.items())
        pages["timeline.html"] = (f'<h1>Timeline</h1><p>Recorded dates are preserved, including approximate and incomplete dates. {len(events_sorted):,} events, one page per decade.</p>'
                                  f'<div data-timeline data-total="{len(events_sorted)}">' + index + '</div>')
        for n, d in enumerate(decades):
            steps = "".join(link for link in (
                f'<a href="{decades[n - 1]}.html">← {_text(label(decades[n - 1]))}</a>' if n else "",
                f'<a href="{decades[n + 1]}.html">{_text(label(decades[n + 1]))} →</a>' if n + 1 < len(decades) else "") if link)
            nav = f'<nav class="pagination" aria-label="Timeline decades"><div>{steps}</div></nav>'
            pages[f"timeline/{d}.html"] = (f'<h1>Timeline: {_text(label(d))}</h1><p>{len(by_decade[d]):,} event{"" if len(by_decade[d]) == 1 else "s"}. '
                                           'Recorded dates are preserved, including approximate and incomplete dates. <a href="../timeline.html">All decades</a>.</p>'
                                           + nav + timeline_list(by_decade[d], "../") + nav)
            extra_titles[f"timeline/{d}.html"] = ("timeline", f"Timeline: {label(d)}")
    else:
        pages["timeline.html"] = '<h1>Timeline</h1><p>Recorded dates are preserved, including approximate and incomplete dates.</p><div data-timeline>' + timeline_list(events_sorted) + '</div>'
    def place_item(p: dict[str, Any], prefix: str = "") -> str:
        coords = p.get("latitude") is not None and p.get("longitude") is not None
        details = f'{p["latitude"]}, {p["longitude"]}' if coords else "Coordinates not supplied"
        if coords and p.get("precision"):
            details += f' · located to {p["precision"]} level' if p["precision"] != "exact" else " · exact location"
        name = f'<a href="{prefix}{place_urls[p["id"]]}">{_text(p["name"])}</a>' if p["id"] in place_urls else _text(p["name"])
        return (f'<li id="{_anchor(p["id"])}"><h3>{name}</h3><p>{_text(details)}</p>'
                + empty([event(e, prefix, canonical=False) for e in events_by_place[p["id"]]], "No events linked to this place.") + '</li>')

    points, place_rows = [], []
    region_rows = []
    located_count = 0
    for region in region_order:
        members = regions[region]
        region_events = [e for p in members for e in events_by_place[p["id"]]]
        region_people = {pid for e in region_events for pid in e.get("participant_ids", []) if pid in people}
        located = sum(1 for p in members if p.get("latitude") is not None and p.get("longitude") is not None)
        located_count += located
        target = region_pages[region][0] if compact_places else "#" + _anchor("region:" + region)
        region_rows.append(f'<tr><td><a href="{target}">{_text(region)}</a></td><td>{len(members)}</td><td>{located}</td><td>{len(region_events)}</td><td>{len(region_people)}</td></tr>')
    if compact_places:
        # Each region has pages of its own; the map is drawn by the script from the shared data.
        for region in region_order:
            urls = region_pages[region]
            for n, url in enumerate(urls):
                chunk = regions[region][n * PLACES_PER_PAGE:(n + 1) * PLACES_PER_PAGE]
                nav = ('<nav class="pagination" aria-label="Pages for this region"><div>' + "".join(
                    f'<a href="{other.split("/")[1]}"' + (' aria-current="page"' if other == url else "") + f'>Page {i + 1}</a>' for i, other in enumerate(urls)) + "</div></nav>") if len(urls) > 1 else ""
                page_note = f", page {n + 1} of {len(urls)}" if len(urls) > 1 else ""
                pages[url] = (f'<h1>Places: {_text(region)}</h1><p>{len(regions[region]):,} place{"" if len(regions[region]) == 1 else "s"}{page_note}, '
                              'grouped by the last part of each place name as recorded. <a href="../places.html">All countries and regions</a>.</p>'
                              + nav + empty([place_item(p, "../") for p in chunk]) + nav)
                extra_titles[url] = ("map", f"Places: {region}" + (f", page {n + 1}" if n else ""))
        located_note = (f'<p>{located_count:,} of {len(project["places"]):,} places have supplied coordinates. The map needs JavaScript; '
                        'each region\'s page lists the coordinates.</p>' if located_count else "<p>No coordinates supplied.</p>")
        map_block = f'<div id="map-output">{located_note}</div>'
    else:
        for region in region_order:
            items = []
            for p in regions[region]:
                if p.get("latitude") is not None and p.get("longitude") is not None:
                    x, y = (p["longitude"] + 180) * 960 / 360, (90 - p["latitude"]) * 480 / 180
                    broad = p.get("precision") in BROAD_PRECISIONS
                    points.append(f'<a href="#{_anchor(p["id"])}"><circle cx="{x:.3f}" cy="{y:.3f}" r="{9 if broad else 5}"' + (' class="broad"' if broad else "") + f'><title>{_text(p["name"])}</title></circle></a>')
                items.append(place_item(p))
            place_rows.append(f'<section class="place-region" id="{_anchor("region:" + region)}"><h2>{_text(region)}</h2>' + empty(items) + '</section>')
        map_block = ('<div id="map-output"><svg class="place-map" viewBox="0 0 960 480" role="img" aria-label="Places with supplied coordinates"><rect width="960" height="480" fill="#e8efec"/><image href="assets/world.svg" width="960" height="480"/><path d="M0 240H960M480 0V480" stroke="#a8b9af"/>'
                     + "".join(points) + '</svg></div>' + ("<p>No coordinates supplied.</p>" if not points else ""))
    summary_table = ('<h2>By country or region</h2><p class="meta">Grouped by the last part of each place name as recorded.</p><div class="table-wrap"><table><thead><tr><th>Country or region</th><th>Places</th><th>With coordinates</th><th>Events</th><th>People</th></tr></thead><tbody>'
                     + "".join(region_rows) + '</tbody></table></div>') if len(region_rows) > 1 or compact_places else ""
    pages["places.html"] = ('<h1>Places</h1><p>This offline coordinate overview uses supplied coordinates only. No geocoding or external map service is used. Basemap: <a href="https://www.naturalearthdata.com/">Natural Earth</a> (public domain).</p>'
                            + map_block + summary_table + ("" if compact_places else "".join(place_rows) if place_rows else empty([])))
    def cited_for(sid: str) -> tuple[dict[str, list[str]], list[dict[str, Any]], list[dict[str, Any]]]:
        """The public people (with claim predicates), findings and family links resting on a source's citations."""
        claimed: dict[str, dict[str, Any]] = {}
        found: dict[str, dict[str, Any]] = {}
        for c in citations_by_source[sid]:
            claimed.update(claims_by_citation[c["id"]])
            found.update((f["id"], f) for f in findings_by_citation[c["id"]])
        who: dict[str, dict[str, None]] = defaultdict(dict)
        links: dict[str, dict[str, Any]] = {}
        for row in claimed.values():
            if row.get("predicate") == "sex":  # never listed as a claim on the site either
                continue
            subject = row["subject_id"]
            # A claim about an event is shown on its people's pages, so it is cited for them.
            if subject in events_by_id:
                subjects = set(events_by_id[subject].get("participant_ids", [])) | event_owners[subject]
            else:
                subjects = {subject}
            for pid in subjects & people.keys():
                who[pid][str(row["predicate"])] = None
            for rel in [*relationships_by_claim[row["id"]], *([relationships_by_id[subject]] if subject in relationships_by_id else [])]:
                links[rel["id"]] = rel
        ordered = sorted(who, key=lambda pid: (person_name(pid).casefold(), pid))
        return ({pid: list(who[pid]) for pid in ordered}, list(found.values()),
                sorted(links.values(), key=lambda r: (person_name(r["subject_id"]).casefold(), r["id"])))

    support = {sid: cited_for(sid) for sid in sources}

    def capped(items: list[str], noun: str) -> str:
        # A source cited hundreds of times stays short; each person's page has the rest.
        more = len(items) - CITED_FOR_LIMIT
        return ('<ul>' + "".join(items[:CITED_FOR_LIMIT]) + "</ul>"
                + (f'<p class="meta">and {more:,} more {noun}</p>' if more > 0 else ""))

    def source_card(src: dict[str, Any], prefix: str = "", level: int = 2) -> str:
        link = _url(src.get("url"))
        fields = "".join(f'<p><strong>{_text(k.replace("_", " ").capitalize())}:</strong> {_text(src[k])}</p>' for k in ("author", "publication", "source_type", "repository", "access_note", "licence") if src.get(k))
        who, found, links = support[src["id"]]
        uses = []
        if who:
            uses.append("<dt>People</dt><dd>" + capped([f'<li>{ref(pid, prefix)} <span class="meta">— {_text(", ".join(predicates))}</span></li>' for pid, predicates in who.items()], "people") + "</dd>")
        if found:
            uses.append("<dt>Findings</dt><dd>" + capped([f'<li>{ref(f["id"], prefix, f["conclusion"])}</li>' for f in found], "findings") + "</dd>")
        if links:
            uses.append("<dt>Family links</dt><dd>" + capped([f'<li>{ref(r["id"], prefix, person_name(r["subject_id"]) + " — " + str(r["kind"]) + " → " + person_name(r["object_id"]))}</li>' for r in links], "family links") + "</dd>")
        sub = f"h{level + 1}"
        return (f'<article class="record-card card" data-source-id="{_text(src["id"])}" id="{_anchor(src["id"])}"><h{level}>{_text(src["title"])}</h{level}>{fields}' + (f'<p><a href="{_text(link)}" rel="noreferrer">Open original source</a></p>' if link else "")
                + (f'<{sub}>Cited for</{sub}><dl class="cited-for">' + "".join(uses) + "</dl>" if uses else "")
                + f'<{sub}>Citations</{sub}>' + empty(["<li>" + citation(c, prefix, canonical=True) + "</li>" for c in citations_by_source[src["id"]]]) + '</article>')

    # Sources by record type, as recorded in ``source_type``. Types written in
    # different styles ("Parish register", "parish-register") are one type, and
    # [source_types.<key>] in genealogy.toml may give a type a label and a caution.
    type_wording = {_slug(key): value for key, value in config.source_types.items()}
    by_type: dict[str, list[str]] = defaultdict(list)
    for sid in (sources_ordered if compact_sources else sources):
        by_type[_slug(str(sources[sid].get("source_type") or "")) or "unknown"].append(sid)
    type_order = sorted(by_type, key=lambda t: (-len(by_type[t]), t))

    def type_label(slug: str) -> str:
        if type_wording.get(slug, {}).get("label"):
            return type_wording[slug]["label"]
        raw = Counter(str(sources[sid].get("source_type") or "unknown") for sid in by_type[slug]).most_common(1)[0][0]
        return raw[:1].upper() + raw[1:]

    def type_note(slug: str) -> str:
        note = type_wording.get(slug, {}).get("note")
        return f'<p class="note source-type-note"><strong>Reading these records:</strong> {_text(note)}</p>' if note else ""

    type_pages = {slug: [f"sources/type-{slug}.html" if n == 0 else f"sources/type-{slug}--{n + 1}.html"
                         for n in range(-(-len(by_type[slug]) // SOURCES_PER_PAGE))] for slug in type_order} if compact_sources else {}
    grouped = compact_sources or len(by_type) > 1 or any(slug in type_wording for slug in by_type)
    type_rows = []
    for slug in type_order:
        members = by_type[slug]
        cited_people = {pid for sid in members for pid in support[sid][0]}
        target = type_pages[slug][0] if compact_sources else f"#type-{slug}"
        type_rows.append(f'<tr><td><a href="{target}">{_text(type_label(slug))}</a></td><td>{len(members):,}</td>'
                         f'<td>{sum(len(citations_by_source[sid]) for sid in members):,}</td><td>{len(cited_people):,}</td></tr>')
    type_table = ('<h2>By record type</h2><p class="meta">Grouped by each source\'s recorded type. People cited: public people with a claim resting on the type\'s citations.</p>'
                  '<div class="table-wrap"><table><thead><tr><th>Record type</th><th>Sources</th><th>Citations</th><th>People cited</th></tr></thead><tbody>'
                  + "".join(type_rows) + '</tbody></table></div>') if grouped and sources else ""
    sources_intro = '<h1>Sources and citations</h1><p>Consult original records when assessing a claim. A citation identifies the specific record or passage. Each source lists the people, findings and family links its citations support.</p>' + type_table
    if compact_sources:
        # The first page is written out; the script searches every source from the shared data.
        chunks = [sources_ordered[i:i + SOURCES_PER_PAGE] for i in range(0, len(sources_ordered), SOURCES_PER_PAGE)]

        def source_page_nav(prefix: str, current: int) -> str:
            return ('<nav class="catalogue-pages" aria-label="Source pages" data-source-pages><h2>Browse by title</h2><ol>'
                    + "".join(f'<li><a href="{prefix}{source_page_url(n)}"' + (' aria-current="page"' if n == current else "")
                              + f'>{_text(sources[chunk[0]]["title"])} – {_text(sources[chunk[-1]]["title"])}</a></li>' for n, chunk in enumerate(chunks, 1))
                    + "</ol></nav>")
        pages["sources.html"] = (sources_intro + f'<div data-sources data-total="{len(sources)}">' + "".join(source_card(sources[sid]) for sid in chunks[0]) + '</div>'
                                 + source_page_nav("", 1))
        for n, chunk in enumerate(chunks[1:], 2):
            pages[source_page_url(n)] = (f'<h1>Sources and citations, page {n} of {len(chunks)}</h1><p>{len(sources):,} sources in title order. '
                                         '<a href="../sources.html">Search the sources</a>.</p>' + "".join(source_card(sources[sid], "../") for sid in chunk) + source_page_nav("../", n))
            extra_titles[source_page_url(n)] = ("sources", f"Sources, page {n}")
        # Each record type has pages of its own, in title order, 100 sources to a page.
        for slug, urls in type_pages.items():
            label = type_label(slug)
            for n, url in enumerate(urls):
                chunk = by_type[slug][n * SOURCES_PER_PAGE:(n + 1) * SOURCES_PER_PAGE]
                nav = ('<nav class="pagination" aria-label="Pages for this record type"><div>' + "".join(
                    f'<a href="{other.split("/")[1]}"' + (' aria-current="page"' if other == url else "") + f'>Page {i + 1}</a>' for i, other in enumerate(urls)) + "</div></nav>") if len(urls) > 1 else ""
                page_note = f", page {n + 1} of {len(urls)}" if len(urls) > 1 else ""
                pages[url] = (f'<h1>Sources: {_text(label)}</h1>' + type_note(slug)
                              + f'<p>{len(by_type[slug]):,} source{"" if len(by_type[slug]) == 1 else "s"} of this type{page_note}, in title order. <a href="../sources.html">All sources and record types</a>.</p>'
                              + nav + "".join(source_card(sources[sid], "../") for sid in chunk) + nav)
                extra_titles[url] = ("sources", f"Sources: {label}" + (f", page {n + 1}" if n else ""))
    elif grouped:
        pages["sources.html"] = sources_intro + '<div data-sources>' + "".join(
            f'<section class="source-type" id="type-{slug}" data-source-type="{_text(slug)}"><h2>{_text(type_label(slug))}</h2>' + type_note(slug)
            + "".join(source_card(sources[sid], level=3) for sid in by_type[slug]) + '</section>' for slug in type_order) + '</div>'
    else:
        pages["sources.html"] = sources_intro + '<div data-sources>' + ("".join(source_card(src) for src in sources.values()) or '<p class="empty-state">No public sources recorded.</p>') + '</div>'
    research = ['<h1>Research notebook</h1><p>Claims and their evidence first, then the work still outstanding: hypotheses, open questions and draft or reviewed findings. <a href="evidence.html">Reading the evidence</a>.</p><h2>Claims</h2>', (
        f'<p>{len(project["claims"]):,} claims. Each is shown, with its citations and evidence, on the page of the person it concerns.</p>'
        + "".join(claim(c) for c in project["claims"] if c.get("predicate") != "sex" and c["id"] not in home_of)
        if compact_claims else "".join(claim(c) for c in project["claims"] if c.get("predicate") != "sex") or '<p>No public claims recorded.</p>')]
    for collection, heading, field in (("hypotheses", "Hypotheses", "statement"), ("questions", "Research questions", "question"), ("findings", "Findings", "conclusion")):
        rows = sorted(project[collection], key=lambda r: (str(r.get("status", "open")).casefold() not in OUTSTANDING, r["id"]))
        outstanding = sum(str(r.get("status", "open")).casefold() in OUTSTANDING for r in rows)
        if collection == "findings" and compact_findings:
            # The findings log and its archive hold every finding; the notebook keeps the open work.
            research.append(f'<h2>{heading}</h2><p class="result-count">{outstanding} of {len(rows):,} open or in draft. All findings are in the <a href="findings.html">findings log</a>.</p>'
                            + empty([f'<li data-status="{_text(r.get("status", ""))}">{ref(r["id"], label=r[field])}{metadata(r)}</li>' for r in rows if str(r.get("status", "open")).casefold() in OUTSTANDING], "No open or draft findings."))
            continue
        research.append(f'<h2>{heading}</h2>' + (f'<p class="result-count">{outstanding} of {len(rows)} open or in draft</p>' if rows else "") + empty([f'<li id="{_anchor(r["id"])}" data-status="{_text(r.get("status", ""))}"><h3>{_text(r[field])}</h3>{metadata(r)}{finding_kind(r) if collection == "findings" else ""}{finding_details(r) if collection == "findings" else ""}{question_next(r) if collection == "questions" else ""}<p>' + ", ".join(ref(rid) for rid in r.get("related_ids", [])) + '</p><p>' + ", ".join(ref(eid, label="Evidence assessment") for eid in r.get("evidence_ids", [])) + '</p></li>' for r in rows]))
    pages["research.html"] = "".join(research)
    for route, heading, hook in (("compare.html", "Compare people", "compare"), ("connections.html", "Find a connection", "connection")):
        pages[route] = f'<h1>{heading}</h1><p>Select two people to explore this public collection. Interactive results require JavaScript.</p><div class="tool-controls"><label>First person <select data-{hook}-a>{options}</select></label><label>Second person <select data-{hook}-b>{options}</select></label></div><div id="{hook}-result" role="status"></div><h2>Browse dossiers</h2>' + browse_people
    def record_label(rid: str) -> str:
        if rid in people:
            return person_name(rid)
        if rid in studies:
            return studies[rid]["title"]
        for collection, field in (("places", "name"), ("sources", "title"), ("findings", "conclusion"), ("questions", "question"), ("hypotheses", "statement")):
            row = next((r for r in project[collection] if r["id"] == rid), None) if rid in record_routes else None
            if row:
                text = str(row[field])
                return text if len(text) <= 90 else text[:87].rstrip() + "…"
        return "record"

    def prose(text: str | None, prefix: str = "") -> str:
        return render_prose(text, lambda rid: (prefix + record_routes[rid], record_label(rid)) if rid in record_routes else None, heading_offset=2)

    def subject_item(rid: str, prefix: str) -> str:
        span = lifespan(rid) if rid in people else ""
        return f'<li>{ref(rid, prefix, record_label(rid))}' + (f' <span class="meta">{_text(span)}</span>' if span else "") + "</li>"

    def study_meta(row: dict[str, Any], prefix: str = "") -> str:
        parts = [f'<span class="badge" data-status="{_text(row.get("status", ""))}">{_text(status_label(row.get("status")) or "Draft")}</span>']
        if row.get("updated_on"):
            parts.append(f'<span class="meta">Updated {_text(row["updated_on"])}</span>')
        return " ".join(parts)

    # Studies: a written account with its rationale, conclusion and linked subjects.
    def study_card(sid: str, prefix: str = "") -> str:
        row = studies[sid]
        subjects = [rid for rid in row.get("related_ids", []) if rid in record_routes]
        return (f'<article class="card study-card" data-study-id="{_text(sid)}"><h2><a href="{prefix}{study_urls[sid]}">{_text(row["title"])}</a></h2><p>{study_meta(row, prefix)}</p>'
                + (f'<p>{_text(row["summary"])}</p>' if row.get("summary") else "")
                + f'<p class="meta">{len([r for r in subjects if r in people])} people · {len(subjects)} linked records</p></article>')

    studies_newest = sorted(studies, key=lambda sid: (str(studies[sid].get("updated_on") or ""), studies[sid]["title"]), reverse=True)
    studies_intro = '<h1>Studies</h1><p>Written research accounts: why each question was investigated, what the records show and the current conclusion. Each study links the people and records it concerns, and their pages link back.</p>'
    if compact_studies:
        # The studies page opens with the most recently updated; the script
        # searches every study from the shared data. The title pages start at
        # page 1, because the studies page itself is in date order, not title order.
        by_title = sorted(studies, key=lambda sid: (str(studies[sid]["title"]).casefold(), sid))
        study_chunks = [by_title[i:i + STUDIES_PER_PAGE] for i in range(0, len(by_title), STUDIES_PER_PAGE)]
        study_page_url = lambda n: f"studies/page-{n}.html"

        def study_page_nav(prefix: str, current: int) -> str:
            return ('<nav class="catalogue-pages" aria-label="Study pages" data-study-pages><h2>Browse by title</h2><ol>'
                    + "".join(f'<li><a href="{prefix}{study_page_url(n)}"' + (' aria-current="page"' if n == current else "")
                              + f'>{_text(studies[chunk[0]]["title"])} – {_text(studies[chunk[-1]]["title"])}</a></li>' for n, chunk in enumerate(study_chunks, 1))
                    + "</ol></nav>")
        pages["studies.html"] = (studies_intro + f'<p>The {STUDIES_PER_PAGE} most recently updated of {len(studies):,} studies. Every study is listed by title on the pages below.</p>'
                                 + f'<div class="card-grid" data-studies data-total="{len(studies)}">' + "".join(study_card(sid) for sid in studies_newest[:STUDIES_PER_PAGE]) + '</div>'
                                 + study_page_nav("", 0))
        for n, chunk in enumerate(study_chunks, 1):
            pages[study_page_url(n)] = (f'<h1>Studies by title, page {n} of {len(study_chunks)}</h1><p>{len(studies):,} studies in title order. '
                                        '<a href="../studies.html">Search the studies</a>.</p><div class="card-grid">' + "".join(study_card(sid, "../") for sid in chunk) + '</div>'
                                        + study_page_nav("../", n))
            extra_titles[study_page_url(n)] = ("studies", f"Studies by title, page {n}")
    else:
        pages["studies.html"] = studies_intro + ('<div class="card-grid" data-studies>' + "".join(study_card(sid) for sid in studies_newest) + '</div>' if studies else '<p class="empty-state">No public studies have been written yet. A tree export cannot supply them; add a <code>Study</code> record to the research case.</p>')

    def kind_class(kind: str) -> str:
        kind = str(kind).casefold()
        return ("k-begin" if kind in ("birth", "baptism", "christening") else "k-end" if kind in ("death", "burial", "cremation")
                else "k-union" if kind in FAMILY_EVENTS else "k-other")

    def event_line(e: dict[str, Any]) -> str:
        """E.g. "about 1850 · birth · Invented Parish": the date as recorded, not the year it is drawn at."""
        place = places.get(e.get("place_id"), {}).get("name")
        return " · ".join(str(part) for part in (e.get("date"), e["kind"], place) if part)

    def chronology(row: dict[str, Any], prefix: str) -> str:
        """A static drawing of a study's people over time: a lane per person, a marker per dated event.

        Only public records reach here; events without a year are counted, not placed.
        """
        linked = list(dict.fromkeys(row.get("related_ids", [])))
        lanes: list[tuple[str | None, list[dict[str, Any]]]] = [(rid, events_by_person[rid]) for rid in linked if rid in people]
        covered = {e["id"] for _, evs in lanes for e in evs}
        # An event linked to the study whose people are not in it still belongs on the drawing.
        other = sorted((events_by_id[rid] for rid in linked if rid in events_by_id and rid not in covered), key=lambda e: (date_sort_key(e.get("date")), e["id"]))
        if other:
            lanes.append((None, other))
        undated = {e["id"] for _, evs in lanes for e in evs if not year_of(e.get("date"))}
        lanes = [(pid, dated) for pid, evs in lanes if (dated := [(y, e) for e in evs if (y := year_of(e.get("date")))])]
        if len({e["id"] for _, dated in lanes for _, e in dated}) < 2:
            return ""
        lanes.sort(key=lambda lane: (lane[0] is None, min(y for y, _ in lane[1]), person_name(lane[0]).casefold() if lane[0] else "", lane[0] or ""))
        width, left, right, lane_h, top = 760, 190, 744, 26, 8

        def scale(chosen: list[tuple[str | None, list[tuple[int, dict[str, Any]]]]]) -> tuple[int, int, int, int, Any]:
            """The data's first and last years, the axis padded to whole decades, and the year-to-x mapping."""
            first, last = min(y for _, d in chosen for y, _ in d), max(y for _, d in chosen for y, _ in d)
            lo, hi = first // 10 * 10, last // 10 * 10 + 10
            return first, last, lo, hi, lambda year: left + (right - left) * (year - lo) / (hi - lo)

        def draw(chosen: list[tuple[str | None, list[tuple[int, dict[str, Any]]]]]) -> tuple[list[str], list[str]]:
            x = scale(chosen)[4]
            marks, names = [], []
            for i, (pid, dated) in enumerate(chosen):
                y = top + i * lane_h + lane_h // 2
                years = [year for year, _ in dated]
                born = next((year for year, e in dated if str(e["kind"]).casefold() == "birth"), None) if pid else None
                died = next((year for year, e in dated if str(e["kind"]).casefold() == "death"), None) if pid else None
                start, end = born or min(years), died or max(years)
                lane = f'<path class="life" d="M{x(start):.1f} {y}H{x(end):.1f}"/>'
                at: dict[int, list[dict[str, Any]]] = defaultdict(list)
                for year, e in dated:
                    at[year].append(e)
                # Events in one year would sit on one spot: one marker names them all.
                lane += "".join(f'<circle class="{kind_class(es[0]["kind"])}" cx="{x(year):.1f}" cy="{y}" r="4.5"><title>{_text("; ".join(event_line(e) for e in es))}</title></circle>'
                                for year, es in at.items())
                marks.append(lane)
                label = person_name(pid) if pid else "Other linked events"
                short = label if len(label) <= 27 else label[:26].rstrip() + "…"
                name = f'<text x="{left - 12}" y="{y + 4}" text-anchor="end">{_text(short)}</text>'
                names.append(f'<a href="{prefix}{_text(record_routes[pid])}">' + (f'<title>{_text(label)}</title>' if short != label else "") + name + "</a>"
                             if pid in record_routes else name)
            return marks, names

        chosen = lanes[:CHRONOLOGY_LANES]
        marks, names = draw(chosen)
        size, keep = 0, 0
        for mark, name in zip(marks, names):
            size += len(mark) + len(name)
            if keep and size > CHRONOLOGY_BYTES:
                break
            keep += 1
        if keep < len(chosen):
            chosen = chosen[:keep]
            marks, names = draw(chosen)
        first, last, lo, hi, x = scale(chosen)
        step = next((s for s in (10, 20, 50, 100, 200, 500) if (hi - lo) / s <= 12), 1000)
        bottom = top + len(chosen) * lane_h
        ticks = list(range(lo, hi + 1, step))
        axis = (f'<path class="grid" d="' + "".join(f'M{x(t):.1f} {top}V{bottom}' for t in ticks) + '"/>'
                + "".join(f'<text x="{x(t):.1f}" y="{bottom + 18}" text-anchor="middle">{t}</text>' for t in ticks))
        persons = sum(1 for pid, _ in chosen if pid)
        span = f"{lo}s" if first // 10 == last // 10 else f"{lo}s–{last // 10 * 10}s"
        summary = f'Chronology of {persons} {"person" if persons == 1 else "people"}, {span}' if persons else f"Chronology of linked events, {span}"
        svg = (f'<svg class="chronology-chart" viewBox="0 0 {width} {bottom + 28}"><g role="img" aria-label="{_text(summary)}">{axis}{"".join(marks)}</g>'
               f'<g class="lane-names">{"".join(names)}</g></svg>')
        notes = []
        if undated:
            notes.append(f'{len(undated)} undated event{" is" if len(undated) == 1 else "s are"} not shown.')
        hidden = sum(1 for pid, _ in lanes[len(chosen):] if pid)
        if hidden:
            notes.append(f'And {hidden} more {"person is" if hidden == 1 else "people are"} not drawn.')
        key = "".join(f'<span class="chronology-key"><i class="{cls}"></i>{words}</span>' for cls, words in
                      (("k-begin", "birth or baptism"), ("k-union", "marriage"), ("k-end", "death or burial"), ("k-other", "other events")))
        text = "".join(f'<li>{ref(pid, prefix) if pid else "Other linked events"}<ul>' + "".join(f"<li>{_text(event_line(e))}</li>" for _, e in dated) + "</ul></li>"
                       for pid, dated in chosen)
        return ('<h2>Chronology</h2><figure class="chronology"><div class="chronology-plot">' + svg + '</div><figcaption>'
                'Each line runs from a recorded birth to a recorded death, otherwise from the first to the last dated event. '
                f'Approximate dates are drawn at their recorded year.<span class="chronology-legend">{key}</span></figcaption></figure>'
                + (f'<p class="meta chronology-notes">{" ".join(notes)}</p>' if notes else "")
                + f'<details class="chronology-text"><summary>{_text(summary)}, as text</summary><ol>{text}</ol></details>')

    evidence_by_id = {e["id"]: e for e in project["evidence"]}

    def study_groups(row: dict[str, Any], prefix: str) -> str:
        """The households or groups a study compares, a drawing of how they connect, and the records still to inspect.

        A published study's members and link evidence are all public: the
        projection withholds a study that names anything else.
        """
        groups = [g for g in row.get("groups", []) if isinstance(g, dict)]
        anchor = {g["id"]: "group-" + _key(g["id"])[:16] for g in groups}
        title = {g["id"]: str(g["title"]) for g in groups}
        out = ""
        if groups:
            cards = []
            for g in groups:
                members = [pid for pid in dict.fromkeys(g.get("member_ids", [])) if pid in people]
                items = [f'<li>{ref(pid, prefix)}' + (f' <span class="meta">{_text(lifespan(pid))}</span>' if lifespan(pid) else "") + "</li>" for pid in members]
                cards.append(f'<section class="study-group card" id="{anchor[g["id"]]}"><h3>{_text(g["title"])}</h3>'
                             + (f'<p>{_text(g["note"])}</p>' if g.get("note") else "") + empty(items, "No public members recorded.") + "</section>")
            out += ('<h2>Households and groups</h2><p class="meta groups-caution">Membership of a group records who the researcher is studying together; '
                    'it does not by itself assert kinship.</p><div class="study-groups">' + "".join(cards) + "</div>")
        links = [l for l in row.get("links", []) if isinstance(l, dict) and l.get("from") in anchor and l.get("to") in anchor]
        if links:
            drawn = groups[:STUDY_GROUPS_DRAWN]
            index = {g["id"]: i for i, g in enumerate(drawn)}
            box_w, box_h, pitch, top, width = 300, 44, 60, 8, 760
            boxes, curves, labels, repeats = [], [], [], Counter()
            for i, g in enumerate(drawn):
                y = top + i * pitch
                count = sum(1 for pid in dict.fromkeys(g.get("member_ids", [])) if pid in people)
                short = title[g["id"]] if len(title[g["id"]]) <= 38 else title[g["id"]][:37].rstrip() + "…"
                boxes.append(f'<a href="#{anchor[g["id"]]}"><title>{_text(title[g["id"]])}</title><rect x="8" y="{y}" width="{box_w}" height="{box_h}" rx="6"/>'
                             f'<text x="20" y="{y + 19}">{_text(short)}</text><text class="count" x="20" y="{y + 36}">{count} {"person" if count == 1 else "people"}</text></a>')
            for l in links:
                if l["from"] not in index or l["to"] not in index:
                    continue
                a, b = sorted((index[l["from"]], index[l["to"]]))
                repeats[(a, b)] += 1
                # Arcs to the right of the boxes, wider for longer spans and
                # for a second link between the same two groups.
                bulge = min(70 + 60 * (b - a - 1) + 50 * (repeats[(a, b)] - 1), 330)
                ya, yb, x0 = top + a * pitch + box_h / 2, top + b * pitch + box_h / 2, 8 + box_w
                counted = config.grades[l["status"]]["confidence"] if l["status"] in config.grades else l["status"]
                style = "settled" if counted in ("documented", "probable") else "open disproved" if counted == "disproved" else "open"
                curves.append(f'<path class="link {style}" d="M{x0} {ya}C{x0 + bulge} {ya} {x0 + bulge} {yb} {x0} {yb}"/>')
                words = assessment_label(l["status"], config.grades)
                words = words if len(words) <= 26 else words[:25].rstrip() + "…"
                labels.append(f'<text x="{x0 + bulge * 0.75 + 6:.0f}" y="{(ya + yb) / 2 + 4:.0f}">{_text(words)}</text>')
            height = top + len(drawn) * pitch
            summary = f'Diagram of {len(drawn)} groups and {len(curves)} {"link" if len(curves) == 1 else "links"} between them'
            svg = (f'<svg class="groups-chart" viewBox="0 0 {width} {height}"><g role="img" aria-label="{_text(summary)}">{"".join(curves)}'
                   f'<g class="link-labels">{"".join(labels)}</g></g><g class="group-boxes">{"".join(boxes)}</g></svg>')
            notes = (f'<p class="meta">{len(groups) - len(drawn)} more groups are listed above but not drawn; their links are in the text below.</p>'
                     if len(groups) > len(drawn) else "")
            text = []
            for l in links:
                counted = config.grades[l["status"]]["confidence"] if l["status"] in config.grades else l["status"]
                records = [record_link(eid, prefix) if eid in citations else record_link(e["citation_id"], prefix)
                           for eid in dict.fromkeys(l.get("evidence_ids", []))
                           if eid in citations or ((e := evidence_by_id.get(eid)) and e["citation_id"] in citations)]
                text.append(f'<li><a href="#{anchor[l["from"]]}">{_text(title[l["from"]])}</a> → <a href="#{anchor[l["to"]]}">{_text(title[l["to"]])}</a>'
                            + metadata({"confidence": counted, "grade": l["status"] if l["status"] in config.grades else None}, prefix)
                            + (f'<p>{_text(l["note"])}</p>' if l.get("note") else "")
                            + (f'<p class="meta">Records: {", ".join(records)}</p>' if records else "") + "</li>")
            out += ('<h3>How the groups connect</h3><figure class="groups-diagram"><div class="groups-plot">' + svg + '</div><figcaption>'
                    'Each line joins two groups and is labelled with how far the link between them is established. '
                    'Solid lines are links assessed as documented or probable; dashed lines are possible, unassessed or disproved links.</figcaption></figure>' + notes
                    + f'<details class="groups-text"><summary>{_text(summary)}, as text</summary><ul>{"".join(text)}</ul></details>')
        pending = [item for item in row.get("next_records", []) if isinstance(item, str) and item.strip()]
        if pending:
            out += '<h2>Records still to inspect</h2><ul class="next-records">' + "".join(f"<li>{_text(item)}</li>" for item in pending) + "</ul>"
        return out

    for sid, row in studies.items():
        prefix = "../"
        linked = [rid for rid in row.get("related_ids", []) if rid in record_routes]
        related_research = [r for collection in ("findings", "questions", "hypotheses") for r in project[collection] if sid in r.get("related_ids", []) or r["id"] in linked]
        content = f'<p class="eyebrow">Research study</p><h1>{_text(row["title"])}</h1><p>{study_meta(row, prefix)}</p>'
        if row.get("summary"):
            content += f'<p class="lead">{_text(row["summary"])}</p>'
        if row.get("rationale"):
            content += '<h2>Why this study</h2>' + prose(row["rationale"], prefix)
        if row.get("body"):
            content += '<section class="study-body">' + prose(row["body"], prefix) + '</section>'
        content += '<h2>Current conclusion</h2>' + (prose(row["conclusion"], prefix) if row.get("conclusion") else '<p class="empty-state">No conclusion has been reached yet.</p>')
        content += chronology(row, prefix)
        content += study_groups(row, prefix)
        content += '<h2>People and records in this study</h2>' + empty([subject_item(rid, prefix) for rid in linked], "No public people or records are linked.")
        content += '<h2>Related findings and questions</h2>' + empty([f'<li>{ref(r["id"], prefix, r.get("conclusion") or r.get("question") or r.get("statement"))}{metadata(r, prefix)}</li>' for r in related_research], "No related findings or questions recorded.")
        pages[study_urls[sid]] = content

    # Latest findings: the dated discovery log; the research page keeps the full account.
    months = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")

    def finding_item(row: dict[str, Any], prefix: str = "") -> str:
        subjects = ", ".join(ref(rid, prefix, record_label(rid)) for rid in row.get("related_ids", []) if rid in record_routes)
        in_studies = ", ".join(f'<a href="{prefix}{study_urls[s["id"]]}">{_text(s["title"])}</a>' for s in studies_by_subject[row["id"]])
        return (f'<li class="finding-entry" id="{_anchor(row["id"])}" data-recorded-on="{_text(row.get("recorded_on") or "")}"><p class="meta">{_text(row.get("recorded_on") or "Undated")}</p>'
                f'<h3><a href="{prefix}{record_routes[row["id"]]}">{_text(row["conclusion"])}</a></h3>{metadata(row, prefix)}{finding_kind(row)}'
                + finding_details(row, prefix) + (f'<p>About: {subjects}</p>' if subjects else "") + (f'<p>Studies: {in_studies}</p>' if in_studies else "")
                + (f'<p class="meta">{len(row.get("evidence_ids", []))} evidence assessments</p>' if row.get("evidence_ids") else "") + "</li>")

    def by_month(rows: list[dict[str, Any]], prefix: str = "") -> str:
        out, current = [], None
        for row in rows:
            month = row["recorded_on"][:7]
            if month != current:
                out.append(("</ul>" if current else "") + f'<h2>{months[int(month[5:7]) - 1] + " " if len(month) == 7 else ""}{_text(month[:4])}</h2><ul class="record-list findings-log">')
                current = month
            out.append(finding_item(row, prefix))
        return "".join(out) + ("</ul>" if current else "")

    # A long log opens with the newest findings; archive pages are numbered from
    # the earliest, so a finding keeps its page as newer ones are added.
    archive: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in dated:
        if row["id"] in archive_page:
            archive[archive_page[row["id"]]].append(row)
    archive_url = lambda number: f"findings/page-{number}.html"
    archive_nav = lambda prefix: ('<nav class="pagination findings-archive" aria-label="Finding archive"><span>Archive pages, from the earliest:</span><div>'
                                  + "".join(f'<a href="{prefix}{archive_url(n)}">{n}</a>' for n in sorted(archive)) + "</div></nav>")
    log = ['<h1>Latest findings</h1><p>A dated log of research conclusions, newest first. Each entry links to the full finding with its evidence; studies and dossiers hold the current account.</p>']
    if archive:
        log.append(f'<p class="result-count">The newest {LATEST_FINDINGS} of {len(dated):,} dated findings.</p>' + by_month(dated[:LATEST_FINDINGS]) + archive_nav(""))
    else:
        log.append(by_month(dated))
    if undated:
        log.append('<h2>Undated findings</h2><ul class="record-list findings-log">' + "".join(finding_item(row) for row in undated) + "</ul>")
    if not project["findings"]:
        log.append('<p class="empty-state">No public findings recorded yet.</p>')
    pages["findings.html"] = "".join(log)
    for number, rows in archive.items():
        newer = f'<a href="{archive_url(number + 1).split("/")[1]}">← Newer</a>' if number + 1 in archive else '<a href="../findings.html">← Latest findings</a>'
        older = f'<a href="{archive_url(number - 1).split("/")[1]}">Older →</a>' if number - 1 in archive else ""
        pages[archive_url(number)] = (f'<h1>Findings, page {number} of {len(archive)}</h1><p>Archive pages are numbered from the earliest finding, so a finding keeps its page. <a href="../findings.html">Latest findings</a>.</p>'
                                      + by_month(rows, "../") + f'<nav class="pagination" aria-label="Finding pages"><div>{newer}{older}</div></nav>' + archive_nav("../"))
        extra_titles[archive_url(number)] = ("findings", f"Findings, page {number}")

    # Families and branches: surname groups and connected groups of recorded relatives.
    groups: dict[str, list[str]] = defaultdict(list)
    for pid in people:
        groups[canonical_surname(pid) or ""].append(pid)
    branch_rows = []
    for name, members in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0].casefold())):
        years = sorted(y for pid in members for e in events_by_person[pid] if e["kind"] in ("birth", "death", "baptism", "christening", "burial") and (y := year_of(e.get("date"))))
        where = Counter(places[e["place_id"]]["name"] for pid in members for e in events_by_person[pid] if e.get("place_id") in places)
        founders = [pid for pid in members if not any(canonical_surname(r["object_id"]) == name for r in parents_of[pid])]
        founders.sort(key=lambda pid: (date_sort_key(next((e.get("date") for e in events_by_person[pid] if e["kind"] == "birth"), None)), person_name(pid)))
        label = name or "No surname recorded"
        link = f'catalogue.html?surname={quote(name)}' if name else "catalogue.html"
        spellings = Counter(surname(pid) for pid in members)
        recorded_as = ("" if set(spellings) <= {name} else '<br><span class="meta">Recorded as '
                       + _text(", ".join(f"{s} ({n})" for s, n in sorted(spellings.items(), key=lambda item: (-item[1], item[0].casefold())))) + "</span>")
        branch_rows.append(f'<tr data-surname="{_text(name)}"><td><a href="{_text(link)}">{_text(label)}</a>{recorded_as}</td><td>{len(members)}</td><td>{_text(f"{years[0]}–{years[-1]}" if years else "—")}</td><td>{_text("; ".join(place for place, _ in where.most_common(3)) or "—")}</td><td>' + ", ".join(ref(pid) for pid in founders[:3]) + "</td></tr>")
    parent_of = {pid: pid for pid in people}

    def find(pid: str) -> str:
        while parent_of[pid] != pid:
            parent_of[pid] = parent_of[parent_of[pid]]
            pid = parent_of[pid]
        return pid
    for row in project["relationships"]:
        if row.get("confidence") != "disproved" and row["subject_id"] in people and row["object_id"] in people:
            a, b = find(row["subject_id"]), find(row["object_id"])
            if a != b:
                parent_of[b] = a
    components: dict[str, list[str]] = defaultdict(list)
    for pid in people:
        components[find(pid)].append(pid)
    connected = sorted((members for members in components.values() if len(members) > 1), key=lambda m: (-len(m), min(m)))
    singles = sum(1 for members in components.values() if len(members) == 1)
    component_rows = []
    for number, members in enumerate(connected[:60], 1):
        names = Counter(canonical_surname(pid) for pid in members if surname(pid))
        years = sorted(y for pid in members for e in events_by_person[pid] if e["kind"] == "birth" and (y := year_of(e.get("date"))))
        earliest = min(members, key=lambda pid: (date_sort_key(next((e.get("date") for e in events_by_person[pid] if e["kind"] == "birth"), None)), person_name(pid)))
        component_rows.append(f'<tr><td>Group {number}</td><td>{len(members)}</td><td>{_text(", ".join(n for n, _ in names.most_common(3)) or "—")}</td><td>{_text(f"{years[0]}–{years[-1]}" if years else "—")}</td><td>{ref(earliest)} · <a href="tree.html?person={quote(earliest)}">tree</a></td></tr>')
    pages["branches.html"] = ('<h1>Families and branches</h1><p>Surname groups use each person\'s first recorded surname'
                              + ("; spellings this project lists as variants of one surname are grouped under it" if name_variants else "")
                              + '. Connected groups are people joined by recorded relationships; separate groups may still be related through records not yet found.</p>'
                              + '<h2>Surnames</h2>' + ('<div class="table-wrap"><table><thead><tr><th>Surname</th><th>People</th><th>Recorded years</th><th>Most recorded places</th><th>Earliest recorded</th></tr></thead><tbody>' + "".join(branch_rows) + '</tbody></table></div>' if branch_rows else '<p class="empty-state">No public people are available.</p>')
                              + '<h2>Connected groups</h2>' + ('<div class="table-wrap"><table><thead><tr><th>Group</th><th>People</th><th>Main surnames</th><th>Births</th><th>Earliest born</th></tr></thead><tbody>' + "".join(component_rows) + '</tbody></table></div>' if component_rows else '<p class="empty-state">No recorded relationships connect public people yet.</p>')
                              + (f'<p class="meta">{len(connected) - 60} smaller groups are not listed. </p>' if len(connected) > 60 else "") + (f'<p class="meta">{singles} people have no public recorded relatives.</p>' if singles else ""))

    def guide_examples() -> dict[str, str]:
        """One example from the site per guide entry: the first family link, by
        its first person's name, whose badge leads to that entry, and the first
        claim with each status. The projection holds only public records; both
        people are checked anyway, so a withheld person can never be named."""
        found: dict[str, str] = {}
        family_kinds = PARENT_KINDS | PARTNER_KINDS | SIBLING_KINDS
        links = sorted((r for r in project["relationships"] if str(r["kind"]).casefold() in family_kinds
                        and r["subject_id"] in people and r["object_id"] in people and r["subject_id"] != r["object_id"]),
                       key=lambda r: (person_name(r["subject_id"]), person_name(r["object_id"]), r["id"]))
        for r in links:
            confidence, kind, (a, b) = str(r.get("confidence") or "unknown"), str(r["kind"]).casefold(), (r["subject_id"], r["object_id"])
            # The same anchors metadata() links this link's badge to.
            anchors = [f'grade-{r["grade"]}' if grade_label(r, config.grades) else "confidence-tree-link" if confidence == "unknown" else f"confidence-{confidence}"]
            anchors += ["estimate"] * isinstance(r.get("estimate"), int) + ["tree-marked"] * bool(r.get("tree_status"))
            if all(anchor in found for anchor in anchors):
                continue
            role = (parent_role(r, sex.get(b)).lower() if kind in PARENT_KINDS else "spouse or partner" if kind in PARTNER_KINDS
                    else "half-sibling" if "half" in kind or "half" in str(r.get("pedigree") or "").casefold() else "sibling")
            pronoun = {"m": "his", "male": "his", "f": "her", "female": "her"}.get(sex.get(a, "").casefold(), "their")
            words = f"{person_name(a)} and {pronoun} {role} {person_name(b)}"
            for anchor in anchors:
                found.setdefault(anchor, f'<a href="{_text(people_urls[a])}#family-heading">{_text(words)}</a>')
        for c in sorted((c for c in project["claims"] if c.get("predicate") != "sex" and c["subject_id"] in people and c["id"] in record_routes),
                        key=lambda c: (person_name(c["subject_id"]), str(c["predicate"]), c["id"])):
            key = str(c.get("status") or "").casefold()
            if key in CLAIM_STATUS:
                found.setdefault(f"status-{key}", f'<a href="{_text(record_routes[c["id"]])}">{_text(person_name(c["subject_id"]))} — {_text(c["predicate"])}: {_text(c.get("value", ""))}</a>')
        return found

    examples = guide_examples()

    def guide_more(anchor: str) -> str:
        """Under an entry's meaning: what its grade usually rests on, and one example from the site."""
        basis = guide_basis(anchor, config.grades)
        return ((f'<dd class="guide-basis">Usually rests on: {_text(basis)}</dd>' if basis else "")
                + (f'<dd class="guide-example">Example: {examples[anchor]}</dd>' if anchor in examples else ""))

    guide = ['<h1>Reading the evidence</h1><p>Every relationship, claim and finding on this site carries a label describing how far it has been assessed. Labels never claim more than the record behind them. A family-tree export supplies assertions: it cannot by itself prove parentage, supply missing sources, or establish DNA findings.</p>']
    current_group = None
    for anchor, label, meaning, group in guide_entries(config.grades):
        if group != current_group:
            guide.append(("</dl>" if current_group else "") + f'<h2>{_text(group)}</h2><dl class="evidence-guide">')
            current_group = group
        guide.append(f'<dt id="{_text(anchor)}">{_text(label)}</dt><dd>{_text(meaning)}</dd>' + guide_more(anchor))
    guide.append('</dl><h2>Privacy</h2><p>Living people, people whose status is unknown, and restricted, licensed or private material are withheld from every page, search index, map and download. A missing person or record is therefore not evidence that they did not exist.</p>')
    pages["evidence.html"] = "".join(guide)

    def correction_mailto(pid: str) -> str:
        """A message that starts with the person's name and ID, and their page address when known."""
        body = ([f"Page: {base_url}{quote(people_urls[pid])}", ""] if base_url else []) + [
            "What is wrong, and what it should say:", "", "", "The record that shows it:", ""]
        subject = quote(f"Correction: {person_name(pid)} ({pid})", safe="")
        text = quote("\r\n".join(body), safe="")  # mailto: line breaks are CRLF (RFC 6068)
        return f'mailto:{quote(contact["email"], safe="@+")}?subject={subject}&body={text}'

    if "corrections.html" in routes:
        send = []
        if "email" in contact:
            send.append(f'<li>Email <a class="contact-address" href="mailto:{_text(quote(contact["email"], safe="@+"))}">{_text(contact["email"])}</a>. '
                        'Each person\'s page has a <strong>Suggest a correction</strong> link that starts the message with their name and record ID.</li>')
        if "url" in contact:
            send.append(f'<li><a class="contact-address" href="{_text(contact["url"])}" rel="noreferrer">Send a correction online</a></li>')
        pages["corrections.html"] = (
            '<h1>Corrections</h1><p>Found a mistake, or hold a record that would help? Corrections and new evidence are welcome. '
            'Every detail on this site rests on the records it cites, so a correction is most useful when it points to a record too.</p>'
            '<h2>What a useful correction contains</h2><ul>'
            '<li>The person\'s name and the address of their page on this site, or their record ID.</li>'
            '<li>The detail that is wrong, and what you think it should say.</li>'
            '<li>The record that shows it: where it is held, its reference and date, or a copy. If you know it from family papers or memory, say so.</li></ul>'
            '<p class="note"><strong>Please do not send details of people who may still be living.</strong></p>'
            '<h2>How to send it</h2><ul>' + "".join(send) + '</ul>'
            + (f'<p class="preserve-lines">{_text(contact["note"])}</p>' if "note" in contact else "")
            + '<h2>Imported trees</h2><p>Some details here may come from an imported family tree. If a person\'s page lists an external identifier, '
            'such as a profile on an online tree, a correction to an imported detail should also go to that tree, so the two stay in step.</p>')
    numbers = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
    count = lambda n, one, many: f'{numbers[n] if n < len(numbers) else f"{n:,}"} {one if n == 1 else many}'
    listed = lambda items: items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]
    finding_ids = {f["id"] for f in project["findings"]}

    def introduction(pid: str) -> str:
        """Plain sentences from the public record only: a missing event or relative means a missing clause."""
        prefix = "../"

        def phrase(kinds: tuple[tuple[str, str, str], ...]) -> tuple[str, str] | None:
            # The first recorded event of the first kind recorded, with a date or a place to state.
            for kind, alone, joined in kinds:
                found = next((e for e in events_by_person[pid] if str(e["kind"]).casefold() == kind and (e.get("date") or e.get("place_id") in places)), None)
                if found:
                    words = (f' {_text(found["date"])}' if found.get("date") else "") + (
                        f' in {ref(found["place_id"], prefix, places[found["place_id"]]["name"])}' if found.get("place_id") in places else "")
                    return alone + words, joined + words
            return None
        start = phrase((("birth", "was born", "was born"), ("baptism", "was baptised", "was baptised"), ("christening", "was baptised", "was baptised")))
        end = phrase((("death", "died", "died"), ("burial", "was buried", "buried")))
        sentences = []
        if start or end:
            sentences.append(f'{_text(person_name(pid))} ' + (f"{start[0]}, and {end[1]}" if start and end else start[0] if start else end[0]) + ".")
        all_parents, all_partners, all_children = kin(pid)
        parents = list(dict.fromkeys(r["object_id"] for r in all_parents if not rejected(r)))
        partners = {other for row, other in all_partners if not rejected(row)}
        children = {r["subject_id"] for r in all_children if not rejected(r)}
        clauses = ([f'{listed([ref(p, prefix) for p in parents])} as {"a parent" if len(parents) == 1 else "parents"}'] if parents else []) + (
            [count(len(partners), "spouse or partner", "spouses or partners")] if partners else []) + ([count(len(children), "child", "children")] if children else [])
        if clauses:
            sentences.append(f"This page lists {listed(clauses)}.")
        return f'<p class="lead intro">{" ".join(sentences)}</p>' if sentences else ""

    def latest_finding(pid: str) -> str:
        """The newest dated public finding about a person, and when research on them was last recorded."""
        found = [f for f in research_by_subject[pid] if f["id"] in finding_ids and f.get("recorded_on")]
        if not found:
            return ""
        newest = max(found, key=lambda f: (f["recorded_on"], f["id"]))
        last = max([f["recorded_on"] for f in found] + [s["updated_on"] for s in studies_by_subject[pid] if s.get("updated_on")])
        return ('<aside class="latest-finding" aria-labelledby="latest-finding-heading"><h2 id="latest-finding-heading">Latest finding</h2>'
                f'<p>{ref(newest["id"], "../", newest["conclusion"])}{metadata(newest, "../")}</p><p class="meta">Recorded {_text(newest["recorded_on"])}</p>'
                f'<p class="meta research-date">Research last recorded {_text(last)}</p></aside>')

    def search_item(row: dict[str, Any], prefix: str = "", *, omit: str | None = None) -> str:
        """One search: when, where it looked, what it found (often nothing), what it could not cover and the records found."""
        found = [f"<li>{record_link(cid, prefix)}</li>" for cid in row.get("citation_ids", []) if cid in citations]
        others = [ref(rid, prefix, record_label(rid)) for rid in row.get("related_ids", []) if rid != omit]
        details = [("Searched", _text(row["search"])), ("Result", _text(row["result"]))]
        details += [("Limits", _text(row["limitation"]))] if row.get("limitation") else []
        details += [("Records found", '<ul class="finding-records">' + "".join(found) + "</ul>")] if found else []
        details += [("Also for" if omit else "For", ", ".join(others))] if others else []
        return (f'<li id="{_anchor(row["id"])}"><p class="search-date"><strong>{_text(row.get("searched_on") or "Date not recorded")}</strong></p>'
                '<dl class="search-details">' + "".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in details) + "</dl></li>")

    def research_log(pid: str) -> str:
        rows = searches_by_subject[pid]
        return ('<h2 id="research-log">Research log</h2>' + ('<p class="meta">Searches made for this person, newest first, including those that found nothing.</p>' if rows else "")
                + empty([search_item(r, "../", omit=pid) for r in rows], "No public searches recorded for this person.").replace('class="record-list"', 'class="record-list research-log"', 1))

    total_searches = len(searches_newest)
    pages["research.html"] += ('<h2 id="research-log">Research log</h2><p>Where each search looked and what it found, including searches that found nothing, so that they need not be repeated.</p>'
                               + (f'<p class="result-count">The newest {LATEST_SEARCHES} of {total_searches:,} searches. Each person\'s page lists every search made for them.</p>' if total_searches > LATEST_SEARCHES
                                  else f'<p class="result-count">{total_searches} search{"" if total_searches == 1 else "es"}, newest first.</p>' if total_searches else "")
                               + empty([search_item(r) for r in searches_newest[:LATEST_SEARCHES]], "No public searches recorded.").replace('class="record-list"', 'class="record-list research-log"', 1))

    for pid, person in people.items():
        related_events = events_by_person[pid]
        subject_ids = {pid, *(e["id"] for e in related_events)}
        related_rels = relationships_by_person[pid]
        subject_ids.update(r["id"] for r in related_rels)
        personal_claims = [c for subject in sorted(subject_ids) for c in claims_by_subject[subject] if c.get("predicate") != "sex"]
        name_items = [f'<li>{_text(n["value"])} — {_text(n.get("kind", "unknown"))}{metadata(n, "../")}</li>' for n in person.get("names", [])]
        external = []
        for identifier in person.get("external_ids", []):
            label = _text(identifier["system"] + ": " + identifier["value"])
            url = _url(identifier.get("url"))
            external.append("<li>" + (f'<a href="{_text(url)}" rel="noreferrer">{label}</a>' if url else label) + "</li>")
        span = lifespan(pid)
        recorded_sex = sex.get(pid)
        content = f'<p class="eyebrow">Person dossier</p><h1>{_text(person_name(pid))}</h1>' + (f'<p class="lifespan">{_text(span)}</p>' if span else "") + f'<p class="record-id">{_text(pid)}</p>'
        # Jump links are judged from the lists the sections below are built from, so a
        # section showing only its empty-state line is never linked.
        family_rows = parents_of[pid] or partners_of[pid] or children_of[pid] or [r for r, _ in siblings_of[pid] if r.get("confidence") != "disproved"]
        jumps = [("names", "Names", name_items), ("biography", "Biography", person.get("notes")), ("family-heading", "Family", family_rows),
                 ("events", "Events", related_events), ("claims", "Claims and evidence", personal_claims), ("studies", "Studies", studies_by_subject[pid]),
                 ("research", "Research", research_by_subject[pid]), ("research-log", "Research log", searches_by_subject[pid]), ("relationships", "All relationships", related_rels), ("external", "External identifiers", external)]
        if any(filled for _, _, filled in jumps):
            content += '<nav class="page-sections" aria-label="On this page"><ul>' + "".join(f'<li><a href="#{key}">{label}</a></li>' for key, label, filled in jumps if filled) + "</ul></nav>"
        explore = [(f"tree.html?person={quote(pid)}", "Family tree"), (f"connections.html?a={quote(pid)}", "Find a connection"), (f"compare.html?a={quote(pid)}", "Compare")]
        if canonical_surname(pid):
            explore.append((f"catalogue.html?surname={quote(canonical_surname(pid))}", f"Everyone surnamed {canonical_surname(pid)}"))
        content += '<p class="explore"><span class="meta">Explore:</span> ' + " · ".join(f'<a href="../{_text(url)}">{_text(label)}</a>' for url, label in explore) + "</p>"
        if recorded_sex:
            content += f'<p class="meta">Recorded sex: {_text(recorded_sex)} <span class="badge">Unassessed tree assertion</span></p>'
        # The researcher's own notes, when there are any, open the page instead of generated sentences.
        content += ("" if person.get("notes") else introduction(pid)) + latest_finding(pid)
        content += '<h2 id="names">Names</h2>' + empty(name_items)
        if person.get("notes"):
            content += '<h2 id="biography">Biography and notes</h2><p class="preserve-lines">' + _text(person["notes"]) + '</p>'
        content += family(pid)
        content += '<h2 id="events">Events</h2>' + empty([event(e, "../") for e in related_events]) + '<h2 id="claims">Claims, citations and evidence</h2>' + ("".join(claim(c, "../") for c in personal_claims) or '<p>No public claims recorded for this person.</p>')
        content += '<h2 id="studies">Studies</h2>' + empty([f'<li><a href="../{study_urls[s["id"]]}">{_text(s["title"])}</a> {study_meta(s, "../")}</li>' for s in studies_by_subject[pid]], "No public studies mention this person.")
        content += '<h2 id="research">Research</h2>' + empty([f'<li>{ref(r["id"], "../", r.get("question") or r.get("conclusion") or r.get("statement"))}{metadata(r, "../")}{question_next(r, "../") if "question" in r else ""}</li>' for r in research_by_subject[pid]]) + research_log(pid) + '<h2 id="relationships">All recorded relationships</h2>' + empty([relationship(r, "../") for r in related_rels]) + '<h2 id="external">External identifiers</h2>' + empty(external)
        if "corrections.html" in routes:
            content += '<p class="suggest-correction">' + (f'<a href="{_text(correction_mailto(pid))}">Suggest a correction</a> · <a href="../corrections.html">What to include</a>'
                                                           if "email" in contact else '<a href="../corrections.html">Suggest a correction</a>') + "</p>"
        pages[people_urls[pid]] = content

    # Place pages: where a place sits among the places recorded around it, and
    # who and what is recorded there. Every list is capped by count and by size,
    # so a busy town or a country of many parishes stays one small page.
    def place_chain(pid: str) -> list[str]:
        """The places containing this one, broadest first; a loop in ``parent_id`` stops the walk."""
        chain, seen, parent = [], {pid}, places[pid].get("parent_id")
        while parent in places and parent not in seen:
            chain.append(parent)
            seen.add(parent)
            parent = places[parent].get("parent_id")
        return chain[::-1]

    def place_list(items: list[str], noun: str, budget: int = PLACE_PEOPLE_BYTES // 3) -> str:
        kept, size = [], 0
        for item in items[:PLACE_LIST_LIMIT]:
            size += len(item)
            if kept and size > budget:
                break
            kept.append(item)
        more = len(items) - len(kept)
        return "<ul>" + "".join(kept) + "</ul>" + (f'<p class="meta">and {more:,} more {noun}</p>' if more > 0 else "")

    def place_locator(p: dict[str, Any], prefix: str) -> str:
        """The bundled basemap cropped around one supplied coordinate, with a marker."""
        if p.get("latitude") is None or p.get("longitude") is None:
            return ""
        x, y = (p["longitude"] + 180) * 960 / 360, (90 - p["latitude"]) * 480 / 180
        w, h = 240, 120
        left, top = min(max(x - w / 2, 0), 960 - w), min(max(y - h / 2, 0), 480 - h)
        broad = p.get("precision") in BROAD_PRECISIONS
        return (f'<figure class="place-locator"><svg class="place-map" viewBox="{left:.1f} {top:.1f} {w} {h}" role="img" aria-label="{_text("Map marker for " + str(p["name"]))}">'
                f'<rect width="960" height="480" fill="#e8efec"/><image href="{prefix}assets/world.svg" width="960" height="480"/>'
                f'<circle cx="{x:.3f}" cy="{y:.3f}" r="{5 if broad else 2.5}"' + (' class="broad"' if broad else "") + '/></svg>'
                '<figcaption>Supplied coordinates on a Natural Earth overview' + ("; the ring marks a place located only broadly" if broad else "")
                + ". Not a street map.</figcaption></figure>")

    for pid, url in place_urls.items():
        prefix, p = "../", places[pid]
        content = f'<p class="eyebrow">Place</p><h1>{_text(p["name"])}</h1>'
        chain = place_chain(pid)
        if chain:
            content += '<p class="place-chain"><span class="meta">Within</span> ' + " › ".join(ref(c, prefix, places[c]["name"]) for c in chain) + "</p>"
        content += f'<p class="record-id">{_text(pid)}</p>'
        coords = p.get("latitude") is not None and p.get("longitude") is not None
        details = f'{p["latitude"]}, {p["longitude"]}' if coords else "Coordinates not supplied"
        if coords and p.get("precision"):
            details += f' · located to {p["precision"]} level' if p["precision"] != "exact" else " · exact location"
        content += f'<p>{_text(details)}</p>' + place_locator(p, prefix)
        here = events_by_place.get(pid, [])
        who: dict[str, list[dict[str, Any]]] = {}
        for e in here:  # already in date order
            for person_id in sorted((set(e.get("participant_ids", [])) | event_owners[e["id"]]) & people.keys(), key=lambda i: (person_name(i).casefold(), i)):
                who.setdefault(person_id, []).append(e)
        years = sorted(y for e in here if (y := year_of(e.get("date"))))
        span = (f"{years[0]}" if years[0] == years[-1] else f"{years[0]}–{years[-1]}") if years else None
        listing = (place_pages.get(pid) or "places.html") + "#" + _anchor(pid)
        content += (f'<p class="lead">{count(len(here), "public event is", "public events are").capitalize()} recorded here'
                    + (f', involving {count(len(who), "person", "people")}' if who else "") + (f'; recorded years {span}' if span else "; none has a recorded year" if here else "")
                    + f'. <a href="{prefix}{_text(listing)}">Listed with its region</a>.</p>')
        content += '<h2>Places within it</h2>' + (place_list([
            f'<li>{ref(c["id"], prefix, c["name"])}' + (f' <span class="meta">{facts}</span>' if (facts := ", ".join(
                ([count(len(events_by_place[c["id"]]), "event", "events")] if events_by_place.get(c["id"]) else [])
                + ([count(len(sub_places[c["id"]]), "place", "places") + " within"] if sub_places.get(c["id"]) else []))) else "") + "</li>"
            for c in sub_places.get(pid, [])], "places") if sub_places.get(pid) else '<p class="empty-state">No public places are recorded within this one.</p>')
        content += '<h2>People recorded here</h2>' + (place_list([
            f'<li>{ref(person_id, prefix)} <span class="meta">— ' + _text("; ".join(f'{e["kind"]}: {e.get("date") or "date unknown"}' for e in evs)) + "</span></li>"
            for person_id, evs in who.items()], "people", PLACE_PEOPLE_BYTES) if who else '<p class="empty-state">No public people have events recorded here.</p>')
        names = Counter(canonical_surname(person_id) for person_id in who if canonical_surname(person_id))
        content += '<h2>Surnames recorded here</h2>' + (place_list([
            f'<li><a href="{prefix}catalogue.html?surname={_text(quote(name))}">{_text(name)}</a> <span class="meta">({n:,})</span></li>'
            for name, n in sorted(names.items(), key=lambda item: (-item[1], item[0].casefold()))], "surnames") if names else '<p class="empty-state">No surnames recorded here.</p>')
        content += '<h2>Studies</h2>' + (place_list([f'<li><a href="{prefix}{study_urls[s["id"]]}">{_text(s["title"])}</a> {study_meta(s, prefix)}</li>' for s in studies_by_subject[pid]], "studies")
                                         if studies_by_subject.get(pid) else '<p class="empty-state">No public studies mention this place.</p>')
        pages[url] = content
        extra_titles[url] = ("map", str(p["name"]))
    def statistics() -> str:
        """Counts of the public projection only: a withheld person or record is never counted, so a table
        describes what is published. A table with nothing to count is left out."""
        def recorded(pid: str, kinds: tuple[str, ...], key: str) -> dict[str, Any] | None:
            # The first event of the first kind recorded with a date (or place), as the dossier's opening sentence reads it.
            return next((e for kind in kinds for e in events_by_person[pid] if str(e["kind"]).casefold() == kind and e.get(key)), None)

        def table(key: str, heading: str, columns: tuple[str, ...], rows: list[tuple[tuple[str, ...], int]], note: str = "", level: int = 2) -> str:
            """``rows`` are (escaped cells, count) in reading order; bars are scaled to the largest count."""
            if not rows:
                return ""
            top = max(n for _, n in rows) or 1  # a table of zero counts still draws
            body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + f'<td class="count">{n:,}'
                           f'<div class="bar" style="--w:{max(1, round(n * 100 / top))}%" aria-hidden="true"></div></td></tr>' for cells, n in rows[:STATISTICS_ROWS])
            more = f'<p class="meta">{len(rows) - STATISTICS_ROWS:,} more not listed.</p>' if len(rows) > STATISTICS_ROWS else ""
            return (f'<h{level} id="{key}">{_text(heading)}</h{level}>' + (f'<p class="meta">{note}</p>' if note else "")
                    + f'<div class="table-wrap"><table class="statistics" aria-labelledby="{key}"><thead><tr>' + "".join(f'<th scope="col">{_text(c)}</th>' for c in columns)
                    + f"</tr></thead><tbody>{body}</tbody></table></div>" + more)

        ranked = lambda counts: sorted(counts.items(), key=lambda item: (-item[1], str(item[0]).casefold()))
        region_of = {p["id"]: region for region, members in regions.items() for p in members}
        region_link = lambda region: f'<a href="{region_pages[region][0] if compact_places else "places.html#" + _anchor("region:" + region)}">{_text(region)}</a>'
        births = {pid: recorded(pid, ("birth", "baptism", "christening"), "date") for pid in people}
        centuries = Counter(year // 100 * 100 for e in births.values() if e and (year := year_of(e["date"])))
        undated = len(people) - sum(centuries.values())
        birth_region = {pid: region_of.get((recorded(pid, ("birth", "baptism", "christening"), "place_id") or {}).get("place_id")) for pid in people}
        death_region = {pid: region_of.get((recorded(pid, ("death", "burial"), "place_id") or {}).get("place_id")) for pid in people}
        born_in = Counter(region for region in birth_region.values() if region)
        if set(born_in) <= {UNPLACED_REGION}:  # no birthplace names a broader jurisdiction: nothing to group
            born_in.clear()

        def forename(pid: str) -> str:
            """The first forename of the name the site shows: its recorded given name, else the name without its surname."""
            n = next((n for n in people[pid].get("names", []) if n.get("value")), {})
            text = n.get("given") or re.sub(r"/[^/]*/", " ", str(n.get("value") or ""))
            if not n.get("given") and n.get("surname") and text.rstrip().endswith(n["surname"]):
                text = text.rstrip()[:-len(n["surname"])]
            word = next(iter(text.split()), "")
            return word if any(c.isalpha() for c in word) else ""
        given = Counter(name for pid in people if (name := forename(pid)))
        surnames = Counter(name for pid in people if (name := canonical_surname(pid)))
        families = Counter({pid: n for pid in people if (n := len({r["subject_id"] for r in children_of[pid] if not rejected(r)}))})
        place_events = Counter({plid: len(rows) for plid, rows in events_by_place.items() if plid in places})
        moves = Counter((birth_region[pid], death_region[pid]) for pid in people
                        if UNPLACED_REGION not in (birth_region[pid], death_region[pid]) and birth_region[pid] and death_region[pid])
        stayed = sum(n for (born, died), n in moves.items() if born == died)
        moves = Counter({pair: n for pair, n in moves.items() if pair[0] != pair[1]})
        kinds: Counter[str] = Counter()
        kind_label: dict[str, str] = {}
        for row in project["events"]:
            key = str(row["kind"]).casefold()
            kinds[key] += 1
            kind_label.setdefault(key, str(row["kind"])[:1].upper() + str(row["kind"])[1:])
        claim_status = Counter(str(c.get("status") or "asserted") for c in project["claims"] if c.get("predicate") != "sex")
        links: Counter[tuple[str, str]] = Counter()
        for row in project["relationships"]:
            confidence = str(row.get("confidence") or "unknown")
            graded = grade_label(row, config.grades)
            links[(f'grade-{row["grade"]}' if graded else "confidence-tree-link" if confidence == "unknown" else f"confidence-{confidence}",
                   graded or confidence_label(confidence, relationship=True))] += 1
        finding_years = Counter(str(year_of(f.get("recorded_on")) or "Undated") for f in project["findings"])
        guide = lambda anchor, words: f'<a href="evidence.html#{_text(anchor)}">{_text(words)}</a>'
        people_tables = "".join((
            table("birth-centuries", "Births by century", ("Century", "People"),
                  [((f"{c}–{c + 99}",), n) for c, n in sorted(centuries.items())],
                  "From each person's recorded birth year, or baptism year when no birth is dated."
                  + (f" {undated:,} {'person has' if undated == 1 else 'people have'} no recorded year." if centuries and undated else "")),
            table("birth-regions", "Births by country or region", ("Country or region", "People"),
                  [((region_link(r),), born_in[r]) for r in sorted(born_in, key=lambda r: (r == UNPLACED_REGION, -born_in[r], r.casefold()))],
                  "The last part of each birthplace name as recorded, as on the places page."),
            table("given-names", "Most common given names", ("Given name", "People"), [((_text(name),), n) for name, n in ranked(given)],
                  "The first forename of each person's main recorded name."),
            table("surnames", "Most common surnames", ("Surname", "People"),
                  [((f'<a href="catalogue.html?surname={_text(quote(name))}">{_text(name)}</a>',), n) for name, n in ranked(surnames)],
                  "Each person's first recorded surname" + ("; spellings this project lists as variants of one surname are counted under it." if name_variants else ".")),
            table("families", "Largest families", ("Parent", "Recorded children"),
                  [((ref(pid),), n) for pid, n in sorted(families.items(), key=lambda item: (-item[1], person_name(item[0]).casefold(), item[0]))],
                  "Parents with the most recorded children; links assessed as disproved are not counted."),
            table("places", "Most recorded places", ("Place", "Events"),
                  [((ref(plid, "", places[plid]["name"]),), n) for plid, n in sorted(place_events.items(), key=lambda item: (-item[1], str(places[item[0]]["name"]).casefold(), item[0]))]),
            table("migrations", "From birth to death", ("Born in", "Died in", "People"),
                  [((region_link(born), region_link(died)), n) for (born, died), n in ranked(moves)],
                  "People whose recorded birth (or baptism) and death (or burial) places are in different countries or regions."
                  + (f" {stayed:,} {'person was' if stayed == 1 else 'people were'} born and died in the same one." if stayed else "")),
            table("event-kinds", "Events by kind", ("Kind", "Events"), [((_text(kind_label[k]),), n) for k, n in ranked(kinds)]),
        ))
        research_tables = "".join((
            table("claim-status", "Claims by status", ("Status", "Claims"),
                  [((guide(status_anchor(s), status_label(s)),), n) for s, n in ranked(claim_status)], level=3),
            table("relationship-confidence", "Family links by assessment", ("Assessment", "Links"),
                  [((guide(anchor, words),), n) for (anchor, words), n in sorted(links.items(), key=lambda item: (-item[1], item[0][1].casefold()))], level=3),
            table("findings-by-year", "Findings by year recorded", ("Year", "Findings"),
                  [((_text(year),), n) for year, n in sorted(finding_years.items(), key=lambda item: (item[0] == "Undated", -int(item[0]) if item[0].isdigit() else 0))], level=3),
        ))
        return ('<h1>Statistics</h1><p>Counts of the public records on this site: '
                f'{len(people):,} {"person" if len(people) == 1 else "people"}, {len(project["events"]):,} events and {len(project["places"]):,} places. '
                'People and records withheld for privacy are not counted, so these figures describe what is published, not everyone researched.</p>'
                + (people_tables or '<p class="empty-state">No public people are available.</p>')
                + ('<h2 id="research-progress">Research progress</h2>' + research_tables if research_tables else ""))
    pages["statistics.html"] = statistics()
    downloads = [("data/site.json", "Public research JSON"), ("data/site.csv", "Public research CSV"), ("data/places.geojson", "Place GeoJSON"),
                 ("data/public-tree.ged", "Public tree as GEDCOM 5.5.1"), ("data/routes.json", "Route index JSON")]
    if base_url:
        downloads += [("sitemap.xml", "XML sitemap"), ("findings.xml", "Latest findings (Atom feed)")]
    data_links = "<ul>" + "".join(f'<li><a href="{path}">{label}</a></li>' for path, label in downloads) + "</ul>"
    pages["sitemap.html"] = '<h1>Site index and downloads</h1><h2>Explore</h2><ul>' + "".join(f'<li><a href="{path}">{title}</a></li>' for path, (_, title) in routes.items()) + '</ul>' + ('<h2>Studies</h2>' + (f'<p>All {len(studies):,} studies are listed on the <a href="studies.html">studies page</a>, newest first, and <a href="studies/page-1.html">by title</a>.</p>'
                                                  if compact_studies else empty([f'<li><a href="{study_urls[sid]}">{_text(row["title"])}</a></li>' for sid, row in studies.items()])) if studies else "") + '<h2>People</h2>' + browse_people + '<h2>Machine-readable data</h2>' + data_links + '<p>Downloads contain only the public records shown on this site.</p>'
    shared = browser_data(project, people_urls, {sid: route for sid, route in record_routes.items() if sid in sources} if compact_sources else None,
                          config.grades, study_urls if compact_studies else None, name_variants)
    outputs: dict[str, str] = {
        "data/site.json": exports.to_json(project), "data/site.csv": exports.to_csv(project),
        "data/places.geojson": json.dumps(geojson(project), ensure_ascii=False, indent=2) + "\n",
        "data/public-tree.ged": exports.to_gedcom(project),
        # One cached script shared by every interactive page; works from file:// too.
        "data/site-data.js": "window.GENEALOGY_SITE_DATA=" + _json(shared) + ";\n",
    }
    outputs["data/routes.json"] = json.dumps(sorted(pages), indent=2) + "\n"
    if base_url:
        outputs["sitemap.xml"] = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "".join(
            f"  <url><loc>{xml_escape(base_url + quote(path))}</loc></url>\n" for path in sorted(pages)) + "</urlset>\n"

        outputs["findings.xml"] = atom_feed(
            title=f"{config.name}: latest findings", feed_id=base_url + "findings.html", alternate=base_url + "findings.html",
            self_url=base_url + "findings.xml", author=config.name,
            updated=max((f["recorded_on"] for f in dated), default="1970-01-01"),
            entries=[FeedEntry(id=base_url + record_routes[f["id"]], title=f["conclusion"][:150], link=base_url + record_routes[f["id"]],
                               updated=f["recorded_on"], summary=f["conclusion"] + (f' Limits: {f["limitations"]}' if f.get("limitations") else "")
                               + (" Changed: " + "; ".join(f'{changed_label(c["record_id"])}: {shift(c)}' for c in f["changes"]) + "." if f.get("changes") else ""))
                     for f in dated[:50]])
    branding = config.raw.get("site", {})
    description = branding.get("description", "A public collection of people, records and research.") if isinstance(branding, dict) else "A public collection of people, records and research."
    person_titles = {url: person_name(pid) for pid, url in people_urls.items()}
    person_ids_by_path = {url: pid for pid, url in people_urls.items()}
    study_titles = {url: studies[sid]["title"] for sid, url in study_urls.items()}
    for path, content in pages.items():
        prefix = "../" if "/" in path else ""
        view, title = routes[path] if path in routes else ("study", study_titles[path]) if path in study_titles else extra_titles[path] if path in extra_titles else ("person", person_titles[path])
        person_attribute = f' data-person-id="{_text(person_ids_by_path[path])}"' if path in person_ids_by_path else ""
        nav = "".join(f'<a data-view="{v}" href="{prefix}{p}"' + (' aria-current="page"' if path == p else '') + f'>{t}</a>' for p, (v, t) in routes.items())
        # Dossiers need only the menu enhancement. Interactive pages share one
        # data script rather than embedding the whole collection in each page.
        # The paged pages of a large site are plain lists and need no data.
        interactive = "/" not in path and view in {"people", "tree", "timeline", "map", "compare", "connections", "sources", "studies", "overview"}
        data_script = f'<script defer src="{prefix}data/site-data.js"></script>' if interactive else ""
        payload = {"project": project["project"], "site": {"root": prefix}}
        corrections_link = f' · <a href="{prefix}corrections.html">Corrections</a>' if "corrections.html" in routes else ""
        canonical = f'<link rel="canonical" href="{_text(base_url + quote(path))}">' if base_url else ""
        outputs[path] = f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="{_text(description)}"><title>{_text(title)} — {_text(config.name)}</title>{canonical}<link rel="icon" href="{prefix}assets/favicon.svg"><meta name="theme-color" content="#193f33"><link rel="stylesheet" href="{prefix}assets/site.css">{data_script}<script defer src="{prefix}assets/site.js"></script><noscript><style>.site-sidebar nav{{display:grid!important}}#menu-toggle{{display:none!important}}</style></noscript></head><body data-view="{view}"{person_attribute}><a class="skip-link" href="#main-content">Skip to content</a><div class="site-shell"><aside class="site-sidebar" id="site-sidebar"><a class="site-brand brand" href="{prefix}index.html">{_text(config.name)}</a><p class="site-tagline">People · records · evidence</p><nav aria-label="Main navigation">{nav}</nav></aside><div class="site-content"><header class="site-header"><button id="menu-toggle" aria-controls="site-sidebar" aria-expanded="false">Menu</button><span>{_text(config.name)}</span></header><main id="main-content">{content}</main><footer class="site-footer"><p>Public research edition · <a href="{prefix}sitemap.html">Site index and downloads</a> · <a href="{prefix}evidence.html">Reading the evidence</a>{corrections_link}</p><p>Missing information is unknown; confidence and status remain attached to recorded claims.</p></footer></div></div><script type="application/json" id="site-data">{_json(payload)}</script></body></html>'
    # A moved page is a stub, not a route: it stays out of routes.json and the
    # sitemap, and asks search engines to index the current page instead.
    for old, new in moved.items():
        target = _text(new.split("/")[1])
        canonical = f'<link rel="canonical" href="{_text(base_url + quote(new))}">' if base_url else ""
        outputs[old] = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                        f'<meta name="robots" content="noindex"><meta http-equiv="refresh" content="0; url={target}"><title>Page moved — {_text(config.name)}</title>{canonical}'
                        '<link rel="icon" href="../assets/favicon.svg"><link rel="stylesheet" href="../assets/site.css"></head><body><main id="main-content">'
                        f'<h1>This person\'s page has moved</h1><p>Their page is now <a href="{target}">{_text(person_titles[new])}</a>. Please update any link or bookmark.</p></main></body></html>')
    if moved:
        outputs["data/redirects.json"] = json.dumps(dict(sorted(moved.items())), indent=2) + "\n"
    if moved and base_url:
        # Hosts that read this file answer the old address with a real 301
        # (Netlify only with "301!", as the stub exists; see deployment.md).
        root = urlsplit(base_url).path
        outputs["_redirects"] = "".join(f"{root}{old} {root}{new} 301\n" for old, new in sorted(moved.items()))
    asset_root = Path(__file__).with_name("web")
    for filename in ASSETS:
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
