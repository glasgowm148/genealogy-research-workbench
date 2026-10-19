# Build and deployment

## Configure your project

`genealogy init` creates `genealogy.toml`. Change `[project].name` to your public project title. An optional description is supported:

```toml
[site]
description = "Our family history, its records, and the questions still open."
```

The title/description are public. Keep private personal information out of them. When the site will live at a known address, set it so the build also writes an XML sitemap and canonical links:

```toml
[site]
base_url = "https://example.org/family/"
``` `[project].case_directory` and `default_case` select the case; use the CLI `--case` option for a different one. Existing catalogue/maps/timelines format/output settings control compatible standalone exports as well as the cohesive website built by the CLI.

## Build and inspect

```sh
genealogy --project my-family validate
genealogy --project my-family build
python -m http.server 8000 --bind 127.0.0.1 --directory my-family/dist
```

`build --output OTHER_DIRECTORY` selects another output. Use a dedicated output folder, never a directory containing your raw inputs or case files.

| Route | Contents |
| --- | --- |
| `index.html` | Overview, counts and research entry points |
| `catalogue.html` | Search, surname, year and evidence filters, sort and pagination |
| `people/p-<hash>.html` | Stable person dossier: family (parents, partners, children, siblings), events, claims, sources and research |
| `tree.html` | Whole-tree canvas, family focus and branch cards |
| `timeline.html` | Recorded life events with filters |
| `places.html` | Place/event list and supplied-coordinate map |
| `sources.html` | Bibliography and citations |
| `research.html` | Claims, evidence, hypotheses, questions and findings, outstanding work first |
| `branches.html` | Surname groups and connected groups of recorded relatives, linked to the catalogue and tree |
| `studies.html`, `studies/s-<hash>.html` | Written research studies with rationale, conclusion and linked subjects |
| `findings.html` | Dated log of findings, newest first (`findings.xml` Atom feed when `site.base_url` is set) |
| `compare.html` | Side-by-side person comparison |
| `connections.html` | Shortest path through recorded relationships |
| `evidence.html` | Reader's guide to every confidence, status and relationship label |
| `sitemap.html` | Human-readable routes, person index and downloads |
| `sitemap.xml` | Search-engine sitemap (only when `site.base_url` is set) |
| `data/site-data.js` | The public dataset, shared by every interactive page |
| `data/` | Public JSON, CSV, GeoJSON, GEDCOM 5.5.1 (`public-tree.ged`) and route index |

Every page and download is generated from the same privacy-filtered projection, so a withheld person is absent from HTML, search, maps, data files, the GEDCOM download and the sitemap alike. Labels such as "Unassessed tree link" or "tree-marked uncertain" link to `evidence.html`, which explains them.

A connection follows stored relationships and their uncertainty; it is not proof of kinship. The coordinate map uses a bundled low-resolution Natural Earth basemap; it is not a street map. Missing coordinates remain missing. Approximate dates retain their supplied text.

All site assets are local and links are relative. Test both desktop and mobile before publication. Core records remain readable without JavaScript, while filtering, graph exploration, comparison and connection tools need it. The interactive pages load one shared `data/site-data.js` script, so they also work when the folder is opened directly from disk (`file://`) and the browser caches the data once for the whole site.

## Check the links before publishing

```sh
genealogy --project my-family check-links
```

This checks every internal link, image, script and `#anchor` in `dist/` the way a plain static server resolves them, and exits non-zero when something points at nothing. A link to `page` that exists only as `page.html` is reported, because many hosts do not add the extension. When you add your own hand-written pages, record any known breakage once with `--baseline known-links.json --update-baseline`. From then on only new breakage fails, and later updates only ever remove pairs. The checker is also importable as `genealogy.sitecheck` for projects with their own site builders.

## Rebuilds

Builds overwrite their owned outputs. The `.genealogy-site-manifest.json` tracks generated files, allowing obsolete person pages to be removed when people become private or are removed. Unrelated files outside that manifest are preserved. Do not hand-edit generated person pages; put durable research into the case.

Deployed hosting must also remove obsolete pages. Replace the old site directory with the reviewed new build, or use your host’s delete/synchronization option. Simply copying new files over an old deployment can leave a withdrawn person page accessible.

## Static hosting

Deploy only the contents of the reviewed `dist/` folder to your static host or web server. The toolkit needs no application server, database, external scripts, font provider, analytics, or geocoding service. It supports a URL subdirectory because links are relative.

The package does not automatically deploy, create hosting accounts, upload research, or edit WikiTree. Keep the local upload server private; it is not a production hosting server. The same distinction applies to research bundles: a complete bundle is private, even if its corresponding website is public.
