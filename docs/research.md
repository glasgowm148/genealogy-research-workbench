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
  --confidence probable --status reviewed --recorded-on 2026-10-19 --sensitivity public \
  --limitations "The register is a later copy; the original was not seen." \
  --cite citation:register-1801 --kind vital
```

`--recorded-on` dates the finding, so it appears in the site's **Latest findings** log, newest first. Undated findings are listed after the dated ones. With `site.base_url` set, the build also writes an Atom feed, `findings.xml`. A log of more than 30 dated findings opens with the newest 30. Older findings are on archive pages (`findings/page-N.html`) numbered from the earliest finding, so a finding never changes page as newer ones are added.

- `--limitations` says what the finding does not establish. It is shown beside the conclusion, never merged into it.
- `--cite` links a record the finding rests on directly, when there is no claim-level evidence. Repeat it for several. A finding that cites a private or restricted record is withheld from the site, like any record that depends on one.
- `--kind` is your own grouping, such as `vital`, `relationship` or `record`, shown as a label.
- `--change RECORD_ID:BEFORE:AFTER` records that this finding reassessed a relationship or claim, for example `--change rel:ada-parent:possible:documented`. BEFORE and AFTER are confidence values or [your own grade](#use-your-own-grades) keys; leave BEFORE empty (`rel:ada-parent::probable`) for a link the finding added. Repeat it for several. In the case JSON each change is `{"record_id", "before", "after", "note"}`, and `note` can say briefly what moved it.

A change keeps the assessment's history beside the record: the dossier's family row, or the claim, reads "Changed from Possible to Documented, 2026-09-08", linked to the finding, with your grade's wording where the value is a grade. The findings log, the research notebook and the Atom feed show each change as "Possible → Documented". A finding that changed a private or withheld link or claim is withheld with it.

Edit the record first, then record the finding. `genealogy validate` and every build check that the latest change to a record (by `--recorded-on`; undated findings count as the earliest, and on the same date the finding recorded last wins) ends at the record's current `grade`, or its `confidence` when it has no grade. `finding add` checks the case with the new finding, so it can record the change that an edited record now needs.

Use real IDs already in the selected case; validation rejects missing references. Confidence values are `documented`, `probable`, `possible`, `disproved`, and `unknown`. A finding’s confidence does not automatically change a relationship. Preserve alternative hypotheses and record what could change the assessment.

The strict CLI adds records; it does not silently replace an existing record. To revise an existing assessment, back up the case and edit its typed JSON (or use the Python API), then run `genealogy validate`. Review all changed public text before rebuilding. To refresh a tree from a newer export while keeping the findings, questions and studies you added, use `genealogy import FILE --update` ([details](imports.md#importing-again)).

## Record a research question

A research question names something you have not yet established, such as a missing parent, a date or a household. While its `status` is `open` or `draft`, two optional fields record your plan for answering it:

- `resolves`: what evidence would answer the question;
- `next_record`: the next record you mean to check.

```json
{"id": "question:ann-parents", "question": "Who were Ann's parents?", "related_ids": ["gedcom:person:I1"],
 "status": "open", "priority": "high",
 "resolves": "A baptism or marriage entry that names Ann's father and mother.",
 "next_record": "Harbour parish register, baptisms 1835–1840", "sensitivity": "public"}
```

```sh
genealogy --project my-family record add ResearchQuestion --input question.json
```

On **Research** and in the dossier of each related person, an open question shows "What would answer this" and "Next record to check". A blank field prints "Not yet identified", so readers can see which steps are still unplanned. The toolkit never fills a blank in for you. Once a question is answered or closed (any other status), neither line is shown. There is no `question add` command: add questions with `record add`, and to change one, edit its JSON.

## Assess a relationship

Imported links stay "Unassessed tree link" until you assess them. To record an assessment, edit the relationship's `confidence` (`documented`, `probable`, `possible` or `disproved`) and, if you work with probabilities, an `estimate` from 1 to 99 per cent. Record the reasoning in a claim, evidence assessment or finding linked to it. The site shows, for example, "Probable (70%)". A percentage is your assessed estimate: imports never set one, and import review clears any it finds.

A sibling can be recorded directly, for example when a will or census names a brother but neither parent is yet in the project: add a relationship with `"kind": "sibling"` (or `half_sibling`). It is symmetric, like a spouse link, so the order of `subject_id` and `object_id` does not matter, and it is assessed like any other link, with a `confidence`, `estimate`, `grade` and linked claims. Both dossiers list it under **Siblings** as "Recorded sibling", or with the siblings found through shared parents when they also have parents in common; a disproved link stays only under **All recorded relationships**.

### Use your own grades

If your project already grades evidence in its own words, such as "strongly supported" or "uncertain", define those grades in `genealogy.toml`, in the order you want them listed. Each one says which standard grade it counts as:

```toml
[grades.strongly_supported]
label = "Strongly supported"
meaning = "Several independent records agree, short of proof."
confidence = "probable"

[grades.uncertain]
label = "Uncertain"
meaning = "The records are too thin to weigh either way."
confidence = "possible"
```

Then give a relationship, claim, evidence assessment or hypothesis a `grade` as well as its `confidence`, for example `"confidence": "probable", "grade": "strongly_supported"`. The site prints your label ("Strongly supported (80%)"), and **Reading the evidence** lists each grade with its meaning and the standard grade it counts as. Filters, colours and the tree use the standard grade.

`genealogy validate` and every build reject a grade that `genealogy.toml` does not define, or whose `confidence` differs from the one the grade counts as.

## Group spellings of a surname

Records spell the same family name in different ways: Fable, Fabel, Faible. Keep each name as the record gives it, and list the spellings that belong together in `genealogy.toml`, under the spelling you want them grouped as:

```toml
[names.variants]
Fable = ["Fabel", "Faible"]
```

On the site, **Families & branches** then has one Fable row covering everyone recorded under any of the three, with a line such as "Recorded as Fabel (3), Fable (1), Faible (1)"; its link opens the catalogue filtered to the whole group, and the catalogue's surname menu lists "Fable (5, incl. Fabel, Faible)". A catalogue search for any one spelling finds people recorded under the others. Dossiers, the catalogue's Surname column and the downloads keep each spelling as recorded.

Case does not matter, and a spelling can belong to one surname only: `genealogy.toml` is rejected if a spelling is listed under two surnames, or if a surname you group under is also listed as another one's variant. The list is published with the site in `data/site-data.js`, except for a surname that no public person is recorded under, so list spellings, not people.

## Summarise a record

A citation can carry an `abstract`: your reading of the record, in your own words. Write what the record states (who, what, when, where, and the relationships it names) and keep your interpretation for claims, evidence assessments and findings:

```json
{"id": "citation:baptism-1837", "source_id": "source:parish-register", "locator": "entry 75",
 "abstract": "Baptism of Ann, born 17 January 1837, daughter of Robert and Mary, of Harbour Row.", "sensitivity": "public"}
```

The site shows it with the citation as "Abstract" on the source's page. Unlike a quotation or transcription, it is your own text, so a public citation publishes it.

An evidence assessment can carry a `limitation`: what this record cannot show for the claim, such as an age it does not state or a later copy standing in for the original:

```json
{"id": "evidence:marriage-household", "claim_id": "claim:ann-married", "citation_id": "citation:census-1891",
 "assessment": "Names Ann as the head's wife.", "limitation": "The return states no marriage date.", "sensitivity": "public"}
```

Each claim on a person's page shows its records as one table: **Record** (the source and locator, linked to the citation), **What it says** (the abstract, or else the quotation or transcription), **Assessment** ("Supports" or "Challenges", your assessment and its grade) and **Limitation**. A record has one row per assessment of it; a record the claim cites that no assessment covers yet shows "Not yet assessed". Evidence is private by default, so give an assessment `"sensitivity": "public"` to publish it and its limitation.

### Explain a record type

Give each source a `source_type` that names the kind of record, such as `parish_register`, `banns` or `census_transcription`. The sources page groups sources by type, and each source lists the people, findings and family links that cite it. When a kind of record is easily over-read, add a caution under `[source_types]` in `genealogy.toml`; it is printed at the top of that type's sources:

```toml
[source_types.banns]
label = "Marriage banns"
note = "Banns alone do not prove a wedding took place."
```

`genealogy validate` and every build reject a key that is not lower-case letters, digits, `_` or `-`, an empty `label` or `note`, and any other setting.

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

Pipe tables work too: a header row, a separator row such as `|---|---|`, then one row per line. Cells may contain links and `[[record]]` references. Raw HTML is shown as text. Validation rejects a reference to a record that does not exist. A study is published only when it is public and **every** record it lists in `related_ids` or references in its prose is public, so it can never reveal a living or withheld person. Its free text is still your responsibility: the toolkit cannot detect a name typed as plain text.

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

Sites with their own builders can reuse smaller pieces: `genealogy.labels` for the reader vocabulary, `genealogy.markup` for escaped research prose, `genealogy.sitecheck` for link checking, and `genealogy.feeds.atom_feed` for a deterministic Atom feed whose `updated` time comes from the newest entry rather than the build.

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
