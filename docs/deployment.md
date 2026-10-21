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
```

To invite corrections, give a contact. With one set, the build adds a **Corrections** page (`corrections.html`, linked from the menu and every footer) explaining what a useful correction contains, and each person's page gains a **Suggest a correction** link:

```toml
[site]
contact_email = "corrections@example.org"            # one address
contact_url = "https://example.org/family/contact"  # https only
corrections_note = "Replies can take a few weeks."   # optional, shown as written
```

Either contact is enough. With `contact_email`, the person's link opens an email whose subject is `Correction: <name> (<record ID>)`; with `base_url` also set, the message starts with the page address. With only `contact_url`, the link leads to the Corrections page. The contact is taken only from these settings, never from the case, and it is public: use an address you are happy to publish. `corrections_note` is used only when a contact is set. Remove the settings and rebuild to take the page and links down.

When a site has more than one record type, the sources page groups sources by their recorded `source_type`, printed as written with a capital first letter ("Parish register"); types written in different styles, such as `parish_register` and "Parish register", are one type. To give a type a reader's label, or a caution printed at the top of its section, add a table per type. The key uses lower-case letters, digits, `_` or `-`, and each table takes `label`, `note` or both:

```toml
[source_types.banns]
label = "Marriage banns"
note = "Banns alone do not prove a wedding took place."
```

`[project].case_directory` and `default_case` select the case; use the CLI `--case` option for a different one. Existing catalogue/maps/timelines format/output settings control compatible standalone exports as well as the cohesive website built by the CLI.

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
| `catalogue.html` | Search, surname, year and evidence filters, sort and pagination; the surname filter and search fold the spellings listed under `[names.variants]` into one surname. **Research filters** narrow it further, on public records only: recorded sex (the first sex claim not rejected; offered when someone has one), no parent recorded, has recorded children, no recorded spouse or partner (a disproved link counts for none of these), birth and death year ranges (from the person's birth or death event; the event-year range still matches any event), and an event place (any part of the name of any place in the person's events). Every search, filter and sort is kept in the page address, for example `catalogue.html?surname=Fable&sex=F&birth_from=1800&no_parent=1`, so a filtered view can be bookmarked or shared; the keys are `q`, `surname`, `sex` (`F`, `M`, another recorded value, or `not-recorded`), `birth_from`, `birth_to`, `death_from`, `death_to`, `place`, `no_parent`, `has_children`, `no_spouse` (`1` when ticked), `year_from`, `year_to`, `evidence` and `sort`. A value the catalogue does not offer is ignored |
| `people/p-<hash>.html` | Stable person dossier. Without notes, it opens with sentences written from the public record ("Ada Fable was born ABT 1801 in Invented Parish, and died 12 MAR 1870 in Invented Town. This page lists Tobin Fable and Wren Fable as parents, one spouse or partner and two children."); a missing event or relative leaves its clause out. Then a **Latest finding** box (the newest dated public finding about the person and "Research last recorded", the latest of those findings and related studies), and the family (parents, partners, children, siblings, each with its reason and supporting records, and rejected links set apart), events, claims, sources and research An **On this page** menu links each section that has something in it (kept in view on screens 1450px and wider), and an **Explore** line opens the family tree focused on the person (`tree.html?person=<id>`), Connections and Compare with the person chosen (`?a=<id>`), and the catalogue filtered to their surname |
| `people/p-<hash>.html` (moved) | For each former ID of a public person ([Record a merge or a changed ID](research.md#record-a-merge-or-a-changed-id)), a small page at the old address that sends readers on to the current dossier; marked `noindex`, with a canonical link to the current page when `site.base_url` is set. Not listed in `data/routes.json` or `sitemap.xml` |
| `tree.html` | Whole-tree canvas, family focus and branch cards |
| `timeline.html` | Recorded life events with filters |
| `places.html` | Place/event list and supplied-coordinate map |
| `sources.html` | Sources and their citations, grouped by record type (`source_type`) with a table of types; each source lists what it is cited for: the people whose claims rest on it (with the claims, such as "birth, occupation"), the findings citing it and the family links whose claims cite it, the first 20 of each then a count; past 300 sources, `sources/type-<type>.html` lists each type's sources |
| `research.html` | Claims, evidence, hypotheses, questions and findings, outstanding work first, then a **Research log** of the newest 50 searches with the total; each dossier's **Research log** lists every search made for that person ([Log a search](research.md#log-a-search)) |
| `branches.html` | Surname groups and connected groups of recorded relatives, linked to the catalogue and tree; spellings listed under `[names.variants]` share one group, with the spellings recorded ([Group spellings of a surname](research.md#group-spellings-of-a-surname)) |
| `studies.html`, `studies/s-<hash>.html` | Written research studies with rationale, conclusion, a chronology of the linked people's dated events (static SVG with a text version) and linked subjects, and, where recorded, the households and groups compared with a diagram of how they connect (static SVG with a text version) and the records still to inspect, most recently updated first, with a search by title, summary or linked person; past 300 studies, `studies/page-<n>.html` lists them by title |
| `findings.html`, `findings/page-<n>.html` | Dated log of findings, newest first (`findings.xml` Atom feed when `site.base_url` is set); past 30 findings, archive pages numbered from the earliest |
| `compare.html` | Side-by-side person comparison; `?a=<id>&b=<id>` chooses the people |
| `connections.html` | Shortest path through recorded relationships; `?a=<id>&b=<id>` chooses the people |
| `evidence.html` | Reader's guide to every confidence, status and relationship label, with what each grade usually rests on and one public example from the site |
| `sitemap.html` | Human-readable routes, person index and downloads |
| `corrections.html` | How to send a correction and what to include (only when `site.contact_email` or `site.contact_url` is set) |
| `sitemap.xml` | Search-engine sitemap (only when `site.base_url` is set) |
| `data/site-data.js` | The fields of the public records that the interactive pages read, shared by every interactive page; `data/site.json` has every public field |
| `data/` | Public JSON, CSV, GeoJSON, GEDCOM 5.5.1 (`public-tree.ged`) and route index |
| `data/redirects.json` | Each moved person address and the address it now leads to (only when a public person has former IDs) |
| `_redirects` | The same moves as permanent (301) redirects, one `/people/p-<old>.html /people/p-<new>.html 301` line each, prefixed with the path of `site.base_url` (only when `site.base_url` is set and a public person has former IDs) |
| `places/pl-<hash>.html` | Stable page for each place with a public event or a sub-place ([Place hierarchy](research.md#place-hierarchy)): the places it lies within (from `parent_id`, linked, broadest first), the places within it, coordinates and precision with a small marker map on the bundled basemap, the people with events there (linked, with each event's kind and date, in date order), the surnames recorded there with counts, the span of recorded years, and the studies that list or mention it. Each list stops at 200 entries (fewer when its entries are long) and counts the rest, so the page stays under 100 KB. Every link to a place leads here; a place without a page keeps its entry on `places.html` (or its region page) |

Every page and download is generated from the same privacy-filtered projection, so a withheld person is absent from HTML, search, maps, data files, the GEDCOM download and the sitemap alike. Labels such as "Unassessed tree link" or "tree-marked uncertain" link to `evidence.html`, which explains them.

A connection follows stored relationships and their uncertainty; it is not proof of kinship. The coordinate map uses a bundled low-resolution Natural Earth basemap; it is not a street map. Missing coordinates remain missing. Approximate dates retain their supplied text.

All site assets are local and links are relative. Test both desktop and mobile before publication. Core records remain readable without JavaScript, while filtering, graph exploration, comparison and connection tools need it. The interactive pages load one shared `data/site-data.js` script, so they also work when the folder is opened directly from disk (`file://`) and the browser caches the data once for the whole site.

### Large sites

Past 300 people, events, places, sources or studies (300 relationships, claims or findings for those lists), a site stops writing every record into its tool pages, so each page stays small:

- The catalogue writes its first 100 people; `catalogue/page-<n>.html` holds the rest in name order. With JavaScript, search, filters and pages cover everyone from `data/site-data.js`.
- The timeline lists its decades; `timeline/<decade>s.html` (and `timeline/undated.html`) holds each decade's events, and an event's link points there. With JavaScript, the timeline search covers every event.
- Places lists its countries and regions; `places/<region>.html` holds each region's places, 100 to a page. The map is drawn by the script.
- Sources writes its first 100 sources; `sources/page-<n>.html` holds the rest in title order. Its record-type table links to `sources/type-<type>.html` (then `type-<type>--2.html` and on), which list each type's sources in title order, 100 to a page. With JavaScript, the search covers every source.
- Studies writes the 100 most recently updated studies; `studies/page-<n>.html` lists every study in title order, starting at `studies/page-1.html` because the studies page itself is in date order. Each study keeps its own page. With JavaScript, the search covers every study's title, summary and linked people; the shared data never carries a study's body.
- Person menus on the tree, compare and connections pages are filled by the script. Relationships and claims are shown on their subject's page, and findings on the findings log and its archive.

The paged pages are plain lists that need no script.

## Check the links before publishing

```sh
genealogy --project my-family check-links
```

This checks every internal link, image, script, refresh redirect and `#anchor` in `dist/` the way a plain static server resolves them, and exits non-zero when something points at nothing. A link to `page` that exists only as `page.html` is reported, because many hosts do not add the extension. When you add your own hand-written pages, record any known breakage once with `--baseline known-links.json --update-baseline`. From then on only new breakage fails, and later updates only ever remove pairs. The checker is also importable as `genealogy.sitecheck` for projects with their own site builders.

## Rebuilds

Builds overwrite their owned outputs. The `.genealogy-site-manifest.json` tracks generated files, allowing obsolete person pages to be removed when people become private or are removed, and a moved page, `data/redirects.json` or `_redirects` once no former ID needs it. Unrelated files outside that manifest are preserved. Do not hand-edit generated person pages; put durable research into the case.

Deployed hosting must also remove obsolete pages. Replace the old site directory with the reviewed new build, or use your host’s delete/synchronization option. Simply copying new files over an old deployment can leave a withdrawn person page accessible.

## Static hosting

Deploy only the contents of the reviewed `dist/` folder to your static host or web server. The toolkit needs no application server, database, external scripts, font provider, analytics, or geocoding service. It supports a URL subdirectory because links are relative.

Moved person pages work on any host: the page at the old address sends the browser on. Hosts that read a `_redirects` file can answer with a real 301 redirect instead, which search engines follow best. Cloudflare Pages applies these rules even though the moved page exists. Netlify serves an existing file in preference to a rule, so there the moved page still does the redirect; to have Netlify answer with the 301, change `301` to `301!` in your deployment step. The build owns `_redirects` while it writes one, so keep other redirect rules in your host's own configuration.

The package does not automatically deploy, create hosting accounts, upload research, or edit WikiTree. Keep the local upload server private; it is not a production hosting server. The same distinction applies to research bundles: a complete bundle is private, even if its corresponding website is public.
