# Genealogy Research Workbench instructions

- Keep the core platform-neutral. Platform-specific behaviour belongs in adapters.
- Treat living-person data, restricted or licensed records, raw DNA and secrets as non-public by default; do not place them in examples or generated public output.
- Use fictional, non-identifying fixtures only.
- Preserve provenance: claims should remain distinguishable from supporting evidence, citations and sources.
- Do not make network requests from core commands without an explicit adapter and user request.
- The project database (`genealogy.store`) is the single authority for a project's structured research. All writers (CLI, importers, adapters, the upload server, project scripts) go through `genealogy.store.services.Research` inside `Store.write`; do not add code that writes research tables, JSON case files or other parallel registries directly.
- Keep schema changes as new numbered migrations in `src/genealogy/store/migrations/` with `SCHEMA_VERSION` raised, a migration test and a `docs/database.md` update. Never edit a released migration.
- Every public output must come from `genealogy.store.projection.public_case`. Do not add a public output that reads the database (or a private case view) directly.
