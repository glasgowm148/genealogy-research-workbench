"""GeoJSON maps derived from research-place coordinates."""

from __future__ import annotations

from html import escape
import json
from typing import Any, Mapping


def geojson(project: Mapping[str, Any]) -> dict[str, Any]:
    features = []
    for place in project.get("places", []):
        coordinates = place.get("coordinates")
        if coordinates is None and place.get("longitude") is not None and place.get("latitude") is not None:
            coordinates = [place["longitude"], place["latitude"]]
        if not (isinstance(coordinates, (list, tuple)) and len(coordinates) == 2):
            continue
        try:
            longitude, latitude = float(coordinates[0]), float(coordinates[1])
        except (TypeError, ValueError):
            continue
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            continue
        properties = {key: value for key, value in place.items() if key != "coordinates"}
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [longitude, latitude]}, "properties": properties})
    return {"type": "FeatureCollection", "features": features}


def render_map_html(project: Mapping[str, Any]) -> str:
    """Render an offline SVG overview and coordinate table without map services."""
    data = geojson(project)
    title = escape(str(project.get("project", {}).get("title", "Genealogy research")))
    points = []
    rows = []
    for index, feature in enumerate(data["features"], start=1):
        longitude, latitude = feature["geometry"]["coordinates"]
        properties = feature.get("properties", {})
        name = str(properties.get("name") or properties.get("id") or f"Place {index}")
        x = (float(longitude) + 180) / 360 * 960
        y = (90 - float(latitude)) / 180 * 480
        points.append(
            f'<g><circle cx="{x:.2f}" cy="{y:.2f}" r="6"><title>{escape(name)}</title></circle>'
            f'<text x="{x + 9:.2f}" y="{y + 4:.2f}">{escape(name)}</text></g>'
        )
        rows.append(
            f'<tr><th scope="row">{escape(name)}</th><td>{latitude:.6g}</td><td>{longitude:.6g}</td>'
            f'<td><code>{escape(str(properties.get("id") or ""))}</code></td></tr>'
        )
    embedded = json.dumps(data, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} — places</title><style>body{{margin:0;background:#fbfaf6;color:#17212b;font:16px/1.5 system-ui,sans-serif}}main{{max-width:76rem;margin:auto;padding:2rem}}svg{{width:100%;height:auto;background:#e9f1ed;border:1px solid #c8d1cc}}circle{{fill:#9d3d2f;stroke:white;stroke-width:2}}text{{font-size:12px;paint-order:stroke;stroke:#e9f1ed;stroke-width:3px;stroke-linejoin:round}}.table-wrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;background:white;margin-top:1rem}}th,td{{padding:.6rem;text-align:left;border-bottom:1px solid #d7d3c8}}</style></head><body><main><h1>{title}: places</h1><p>This offline overview uses an equirectangular projection; coordinates remain available as GeoJSON exports.</p><svg viewBox="0 0 960 480" role="img" aria-label="Research place overview"><path d="M0 240H960M480 0V480" stroke="#b6c5bd" fill="none"/>{''.join(points)}</svg><div class="table-wrap"><table><thead><tr><th>Place</th><th>Latitude</th><th>Longitude</th><th>Record ID</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="4">No mapped places recorded.</td></tr>'}</tbody></table></div><script type="application/json" id="map-data">{embedded}</script></main></body></html>"""
