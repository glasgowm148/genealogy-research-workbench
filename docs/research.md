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
  --confidence probable --status reviewed --sensitivity public
```

Use real IDs already in the selected case; validation rejects missing references. Confidence values are `documented`, `probable`, `possible`, `disproved`, and `unknown`. A finding’s confidence does not automatically change a relationship. Preserve alternative hypotheses and record what could change the assessment.

The strict CLI adds records; it does not silently replace an existing record. To revise an existing assessment, back up the case and edit its typed JSON (or use the Python API), then run `genealogy validate`. Review all changed public text before rebuilding. `genealogy import --replace` replaces the selected imported case, including subsequent manual work; use a new case/project to compare fresh exports safely.

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
