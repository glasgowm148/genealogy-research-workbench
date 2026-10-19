# Importing a tree

The high-level `genealogy import FILE` command accepts an explicitly selected local file, at most 32 MiB, encoded as UTF-8 (a UTF-8 BOM is accepted). `.ged` and `.gedcom` select GEDCOM; `.json` selects OneTree. Use `--format gedcom` or `--format one-tree` when the extension is different.

```sh
genealogy init my-family --name "Family research"
genealogy --project my-family import /path/to/tree.ged --publish-deceased
genealogy --project my-family build
```

Imports preserve the original bytes in `private/imports/` with a SHA-256 identity, a bounded report, and private file permissions. The selected case is saved only after parsing and reference validation succeed. Errors do not replace an existing valid case. Different inputs do not silently merge: use an empty project or explicitly choose `--replace`. Identical bytes and review choices are a no-op.

## GEDCOM

The importer supports common GEDCOM 5.5/5.5.1 and GEDCOM 7 text structures; this is a useful subset, not a claim of complete standard conformance.

- `INDI` names and aliases, sex, birth, death, burial, baptism/christening, residence and occupation fields supported by the parser.
- `FAM` partners, child → parent relationships, and marriage events.
- Event dates retained as supplied, including approximate/range qualifiers; supplied place labels and valid latitude/longitude.
- Source records, source titles/repositories, individual and event citations with page locators.
- Notes and continuation lines retained privately; source quotations/transcriptions are not automatically published.
- Missing referenced people or sources are reported; unavailable relatives are not invented.
- Privacy restrictions and explicit living flags remain protected. Imported relationship confidence stays unassessed.

Use `--publish-deceased` only after reviewing the tree. Add `--publish-reviewed-sources` only after reviewing linked bibliographic metadata and locators. Neither option promotes full source text, private notes, or licensed records. See [publication rules](privacy.md).

ANSEL/legacy encodings, GEDZIP archives, embedded media, proprietary custom tags, and full standard-level round-trip fidelity are outside this release. Re-export as UTF-8 plain GEDCOM. The private original file retains unsupported content for later inspection.

## OneTree JSON

Recognised shapes include:

```json
{
  "data": {
    "Example-1": {
      "Name": "Example-1",
      "Id": 101,
      "FirstName": "Invented",
      "LastNameAtBirth": "Example",
      "BirthDate": "1800-01-01",
      "DeathDate": "1880-01-01",
      "BirthLocation": "Fictional Harbour",
      "Privacy": 60,
      "Father": 102
    },
    "Example-2": {
      "Name": "Example-2",
      "Id": 102,
      "FirstName": "Another",
      "LastNameAtBirth": "Example",
      "DeathDate": "1840",
      "Privacy": 60
    }
  }
}
```

A profile list, a dictionary keyed by profile ID, and a `people`/`relationships` container are also accepted. Provider numeric IDs resolve parent references to the same stable person identities. Imported spouses and children are reconciled without fabricating missing people. Name variants, vital dates/places, supplied coordinates, privacy flags and explicit relationship assessments are normalised where supported. Publication review resets imported relationship confidence to unassessed.

The schema is based on WikiTree/OneTree-style exports, not every unrelated product named “OneTree”. Some products use zipped archives or different JSON structures. Unknown schemas produce a useful import error rather than a guessed tree. Arbitrary biography markup and embedded source text are not parsed into independently assessed citations. Full profile text is retained in private provenance/original input, not automatically published.

## Import reports and missing information

The command prints people/record counts, public-review counts and up to 20 warnings; reports remain under `private/imports/`. Review warnings before publishing. A place name without coordinates is still searchable, but cannot be placed accurately on the coordinate map. No geocoding or online lookup happens automatically.

Try [small edge-case fixtures](../examples/imports/README.md) or the [larger fictional family](../examples/demo/README.md). Never use real living-person data in a bug report; reduce it to a fictional example with the same structure.
