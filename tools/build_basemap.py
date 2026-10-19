#!/usr/bin/env python3
"""Build a dependency-free equirectangular SVG from an explicit Natural Earth GeoJSON."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def render(raw: bytes) -> str:
    data = json.loads(raw)
    paths = []
    for feature in data['features']:
        geometry = feature['geometry']
        polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
        for polygon in polygons:
            rings = []
            for ring in polygon:
                points = [f'{(lon + 180) * 2.5:.2f},{(90 - lat) * 2.5:.2f}' for lon, lat, *_ in ring]
                rings.append('M' + 'L'.join(points) + 'Z')
            paths.append('<path d="' + ''.join(rings) + '"/>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 450" role="img" aria-label="Natural Earth world overview">'
            '<title>Made with Natural Earth — public-domain country geometry</title>'
            '<metadata>Source SHA256: ' + hashlib.sha256(raw).hexdigest() + '</metadata>'
            '<g fill="#d5decd" stroke="none" fill-rule="evenodd">' + ''.join(paths) + '</g></svg>\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(args.source.read_bytes()), encoding='utf-8')
