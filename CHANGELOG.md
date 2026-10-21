# Changelog

## Unreleased

- A recorded sibling link (`kind: "sibling"`, `half_sibling` and similar) now appears under **Siblings** on both dossiers with its own label, merged with any sibling found through shared parents, and the tree's family view draws it. A disproved link is listed only under **All recorded relationships**; the GEDCOM export still has no sibling record. See [Assess a relationship](docs/research.md#assess-a-relationship).
- The studies page can be searched by title, summary or the people a study links. Past 300 studies it writes the 100 most recently updated, `studies/page-<n>.html` lists every study by title, and the search covers every study from `data/site-data.js`, which carries no study bodies. The site index links to these pages instead of listing every study. See [Large sites](docs/deployment.md#large-sites).
- A research question can record what evidence would answer it (`resolves`) and the next record to check (`next_record`). An open question shows both on **Research** and in each related dossier, with "Not yet identified" for a blank. See [Record a research question](docs/research.md#record-a-research-question).
- A corrections page: set `contact_email` or an https `contact_url` under `[site]` (with an optional `corrections_note`) and the site gains `corrections.html`, explaining what a useful correction contains and asking for no details of living people, plus a footer link and a **Suggest a correction** link on every person's page that starts an email with the person's name and record ID. Without a contact there is no page and no link, and a rebuild removes them. See [Build and deployment](docs/deployment.md#configure-your-project).
- Each claim shows its records as one table: the record, what it says (its abstract or quotation), the assessment and the assessment's new optional `limitation`. A cited record nobody has assessed yet shows "Not yet assessed". See [Summarise a record](docs/research.md#summarise-a-record).
- Spellings of one surname can be grouped under `[names.variants]` in `genealogy.toml`, for example `Fable = ["Fabel", "Faible"]`. **Families & branches** shows one row for the group with the spellings recorded ("Recorded as Fabel (3), Faible (1)"), the catalogue's surname filter covers the whole group, and a catalogue search for any spelling finds the others. Names stay as recorded on dossiers and in the downloads. See [Group spellings of a surname](docs/research.md#group-spellings-of-a-surname).
- Each source on the sources page lists what it is cited for: the public people whose claims rest on its citations (with the claims, for example "Ada Fable — birth, occupation"), the findings citing it and the family links whose claims cite it, the first 20 of each and then a count. The sources page adds a **By record type** table (sources, citations and people cited per `source_type`) and groups the sources by type; past 300 sources, each type has its own pages, `sources/type-<type>.html`. `[source_types.<key>]` in `genealogy.toml` gives a type a `label` and a reader's caution (`note`). See [Explain a record type](docs/research.md#explain-a-record-type).
- A finding can record which relationship or claim it reassessed, and from what (`Finding.changes`, `finding add --change RECORD_ID:BEFORE:AFTER`). The family row or claim reads "Changed from Possible to Documented, 2026-09-08", linked to the finding, and the findings log, research notebook and Atom feed show "Possible → Documented". Validation checks that each value is a confidence or a defined grade and that a record's latest change ends at its current grade or confidence. A finding that changed a withheld record is withheld. See [Record a finding](docs/research.md#record-a-finding).

## 0.6.0 — 20 October 2026

- A citation can carry an `abstract`, your reading of the record in your own words; the site shows it with the citation. See [Summarise a record](docs/research.md#summarise-a-record).
- Projects can define their own confidence grades under `[grades]` in `genealogy.toml`, each counted as a standard grade. A relationship, claim, evidence assessment or hypothesis with a `grade` shows the project's wording, and **Reading the evidence** explains each grade. See [Use your own grades](docs/research.md#use-your-own-grades).
- Large sites stay quick: past 300 records, the catalogue, timeline, places and sources pages write one page of records and keep the rest on paged pages (`catalogue/page-<n>.html`, `timeline/<decade>s.html`, `places/<region>.html`, `sources/page-<n>.html`), while the script searches everyone from the shared data. Person menus, relationships, claims and findings no longer repeat on the tool pages. See [Large sites](docs/deployment.md#large-sites).
- `data/site-data.js` carries only the fields the pages read: under a third of its former size on a tree of 4,800 people. `data/site.json` still has every public field.
- A rebuild removes findings archive pages that a shorter log no longer needs.

## 0.5.0 — 20 October 2026

- Findings can state their limitations (`Finding.limitations`), cite records directly (`Finding.citation_ids`) and carry a project's own type (`Finding.kind`). The site shows all three; `finding add` takes `--limitations`, `--cite` and `--kind`. A finding citing a non-public record is withheld.
- Research prose supports pipe tables, including links and record references in cells.
- A findings log of more than 30 dated findings opens with the newest 30. Older ones move to archive pages numbered from the earliest finding, so their links stay stable. The home page lists the newest 10 findings.

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
