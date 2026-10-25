"""TOML configuration for a reusable genealogy project."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib
import re
from typing import Any, ClassVar, Mapping
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit

from .models import Confidence


DEFAULT_PROJECT_NAME = "Genealogy research project"
# The catalogue's address parameters (docs/deployment.md, catalogue.html), the
# ones a saved ``[[catalogue.views]]`` query may use. The older keys the page
# rewrites on opening (``birth_from``, ``no_parent``) are left out: a view
# using one could never be marked current.
CATALOGUE_PARAMETERS = frozenset((
    "q", "first", "last", "last_scope", "name", "sex", "exact", "spouse", "father", "mother", "child", "sibling",
    "date_type", "year_from", "year_to", "place_type", "place", "region", "exclude_place", "study", "record_type",
    "quality", "evidence", "born_surname", "married_surname", "suffix", "missing_father", "missing_mother",
    "has_children", "no_spouse", "no_external", "needs_update", "change_relationship", "change_action",
    "change_confidence", "sort", "group_location", "group_branch", "group_surname", "location_detail", "view", "surname"))


def exact_bool(value: Any, *, setting: str) -> bool:
    """Accept TOML booleans only; truthy strings are unsafe configuration."""
    if type(value) is not bool:
        raise ValueError(f"{setting} must be a boolean")
    return value


def _table(data: Mapping[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"[{name}] must be a table")
    return dict(value)


def safe_relative_path(value: Any, *, setting: str) -> str:
    """Validate a project-owned path without resolving filesystem links."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{setting} must be a non-empty relative path")
    path = Path(value)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ValueError(f"{setting} must stay within the project directory")
    return value


def _control(value: str) -> bool:
    return any(unicodedata.category(c) in ("Cc", "Cf") for c in value)


def site_contact(site: Any) -> dict[str, str]:
    """The validated corrections contact from ``[site]``: ``email``, ``url`` and ``note``, when set.

    Only these explicit settings are used; a contact is never derived from the case.
    """
    if not isinstance(site, dict):
        raise ValueError("[site] must be a table")
    contact = {}
    if "contact_email" in site:
        value = site["contact_email"]
        # One plain address: list separators and URL delimiters would change
        # what a mailto: link means.
        if (not isinstance(value, str) or value.count("@") != 1 or _control(value)
                or re.search(r"[\s,;<>\"()\[\]\\?#&%/:]", value) or not all(value.split("@"))):
            raise ValueError("site.contact_email must be one email address, such as corrections@example.org")
        contact["email"] = value
    if "contact_url" in site:
        value = site["contact_url"]
        try:
            parsed = urlsplit(value) if isinstance(value, str) and not _control(value) and not re.search(r"\s", value) else None
        except ValueError:
            parsed = None
        if not parsed or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("site.contact_url must be an absolute https URL without credentials")
        contact["url"] = value
    if "corrections_note" in site:
        if not isinstance(site["corrections_note"], str):
            raise ValueError("site.corrections_note must be a string")
        if site["corrections_note"].strip():
            contact["note"] = site["corrections_note"]
    return contact


HOME_LIST_LIMIT = 12  # studies or resource cards the home page may be given; more would crowd it


def _home_link(value: Any, *, setting: str) -> str:
    """An absolute http(s) URL without credentials, or a path inside the built site such as "sources.html"."""
    if not isinstance(value, str) or not value or _control(value) or re.search(r"[\s<>\"'\\]", value):
        raise ValueError(f"{setting} must be an http(s) URL or a page of the site")
    try:
        parsed = urlsplit(value)
    except ValueError:
        parsed = None
    if parsed and parsed.scheme in ("http", "https") and parsed.hostname and not (parsed.username or parsed.password):
        return value
    # A site path stays inside the site wherever it is hosted: no scheme, no host, not rooted, never "..".
    if parsed and not parsed.scheme and not parsed.netloc and not value.startswith("/") and ".." not in parsed.path.split("/"):
        return value
    raise ValueError(f"{setting} must be an http(s) URL or a page of the site")


def home_settings(home: Any) -> dict[str, Any]:
    """The validated ``[home]`` table: ``featured_question`` (a question ID, or None for the
    highest-priority open one), ``studies`` (study IDs, or None for the newest three) and
    ``resources`` (``{label, title, description, url}`` cards; title and url required)."""
    if not isinstance(home, dict):
        raise ValueError("[home] must be a table")
    unknown = set(home) - {"featured_question", "studies", "resources"}
    if unknown:
        raise ValueError(f"home has unknown settings: {', '.join(sorted(unknown))}")
    text = lambda value: isinstance(value, str) and bool(value.strip()) and not _control(value)
    question = home.get("featured_question")
    if question is not None and not text(question):
        raise ValueError("home.featured_question must be a research question ID")
    studies = home.get("studies")
    if studies is not None and (not isinstance(studies, list) or not all(text(s) for s in studies)
                                or len({s.strip() for s in studies}) != len(studies) or len(studies) > HOME_LIST_LIMIT):
        raise ValueError(f"home.studies must be a list of up to {HOME_LIST_LIMIT} different study IDs")
    resources = home.get("resources", [])
    if not isinstance(resources, list) or len(resources) > HOME_LIST_LIMIT:
        raise ValueError(f"home.resources must be a list of up to {HOME_LIST_LIMIT} tables")
    cards = []
    for n, card in enumerate(resources, 1):
        setting = f"home.resources[{n}]"
        if not isinstance(card, dict):
            raise ValueError(f"{setting} must be a table")
        unknown = set(card) - {"label", "title", "description", "url"}
        if unknown:
            raise ValueError(f"{setting} has unknown settings: {', '.join(sorted(unknown))}")
        for name in ("label", "title", "description"):
            if (name in card or name == "title") and not text(card.get(name)):
                raise ValueError(f"{setting}.{name} must be a non-empty string")
        cards.append({**{name: card[name].strip() for name in ("label", "title", "description") if name in card},
                      "url": _home_link(card.get("url"), setting=f"{setting}.url")})
    return {"featured_question": question.strip() if question is not None else None,
            "studies": [s.strip() for s in studies] if studies is not None else None, "resources": cards}


@dataclass(slots=True)
class ProjectConfig:
    DEFAULT_NAME: ClassVar[str] = DEFAULT_PROJECT_NAME
    project_id: str | None = None
    name: str = DEFAULT_PROJECT_NAME
    case_directory: str = "cases"
    default_case: str | None = None
    privacy: dict[str, Any] = field(default_factory=dict)
    catalogue: dict[str, Any] = field(default_factory=dict)
    maps: dict[str, Any] = field(default_factory=dict)
    timelines: dict[str, Any] = field(default_factory=dict)
    adapters: dict[str, Any] = field(default_factory=dict)
    exports: dict[str, Any] = field(default_factory=dict)
    research: dict[str, Any] = field(default_factory=dict)
    paths: dict[str, Any] = field(default_factory=dict)
    # A project's own confidence grades, in display order: key -> {label,
    # meaning, confidence}. ``confidence`` is the standard grade it counts as;
    # an optional ``basis`` says what the grade usually rests on.
    grades: dict[str, dict[str, str]] = field(default_factory=dict)
    # ``[names] variants``: canonical surname -> other spellings found in records.
    names: dict[str, Any] = field(default_factory=dict)
    # Reader wording per ``Source.source_type``: key -> {label, note}. The note
    # is a caution printed with that type's sources ("banns alone do not prove
    # a wedding took place"). Keys match source types written in any style.
    source_types: dict[str, dict[str, str]] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, path: str | Path = "genealogy.toml") -> "ProjectConfig":
        with Path(path).open("rb") as handle:
            data = tomllib.load(handle)
        project = _table(data, "project")
        config = cls(
            project_id=project.get("id"),
            name=project.get("name", DEFAULT_PROJECT_NAME),
            case_directory=project.get("case_directory", "cases"),
            default_case=project.get("default_case"),
            privacy=_table(data, "privacy"),
            catalogue=_table(data, "catalogue"),
            maps=_table(data, "maps"),
            timelines=_table(data, "timelines"),
            adapters=_table(data, "adapters"),
            exports=_table(data, "exports"),
            research=_table(data, "research"),
            paths=_table(data, "paths"),
            grades=_table(data, "grades"),
            names=_table(data, "names"),
            source_types=_table(data, "source_types"),
            raw=data,
        )
        config.validate()
        return config

    def boolean(self, section: str, key: str, default: bool) -> bool:
        values = getattr(self, section)
        value = values.get(key, default)
        return exact_bool(value, setting=f"{section}.{key}")

    def validate(self) -> None:
        safe_relative_path(self.case_directory, setting="project.case_directory")
        site_contact(self.raw.get("site", {}))
        self.dna_heading  # validates [site] dna_heading
        self.brand  # validates [site] brand_name and brand_caption
        home_settings(self.raw.get("home", {}))
        for key in ("allow_living", "allow_licensed", "allow_restricted"):
            if key in self.privacy:
                exact_bool(self.privacy[key], setting=f"privacy.{key}")
        for section in ("catalogue", "maps", "timelines"):
            values = getattr(self, section)
            if "enabled" in values:
                exact_bool(values["enabled"], setting=f"{section}.enabled")
        if "duplicates" in self.research:
            exact_bool(self.research["duplicates"], setting="research.duplicates")
        if "directory" in self.exports:
            safe_relative_path(self.exports["directory"], setting="exports.directory")
        for format_name in ("json", "ndjson", "csv", "geojson"):
            if format_name in self.exports:
                safe_relative_path(self.exports[format_name], setting=f"exports.{format_name}")
        for key, grade in self.grades.items():
            setting = f"grades.{key}"
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", key):
                raise ValueError(f"{setting}: a grade key uses lower-case letters, digits, '_' or '-'")
            if not isinstance(grade, dict):
                raise ValueError(f"[{setting}] must be a table")
            unknown = set(grade) - {"label", "meaning", "confidence", "basis"}
            if unknown:
                raise ValueError(f"{setting} has unknown settings: {', '.join(sorted(unknown))}")
            for name in ("label", "meaning"):
                if not isinstance(grade.get(name), str) or not grade[name].strip():
                    raise ValueError(f"{setting}.{name} must be a non-empty string")
            if "basis" in grade and (not isinstance(grade["basis"], str) or not grade["basis"].strip()):
                raise ValueError(f"{setting}.basis must be a non-empty string")
            if grade.get("confidence") not in {c.value for c in Confidence}:
                raise ValueError(f"{setting}.confidence must be one of: {', '.join(c.value for c in Confidence)}")
        seen: dict[str, str] = {}
        for key, wording in self.source_types.items():
            setting = f"source_types.{key}"
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", key):
                raise ValueError(f"{setting}: a source type key uses lower-case letters, digits, '_' or '-'")
            if not isinstance(wording, dict):
                raise ValueError(f"[{setting}] must be a table")
            unknown = set(wording) - {"label", "note"}
            if unknown:
                raise ValueError(f"{setting} has unknown settings: {', '.join(sorted(unknown))}")
            if not wording:
                raise ValueError(f"{setting} needs a label or a note")
            for name in wording:
                if not isinstance(wording[name], str) or not wording[name].strip():
                    raise ValueError(f"{setting}.{name} must be a non-empty string")
            # "parish_register" and "parish-register" match the same sources.
            same = key.replace("_", "-")
            if same in seen:
                raise ValueError(f"{setting} names the same source type as source_types.{seen[same]}")
            seen[same] = key

        self.catalogue_views  # validates [[catalogue.views]]
        unknown = set(self.names) - {"variants", "surname"}
        if unknown:
            raise ValueError(f"names has unknown settings: {', '.join(sorted(unknown))}")
        self.name_variants  # validates [names.variants]
        # The catalogue's wording: "connected with the Fable surname", "No confirmed WikiTree link".
        for setting, value in (("names.surname", self.names.get("surname")), ("site.tree_name", (self.raw.get("site") or {}).get("tree_name"))):
            if value is not None and (not isinstance(value, str) or not value.strip() or _control(value)):
                raise ValueError(f"{setting} must be a non-empty string")

    @property
    def name_variants(self) -> dict[str, str]:
        """Every listed spelling, canonical ones included, casefolded -> canonical surname."""
        variants = self.names.get("variants", {})
        if not isinstance(variants, dict):
            raise ValueError("[names.variants] must be a table")
        folded: dict[str, str] = {}
        for canonical, spellings in variants.items():
            setting = f"names.variants.{canonical}"
            if not canonical.strip():
                raise ValueError("names.variants: a canonical surname must be non-empty")
            if not isinstance(spellings, list) or not all(isinstance(s, str) and s.strip() for s in spellings):
                raise ValueError(f"{setting} must be a list of non-empty strings")
            # One spelling, in any case, belongs to one surname only; otherwise
            # the grouping would depend on the order of genealogy.toml.
            for spelling in (canonical, *spellings):
                owner = folded.setdefault(spelling.casefold(), canonical)
                if owner != canonical:
                    raise ValueError(f"{setting}: {spelling!r} is already listed under {owner!r}")
        return folded

    @property
    def catalogue_views(self) -> list[tuple[str, str]]:
        """``[[catalogue.views]]``: saved catalogue searches as (label, query), the query re-encoded the way the page writes it."""
        views = self.catalogue.get("views", [])
        if not isinstance(views, list):
            raise ValueError("catalogue.views must be a list of tables ([[catalogue.views]])")
        result: list[tuple[str, str]] = []
        for number, view in enumerate(views, 1):
            setting = f"catalogue.views[{number}]"
            if not isinstance(view, dict):
                raise ValueError(f"{setting} must be a table with a label and a query")
            unknown = set(view) - {"label", "query"}
            if unknown:
                raise ValueError(f"{setting} has unknown settings: {', '.join(sorted(unknown))}")
            label, query = view.get("label"), view.get("query")
            if not isinstance(label, str) or not label.strip() or len(label.strip()) > 60 or _control(label):
                raise ValueError(f"{setting}.label must be a non-empty string of at most 60 characters")
            if not isinstance(query, str) or not query or _control(query) or re.search(r"[\s#?]", query):
                raise ValueError(f"{setting}.query must be a query string such as no_external=1, without '?', '#' or spaces")
            try:
                pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True)
            except ValueError:
                raise ValueError(f"{setting}.query must be name=value pairs joined by '&', such as no_external=1&sex=F") from None
            keys = [key for key, _ in pairs]
            unknown = sorted(set(keys) - CATALOGUE_PARAMETERS)
            if unknown:
                raise ValueError(f"{setting}.query uses parameters the catalogue does not read: {', '.join(unknown)}")
            if len(keys) != len(set(keys)) or not all(value.strip() for _, value in pairs):
                raise ValueError(f"{setting}.query must give each parameter once, with a value")
            # The page marks the view whose query its address carries, in any order; two views with one query would both match.
            if any(set(pairs) == set(parse_qsl(other)) for _, other in result):
                raise ValueError(f"{setting}.query repeats an earlier view's query")
            result.append((label.strip(), urlencode(pairs)))
        return result

    @property
    def catalogue_surname(self) -> str | None:
        """``[names] surname``, else the first surname grouped under ``[names.variants]``; None when neither is set."""
        surname = self.names.get("surname")
        return surname.strip() if isinstance(surname, str) and surname.strip() else next(iter(self.names.get("variants") or {}), None)

    @property
    def tree_name(self) -> str | None:
        """``[site] tree_name``: the online tree the people's external identifiers belong to, e.g. "WikiTree"."""
        value = (self.raw.get("site") or {}).get("tree_name")
        return value.strip() if isinstance(value, str) and value.strip() else None

    @property
    def dna_heading(self) -> str:
        """``[site] dna_heading``: the DNA page's title in the project's words ("Y-DNA"); "DNA" when unset."""
        value = (self.raw.get("site") or {}).get("dna_heading")
        if value is not None and (not isinstance(value, str) or not value.strip() or _control(value) or len(value.strip()) > 60):
            raise ValueError("site.dna_heading must be a non-empty string of at most 60 characters")
        return value.strip() if value is not None else "DNA"

    @property
    def brand(self) -> tuple[str, str]:
        """The sidebar's wordmark: ``[site] brand_name`` set large ("Glasgow") over ``brand_caption`` ("Surname
        Project"). Unset, the project's name is the wordmark and the caption is the site's tagline."""
        site = self.raw.get("site") or {}
        values = []
        for key, default, limit in (("brand_name", self.name, 120), ("brand_caption", "People · records · evidence", 60)):
            value = site.get(key)
            if value is not None and (not isinstance(value, str) or not value.strip() or _control(value) or len(value.strip()) > limit):
                raise ValueError(f"site.{key} must be a non-empty string of at most {limit} characters")
            values.append(value.strip() if value is not None else default)
        return values[0], values[1]

    def to_dict(self) -> dict[str, Any]:
        # Preserve project-defined extension sections so a toolkit upgrade does
        # not erase a consumer project's configuration vocabulary.
        data = {key: value for key, value in self.raw.items()}
        project = dict(data.get("project", {}))
        project.update({"id": self.project_id, "name": self.name,
                        "case_directory": self.case_directory,
                        "default_case": self.default_case})
        data["project"] = project
        data.update({"privacy": self.privacy, "catalogue": self.catalogue,
                     "maps": self.maps, "timelines": self.timelines,
                     "adapters": self.adapters, "exports": self.exports,
                     "research": self.research, "paths": self.paths})
        if self.grades:
            data["grades"] = self.grades
        if self.names:
            data["names"] = self.names
        if self.source_types:
            data["source_types"] = self.source_types
        return data
