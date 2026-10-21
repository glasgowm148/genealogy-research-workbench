# Developer guide

The reusable core is platform-neutral. Adapters convert explicit provider inputs to typed records; research services manage cases; public projection applies privacy; website/export code consumes only that projection.

## Install and test

From a toolkit checkout, with Python 3.11+:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
make check
python -m build
```

Install a built wheel in a separate environment to test the actual distribution:

```sh
python3 -m venv /tmp/workbench-wheel
/tmp/workbench-wheel/bin/python -m pip install dist/genealogy_research_workbench-0.7.0-py3-none-any.whl
cd /tmp
/tmp/workbench-wheel/bin/genealogy init wheel-demo --name "Wheel demonstration"
/tmp/workbench-wheel/bin/genealogy --project wheel-demo build
```

Windows uses the environment’s `Scripts` directory instead of `bin`. Development installs need build/lint tooling; ordinary use has no runtime dependencies. The examples and documentation are included in the source distribution; the wheel includes the runtime, website assets, and project starter.

Browser tests are explicit:

```sh
python -m pip install -e '.[dev,browser]'
python -m playwright install chromium
make browser-check
```

They exercise desktop/mobile routes, search and surname filters, tree views, family dossiers, the evidence guide, comparisons, connections, opening the built site directly from disk, and real GEDCOM/OneTree uploads through the local server. Set `GENEALOGY_BROWSER_EXECUTABLE` to use an installed Chromium or Chrome instead of Playwright's download. Set `GENEALOGY_AXE_PATH` to an [axe-core](https://github.com/dequelabs/axe-core) `axe.min.js` (for example from `npm install axe-core`) to also check every page type against WCAG 2.1 A/AA at desktop and mobile widths; CI does this. Standard unit tests do not require a browser. CI tests Python 3.11–3.14, builds distributions, smoke-tests an installed wheel outside the source checkout, and runs the separate browser job.

## Layout

| Path | Purpose |
| --- | --- |
| `src/genealogy/models.py`, `case.py`, `research.py` | Typed records and durable research services |
| `src/genealogy/adapters/` | GEDCOM, OneTree, WikiTree and other explicit boundaries |
| `src/genealogy/importing.py`, `publication.py` | High-level import and deliberate publication review |
| `src/genealogy/server.py` | Loopback-only upload wizard and isolated previews |
| `src/genealogy/site.py`, `web/` | Public website renderer and offline assets |
| `src/genealogy/exports.py`, `privacy.py` | Shared public projection and exports |
| `src/genealogy/starter/` | Resources included in installed packages |
| `starter-project/` | Inspectable matching project template |
| `examples/` | Fictional research and import examples |
| `tests/` | Unit, integration, scale and opt-in browser checks |

Keep package starter and top-level starter changes aligned. Never add real people’s private records, source captures, raw DNA, credentials or browser state to fixtures.

## Extending an adapter

An adapter returns `AdapterBatch`: typed neutral entities, private audit observations and bounded warnings. Preserve stable external IDs, avoid dangling references, and never upgrade a tree assertion to documented evidence merely because it was imported. Raw provider material belongs in caller-owned private input storage, not public records.

`AdapterBatch.add_to_case` validates collisions before inserting the batch. `ResearchCase.add_many` makes large imports linear in record count. New formats need tests for malformed structures, missing relatives, repeated imports, living/restricted/licensed records, and Unicode. Offline core commands must not discover inputs or start provider requests implicitly.

## Release checklist

1. Set the version in `pyproject.toml` and date its `CHANGELOG.md` entry.
2. Run the unit and browser checks (with `GENEALOGY_AXE_PATH`), then build the wheel and source distribution.
3. Install the wheel outside the checkout and check `init → import → build → check-links`.
4. Inspect the fictional demo and README screenshots, and validate documentation links.
5. Review the release for real research, credentials, private captures and generated artifacts.
6. Commit, tag `vX.Y.Z`, push `main` and the tag, then publish the GitHub release:

   ```sh
   gh release create vX.Y.Z dist/genealogy_research_workbench-X.Y.Z* --title "Genealogy Research Workbench X.Y.Z" --notes-file CHANGELOG.md
   ```

   Publishing the release runs `.github/workflows/release.yml`. That workflow rebuilds the distributions, checks that the version matches the tag, smoke-tests the wheel, and uploads it to PyPI.
7. Update downstream consumers to the released commit and rerun their integration checks. Push the toolkit before any consumer commit that pins it.

### Publishing to PyPI (one-time setup)

The release workflow uses [trusted publishing](https://docs.pypi.org/trusted-publishers/), so no API token is stored in the repository.

1. On [pypi.org](https://pypi.org), add a pending trusted publisher:
   - project: `genealogy-research-workbench`
   - owner: `glasgowm148`
   - repository: `genealogy-research-workbench`
   - workflow: `release.yml`
   - environment: `pypi`
2. In the GitHub repository settings, create an environment named `pypi`. Optionally require approval before publishing.
3. Publish a release. The workflow runs from the tagged commit, so the first release that can reach PyPI is 0.4.0; earlier tags do not contain it. Re-running a failed workflow run for a 0.4.0 or later release also works once the setup is complete.

Releases from 0.4.0 onwards are on [PyPI](https://pypi.org/project/genealogy-research-workbench/), and the README quick start installs from there. The import package is called `genealogy`. An unrelated PyPI project named `genealogy` installs a module with the same name, so install only one of them in a given environment.

The Glasgow consumer uses a Git submodule pinned to a toolkit commit, with a compatible package-version declaration. Its source tree is not a separately maintained toolkit fork. For local development, install the standalone checkout in the consumer’s environment with `pip install -e /path/to/genealogy-research-workbench`; commit/review changes upstream before updating the consumer’s pin.

MIT applies to the software and fictional examples, not to data imported by users.
