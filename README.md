<div align="center">

<img src="docs/images/banner.svg" alt="Genealogy Research Workbench — your tree, your sources, your own site" width="100%">

**Turn a GEDCOM or OneTree export into a searchable family-history website.**

[Get started](#get-started) · [Take a look](#what-you-can-build) · [Import formats](docs/imports.md) · [Privacy](docs/privacy.md) · [Developer guide](docs/development.md)

</div>

Bring your own family tree. Build a site with people pages, an interactive whole tree, family branches, timelines, places, sources, comparisons, and connection paths. Keep the underlying research in portable, source-aware records that distinguish an imported assertion from an assessed conclusion.

Run everything on your own computer. The toolkit has **no runtime dependencies**, makes **no network requests during import or builds**, and generates ordinary HTML, CSS, JavaScript, and data files. You choose whether and where to publish them.

## What you can build

![The fictional Alderwick family research website](docs/images/overview.webp)

<table>
<tr>
<td width="50%" valign="top"><h3>Explore the whole tree</h3><img src="docs/images/tree.webp" alt="Interactive family tree with whole-tree, focus-family and branch views" width="100%"><p>Pan and zoom through every public person, narrow the birth-year range, focus on a family, and inspect the confidence attached to a recorded relationship.</p></td>
<td width="50%" valign="top"><h3>Find the person behind a name</h3><img src="docs/images/people.webp" alt="Searchable catalogue with dates, relatives, places, evidence and sorting" width="100%"><p>Search names, relatives, events, and places. Sort and paginate the catalogue, then open a dossier with family links, life events, citations, and research.</p></td>
</tr>
<tr>
<td width="50%" valign="top"><h3>Follow lives through time and place</h3><img src="docs/images/places.webp" alt="Offline overview of places using coordinates supplied in the imported data" width="100%"><p>Browse a filterable event timeline and an offline coordinate map. Places without coordinates remain in the place list; the toolkit does not guess their positions.</p></td>
<td width="50%" valign="top"><h3>Keep the evidence in view</h3><img src="docs/images/research.webp" alt="Research notebook with distinct claims, citations, assessments and open questions" width="100%"><p>Sources, claims, evidence assessments, hypotheses, questions, and findings stay distinct. Compare two people or trace a recorded relationship path.</p></td>
</tr>
</table>

The screenshots use the [fully fictional Alderwick demo](examples/demo/README.md), captured on 19 October 2026. They contain no real family data. Core people, source, and research content remains readable with JavaScript disabled; interactive tools use local JavaScript.

## Get started

You need **Python 3.11 or later**. From a downloaded or cloned toolkit checkout:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

On Windows, activate with `.venv\Scripts\activate` instead. No Node.js, database, account, browser automation, or API key is required to use the toolkit. It is also installable from a built wheel; see [installation](docs/development.md#install-and-test).

### Choose a file in your browser

```sh
genealogy --project my-workspace serve
```

Open the printed **http://127.0.0.1:8000/** URL. Choose your `.ged`, `.gedcom`, or OneTree `.json` file, enter a public project title, and create a preview. The file is sent only to the local server on your computer.

![The local GEDCOM and OneTree upload screen](docs/images/upload.webp)

Publication controls are explicit: permit reviewed basic deceased-person facts, and optionally reviewed source bibliography and citation locators. Living, unknown-status, explicitly private, restricted, and licensed material stays protected. Imported notes, quotations, and transcriptions are retained privately. See [the exact publication rules](docs/privacy.md).

The upload screen saves each import as its own project under `my-workspace/private/previews/`. Its preview link works while that server runs. Keep the saved project to continue researching or build its `dist/` folder for hosting. This command is a local desktop tool, not a public upload service.

### Or use the command line

```sh
genealogy init my-family --name "Our family history"
genealogy --project my-family import /path/to/family.ged \
  --publish-deceased --publish-reviewed-sources
genealogy --project my-family validate
genealogy --project my-family build
python -m http.server 8000 --bind 127.0.0.1 --directory my-family/dist
```

Open [localhost:8000](http://localhost:8000/). For OneTree, use the same command with a JSON export:

```sh
genealogy --project my-family import /path/to/one-tree.json --publish-deceased
```

Use a separate empty project for a different export. Import refuses to overwrite a populated case unless you explicitly pass `--replace`; an identical import with the same review options is a no-op. Omitting publication options keeps the imported records private, so the public site can be empty. Your original input is preserved privately and never modified.

### Try it before importing your family

From the toolkit checkout:

```sh
genealogy --project examples/demo build
python -m http.server 8000 --bind 127.0.0.1 --directory examples/demo/dist
```

The demo has 42 invented people, four generations, sources, uncertainty, and research questions. The [matching GEDCOM and OneTree files](examples/demo/input/) let you exercise the complete import workflow.

## How much of a research site can an export recreate?

| From a GEDCOM or OneTree export | With additional research |
| --- | --- |
| People, recorded names, supported event fields, and family links | Evidence-based identity and relationship assessments |
| Search, individual dossiers, whole tree, family focus, and branch cards | Written family studies and researched biographies |
| Timelines and place lists; maps when coordinates are supplied | Reviewed location coordinates and archive research |
| Comparison and shortest recorded connection paths | Resolution of namesakes and competing hypotheses |
| GEDCOM bibliography and citation locators after explicit review | Source transcriptions, images, and record-by-record analysis |
| Public JSON, NDJSON/CSV exports and place GeoJSON | Derived DNA findings supplied separately and reviewed |

An export supplies recorded tree assertions. It cannot manufacture missing sources, prove parentage, recover photographs, or infer DNA results. OneTree biography text is retained privately; arbitrary WikiTree markup is not converted into independently verified citations. [Supported formats and limitations](docs/imports.md) describe exactly what is imported.

This toolkit grew out of the Glasgow Surname Project. The reusable package includes the research model, adapters, local upload workflow, and general website. Glasgow’s historical research, surname rules, private records, custom editorial pages, and DNA studies remain in that project.

## Continue the research

```sh
genealogy --project my-family search "harbour"
genealogy --project my-family record list --kind Person
genealogy --project my-family record show gedcom:person:I1
genealogy --project my-family report --format markdown --output research-brief.md
genealogy --project my-family export json --output dist/research.json
genealogy --project my-family export csv --output dist/research.csv
genealogy --project my-family bundle --output private/research-bundle
genealogy --project my-family bundle --output private/research-bundle --verify
```

Typed records can be added with `record add TYPE --input record.json`. Findings can link related records and evidence; [research recipes](docs/research.md) cover citations, confidence, public review, and maintaining a case. A complete research bundle includes protected content and stays **private**, unlike a filtered website or public export.

## A portable project

```text
my-family/
├── genealogy.toml          Project name, paths, views and privacy settings
├── cases/                  Private typed research cases
├── private/imports/        Original exports and bounded import reports
└── dist/                   Generated, privacy-filtered website and downloads
```

All generated site links are relative, so the site works under a subdirectory and can be hosted on an ordinary static server. It needs no external scripts, maps, fonts, or analytics. Build into a dedicated output folder: generated files are replaced on rebuild, and obsolete generated dossiers are removed. Files outside the generated manifest are preserved.

## Documentation and development

| Guide | Contents |
| --- | --- |
| [Import formats](docs/imports.md) | GEDCOM subset, OneTree shapes, warnings, encoding, and limitations |
| [Privacy and publication](docs/privacy.md) | Review options, withheld content, private bundles, and local uploads |
| [Research recipes](docs/research.md) | Cases, records, sources, claims, findings, and exports |
| [Build and deployment](docs/deployment.md) | Branding, generated routes, static hosting, and rebuilds |
| [Developer guide](docs/development.md) | Tests, package builds, adapters, and release checklist |
| [Changelog](CHANGELOG.md) | Changes in the reusable package |

```sh
python -m pip install -e '.[dev]'
make check
python -m build
```

Browser checks are optional: install `.[browser]`, run `python -m playwright install chromium`, then `make browser-check`. Tests and demos use fictional records only.

Licensed under [MIT](LICENSE). The software license does not grant rights to records, photographs, or other material you import.
