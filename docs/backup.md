# Backup, restore and upgrades

## Backups

```sh
genealogy --project my-family backup create            # into [storage] backups
genealogy --project my-family backup create /Volumes/Backup/my-family-2026-10-25
genealogy backup verify /Volumes/Backup/my-family-2026-10-25
genealogy backup restore /Volumes/Backup/my-family-2026-10-25 ~/restored-family
```

A backup contains a consistent copy of the database made with SQLite's online
backup API (copying the live `.sqlite` file is not safe while it is in use), the
complete native export, a copy of every referenced file, `genealogy.toml` and
the customisation folders (`templates/`, `theme/`, `content/`, `skills/`,
`AGENTS.md`, `README.md`), and a manifest of versions and hashes. `create`
verifies the result before reporting success and refuses to back up while a
referenced file is missing or changed.

`--exclude-root NAME` records the files under one asset root by hash only, for
a root that is itself preserved another way (for example a Git checkout). A
restoration then reports which of those files it could not verify.

Restoration writes into a new, empty directory, checks SQLite integrity and
references, places each file under its asset root, and compares the logical
digest of the restored database and every file hash with the manifest. The
database files are not expected to be byte-identical; their contents are.

Backups and native exports contain private research. Keep them out of version
control and out of any published folder; the starter `.gitignore` covers
`private/`.

## Native export and import

```sh
genealogy --project my-family native export private/exports/full.json
genealogy --project my-family native export private/exports/package --package
genealogy native import private/exports/package new-copy.sqlite
```

The `genealogy-native` format (version 1) contains every table, ordered by key,
so two exports of the same database are identical and diff readably. It is not
a second place to edit research: import creates a new database.

## Upgrading the workbench

1. `genealogy --project DIR backup create`
2. Install the new workbench version.
3. `genealogy --project DIR db status` — a newer schema says so.
4. `genealogy --project DIR db migrate` — applies numbered migrations and keeps
   `research.sqlite.pre-vN.backup` beside the database.
5. `genealogy --project DIR validate` and `genealogy --project DIR build`.

Your `genealogy.toml`, `genealogy.local.toml`, templates and content are never
rewritten by an upgrade. A database written by a newer workbench is refused by
an older one.

### From JSON research cases (workbench 0.8 and earlier)

```sh
genealogy --project DIR upgrade
```

creates the database if needed and loads every `cases/*.json`. The case files
are kept unchanged. Re-running is a no-op for unchanged files. Records sharing
an id across cases become one entity; a differing copy is kept for review as a
`legacy_item` conflict (`genealogy db status` counts them).
