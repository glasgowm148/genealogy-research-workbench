"""Find internal links and asset references in a static site that point at nothing.

The checker walks every ``*.html`` file below a site root and resolves each
internal ``href``/``src``/``srcset``/``poster`` the way a plain static server
does: ``/x/`` needs ``x/index.html``; ``/x`` needs the file ``x`` or the
directory ``x/`` with an ``index.html``. A link that exists only as ``x.html``
is reported as ``html-fallback`` because many static servers do not add the
extension. External, ``mailto:``/``tel:``/``javascript:``/``data:`` and
same-page ``#…`` links are ignored, as are values inside scripts, styles,
text areas and comments. ``#fragment`` targets are checked against the
target page's ``id``/``name`` attributes.

A baseline of known (page, target) pairs lets a project ratchet: new broken
pairs fail, fixed ones can be removed, and the baseline never grows on update.
Project-specific behaviour (a site host, extra attributes, lazily inserted
fragments) is configured through :class:`LinkCheckOptions`.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from html import unescape
import json
import os
from pathlib import Path
import posixpath
import re
from typing import Any, Callable, Iterable
from urllib.parse import unquote, urljoin, urlsplit

_COMMENT = re.compile(r"<!--.*?-->", re.S)
_RAW_BODY = re.compile(r"(<(script|style|textarea)\b[^>]*>).*?</\2\s*>", re.I | re.S)
_TAG = re.compile(r"<([a-zA-Z][a-zA-Z0-9-]*)(\s[^>]*)>", re.S)
_BASE = re.compile(r"""<base\b[^>]*?\bhref\s*=\s*["']([^"']*)["']""", re.I)
_ID = re.compile(r"""\s(?:id|name)\s*=\s*["']([^"']+)["']""", re.I)
_SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "blob:", "about:", "sms:", "file:")
_TEMPLATE = ("${", "{{", "<%", "' +", "\" +")
_SKIP_TAGS = {"base", "form"}
BASELINE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class LinkCheckOptions:
    """How a particular site's links resolve.

    ``host`` is the site's own host name; absolute links to it (or to
    ``extra_hosts``) are checked like root-relative ones. ``attributes`` are the
    link-bearing attributes scanned. ``anchor_pages`` limits fragment checks to
    target pages whose path matches it (``None`` checks every page).
    ``id_list_attributes`` name attributes holding space-separated extra ids
    (for content inserted later by script). ``generated_prefixes`` are folders of
    hashed pages that are checked only when some other page links to them.
    ``base_for(relative_path, text)`` may return a different base URL for a
    page, for example a fragment inserted into another page. It must be a
    module-level function so it can be used by worker processes.
    """

    host: str = "site.invalid"
    extra_hosts: tuple[str, ...] = ()
    attributes: tuple[str, ...] = ("href", "src", "srcset", "poster")
    anchor_pages: str | None = None
    id_list_attributes: tuple[str, ...] = ()
    generated_prefixes: tuple[str, ...] = ()
    base_for: Callable[[str, str], str | None] | None = None
    local_hosts: frozenset[str] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "local_hosts", frozenset(h.casefold() for h in (self.host, *self.extra_hosts)))


def page_url(relative: str) -> str:
    """The URL path a static server gives a file below the site root."""
    if relative == "index.html":
        return "/"
    if relative.endswith("/index.html"):
        return "/" + relative[: -len("index.html")]
    return "/" + relative


def resolve(path: str, files: Iterable[str] | frozenset[str]) -> tuple[str | None, str]:
    """Return (file served for this URL path or None, how it resolved)."""
    decoded = unquote(path or "/")
    if not decoded.startswith("/"):
        decoded = "/" + decoded
    slash = decoded.endswith("/")
    normal = posixpath.normpath(decoded)
    if normal.startswith("//") or ".." in normal.split("/"):
        return None, "outside-site"
    rel = normal.lstrip("/")
    if rel in ("", "."):
        return ("index.html", "dir") if "index.html" in files else (None, "missing")
    if slash:
        candidate = rel + "/index.html"
        return (candidate, "dir") if candidate in files else (None, "missing")
    if rel in files:
        return rel, "file"
    if rel + "/index.html" in files:
        return rel + "/index.html", "dir-noslash"
    if rel + ".html" in files:
        return None, "html-fallback"
    return None, "missing"


def site_files(site_root: Path) -> frozenset[str]:
    files = []
    for directory, _, names in os.walk(site_root):
        prefix = Path(directory).relative_to(site_root).as_posix()
        prefix = "" if prefix == "." else prefix + "/"
        files.extend(prefix + name for name in names)
    return frozenset(files)


def _values(name: str, raw: str) -> list[str]:
    value = unescape(raw).strip()
    if name.lower() == "srcset":
        return [part.strip().split()[0] for part in value.split(",") if part.strip()]
    return [value]


_STATE: dict[str, Any] = {}


def _init(files: frozenset[str], options: LinkCheckOptions) -> None:
    _STATE["files"], _STATE["options"] = files, options
    names = "|".join(re.escape(name) for name in options.attributes)
    _STATE["attr"] = re.compile(rf"""(?:^|\s)({names})\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""", re.I)
    _STATE["lists"] = [re.compile(rf"""{re.escape(name)}\s*=\s*["']([^"']*)["']""", re.I) for name in options.id_list_attributes]
    _STATE["anchors"] = re.compile(options.anchor_pages) if options.anchor_pages else None


def scan(relative: str, site_root: str) -> dict[str, Any]:
    """Check one page: broken links, fragment references, its ids and references."""
    files, options = _STATE["files"], _STATE["options"]
    text = Path(site_root, relative).read_text(encoding="utf-8", errors="replace")
    base = options.base_for(relative, text) if options.base_for else None
    if base is None:
        base = f"https://{options.host}{page_url(relative)}"
        match = _BASE.search(text)
        if match:
            base = urljoin(base, unescape(match.group(1)).strip())
    clean = _RAW_BODY.sub(lambda m: m.group(1), _COMMENT.sub(" ", text))
    broken, anchors, refs, cache = [], [], set(), {}
    checked = internal = 0
    anchor_pages = _STATE["anchors"]
    for tag in _TAG.finditer(clean):
        name, attrs = tag.group(1).lower(), tag.group(2)
        if name in _SKIP_TAGS:
            continue
        for attr in _STATE["attr"].finditer(attrs):
            raw = next(group for group in attr.groups()[1:] if group is not None)
            for value in _values(attr.group(1), raw):
                checked += 1
                low = value.lower()
                if not value or value.startswith("#") or low.startswith(_SKIP_SCHEMES) or any(t in value for t in _TEMPLATE):
                    continue
                try:
                    parts = urlsplit(urljoin(base, value))
                except ValueError:
                    broken.append((name, attr.group(1).lower(), value[:300], value[:300], "invalid-url"))
                    continue
                if parts.scheme not in ("http", "https") or parts.netloc.casefold() not in options.local_hosts:
                    continue
                internal += 1
                path = parts.path or "/"
                if path not in cache:
                    cache[path] = resolve(path, files)
                target, how = cache[path]
                if target is None:
                    broken.append((name, attr.group(1).lower(), value[:300], unquote(path), how))
                    continue
                if options.generated_prefixes and target.startswith(options.generated_prefixes):
                    refs.add(target)
                if parts.fragment and target.endswith(".html") and target != relative and (anchor_pages is None or anchor_pages.fullmatch(target)):
                    anchors.append((target, unquote(parts.fragment), value[:300]))
    ids = None
    if relative.endswith(".html") and (anchor_pages is None or anchor_pages.fullmatch(relative)):
        found = set(_ID.findall(clean))
        for pattern in _STATE["lists"]:
            for listed in pattern.findall(clean):
                found.update(listed.split())
        ids = sorted(found)
    return {"page": relative, "broken": broken, "anchors": anchors, "ids": ids,
            "checked": checked, "internal": internal, "refs": sorted(refs)}


def check_site(site_root: Path, options: LinkCheckOptions | None = None, jobs: int | None = 1) -> dict[str, Any]:
    """Scan a site. ``broken`` rows have page, tag, attr, href, target and how."""
    options = options or LinkCheckOptions()
    site_root = Path(site_root)
    files = site_files(site_root)
    pages = sorted(f for f in files if f.endswith(".html"))
    jobs = jobs if jobs is not None else max(1, min(8, (os.cpu_count() or 2) // 2))
    if jobs <= 1:
        _init(files, options)
        results = [scan(page, str(site_root)) for page in pages]
    else:
        with ProcessPoolExecutor(max_workers=jobs, initializer=_init, initargs=(files, options)) as pool:
            results = list(pool.map(scan, pages, [str(site_root)] * len(pages), chunksize=64))
    # Generated pages under hashed names may be left over by earlier builds;
    # only those some ordinary page leads to can be reached by a reader.
    generated = options.generated_prefixes
    by_page = {result["page"]: result for result in results}
    reachable: set[str] = set()
    frontier = {ref for result in results if not (generated and result["page"].startswith(generated)) for ref in result["refs"]}
    while frontier:
        page = frontier.pop()
        if page not in reachable:
            reachable.add(page)
            frontier.update(ref for ref in (by_page.get(page) or {}).get("refs", []) if ref not in reachable)
    unreferenced = sorted(r["page"] for r in results if generated and r["page"].startswith(generated) and r["page"] not in reachable)
    skipped = set(unreferenced)
    broken, ids, anchor_refs = [], {}, []
    checked = internal = 0
    for result in results:
        if result["page"] in skipped:
            continue
        checked += result["checked"]
        internal += result["internal"]
        if result["ids"] is not None:
            ids[result["page"]] = set(result["ids"])
        for tag, attr, value, target, how in result["broken"]:
            broken.append({"page": result["page"], "tag": tag, "attr": attr, "href": value, "target": target, "how": how})
        anchor_refs.extend((result["page"], *ref) for ref in result["anchors"])
    missing_anchors = [{"page": page, "href": value, "target": target, "anchor": anchor}
                       for page, target, anchor, value in anchor_refs if anchor not in ids.get(target, set())]
    return {"site": str(site_root), "pages": len(pages), "files": files, "references_checked": checked,
            "internal_references": internal, "broken": broken, "anchor_references": len(anchor_refs),
            "missing_anchors": missing_anchors, "unreferenced_generated_pages": unreferenced}


def pairs_of(broken: Iterable[dict[str, Any]]) -> set[tuple[str, str]]:
    return {(row["page"], row["target"]) for row in broken}


def read_baseline(path: Path) -> set[tuple[str, str]] | None:
    if not Path(path).exists():
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {(page, target) for page, targets in (data.get("pairs") or {}).items() for target in targets}


def write_baseline(path: Path, pairs: set[tuple[str, str]], description: str | None = None) -> None:
    grouped: dict[str, list[str]] = {}
    for page, target in sorted(pairs):
        grouped.setdefault(page, []).append(target)
    payload = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "description": description or ("Known broken internal links as (source page, target path) pairs. "
                                        "The link check fails on any pair not listed here. Updating only removes pairs."),
        "count": len(pairs),
        "pairs": grouped,
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def ratchet(current: set[tuple[str, str]], baseline: set[tuple[str, str]] | None) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(new broken pairs, fixed baseline pairs). Without a baseline every pair is new."""
    if baseline is None:
        return sorted(current), []
    return sorted(current - baseline), sorted(baseline - current)
