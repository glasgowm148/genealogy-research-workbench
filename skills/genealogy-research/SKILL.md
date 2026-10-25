---
name: genealogy-research
description: Conduct evidence-led, platform-neutral genealogy research and maintain the project's research database; use for family-history questions, source analysis, or research updates, not for a platform-specific workflow alone.
---

# Genealogy research

Work from a clear research question. Separate observations, sources, citations, evidence and claims; preserve uncertainty and competing hypotheses rather than promoting an inference to fact.

Use portable people, names, events, places and relationships as the primary records. Treat GEDCOM, collaborative trees, archives, spreadsheets/OCR and DNA services as adapters with their own identifiers and provenance.

Protect living-person information, restricted or licensed records, raw DNA, credentials and private correspondence. Do not publish or copy them into fixtures, generated public artefacts or unapproved external services.

Record enough citation detail to find the source again, including repository or holder, collection, item and access date where available. State what evidence supports or weakens each conclusion and leave unresolved questions explicit.

## Recording research

Record everything through the `genealogy` commands (or the `genealogy.store.Research` services), which write the project's one research database with an audit trail: `source add`, `record add`, `citation add`, `transcription add|revise`, `mention add`, `identify`, `relationship add`, `claim add`, `evidence add`, `assess` (with `--expected-revision` for an existing assessment), `finding add`, `question add`, `search add` (including searches that found nothing), `hypothesis add`, `depend` and `note add --file`. Never edit the database file, native exports or generated site files, and never keep conclusions in separate JSON files. For bulk or agent-prepared edits, write a proposal file and run `genealogy proposal check`, `diff` and `apply`; regenerate a stale proposal rather than forcing it.
