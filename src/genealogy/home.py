"""The home page's static family sun: a small, server-drawn preview of the tree page's live view."""
from __future__ import annotations

from html import escape
import math
from typing import Any

SUN_GENERATIONS = 3  # rings drawn around the person with the most recorded descendants
SUN_SLICES = 180  # a ring that would take the drawing past this many slices is counted, not drawn
SUN_LINES = 6  # colours for the lines from each child, as on the tree page's family sun
CENTRE, RING = 46, 40


def sun_tree(pid: str, children: Any, order: Any, generations: int = SUN_GENERATIONS) -> dict[str, Any]:
    """The person's descendants to ``generations`` as nested nodes. A person reached by a
    second line is drawn once, where first met, so a recorded loop never repeats."""
    seen = {pid}

    def grow(person: str, gen: int) -> dict[str, Any]:
        node = {"id": person, "gen": gen, "kids": [], "size": 1}
        if gen < generations:
            for child in sorted(children.get(person, ()), key=order):
                if child not in seen:
                    seen.add(child)
                    kid = grow(child, gen + 1)
                    node["kids"].append(kid)
                    node["size"] += kid["size"]
        return node
    return grow(pid, 0)


def rings(tree: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """Each generation's nodes with their angles; a slice's angle is its share of the descendants."""
    out: list[list[dict[str, Any]]] = []

    def lay(node: dict[str, Any], a0: float, a1: float, line: int) -> None:
        node.update(a0=a0, a1=a1, line=line)
        if node["gen"]:
            while len(out) < node["gen"]:
                out.append([])
            out[node["gen"] - 1].append(node)
        a = a0
        for i, kid in enumerate(node["kids"]):
            width = (a1 - a0) * kid["size"] / (node["size"] - 1)
            lay(kid, a, a + width, i % SUN_LINES if not node["gen"] else line)
            a += width
    lay(tree, -math.pi / 2, math.pi * 1.5, 0)
    return out


def _point(r: float, a: float) -> str:
    return f"{r * math.cos(a):.1f},{r * math.sin(a):.1f}"


def _arc(r0: float, r1: float, a0: float, a1: float) -> str:
    if a1 - a0 > math.tau - 1e-6:  # a whole ring: two half-circles each way, cut out by even-odd filling
        return f"M{r1},0A{r1},{r1} 0 1 1 {-r1},0A{r1},{r1} 0 1 1 {r1},0ZM{r0},0A{r0},{r0} 0 1 0 {-r0},0A{r0},{r0} 0 1 0 {r0},0Z"
    large = 1 if a1 - a0 > math.pi else 0
    return f"M{_point(r1, a0)}A{r1},{r1} 0 {large} 1 {_point(r1, a1)}L{_point(r0, a1)}A{r0},{r0} 0 {large} 0 {_point(r0, a0)}Z"


def sun_svg(drawn: list[list[dict[str, Any]]], total: int) -> str:
    """The rings as a decorative SVG; the page gives the text alternative beside it."""
    size = CENTRE + len(drawn) * RING + 4
    paths = []
    for g, ring in enumerate(drawn, 1):
        r0, r1 = CENTRE + (g - 1) * RING, CENTRE + g * RING
        opacity = f"{max(.55, 1 - (g - 1) * .18):.2f}"
        paths += [f'<path d="{_arc(r0, r1, n["a0"], n["a1"])}" fill-rule="evenodd" class="home-sun-slice sun-line-{n["line"]}" fill-opacity="{opacity}"/>'
                  for n in ring]
    return (f'<svg class="home-sun" viewBox="{-size} {-size} {2 * size} {2 * size}" width="{2 * size}" height="{2 * size}" aria-hidden="true" focusable="false">'
            + "".join(paths) + f'<circle r="{CENTRE - 4}" class="sun-centre"/>'
            + f'<text y="2" text-anchor="middle" class="home-sun-count">{escape(f"{total:,}")}</text>'
            + f'<text y="17" text-anchor="middle" class="home-sun-noun">{"descendant" if total == 1 else "descendants"}</text></svg>')


def file_size(size: int) -> str:
    """A download's size as readers write it: "840 bytes", "12 KB", "1.4 MB"."""
    if size < 1000:
        return f"{size:,} bytes"
    if size < 1_000_000:
        return f"{size / 1000:.0f} KB"
    return f"{size / 1_000_000:.1f} MB"


def priority_map(points: list[tuple[int, str, float, float, bool]], prefix: str = "") -> str:
    """The places basemap cropped around the numbered study places, as on a study's locator.

    ``points`` are (number, name, latitude, longitude, broadly located); the numbered list
    beside the map is its text version, so the drawing is one image with a short label."""
    xy = [((lon + 180) * 960 / 360, (90 - lat) * 480 / 180) for _, _, lat, lon, _ in points]
    xs, ys = [x for x, _ in xy], [y for _, y in xy]
    # Padded around the markers, at least 7.5 degrees across, in the 2:1 shape of the basemap.
    w = min(max((max(xs) - min(xs)) * 1.3, (max(ys) - min(ys)) * 2.6, 20), 960)
    h = w / 2
    left = min(max((max(xs) + min(xs)) / 2 - w / 2, 0), 960 - w)
    top = min(max((max(ys) + min(ys)) / 2 - h / 2, 0), 480 - h)
    r = w * 0.022
    # Drawn last-numbered first, so a lower number is never hidden under a higher one.
    marks = "".join(f'<g class="home-priority-mark{" broad" if broad else ""}"><circle cx="{x:.3f}" cy="{y:.3f}" r="{r:.3f}"/>'
                    f'<text x="{x:.3f}" y="{y + r * .38:.3f}" text-anchor="middle" font-size="{r * 1.1:.3f}">{n}</text></g>'
                    for (n, _, _, _, broad), (x, y) in reversed(list(zip(points, xy))))
    label = f'Map of the {len(points)} {"place" if len(points) == 1 else "places"} with the most research, numbered as in the list'
    return (f'<svg class="home-priority-map" viewBox="{left:.1f} {top:.1f} {w:.1f} {h:.1f}" role="img" aria-label="{escape(label)}">'
            f'<rect width="960" height="480" fill="#e8efec"/><image href="{prefix}assets/world.svg" width="960" height="480"/>{marks}</svg>')
