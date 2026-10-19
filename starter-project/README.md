# Research case

Keep assertions as claims, link their citations and evidence, and record open
questions. Use `genealogy search` and `genealogy report` to review the case,
then `genealogy validate` and `genealogy build` to create offline HTML views.
Use `genealogy record add TYPE --input record.json` to add any typed core
record from a strict JSON object, and `record list` or `record show ID` to inspect it.
Use `genealogy bundle --output research-bundle` for a complete local handoff;
unlike `build` and `export`, a bundle retains protected case content.

Do not put living-person details, restricted material, raw DNA data, credentials, or licensed images in `dist/` or a public repository.

## Import your own tree

This starter contains no example people. Keep original exports private.

```sh
genealogy --project . import /path/to/tree.ged
# After reviewing basic deceased/historical facts for public use:
genealogy --project . import /path/to/tree.ged --replace --publish-deceased
genealogy --project . build
# Or use the local upload wizard, which creates a separate project per upload:
genealogy --project . serve
```

Open the printed `http://127.0.0.1:8000/` address. GEDCOM (`.ged`, `.gedcom`)
and OneTree (`.json`) uploads stay on this computer. Each preview project is
saved under `private/previews/`; its generated site is in its `dist/` directory.
CLI imports retain the original file and a bounded report in `private/imports/`.
Imports into populated cases require `--replace`; there is no implicit tree merge.
An identical repeated import is a no-op. UTF-8 inputs up to 32 MiB are supported.

Publication review is optional and explicit. Without it, this import workflow
keeps people private even when the provider calls them public. Review makes only
basic deceased or historical facts public: notes, source text and quotations stay
private; explicit private, restricted, licensed and living flags are never
superseded. Unknown living status qualifies only with an explicit birth year
more than 120 years ago. Imported relationships remain unverified assertions.
Maps need coordinates already in the input; no network geocoding runs.
For a separately reviewed bibliography, add `--publish-reviewed-sources` together
with `--publish-deceased`, or select the second upload checkbox. This exposes only
reviewed source titles/repositories/URLs and citation locators linked to public
historical subjects; quotations and transcriptions stay private.
Only `dist/` is intended for publication; the local server does not deploy it.
