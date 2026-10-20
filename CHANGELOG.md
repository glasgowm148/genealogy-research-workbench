# Changelog

## 0.4.1 — 20 October 2026

- The README and [Your first site](docs/first-site.md) install the toolkit from PyPI, so the PyPI project page shows the current instructions.

## 0.4.0 — 20 October 2026

- GEDCOM 7 `.gdz` archives import their `gedcom.ged` without unpacking. Media files are counted and kept only in the private archive copy.
- Importing a path that does not exist names the missing file instead of reporting a size limit.
- The local preview server now serves the CSV, GEDCOM and XML downloads it builds (previously 404).
- `genealogy.feeds.atom_feed` writes deterministic Atom feeds; the latest-findings feed gains a self link and full-text summaries.
- Releases publish to PyPI through a trusted-publishing workflow.
- A step-by-step guide, [Your first site](docs/first-site.md), from a tree export to a hosted site.

## 0.3.0 — 20 October 2026

Import
- GEDCOM follows its `HEAD.CHAR` declaration: UTF-8/UTF-16 with or without BOM, ANSI (Windows-1252), ANSEL, ASCII, MACINTOSH and ISO-8859; undecodable bytes are reported by line.
- Raw line breaks inside long notes (as written by WikiTree's GEDCOM export) are kept as continued text and reported instead of rejecting the file.
- Parent links keep their supplied nature (`PEDI`, `_FREL`/`_MREL`, `ADOP`, WikiTree non-biological) in `Relationship.pedigree`; the tree's own marks (WikiTree uncertain/confident/DNA confirmed, GEDCOM 7 `STAT`) in `Relationship.tree_status`, never raising confidence. `DISPROVEN` links are disproved and not published.
- Names keep `given`/`surname` parts, nicknames, married and other names; GEDCOM identifiers (`_UID`, `REFN`, `EXID`, `_FSFTID`, `AFN`, `WWW`), source `AUTH`/`PUBL`/call numbers, citation `QUAY`, GEDCOM 7 `SNOTE` and about 40 event types are imported. Unsupported structures are counted in one warning; `SSN`/`IDNO` are never imported.
- Burial or cremation records mark a person deceased. Invalid coordinates are reported and dropped rather than failing the import.
- OneTree: WikiTree `YYYY-00-00` dates and DataStatus guess/before/after qualifiers, `MiddleName`, `LastNameOther`, `Nicknames`, `IsLiving`, one relationship per couple, marriage events from spouse rows, hidden spouses kept private, one summary warning for relatives outside the export.
- `import --update` refreshes a previous import of the same tree and keeps research added to the case, refusing without changes if that research would be orphaned. `--update` and `--replace` first back up the previous case privately.

Publication
- An approximate birth (`ABT`/`EST`/`CAL`) is treated as up to ten years later for the 120-year rule; open-ended dates still need review. `genealogy.publication.is_historical_birth` exposes the rule.
- The recorded sex of eligible people is published as an unassessed tree assertion.

Website
- Dossiers have a family section (parents, partners and marriages, children, siblings) with roles, labels and a competing-parent-records notice.
- One labelled evidence vocabulary (`genealogy.labels`) and a reader's guide, `evidence.html`.
- Interactive pages share one `data/site-data.js` instead of embedding the dataset in every page (works from `file://`).
- Surname filter and column in the catalogue; outstanding research listed first.
- Public GEDCOM 5.5.1 download (`data/public-tree.ged`, `export gedcom`), and `sitemap.xml`/canonical links when `site.base_url` is set.

Research and website (continued)
- `Study` records: a written study with summary, rationale, a small escaped Markdown body with `[[record]]` references, a conclusion and linked subjects. Each study gets a page and an index entry, and dossiers link to it. A study is published only when every record it lists or references is public.
- `Finding.recorded_on` and `finding add --recorded-on` date findings. A **Latest findings** log lists them newest first, with an Atom feed when `site.base_url` is set.
- **Families & branches** page: surname groups with years, places and earliest people, plus connected groups of recorded relatives. The catalogue accepts `?surname=`/`?q=` and the tree accepts `?person=`.
- `Place.precision` (exact … country, or approximate). Broad locations are drawn as dashed rings and labelled on the map and place list.
- `genealogy check-links` and `genealogy.sitecheck`: a static-site link and anchor checker with a ratcheting baseline, extracted from the Glasgow project's release gate.

- Places are grouped by their broadest recorded jurisdiction ("…, Scotland"), with a country or region summary of places, coordinates, events and people. Nothing is looked up.
- `Relationship.estimate`: an optional assessed percentage (1–99), shown as "Probable (70%)". Imports never set it.
- Muted and eyebrow text colours now meet WCAG AA contrast. An opt-in axe-core browser check (`GENEALOGY_AXE_PATH`, run in CI) covers every page type at desktop and mobile widths.

Fixes
- The fictional demo stored parent links from parent to child, contrary to the documented child → parent direction, so its tree drew descendants as ancestors. It is regenerated.
- Browser tests no longer assume a macOS Chrome path (`GENEALOGY_BROWSER_EXECUTABLE`).
- `genealogy.dates` adds `year_of` and `wikitree_date`; sorting understands Julian/dual years, `circa`/`c.`, interpreted dates and month names.

Compatibility: cases gain optional fields (`Name.given/surname`, `Relationship.pedigree/tree_status`, `Source.author/publication`, `Finding.recorded_on`, `Place.precision`, `Relationship.estimate`) and a `Study` record type. Older 0.2 readers cannot load cases written with them. GEDCOM-imported people now record `living` as `"deceased"` rather than `false`. OneTree spouse relationship IDs are now one per couple, so re-import with `--replace` (not `--update`) if research refers to the old per-profile spouse IDs.

## 0.2.0 — 19 October 2026

- Standalone MIT-licensed package, Python 3.11+, wheel/source distribution metadata and CI.
- Local browser upload wizard and explicit file-import workflow for GEDCOM and OneTree JSON.
- Expanded GEDCOM events, coordinates, names, notes, sources and citations; OneTree wrappers, dictionaries, lists, spouses and parent links.
- Explicit publication review for basic deceased-person facts and optional source bibliography; protected material and raw input stay private.
- Connected offline website: people dossiers/search, whole tree, family focus, branches, timeline, coordinate map, sources, research, comparisons, connections and downloads.
- Linear-time bulk case insertion and bounded per-person pages for larger trees.
- Synthetic 42-person example, import fixtures, browser end-to-end tests and installed-wheel verification.
- Real-export compatibility checks; opaque external record IDs containing `VCF` no longer trigger the raw-genetic-field guard, while nested genetic payloads remain rejected.

## 0.1.0

Initial extracted research model, cases, privacy projection, platform adapters, basic views and Glasgow compatibility bridges. This version was used as a source snapshot by the Glasgow project.
