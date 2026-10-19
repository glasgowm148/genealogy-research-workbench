# Privacy and publication

Private research and public output are different products. A research case can retain material needed for analysis; a website/export passes through the toolkit’s public projection. A complete case bundle remains private.

## Import review

High-level file imports are private by default, including provider records labelled public. Publication is a separate, explicit choice:

| Option | Permits | Keeps private |
| --- | --- | --- |
| No publication options | A private research case | All imported records |
| `--publish-deceased` | Adapter-vetted basic facts about deceased/historical people, safe linked events, places and relationships | Living/unknown-status people, explicit private/restricted/licensed records, notes, descriptions, source text |
| Also `--publish-reviewed-sources` | Reviewed source titles/repositories/safe URLs and citation locators connected to eligible public facts | Quotations, transcriptions, access notes, protected/licensed sources and sources linked only to withheld people |

A person is eligible when explicitly deceased, or when an unambiguous supported birth-year value is more than 120 years old and no explicit living flag overrides it. Date forms the review helper cannot assess safely require manual review. This is a publication heuristic, not proof of a death date. Explicit restrictions always take precedence. Source review requires deceased-facts review.

Imported relationships remain unassessed. A source association remains an asserted association, even when its bibliography is public. Neither import nor publication verifies genealogy.

Original typed records are retained in private import provenance before convenience review strips notes, descriptions or external fields. Raw source files and reports stay under `private/imports/`; case files are private and ignored in generated starter projects. Store original exports under `private/` (or outside the project), especially OneTree JSON files. Use appropriate access controls/backups for the entire project.

## Public projection

`project_for_public_export` validates the case and applies the public gate. Default publication requires records to be explicitly public and people to be deceased. Dependencies are filtered to a fixed point: an otherwise public relationship, claim or citation cannot reveal an omitted person or source by referencing it. Raw DNA payloads are rejected from portable cases.

A hand-maintained case can mark deliberately reviewed records public. Its author remains responsible for free text: a biography of a deceased person can still mention living relatives. The convenience importer therefore does not promote free-form notes or quotations. [Research recipes](research.md) explain explicit case review.

Advanced `privacy.allow_living`, `allow_restricted` and `allow_licensed` settings change the public gate. They default false. Do not enable them for a public family-history site. A private audience and a different legal right to data are separate decisions.

## Local upload server

`genealogy serve` binds only to `127.0.0.1`. Files move from your browser to a local process, not a remote service. Upload requests require the printed origin and a session token. Each upload is isolated, size-limited and validated; static preview routes expose only the generated site, never cases or original files.

Do not expose the upload server through a public proxy, port forwarding, or a shared hosting service. Use an ordinary static server for the reviewed `dist/` output. The generated static site does not need that upload process.

## Before sharing

Read the generated site and downloadable public data, including notes and source titles you explicitly marked public. Check publication against your source licences and the people’s privacy. Never deploy the project root, `cases/`, `private/`, or a research bundle; deploy only the reviewed build directory.

MIT covers the software. It grants no rights to imported records, photographs, licensed databases, or personal data.
