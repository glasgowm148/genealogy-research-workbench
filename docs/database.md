# The research database

Every project has **one authoritative SQLite database** (default
`private/research.sqlite`). The database is the only place structured research
is edited. Everything else is either an external file it references by hash,
or an output generated from it.

| Data | Authority | How it is changed | Generated from it |
| --- | --- | --- | --- |
| People, names, places, events | database | `genealogy person/claim/…`, imports, proposals | site, exports |
| Sources, copies, records, citations, transcriptions, mentions | database | `genealogy source/record/citation/transcription/mention` | site, GEDCOM |
| Claims, evidence, assessments and their revisions | database | `genealogy relationship/claim/identify/evidence/assess` | site, GEDCOM, reports |
| Findings, questions, searches, hypotheses, studies, notes | database | `genealogy finding/question/search/hypothesis/note` | site, reports |
| Dependencies and review flags | database | `genealogy depend`, set automatically when premises change | `genealogy review list` |
| Workflow: proposals and their transitions | database | `genealogy proposal …`, `genealogy wikitree compare --record-proposal` | — |
| External tree state (WikiTree, OneTree, GEDCOM records) | database (observations) | imports, `genealogy wikitree capture` | three-way comparisons |
| Publication approvals | database | `genealogy approval add` | the public projection |
| Original captures, PDFs, images, long prose | files (`asset` rows hold path, SHA-256, access) | `genealogy asset add`, `genealogy note add --file` | — |
| Configuration and presentation | `genealogy.toml`, `templates/`, `theme/`, `content/` | edit the files | — |
| Website (`dist/`), JSON/CSV/GeoJSON/GEDCOM downloads | **generated** | `genealogy build`, `genealogy export` | — |
| Native export, backups | **generated, private** | `genealogy native export`, `genealogy backup create` | restoration |

A database records consistency (references, uniqueness, revisions, who changed
what); it does not decide historical truth. Contradictory evidence and
unresolved alternatives are ordinary research material.

## Model

The schema (`src/genealogy/store/migrations/0001_initial.sql`) is ordinary
relational tables. The core distinctions:

- **Source → holding → copy → record → mention.** A source is the work or
  collection; a holding is a repository's catalogue reference; a copy is one
  captured or inspected copy (two copies sharing a catalogue reference stay
  two rows, and a copy can be `derived_from` another, so repeated information
  is not counted as independent); a record is one entry or document; a
  mention is a participant as written. A record and its mentions exist before
  anyone is identified.
- **What a document says** (`documentary_relation`: "Isaac, son of the
  testator") is separate from **who the participants were** (identity claims:
  mention → person, any number of competing candidates) and from **the working
  conclusion** (relationship claims) and from **what an external tree asserts**
  (`external_observation`, claims with `origin = imported`).
- **Claims** state one proposition. A relationship claim has a child (or first
  party), a relative and that relative's role (`father`, `mother`, `parent`,
  `spouse`, `partner`, `sibling`) plus an optional relation type (biological,
  adoptive, step, foster…). Two candidate fathers are two claims. A wife is not
  made a mother: that needs its own claim.
- **Assessments** belong to a claim and a scope (`project` by default; another
  researcher gets their own scope). Each change adds a revision; earlier
  revisions are history. A revision keeps the project's own status word and
  grade label (with the vocabulary it belongs to), an optional standard
  confidence, an optional estimate **with its kind** (normally `subjective`),
  reasoning, limitations, dates and the tree attachment status, which is not
  belief. Estimates are never invented, defaulted, maximised or averaged.
  The reverse view ("Wren's child is Isaac") is derived from the same
  assessment and has no value of its own.
- **Dependencies** record that a conclusion rests on a premise at a revision.
  Revising or withdrawing the premise flags the dependent for review
  (`genealogy review list`); confidence is never recalculated.
- **Workflow** (proposals and their events) and **publication** (approvals)
  are separate tables from historical assertions.

Every addressable row is registered in `entity`, so links from findings,
questions, studies and notes to any entity are enforced foreign keys. Ids are
opaque and permanent; WikiTree ids, former ids, redirects and GEDCOM UIDs are
mappings in `external_id`, and existing public paths are kept in `route_alias`.
A merge (`Research.merge_people`) moves references and records them for
`undo_merge`.

## Writing safely

- Foreign keys are enforced on every connection; WAL mode; `synchronous=FULL`.
- `Store.write(actor=…, reason=…, tool=…, source=…)` is one short
  `BEGIN IMMEDIATE` transaction with a change set and an audit row per
  mutation. A failure rolls everything back, audit rows included.
- Updates state the revision they were based on. An assessment that exists
  needs `--expected-revision`; a stale value fails with the current record
  (`StaleRevisionError`) so the change can be rebased.
- A busy database fails after 5 s with "being written by another process".
- Never keep a write transaction open while browsing, downloading, calling a
  model or waiting for a person: prepare the change, then write it.
- Bulk or agent-written changes go through a **proposal** file
  (`docs/proposals.md` format, see `genealogy proposal check|diff|apply`):
  every operation names the revision it expects; apply re-checks all of them
  in one transaction and records the proposal as proposed → approved → applied.

Python code uses the same services as the CLI:

```python
from genealogy.store import Research, open_project

with open_project("my-family") as project:
    research = Research(project.store)
    with project.store.write(actor="me", reason="baptism found") as tx:
        claim = research.relationship_claim(tx, child_id=ada, relative_id=wren, role="father")
        research.assess(tx, claim, new=True, status="probable", estimate_percent=70,
                        estimate_kind="subjective", reasoning="Baptism names Wren as father.")
```

## Files

Files never live in database rows. `asset` rows hold the root, path, size,
SHA-256, kind, access and provenance. A **managed** file is copied into
`private/assets/<sha[:2]>/<sha><suffix>`, flushed and verified *before* its
row is committed, so an interrupted operation leaves at most an unreferenced
copy (reported by `genealogy asset verify` as an orphan), never a row pointing
at a missing file. Files can also be referenced where they are, under a
configured `[storage.asset_roots]` name; machine-specific locations go in an
untracked `genealogy.local.toml`. Captures are immutable: `genealogy db check`
reports any whose bytes changed, and a changed file loses any exact-file
publication approval because approvals match the SHA-256.

## Publication

`genealogy.store.projection.public_case` is the single public projection;
every public output (site pages, search index, feeds, sitemap, maps, JSON/CSV/
GeoJSON/GEDCOM downloads, copied files) is built from it. Only rows whose own
`access` is `public` are candidates; people must be deceased, or born more than
`[privacy] living_birth_years` (default 120) before the build year with no
living indication; anything naming, citing or linking an omitted entity is
omitted with it; transcription text needs a public, non-withdrawn
transcription; external ids are published only for systems named in
`[publication] external_id_systems` (default WikiTree, FamilySearch); files are
copied only under an active exact-file approval whose hash matches the current
bytes. The site's own export gate then runs again. `genealogy build` scans the
staged site for every withheld id, external id, name, file name and file hash,
and refuses to replace the previous site if any appears. The omissions are
written to the private build report (`private/exports/last-build-report.json`).

## Builds

`genealogy build` renders into a fresh `.<output>.staging` directory from one
read snapshot of the database, `genealogy.toml` and approved files. It never
reads earlier output, fetches data or writes research. A clean build replaces
the previous one; the previous output is kept until then. A directory that was
not made by a workbench build is never replaced. Set `[site] build_date` for
byte-identical rebuilds.

## Versions and upgrades

- Database schema version 1 (`genealogy db status`). A newer workbench applies
  numbered migrations with `genealogy db migrate`, which backs the database up
  first. A database written by a newer workbench is refused with an
  instruction to upgrade.
- Native export format `genealogy-native` version 1.
- Legacy JSON research cases (`cases/*.json`, workbench ≤ 0.8) are moved into
  the database by `genealogy upgrade`. Case files are left untouched; records
  sharing an id across cases become one entity, and differing copies are kept
  as `legacy_item` conflicts. After upgrading, case files are no longer read or
  written; `genealogy case create` is refused.

## Commands

```text
genealogy init DIR [--name NAME]          new project with its database
genealogy --project DIR db status|check|migrate|init
genealogy --project DIR upgrade           legacy JSON cases → database
genealogy --project DIR import FILE [--publish-deceased] [--update | --lineage NAME]
genealogy --project DIR person add NAME [--record-defined] [--external wikitree:Ada-1]
genealogy --project DIR source add TITLE [--repository R] [--catalogue-ref REF]
genealogy --project DIR record add TYPE --title T [--source S] [--date D] [--summary S]
genealogy --project DIR citation add --source S [--record R] [--locator L]
genealogy --project DIR transcription add|revise|withdraw …
genealogy --project DIR mention add RECORD NAME [--role ROLE]
genealogy --project DIR identify MENTION PERSON [--status WORD]
genealogy --project DIR relationship add CHILD ROLE RELATIVE
genealogy --project DIR claim add PERSON PREDICATE VALUE
genealogy --project DIR assess CLAIM [--expected-revision N] [--status S] [--estimate P] [--reasoning R]
genealogy --project DIR history CLAIM
genealogy --project DIR evidence add CLAIM --citation C [--stance opposes]
genealogy --project DIR depend DEPENDENT PREMISE;  review list;  review ack ID --expected-revision N
genealogy --project DIR finding add ID TEXT …;  search add ID TEXT --result R --for ID
genealogy --project DIR question add TEXT [--about ID] [--resume-when W]
genealogy --project DIR hypothesis add TEXT [--kind identity] [--about ID]
genealogy --project DIR note add [TEXT | --file F] [--about ID]
genealogy --project DIR asset add FILE [--root NAME] [--about ID];  asset verify
genealogy --project DIR approval add FILE PUBLIC-PATH --authority WHO;  approval list
genealogy --project DIR proposal check|diff|apply FILE
genealogy --project DIR wikitree capture FILE --captured-on DATE [--accept-baseline]
genealogy --project DIR wikitree compare PROFILE LOCAL.json [--record-proposal]
genealogy --project DIR show ID;  publication [--year Y]
genealogy --project DIR build [--output DIR];  export json|csv|ndjson|geojson|gedcom
genealogy --project DIR gedcom export FILE [--version 7.0|5.5.1] [--private]
genealogy --project DIR native export FILE [--package];  native import FILE NEW.sqlite
genealogy --project DIR backup create [DEST] [--exclude-root NAME];  backup verify B;  backup restore B NEWDIR
```

Wherever a command takes an entity id it also accepts `SYSTEM:VALUE`, for
example `wikitree:Ada-12`.
