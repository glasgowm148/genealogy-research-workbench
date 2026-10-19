# Data and asset notices

The toolkit code and fictional examples are MIT licensed; see [LICENSE](LICENSE).

The offline world basemap in `src/genealogy/web/world.svg` is derived from Natural Earth 1:50m Admin 0 Countries, version 5.1.2. Natural Earth map data is [public domain](https://www.naturalearthdata.com/about/terms-of-use/). Made with Natural Earth.

- Dataset: [Natural Earth countries](https://www.naturalearthdata.com/downloads/50m-cultural-vectors/50m-admin-0-countries-2/).
- Pinned source: [v5.1.2 GeoJSON](https://github.com/nvkelso/natural-earth-vector/blob/v5.1.2/geojson/ne_50m_admin_0_countries.geojson).
- Conversion: only geometry, projected to a 900 × 450 equirectangular SVG; original attributes are omitted. The SVG metadata records the original GeoJSON SHA-256.
- Regenerate from an explicitly downloaded GeoJSON with `python tools/build_basemap.py INPUT.geojson src/genealogy/web/world.svg`. This maintenance command does not download anything.

Country geometry is a small-scale geographic overview, not a historical boundary source or precise address map. The toolkit does not geocode imported place labels. Imported documents, records, photographs and database contents retain their own rights and are not covered by the software licence.
