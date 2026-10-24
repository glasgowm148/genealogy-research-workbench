# Glasgow site and workbench parity

The [Glasgow Surname Project](https://glasgow.phenotype.dev/) supplies the reference browsing experience. The reusable workbench builds that kind of site from any project's public research case. This comparison was reviewed against the local Glasgow builders and the live site on 23 October 2026.

| Area | Shared workbench capability | Recent improvement |
| --- | --- | --- |
| People | Detailed catalogue, dossiers, relatives, evidence and pending updates | Standalone catalogue also searches vital dates, places and relatives |
| Saved people | Local notebook, saved dossiers, compare two, JSON export | Available across pages, isolated by site; public index loads on demand |
| Family tree | Atlas, whole tree, family, branches, hourglass, sun and lanes | Existing generic views retained |
| Relationships | Grades, roles, rationale and supporting records | All additional supporting records can be opened |
| Timeline | Events, people, place and event-type search | Inclusive year filters, shareable addresses and clear action |
| Maps | Offline supplied coordinates, zoom/pan, precision and filters | Clearer control and marker labels |
| Sources | Source pages, cited-record table, readings and evidence | Record search includes everyone cited, beyond displayed names |
| Research | Questions, hypotheses, studies, findings and search history | Complete paged research log, including unattached searches |
| DNA | Optional public branch structure and documentary placements | Public branch-model CSV download |
| Getting started | GEDCOM/OneTree local upload, preview and privacy review | Clearer saved-project and publication guidance |
| Reader navigation | Search, grouped sidebar, mobile menu and no-JS pages | Escape, outside interaction and navigation close mobile menus |

## What remains project-owned

Glasgow's written research, curated branch names, historical gazetteer, surname-specific rules and source permissions remain in Glasgow. WikiTree profile drafts, amendment tooling, wikitext conversion and specialist genetic analysis are not generic imports. Importing a family tree cannot recreate assessments, studies or DNA placements that a researcher has not recorded. The workbench presents those records when supplied. Raw DNA, private people and protected source content remain outside public output.

This is feature reuse and improved parity, not a claim that two projects have identical content or every specialist workflow. The [Glasgow repository's detailed matrix](https://github.com/glasgowm148/glasgow-surname-ancestry/blob/main/docs/toolkit-parity.md) tracks its translator and local-only research mappings.

## Verify locally

Run `make check` for the core and privacy contracts. With the browser extra and Chromium installed, run `make browser-check` for cross-page notebook use, timeline state, map interaction, mobile navigation and the other reader workflows. Fixtures and screenshots use invented people only. See [development](development.md) and [deployment](deployment.md).
