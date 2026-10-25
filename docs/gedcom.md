# GEDCOM import and export

GEDCOM is an **interchange format**. It is never the authority and never the
backup: use `genealogy native export --package` or `genealogy backup create`
for a complete copy. Specifications: [GEDCOM 7](https://gedcom.io/specifications/FamilySearchGEDCOMv7.html),
[technical FAQs](https://gedcom.io/techfaqs/); 5.5.1 is retained for older programs.

## Import (`genealogy import FILE`)

- Reads GEDCOM 5.5, 5.5.1 and 7 (`.ged`, `.gedcom`) and GEDCOM 7 archives
  (`.gdz`); declared encodings including ANSEL.
- The original file is kept unchanged as an immutable private asset, and
  **every GEDCOM record is kept verbatim** as an external observation, so
  structures the importer does not interpret (counted in the report's warnings)
  are preserved with their provenance rather than discarded.
- Imported relationships and events are recorded as **imported claims**
  (`origin = imported`), not conclusions. A `FAM` becomes separate parent claims
  for each partner and a spouse claim; `PEDI` becomes the relation type;
  `FAMC.STAT DISPROVEN` is kept as the tree's statement.
- Identity across files: people are matched to earlier imports by durable
  identifiers (`UID`, `_UID`, `REFN`, `EXID`, `_FSFTID`, WikiTree ids). File-local
  `@I1@` cross-reference ids are only used within one named import lineage
  (`--lineage`; `--update` reuses the earlier lineage). Nothing is merged
  because names or dates look alike.
- Re-importing an identical file with the same options does nothing. A newer
  export adds new people and records; values that changed on rows already in
  the database are listed as conflicts for review; research is never deleted.

## Export (`genealogy gedcom export FILE --version 7.0|5.5.1 [--private]`)

Without `--private` the export is built from the public projection (withheld
people and records are absent, not flagged). With `--private` it contains
everything: never publish that file.

| Workbench | GEDCOM 7.0 | GEDCOM 5.5.1 |
| --- | --- | --- |
| person id | `UID` (UUID5 of project + person id), stable across exports | `_UID` |
| external ids (WikiTree…) | `EXID` + `TYPE` URI | `REFN` + `TYPE` |
| names (kind) | `NAME` with `GIVN`/`SURN`, `TYPE` (+`PHRASE`) | `NAME`, `TYPE` |
| sex | `SEX M/F/U/X` | `SEX M/F/U` |
| events, dates | `BIRT`, `DEAT`, … `DATE` (`ABT`, `BEF`, `AFT`, `BET … AND`, `FROM … TO`, `EST`, `CAL`); unparsed wording as `PHRASE` | same; wording as `(text)` |
| places | `PLAC`, `MAP` `LATI`/`LONG` | same |
| parent claims | one `FAMC` per claim; couple `FAM` only for an explicit spouse claim whose partners are both current parents of the child; otherwise a single-parent `FAM` | same |
| relation type | `PEDI` BIRTH/ADOPTED/FOSTER/SEALING; OTHER + `PHRASE` | `PEDI` |
| assessment | `_GRWB_ASSESS` (status; grade; confidence; *subjective estimate N%*) under `FAMC`, events and `FAM`, declared in `HEAD.SCHMA` | `NOTE Assessment: …` |
| disproved / documented | `FAMC.STAT DISPROVEN` / `PROVEN` only | same |
| citation | `SOUR @S1@`, `PAGE` locator, `DATA.TEXT` current transcription | same |
| sources | `SOUR` with `TITL`, `AUTH`, `PUBL` | same; plus `SUBM` |

Not written: `QUAY` (record quality and belief in a conclusion are kept
separate, and an assessment is not a universal document score).

### The extension

`_GRWB_ASSESS` — payload: the current assessment in words. Allowed under
`INDI.FAMC`, `FAM` and individual/family event structures; no substructures.
URI: `https://github.com/glasgowm148/genealogy-research-workbench/blob/main/docs/gedcom.md#_grwb_assess`.
Declaring it in `HEAD.SCHMA` does not mean another program keeps or understands it.

### Loss report

Every export writes `FILE.report.json` listing what GEDCOM cannot carry:
records and mentions, documentary relationship statements, identity claims,
findings, questions, searches, hypotheses, studies, dependencies, approvals,
proposals, DNA observations, external observations, earlier assessment
revisions, place precision, date wording (5.5.1), and how many single-parent
families were written for unpaired parent claims.
