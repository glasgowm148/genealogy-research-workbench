# Research recipes

A project’s `genealogy.toml` selects a durable case in `cases/`. Cases contain typed people, events, places, relationships, sources, citations, claims, evidence, hypotheses, questions and findings. IDs are stable; a parent edge points from child (`subject_id`) to parent (`object_id`).

## Inspect and develop a case

```sh
genealogy --project my-family case list
genealogy --project my-family record list --kind Person
genealogy --project my-family record show gedcom:person:I1
genealogy --project my-family search "harbour"
genealogy --project my-family report --format markdown --output research-brief.md
```

Create additional cases without automatically merging identities:

```sh
genealogy --project my-family case create locality-study --title "The harbour households"
genealogy --project my-family --case locality-study validate
```

Use `record add TYPE --input file.json` for a new strictly typed JSON record. For example, a reviewed bibliography entry:

```json
{
  "id": "source:example-register",
  "title": "Fictional register, 1800",
  "source_type": "register",
  "repository": "Invented Example Archive",
  "sensitivity": "public"
}
```

```sh
genealogy --project my-family record add Source --input source.json
```

A citation points to a `source_id`; a claim names its `subject_id`, predicate/value and `citation_ids`; an evidence assessment links a `claim_id` and `citation_id`. These are different records so an inherited assertion is not silently treated as proof. The fictional [demo generator](../examples/demo/create_demo.py) is a complete source-linked example using the Python API.

## Record a finding

```sh
genealogy --project my-family finding add finding:parentage \
  "The cited record supports the proposed parent link" \
  --related gedcom:person:I1 --evidence evidence:reviewed-entry \
  --confidence probable --status reviewed --recorded-on 2026-10-19 --sensitivity public
```

`--recorded-on` dates the finding, so it appears in the site's **Latest findings** log, newest first. Undated findings are listed after the dated ones. With `site.base_url` set, the build also writes an Atom feed, `findings.xml`.

Use real IDs already in the selected case; validation rejects missing references. Confidence values are `documented`, `probable`, `possible`, `disproved`, and `unknown`. A finding’s confidence does not automatically change a relationship. Preserve alternative hypotheses and record what could change the assessment.

The strict CLI adds records; it does not silently replace an existing record. To revise an existing assessment, back up the case and edit its typed JSON (or use the Python API), then run `genealogy validate`. Review all changed public text before rebuilding. To refresh a tree from a newer export while keeping the findings, questions and studies you added, use `genealogy import FILE --update` ([details](imports.md#importing-again)).

## Assess a relationship

Imported links stay "Unassessed tree link" until you assess them. To record an assessment, edit the relationship's `confidence` (`documented`, `probable`, `possible` or `disproved`) and, if you work with probabilities, an `estimate` from 1 to 99 per cent. Record the reasoning in a claim, evidence assessment or finding linked to it. The site shows, for example, "Probable (70%)". A percentage is your assessed estimate: imports never set one, and import review clears any it finds.

## Write a study

A study is the written account of one research question: why it was undertaken, what the records show and the current conclusion. Each study gets its own page, is listed on **Studies**, and is linked from the dossier of every person it concerns. Add one as a typed record:

```json
{
  "id": "study:harbour-households",
  "title": "Two households at the harbour",
  "summary": "Which household the 1841 child belongs to.",
  "rationale": "Two families used the same given names in the same decade.",
  "body": "## The records\n\nThe register names [[gedcom:person:I1]] and [[gedcom:person:I2|her brother]].\n\n- **Documented:** the baptism entry.\n- *Probable:* the census household.",
  "conclusion": "Probably the Quay Street household, pending [[question:census]].",
  "related_ids": ["gedcom:person:I1", "gedcom:person:I2", "question:census"],
  "status": "draft",
  "updated_on": "2026-10-19",
  "sensitivity": "public"
}
```

```sh
genealogy --project my-family record add Study --input study.json
```

The prose fields use a small Markdown subset:

- `##` headings, paragraphs, `-` and `1.` lists, and `>` quotations;
- `**strong**`, `*emphasis*` and `` `code` ``;
- `[label](https://…)` links;
- `[[record-id]]` or `[[record-id|label]]` references to any record in the case.

Raw HTML is shown as text. Validation rejects a reference to a record that does not exist. A study is published only when it is public and **every** record it lists in `related_ids` or references in its prose is public, so it can never reveal a living or withheld person. Its free text is still your responsibility: the toolkit cannot detect a name typed as plain text.

## Place precision

Coordinates supplied for a whole parish, county or country should not be read as an exact address. Set `precision` on a place to one of `exact`, `building`, `street`, `settlement`, `parish`, `district`, `county`, `region`, `country` or `approximate`. Places at parish level or broader are drawn as a dashed ring on the map, and every place says how precisely it is located. Imports leave `precision` unset; nothing is guessed.

## Python API

```python
from pathlib import Path
from genealogy import CaseStore, ProjectConfig, build_site

project = Path("my-family")
config = ProjectConfig.load(project / "genealogy.toml")
case = CaseStore(project / config.case_directory).load(config.default_case)
build_site(case, config, project / "dist")
```

`build_site` uses the same validated public projection as exports. `build_public_views` remains available for the smaller configured standalone catalogue/timeline/map renderers used by existing integrations. Platform adapters live under `genealogy.adapters`; core records do not depend on WikiTree.

## Portable handoffs and exports

```sh
genealogy --project my-family export json --output dist/research.json
genealogy --project my-family export ndjson --output dist/research.ndjson
genealogy --project my-family export csv --output dist/research.csv
genealogy --project my-family export geojson --output dist/places.geojson
genealogy --project my-family bundle --output private/handoff
genealogy --project my-family bundle --output private/handoff --verify
```

Public exports are filtered. The checksummed bundle contains the complete private case, claim/evidence/reference indexes, unresolved work and a Markdown handoff. Store it as private research. No command publishes a website or edits a collaborative tree automatically.
