# Importing a tree

`genealogy import FILE` accepts one explicitly selected local file of at most 32 MiB. `.ged` and `.gedcom` select GEDCOM; `.json` selects OneTree. Use `--format gedcom` or `--format one-tree` when the extension is different.

```sh
genealogy init my-family --name "Family research"
genealogy --project my-family import /path/to/tree.ged --publish-deceased
genealogy --project my-family build
```

Imports keep the original bytes in `private/imports/` with a SHA-256 identity, a bounded report and private file permissions. The case is saved only after parsing and reference validation succeed, so a failed import never replaces a valid case. Identical bytes with the same review choices are a no-op.

## Importing again

| You have | Command | What happens |
| --- | --- | --- |
| An empty project | `import FILE` | The tree becomes the case |
| A newer export of the **same** tree, plus research you added | `import FILE --update` | Records created by earlier imports of that format are replaced; findings, questions, sources and other records you added are kept |
| A different tree, or you want to start again | `import FILE --replace` | Every record in the case is replaced |

Before `--update` or `--replace` changes anything, the previous case is copied to `private/imports/backups/<case>-<time>.json`. To recover, copy that file back to `cases/<case>.json`.

`--update` refuses, and changes nothing, when research you kept would point at a person or record that the new export no longer contains, or when one of your record IDs collides with a newly imported ID. The error lists the references. Correct them, restore the person in your tree program, or use `--replace`. Edits made directly to previously imported records are replaced by the new export; put lasting research in your own records rather than editing imported ones. Identity across exports relies on the exporter keeping its record identifiers (`@I12@`, WikiTree IDs): an export that renumbers everyone is a different tree.

## GEDCOM

The importer supports common GEDCOM 5.5, 5.5.1 and 7 structures. This is a useful subset, not a claim of complete conformance.

**Character sets.** The file's `HEAD.CHAR` declaration is followed: UTF-8 (with or without a byte-order mark), UNICODE/UTF-16 (with or without a BOM), ANSI (Windows-1252), ANSEL, ASCII, MACINTOSH and ISO-8859-1/-15. ANSEL combining accents are moved after their letters and normalised, so accented names are not garbled. A file that declares a legacy set but is actually valid UTF-8 is read as UTF-8 with a warning. Bytes that cannot be decoded stop the import with the line number; nothing is guessed. Windows (CRLF), Unix and classic Mac (CR) line endings all work.

**People and names.** Each `NAME` keeps its displayed value and, separately, its given name and surname (`GIVN`/`SURN` or the `/surname/` slashes), so the site can browse by surname. Name types, `NICK`, `_MARN` married names, `_AKA` and `ROMN`/`FONE`/`TRAN` variants are kept. `SEX` is kept as an unassessed claim.

**Death evidence.** A `DEAT`, `BURI` or `CREM` record (other than `DEAT N`) marks the person deceased. `_LIVING Y` marks them living and wins over any other signal.

**Events.** Birth, christening, baptism, death, burial, cremation, residence, occupation, census, emigration, immigration, naturalisation, probate, will, adoption, education, graduation, retirement, ordination, confirmation, title and generic `EVEN`/`FACT` events. Family events: marriage, banns, licence, contract, settlement, engagement, divorce and annulment. Dates are kept exactly as supplied, including `ABT`, `BET … AND …`, Julian `@#DJULIAN@` and dual years.

**Families and parent roles.** `FAM` partners become one couple; each `CHIL` gets one parent link per partner. The nature of each link is kept rather than flattened: `FAMC.PEDI` (birth, adopted, foster, sealing), Family Tree Maker/Legacy `_FREL`/`_MREL` (Natural, Step, Adopted …) and `ADOP.FAMC`. A link with no stated nature is a recorded parent of unstated kind, not assumed to be biological. GEDCOM 7 `FAMC.STAT DISPROVEN` marks the link disproved and keeps it out of publication; `CHALLENGED`/`PROVEN` are kept as the tree's own mark.

**Identifiers.** `_UID`, `UID`, `REFN` (with `TYPE`), `EXID`, `AFN`, `_FSFTID` (FamilySearch) and `WWW` are kept as private external identifiers.

**Sources and citations.** `SOUR` records keep title, `AUTH` author, `PUBL` publication details, repository name (`REPO`, resolved through repository records) and call number. Citations keep the `PAGE` locator and `DATA.TEXT` quotation. A `QUAY` grade is recorded with its meaning in the private evidence assessment, never as this project's confidence.

**Notes.** `NOTE` and GEDCOM 7 `SNOTE` (inline or shared) are kept privately and never published by the import review.

**Repairs and diagnostics.** Some exporters, including WikiTree's, write raw line breaks inside long notes. A line that cannot be a GEDCOM line and follows text is kept as continued text, and the import reports how many lines were repaired. Missing referenced people or sources are reported and omitted; `@VOID@` pointers are treated as deliberately empty. Invalid coordinates are reported and dropped, never kept or guessed. Every structure the importer does not interpret is counted in a warning (for example `INDI._MILT×16`) and remains only in the private original file. Government identifiers such as `SSN`/`IDNO` are never imported.

Outside this release: GEDZIP archives, embedded media (`OBJE`), source templates, `ASSO` associations, LDS ordinances and full round-trip fidelity. The private original file keeps them.

## OneTree JSON

Recognised shapes include `{"data": {"Profile-1": {...}}}` (the WikiTree OneTree export), a profile list, a dictionary keyed by profile ID, and a `people`/`relationships` container:

```json
{
  "data": {
    "Example-1": {
      "Name": "Example-1", "Id": 101, "FirstName": "Invented", "MiddleName": "Mae",
      "LastNameAtBirth": "Example", "LastNameCurrent": "Married",
      "BirthDate": "1800-00-00", "DeathDate": "1880-03-00",
      "DataStatus": {"BirthDate": "guess", "Father": "10"},
      "BirthLocation": "Fictional Harbour", "Privacy": 60, "Father": 102,
      "Spouses": [{"Id": 103, "marriage_date": "1822-00-00", "marriage_location": "Invented Chapel"}]
    }
  }
}
```

- WikiTree `YYYY-00-00` placeholders become `YYYY` or `YYYY-MM`; `0000-00-00` means no date. `DataStatus` qualifiers are kept: guess → `ABT`, before → `BEF`, after → `AFT`.
- `DataStatus` parent marks are kept as the tree's statement: 10 → tree-marked uncertain, 20 → confident, 30 → DNA confirmed, 5 → non-biological (also recorded as the link's nature). None raises the project's confidence.
- Given names include `MiddleName`; married (`LastNameCurrent`), other (`LastNameOther`) and `Nicknames` names are kept.
- A couple listed from both spouses' profiles is one relationship, and spouse marriage dates/places become one marriage event. A spouse marked `do_not_display` is imported privately and never published.
- `IsLiving` 1/0 and explicit `living` flags are respected. Numeric `Privacy` below 50 is restricted.
- Relatives outside the export are summarised in one warning and omitted; no person is ever created to complete a link.
- Biography text is retained privately. Arbitrary WikiTree markup is not converted into independently verified citations.

The schema follows WikiTree/OneTree-style exports, not every unrelated product called "OneTree". Unknown structures produce an import error rather than a guessed tree. UTF-8 is expected; a UTF-8 or UTF-16 byte-order mark is accepted.

## Reports

The command prints counts, public-review counts and up to 20 warnings; the full report stays under `private/imports/`. Review warnings before publishing. A place without coordinates is still searchable but cannot be mapped. No geocoding or online lookup happens.

Try the [small edge-case fixtures](../examples/imports/README.md) or the [larger fictional family](../examples/demo/README.md). Never put real living-person data in a bug report; reduce it to a fictional example with the same structure.
