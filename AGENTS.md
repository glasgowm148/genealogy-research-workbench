# Genealogy Research Workbench instructions

- Keep the core platform-neutral. Platform-specific behaviour belongs in adapters.
- Treat living-person data, restricted or licensed records, raw DNA and secrets as non-public by default; do not place them in examples or generated public output.
- Use fictional, non-identifying fixtures only.
- Preserve provenance: claims should remain distinguishable from supporting evidence, citations and sources.
- Do not make network requests from core commands without an explicit adapter and user request.
