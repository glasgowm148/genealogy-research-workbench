# Genealogy research project instructions

- The project database (`[storage] database` in `genealogy.toml`) is the only place research is recorded. Change it only through `genealogy` commands or the `genealogy.store.Research` services; never edit the SQLite file, native exports or generated `dist/` files by hand, and never create parallel JSON registries of people, sources or conclusions.
- Keep claims, evidence, citations, sources, transcriptions and hypotheses distinct. A record and its mentions come first; identifying a mention with a person is a separate, assessable claim. Competing candidates stay competing.
- Reassess with `genealogy assess CLAIM --expected-revision N`: earlier revisions remain as history. Never invent a percentage, treat a missing estimate as zero, or average competing estimates. Estimates are subjective unless the research shows otherwise.
- Record dependencies (`genealogy depend`) and review what `genealogy review list` flags when a premise changes; do not recalculate confidence mechanically.
- Bulk or agent-generated changes go through a proposal file (`genealogy proposal check|diff|apply`), never by editing rows directly. A stale proposal must be regenerated, not forced.
- Keep original captures and evidence files unchanged; register them with `genealogy asset add` and correct readings with `genealogy transcription revise`.
- Treat every external service or file format as an adapter, never as the core model. Do not write to external trees from the workbench.
- Keep living-person, restricted, licensed, raw-capture and raw-DNA material out of public exports. Publish files only with an exact-file approval (`genealogy approval add`).
- Use synthetic data in tests and examples.
