"""Command-line operations on the project database.

Every command here goes through :class:`genealogy.store.Research` (or the
operations built on it). Database commands never hold a write transaction while
waiting for input or the network.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .store import NameInput, Research, open_project
from .store.errors import StoreError

ACCESS = ("public", "private", "restricted", "licensed")
DB_COMMANDS = {"db", "upgrade", "person", "place", "source", "record", "citation", "transcription", "mention",
               "identify", "claim", "relationship", "assess", "history", "evidence", "depend", "review", "note",
               "question", "hypothesis", "study", "asset", "approval", "native", "backup", "gedcom", "proposal",
               "wikitree", "show", "publication", "legacy"}


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, default=str))


def _actor(args: argparse.Namespace) -> str:
    return getattr(args, "actor", None) or "cli"


def add_parsers(commands: Any) -> None:
    """Register database subcommands on the main parser."""
    def actor(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        parser.add_argument("--actor", help="who or what is making the change (recorded in the audit trail)")
        parser.add_argument("--reason", help="why the change is made (recorded in the audit trail)")
        return parser

    db = commands.add_parser("db", help="create, inspect, check or migrate the project database")
    db_sub = db.add_subparsers(dest="db_command", required=True)
    db_sub.add_parser("init", help="create the project database for an existing project")
    db_sub.add_parser("status", help="schema version, counts and items needing review")
    db_sub.add_parser("check", help="SQLite integrity, references and referenced file hashes")
    db_sub.add_parser("migrate", help="upgrade an older database to this workbench's schema (backs it up first)")

    actor(commands.add_parser("upgrade", help="move legacy JSON research cases into the project database"))

    person = commands.add_parser("person", help="add or list people")
    person_sub = person.add_subparsers(dest="person_command", required=True)
    p_add = actor(person_sub.add_parser("add", help="add a person (record-defined people need no external id)"))
    p_add.add_argument("name", help="full name as you would display it")
    p_add.add_argument("--given")
    p_add.add_argument("--surname")
    p_add.add_argument("--sex", choices=("male", "female", "unknown", "other"))
    p_add.add_argument("--living", choices=("living", "deceased", "unknown"), default="unknown")
    p_add.add_argument("--label", help="your short label, e.g. 'Lisnagaver Robert'")
    p_add.add_argument("--record-defined", action="store_true", help="a person known only from a record")
    p_add.add_argument("--external", action="append", default=[], metavar="SYSTEM:VALUE")
    p_add.add_argument("--access", choices=ACCESS, default="private")
    p_add.add_argument("--id")
    person_sub.add_parser("list", help="list people with their names and external ids")

    source = commands.add_parser("source", help="register a source work or collection")
    s_sub = source.add_subparsers(dest="source_command", required=True)
    s_add = actor(s_sub.add_parser("add"))
    s_add.add_argument("title")
    s_add.add_argument("--kind", default="unknown")
    s_add.add_argument("--author")
    s_add.add_argument("--publication")
    s_add.add_argument("--url")
    s_add.add_argument("--repository", help="archive or website holding it")
    s_add.add_argument("--catalogue-ref")
    s_add.add_argument("--originality", choices=("original", "derivative", "authored", "unknown"))
    s_add.add_argument("--access", choices=ACCESS, default="private")
    s_add.add_argument("--id")

    record = commands.add_parser("record", help="add a record occurrence, or list/show/add legacy typed records")
    r_sub = record.add_subparsers(dest="record_command", required=True)
    r_add = actor(r_sub.add_parser("add", help="add a record occurrence within a source"))
    r_add.add_argument("record_type", nargs="?", help="record type, e.g. baptism, will (or a legacy model type with --input)")
    r_add.add_argument("--title")
    r_add.add_argument("--source")
    r_add.add_argument("--locator")
    r_add.add_argument("--date", help="date as written")
    r_add.add_argument("--date-start", help="ISO date for sorting")
    r_add.add_argument("--date-kind", default="unknown")
    r_add.add_argument("--place", help="place as written")
    r_add.add_argument("--summary", help="your abstract (interpretation, not transcription)")
    r_add.add_argument("--information", choices=("primary", "secondary", "undetermined", "mixed"))
    r_add.add_argument("--access", choices=ACCESS, default="private")
    r_add.add_argument("--input", type=Path, help="a legacy JSON core record (loaded through the same services)")
    r_add.add_argument("--id")
    r_list = r_sub.add_parser("list", help="list records")
    r_list.add_argument("--kind", help="core record type")
    r_show = r_sub.add_parser("show", help="show one record by id")
    r_show.add_argument("record_id")

    citation = commands.add_parser("citation", help="cite a source or record")
    c_sub = citation.add_subparsers(dest="citation_command", required=True)
    c_add = actor(c_sub.add_parser("add"))
    c_add.add_argument("--source", required=True)
    c_add.add_argument("--record")
    c_add.add_argument("--locator")
    c_add.add_argument("--accessed-on")
    c_add.add_argument("--access", choices=ACCESS, default="private")
    c_add.add_argument("--id")

    transcription = commands.add_parser("transcription", help="add, revise or withdraw a reading of a record")
    t_sub = transcription.add_subparsers(dest="transcription_command", required=True)
    t_add = actor(t_sub.add_parser("add"))
    t_add.add_argument("record")
    t_add.add_argument("text")
    t_add.add_argument("--kind", default="transcription",
                       choices=("transcription", "abstract", "translation", "reading", "index_entry"))
    t_add.add_argument("--reader")
    t_add.add_argument("--read-on")
    t_add.add_argument("--access", choices=ACCESS, default="private")
    t_add.add_argument("--id")
    t_rev = actor(t_sub.add_parser("revise"))
    t_rev.add_argument("transcription")
    t_rev.add_argument("text")
    t_rev.add_argument("--expected-revision", type=int, required=True)
    t_rev.add_argument("--why", required=True, help="what the corrected reading changes")
    t_wd = actor(t_sub.add_parser("withdraw"))
    t_wd.add_argument("transcription")
    t_wd.add_argument("--expected-revision", type=int, required=True)
    t_wd.add_argument("--why", required=True)

    mention = commands.add_parser("mention", help="record a participant named in a record")
    m_sub = mention.add_subparsers(dest="mention_command", required=True)
    m_add = actor(m_sub.add_parser("add"))
    m_add.add_argument("record")
    m_add.add_argument("name_as_written")
    m_add.add_argument("--role")
    m_add.add_argument("--details")
    m_add.add_argument("--access", choices=ACCESS, default="private")
    m_add.add_argument("--id")

    identify = actor(commands.add_parser("identify", help="propose that a mention is a person (candidates coexist)"))
    identify.add_argument("mention")
    identify.add_argument("person")
    identify.add_argument("--statement")
    identify.add_argument("--status", help="your status word for the proposal, e.g. possible")
    identify.add_argument("--reasoning")
    identify.add_argument("--id")

    rel = commands.add_parser("relationship", help="propose a relationship claim")
    rel_sub = rel.add_subparsers(dest="relationship_command", required=True)
    rel_add = actor(rel_sub.add_parser("add"))
    rel_add.add_argument("child", help="the child (or first party)")
    rel_add.add_argument("role", choices=("father", "mother", "parent", "spouse", "partner", "sibling"))
    rel_add.add_argument("relative", help="the relative who has that role")
    rel_add.add_argument("--relation-type", choices=("biological", "adoptive", "step", "foster", "guardian", "unknown"))
    rel_add.add_argument("--statement")
    rel_add.add_argument("--access", choices=ACCESS, default="private")
    rel_add.add_argument("--id")

    claim = commands.add_parser("claim", help="add a vital, attribute or other claim")
    cl_sub = claim.add_subparsers(dest="claim_command", required=True)
    cl_add = actor(cl_sub.add_parser("add"))
    cl_add.add_argument("person")
    cl_add.add_argument("predicate", help="e.g. birth, death, occupation")
    cl_add.add_argument("value")
    cl_add.add_argument("--kind", choices=("vital", "attribute", "other"), default="vital")
    cl_add.add_argument("--access", choices=ACCESS, default="private")
    cl_add.add_argument("--id")

    assess = actor(commands.add_parser("assess", help="add the current revision of a claim's assessment"))
    assess.add_argument("claim")
    assess.add_argument("--expected-revision", type=int,
                        help="the revision you reviewed (required when an assessment exists; 'genealogy history' shows it)")
    assess.add_argument("--scope", default="project", help="whose assessment: 'project' or a researcher scope")
    assess.add_argument("--status", help="your status word (recorded as written)")
    assess.add_argument("--grade", help="your grade label (mapped only by [grades] in genealogy.toml)")
    assess.add_argument("--confidence", choices=("documented", "probable", "possible", "disproved", "unknown"))
    assess.add_argument("--estimate", type=int, help="an optional subjective estimate, 0-100 (never inferred)")
    assess.add_argument("--reasoning")
    assess.add_argument("--limitations")
    assess.add_argument("--assessed-on")
    assess.add_argument("--basis", action="append", default=[], metavar="ID")

    history = commands.add_parser("history", help="show a claim's assessment history")
    history.add_argument("claim")
    history.add_argument("--scope", default="project")

    evidence = commands.add_parser("evidence", help="link a citation or record to a claim, for or against")
    e_sub = evidence.add_subparsers(dest="evidence_command", required=True)
    e_add = actor(e_sub.add_parser("add"))
    e_add.add_argument("claim")
    e_add.add_argument("--citation")
    e_add.add_argument("--record")
    e_add.add_argument("--mention")
    e_add.add_argument("--stance", choices=("supports", "opposes", "context"), default="supports")
    e_add.add_argument("--interpretation")
    e_add.add_argument("--independence-key", help="items sharing a key repeat the same underlying information")
    e_add.add_argument("--limitation")

    depend = actor(commands.add_parser("depend", help="record that a conclusion rests on a premise"))
    depend.add_argument("dependent")
    depend.add_argument("premise")
    depend.add_argument("--note")
    review = commands.add_parser("review", help="list or acknowledge conclusions flagged by changed premises")
    review_sub = review.add_subparsers(dest="review_command", required=True)
    review_sub.add_parser("list")
    ack = actor(review_sub.add_parser("ack"))
    ack.add_argument("dependency")
    ack.add_argument("--expected-revision", type=int, required=True)
    ack.add_argument("--note")

    legacy = commands.add_parser("legacy", help="list or resolve items an import kept for review")
    lg_sub = legacy.add_subparsers(dest="legacy_command", required=True)
    lg_list = lg_sub.add_parser("list", help="items kept for review (open ones unless --all)")
    lg_list.add_argument("--all", action="store_true", help="include resolved items")
    lg_list.add_argument("--disposition", choices=("unresolved", "excluded", "unsupported", "conflict"))
    lg_list.add_argument("--input", dest="input_prefix", metavar="PATH", help="only items from inputs under PATH")
    lg_res = actor(lg_sub.add_parser("resolve", help="record what was decided about an item, and why"))
    lg_res.add_argument("item", nargs="?")
    lg_res.add_argument("--resolution", help="what was decided and why")
    lg_res.add_argument("--expected-revision", type=int)
    lg_res.add_argument("--from", dest="from_file", type=Path,
                        help="JSON list of {id, expected_revision, resolution}, resolved in one transaction")

    note = commands.add_parser("note", help="add research prose linked to entities")
    n_sub = note.add_subparsers(dest="note_command", required=True)
    n_add = actor(n_sub.add_parser("add"))
    n_add.add_argument("text", nargs="?")
    n_add.add_argument("--file", type=Path, help="long prose kept as a file (registered as an asset)")
    n_add.add_argument("--kind", default="note")
    n_add.add_argument("--title")
    n_add.add_argument("--about", action="append", default=[], metavar="ID")
    n_add.add_argument("--access", choices=ACCESS, default="private")

    question = commands.add_parser("question", help="add or update a research question")
    q_sub = question.add_subparsers(dest="question_command", required=True)
    q_add = actor(q_sub.add_parser("add"))
    q_add.add_argument("question")
    q_add.add_argument("--about", action="append", default=[], metavar="ID")
    q_add.add_argument("--resolves", help="what evidence would answer it")
    q_add.add_argument("--next", dest="next_action")
    q_add.add_argument("--resume-when", dest="resume_condition")
    q_add.add_argument("--priority", default="normal")
    q_add.add_argument("--access", choices=ACCESS, default="private")
    q_add.add_argument("--id")
    q_status = actor(q_sub.add_parser("status"))
    q_status.add_argument("question")
    q_status.add_argument("status")
    q_status.add_argument("--expected-revision", type=int, required=True)
    q_status.add_argument("--closed-on")

    hypothesis = commands.add_parser("hypothesis", help="record an identity, parentage or other hypothesis")
    h_sub = hypothesis.add_subparsers(dest="hypothesis_command", required=True)
    h_add = actor(h_sub.add_parser("add"))
    h_add.add_argument("statement")
    h_add.add_argument("--kind", default="other")
    h_add.add_argument("--about", action="append", default=[], metavar="ID")
    h_add.add_argument("--supports")
    h_add.add_argument("--objections")
    h_add.add_argument("--access", choices=ACCESS, default="private")
    h_add.add_argument("--id")

    asset = commands.add_parser("asset", help="register evidence files, or verify every referenced file")
    a_sub = asset.add_subparsers(dest="asset_command", required=True)
    a_add = actor(a_sub.add_parser("add"))
    a_add.add_argument("file", type=Path)
    a_add.add_argument("--root", default="managed", help="'managed' copies into private storage; or a configured root")
    a_add.add_argument("--kind", default="file")
    a_add.add_argument("--about", action="append", default=[], metavar="ID")
    a_add.add_argument("--access", choices=ACCESS, default="private")
    a_add.add_argument("--captured-on")
    a_add.add_argument("--provenance")
    a_sub.add_parser("verify")

    approval = commands.add_parser("approval", help="record or list publication approvals")
    ap_sub = approval.add_subparsers(dest="approval_command", required=True)
    ap_add = actor(ap_sub.add_parser("add", help="approve one exact file (by its current SHA-256) for a public path"))
    ap_add.add_argument("file", type=Path)
    ap_add.add_argument("target", help="public path, e.g. images/will-1805-crop.jpg")
    ap_add.add_argument("--authority", required=True, help="who approved it, in their words")
    ap_add.add_argument("--approved-on")
    ap_sub.add_parser("list")

    native = commands.add_parser("native", help="complete versioned native JSON export and import")
    nat_sub = native.add_subparsers(dest="native_command", required=True)
    nat_exp = nat_sub.add_parser("export")
    nat_exp.add_argument("output", type=Path, help="a .json file, or a new directory with --package")
    nat_exp.add_argument("--package", action="store_true", help="write a package with every referenced file")
    nat_imp = nat_sub.add_parser("import", help="create a new project database from a native export")
    nat_imp.add_argument("input", type=Path, help="native.json or a package directory")
    nat_imp.add_argument("target", type=Path, help="new database file to create")

    backup = commands.add_parser("backup", help="consistent backup, verification and restoration")
    b_sub = backup.add_subparsers(dest="backup_command", required=True)
    b_create = b_sub.add_parser("create")
    b_create.add_argument("destination", nargs="?", type=Path)
    b_create.add_argument("--label")
    b_create.add_argument("--exclude-root", action="append", default=[],
                          help="record this asset root's files by hash only (e.g. a Git checkout backed up elsewhere)")
    b_verify = b_sub.add_parser("verify")
    b_verify.add_argument("backup", type=Path)
    b_restore = b_sub.add_parser("restore")
    b_restore.add_argument("backup", type=Path)
    b_restore.add_argument("target", type=Path, help="a new, empty directory")

    gedcom = commands.add_parser("gedcom", help="GEDCOM 7.0 or 5.5.1 export with a loss report")
    g_sub = gedcom.add_subparsers(dest="gedcom_command", required=True)
    g_exp = g_sub.add_parser("export")
    g_exp.add_argument("output", type=Path)
    g_exp.add_argument("--version", dest="gedcom_version", choices=("7.0", "5.5.1"), default="7.0")
    g_exp.add_argument("--private", action="store_true", help="include private research (never publish this file)")
    g_exp.add_argument("--date", help="export date written in the header (YYYY-MM-DD)")

    proposal = commands.add_parser("proposal", help="check, diff or apply a reviewable change proposal")
    pr_sub = proposal.add_subparsers(dest="proposal_command", required=True)
    for name in ("check", "diff", "apply"):
        sub = pr_sub.add_parser(name)
        sub.add_argument("file", type=Path)
        if name == "apply":
            actor(sub)
            sub.add_argument("--approved-by")

    wikitree = commands.add_parser("wikitree", help="record captures and compare profiles three ways (no live edits)")
    w_sub = wikitree.add_subparsers(dest="wikitree_command", required=True)
    w_cap = actor(w_sub.add_parser("capture", help="record a saved WikiTree API profile JSON as an observation"))
    w_cap.add_argument("file", type=Path)
    w_cap.add_argument("--captured-on", required=True)
    w_cap.add_argument("--accept-baseline", action="store_true", help="make this capture the accepted baseline")
    w_cmp = w_sub.add_parser("compare", help="baseline vs local proposal vs latest capture")
    w_cmp.add_argument("profile")
    w_cmp.add_argument("local", type=Path, help="JSON object of the locally proposed field values")
    w_cmp.add_argument("--record-proposal", action="store_true", help="save the result as a draft proposal")
    w_cmp.add_argument("--actor")

    show = commands.add_parser("show", help="show any entity with its links, revisions and origin")
    show.add_argument("entity")

    publication = commands.add_parser("publication", help="report what the public projection includes and omits")
    publication.add_argument("--year", type=int)


REFERENCE_ARGUMENTS = ("claim", "person", "child", "relative", "record", "mention", "source", "citation", "dependent",
                       "premise", "entity", "question", "transcription", "dependency", "profile_entity")


def resolve_references(store: Any, args: argparse.Namespace) -> None:
    """Let commands name entities by external identifier: SYSTEM:VALUE, e.g. wikitree:Ada-12."""
    def resolve(value: str) -> str:
        if not isinstance(value, str) or store.entity_type(value) or ":" not in value:
            return value
        system, _, external = value.partition(":")
        rows = store.all("SELECT DISTINCT entity_id FROM external_id WHERE system=? AND value=? AND status IN "
                         "('current', 'redirect') ORDER BY entity_id", (system, external))
        if len(rows) > 1:
            raise StoreError(f"{value} identifies {len(rows)} entities; use one of: "
                             + ", ".join(row["entity_id"] for row in rows))
        return rows[0]["entity_id"] if rows else value
    for name in REFERENCE_ARGUMENTS:
        if isinstance(getattr(args, name, None), str):
            setattr(args, name, resolve(getattr(args, name)))
    for name in ("about", "basis", "related"):
        values = getattr(args, name, None)
        if isinstance(values, list):
            setattr(args, name, [resolve(value) for value in values])


def _project(args: argparse.Namespace, *, readonly: bool = False):
    return open_project(args.project, readonly=readonly, create=args.command == "upgrade")


def run(args: argparse.Namespace) -> int:
    command = args.command
    if command == "db" and args.db_command == "init":
        project = open_project(args.project, create=True)
        print(f"Project database ready at {project.database_path}")
        project.close()
        return 0
    if command == "db" and args.db_command == "migrate":
        from .store.core import migrate_store
        from .store.project import StorageSettings, load_config
        settings = StorageSettings.from_config(load_config(args.project))
        _print(migrate_store(Path(args.project) / settings.database))
        return 0
    if command == "native" and args.native_command == "import":
        from .store.native import import_document, verify_package
        source = args.input
        if source.is_dir():
            problems = verify_package(source)
            if problems:
                raise StoreError("package does not verify: " + "; ".join(problems[:5]))
            source = source / "native.json"
        store = import_document(json.loads(source.read_text(encoding="utf-8")), args.target)
        print(f"Created {args.target} from {source}")
        store.close()
        return 0
    if command == "backup" and args.backup_command in ("verify", "restore"):
        from .store.backup import restore_backup, verify_backup
        if args.backup_command == "verify":
            problems = verify_backup(args.backup)
            for problem in problems:
                print(f"problem: {problem}", file=sys.stderr)
            print("Backup verified." if not problems else f"{len(problems)} problems.")
            return 1 if problems else 0
        _print(restore_backup(args.backup, args.target))
        return 0
    with _project(args) as project:
        research = Research(project.store)
        store = project.store
        resolve_references(store, args)
        write = lambda: store.write(actor=_actor(args), reason=getattr(args, "reason", None),  # noqa: E731
                                    tool=f"genealogy {command}")
        if command == "db":
            if args.db_command == "status":
                from .store.operations import status
                _print(status(project))
                return 0
            from .store.assets import verify_assets
            integrity = store.one("PRAGMA integrity_check")
            broken = store.all("PRAGMA foreign_key_check")
            files = verify_assets(project)
            report = {"integrity": list(integrity.values())[0], "broken_references": len(broken),
                      "missing_files": files["missing"][:20], "changed_files": files["changed"][:20],
                      "unreferenced_managed_files": len(files["orphans"]),
                      "review_needed": len(research.review_queue())}
            _print(report)
            return 0 if report["integrity"] == "ok" and not broken and not files["missing"] and not files["changed"] else 1
        if command == "upgrade":
            from .store.operations import upgrade_cases
            report = upgrade_cases(project, actor=_actor(args))
            _print(report)
            if report["conflicts"]:
                print(f"{len(report['conflicts'])} conflicting records were kept for review (legacy_item rows).",
                      file=sys.stderr)
            return 0
        if command == "person":
            if args.person_command == "list":
                rows = store.all("SELECT p.id, p.label, p.living, p.access, group_concat(n.full_name, ' | ') AS names "
                                 "FROM person p LEFT JOIN person_name n ON n.person_id=p.id GROUP BY p.id ORDER BY p.id")
                _print(rows)
                return 0
            with write() as tx:
                person_id = research.create_person(
                    tx, id=args.id, names=[NameInput(args.name, given=args.given, surname=args.surname, preferred=True)],
                    sex=args.sex, living=args.living, label=args.label, record_defined=args.record_defined,
                    access=args.access)
                for item in args.external:
                    system, _, value = item.partition(":")
                    if not value:
                        raise StoreError(f"--external must be SYSTEM:VALUE, not {item!r}")
                    research.map_external(tx, person_id, system, value)
            print(person_id)
            return 0
        if command == "source":
            with write() as tx:
                source_id = research.register_source(tx, id=args.id, title=args.title, kind=args.kind, author=args.author,
                                                     publication=args.publication, url=args.url,
                                                     originality=args.originality, access=args.access)
                if args.repository or args.catalogue_ref:
                    repository = research.add_repository(tx, name=args.repository) if args.repository else None
                    research.add_holding(tx, source_id=source_id, repository_id=repository,
                                         catalogue_ref=args.catalogue_ref)
            print(source_id)
            return 0
        if command == "record":
            from .store.projection import public_case
            if args.record_command in ("list", "show"):
                case, _ = public_case(project, everything=True)
                rows = [(type(r).__name__, r) for records in case.record_sets.values() for r in records]
                if args.record_command == "show":
                    match = [(kind, r) for kind, r in rows if r.id == args.record_id]
                    if not match:
                        raise StoreError(f"record not found: {args.record_id}")
                    _print({"record_type": match[0][0], "record": match[0][1].to_dict()})
                    return 0
                _print([{"record_type": kind, "record": r.to_dict()} for kind, r in rows
                        if not args.kind or kind == args.kind])
                return 0
            if args.input:
                from .cli import record_payload
                from .store.importer import new_loader
                from .store.services import stable_id
                record = record_payload(args.input, args.record_type)
                with write() as tx:
                    batch_id = stable_id("imp", "record", record.id, args.input.name)
                    if not store.get("import_batch", batch_id):
                        tx.insert("import_batch", {"id": batch_id, "adapter": "record-json",
                                                   "input_label": args.input.name, "imported_at": store.clock()})
                    loader = new_loader(research, tx, batch_id=batch_id, input_path=args.input.name, origin="research")
                    loader.load([record])
                    loader.finish()
                    if loader.conflicts:
                        raise StoreError(f"{record.id} already exists with different content; change it with a proposal")
                print(f"Recorded {args.record_type} {record.id}.")
                return 0
            if not args.title:
                raise StoreError("record add needs --title (or --input FILE for a legacy JSON record)")
            with write() as tx:
                record_id = research.add_record(tx, id=args.id, title=args.title, source_id=args.source,
                                                record_type=args.record_type, locator=args.locator,
                                                date_original=args.date, date_start=args.date_start,
                                                date_kind=args.date_kind, place_wording=args.place,
                                                summary=args.summary, information=args.information, access=args.access)
            print(record_id)
            return 0
        if command == "citation":
            with write() as tx:
                print(research.add_citation(tx, id=args.id, source_id=args.source, record_id=args.record,
                                            locator=args.locator, accessed_on=args.accessed_on, access=args.access))
            return 0
        if command == "transcription":
            with write() as tx:
                if args.transcription_command == "add":
                    print(research.add_transcription(tx, id=args.id, record_id=args.record, text=args.text,
                                                     kind=args.kind, reader=args.reader, read_on=args.read_on,
                                                     access=args.access))
                elif args.transcription_command == "revise":
                    print(research.revise_transcription(tx, args.transcription, expected_revision=args.expected_revision,
                                                        text=args.text, reason=args.why))
                else:
                    print(research.withdraw_transcription(tx, args.transcription,
                                                          expected_revision=args.expected_revision, reason=args.why))
            return 0
        if command == "mention":
            with write() as tx:
                print(research.add_mention(tx, id=args.id, record_id=args.record, role=args.role,
                                           name_as_written=args.name_as_written, details=args.details,
                                           access=args.access))
            return 0
        if command == "identify":
            with write() as tx:
                claim_id = research.identity_claim(tx, id=args.id, mention_id=args.mention, person_id=args.person,
                                                   proposition=args.statement)
                if args.status or args.reasoning:
                    research.assess(tx, claim_id, new=True, status=args.status, reasoning=args.reasoning)
            print(claim_id)
            return 0
        if command == "relationship":
            with write() as tx:
                print(research.relationship_claim(tx, id=args.id, child_id=args.child, relative_id=args.relative,
                                                  role=args.role, relation_type=args.relation_type,
                                                  proposition=args.statement, access=args.access))
            return 0
        if command == "claim":
            with write() as tx:
                print(research.create_claim(tx, id=args.id, kind=args.kind, predicate=args.predicate,
                                            proposition=f"{args.predicate}: {args.value}", value_text=args.value,
                                            subject_person_id=args.person, access=args.access))
            return 0
        if command == "assess":
            existing = research.current_assessment(args.claim, args.scope)
            if existing and args.expected_revision is None:
                raise StoreError(f"{args.claim} already has assessment revision {existing['current_revision']} in scope "
                                 f"{args.scope}; review it ('genealogy history {args.claim}') and pass "
                                 f"--expected-revision {existing['current_revision']}")
            with write() as tx:
                if args.scope != "project":
                    research.ensure_scope(tx, args.scope, name=args.scope)
                _, revision = research.assess(
                    tx, args.claim, scope_id=args.scope, new=existing is None,
                    expected_revision=args.expected_revision if existing else None, status=args.status,
                    grade=args.grade, vocabulary="project-grades" if args.grade else None, confidence=args.confidence,
                    estimate_percent=args.estimate, estimate_kind="subjective" if args.estimate is not None else None,
                    reasoning=args.reasoning, limitations=args.limitations, assessed_on=args.assessed_on,
                    basis=args.basis)
            print(f"{args.claim}: assessment revision {revision}")
            return 0
        if command == "history":
            _print({"current": research.current_assessment(args.claim, args.scope),
                    "history": research.assessment_history(args.claim, args.scope)})
            return 0
        if command == "evidence":
            with write() as tx:
                print(research.add_evidence(tx, claim_id=args.claim, citation_id=args.citation, record_id=args.record,
                                            mention_id=args.mention, stance=args.stance,
                                            interpretation=args.interpretation,
                                            independence_key=args.independence_key, limitation=args.limitation))
            return 0
        if command == "depend":
            with write() as tx:
                print(research.add_dependency(tx, dependent_id=args.dependent, premise_id=args.premise, note=args.note))
            return 0
        if command == "review":
            if args.review_command == "list":
                _print(research.review_queue())
                return 0
            with write() as tx:
                research.acknowledge_dependency(tx, args.dependency, expected_revision=args.expected_revision,
                                                note=args.note)
            print(f"Acknowledged {args.dependency}.")
            return 0
        if command == "legacy":
            if args.legacy_command == "list":
                _print(research.legacy_items(open_only=not args.all, disposition=args.disposition,
                                             input_prefix=args.input_prefix))
                return 0
            if args.from_file:
                decisions = json.loads(args.from_file.read_text(encoding="utf-8"))
            elif args.item and args.resolution and args.expected_revision is not None:
                decisions = [{"id": args.item, "expected_revision": args.expected_revision,
                              "resolution": args.resolution}]
            else:
                raise StoreError("legacy resolve needs ITEM --resolution TEXT --expected-revision N, or --from FILE")
            with write() as tx:
                for decision in decisions:
                    research.resolve_legacy_item(tx, decision["id"], resolution=decision["resolution"],
                                                 expected_revision=decision["expected_revision"],
                                                 resolved_by=_actor(args))
            print(f"Resolved {len(decisions)} item(s).")
            return 0
        if command == "note":
            asset_id = None
            prepared = None
            if args.file:
                from .store.assets import prepare_managed, register_asset
                prepared = prepare_managed(project, args.file)
            if not args.text and not args.file:
                raise StoreError("note add needs TEXT or --file")
            with write() as tx:
                if args.file:
                    asset_id = register_asset(project, tx, args.file, kind="prose", prepared=prepared,
                                              access=args.access, immutable=False)["id"]
                print(research.add_note(tx, text=args.text, asset_id=asset_id, kind=args.kind, title=args.title,
                                        access=args.access, links=args.about))
            return 0
        if command == "question":
            with write() as tx:
                if args.question_command == "add":
                    print(research.add_question(tx, id=args.id, question=args.question, priority=args.priority,
                                                resolves=args.resolves, next_action=args.next_action,
                                                resume_condition=args.resume_condition, access=args.access,
                                                links=args.about))
                else:
                    research.set_question_status(tx, args.question, args.status,
                                                 expected_revision=args.expected_revision, closed_on=args.closed_on)
                    print(f"{args.question}: {args.status}")
            return 0
        if command == "hypothesis":
            with write() as tx:
                print(research.add_hypothesis(tx, id=args.id, statement=args.statement, kind=args.kind,
                                              supports=args.supports, objections=args.objections, access=args.access,
                                              links=args.about))
            return 0
        if command == "asset":
            from .store.assets import prepare_managed, register_asset, verify_assets
            if args.asset_command == "verify":
                report = verify_assets(project)
                _print({key: value[:50] for key, value in report.items()})
                return 1 if report["missing"] or report["changed"] else 0
            prepared = prepare_managed(project, args.file) if args.root == "managed" else None
            with write() as tx:
                asset = register_asset(project, tx, args.file, root=args.root, kind=args.kind, access=args.access,
                                       captured_on=args.captured_on, provenance=args.provenance, prepared=prepared)
                for target in args.about:
                    tx.upsert_link(asset["id"], target, "evidence_file")
            print(asset["id"])
            return 0
        if command == "approval":
            if args.approval_command == "list":
                _print(store.all("SELECT * FROM approval ORDER BY target"))
                return 0
            from .store.assets import sha256_file
            with write() as tx:
                print(research.add_approval(tx, kind="exact_file", target=args.target, sha256=sha256_file(args.file),
                                            source_path=str(args.file), authority=args.authority,
                                            approved_on=args.approved_on))
            return 0
        if command == "native":
            from .store.native import dumps, export_document, write_package
            if args.package:
                _print(write_package(project, args.output))
            else:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(dumps(export_document(store)), encoding="utf-8")
                args.output.chmod(0o600)
                print(f"Wrote complete private native export to {args.output}")
            return 0
        if command == "backup":
            from .store.backup import create_backup
            report = create_backup(project, args.destination, label=args.label, exclude_roots=tuple(args.exclude_root))
            _print({key: report[key] for key in ("path", "schema_version", "logical_digest", "asset_count",
                                                  "referenced_only")})
            return 0
        if command == "gedcom":
            from .store.gedcom_export import export_gedcom
            from .store.project import workbench_version
            allowed = None
            if not args.private:
                from .store.projection import public_case
                case, _ = public_case(project)
                allowed = {r.id for records in case.record_sets.values() for r in records}
                allowed |= {row["id"] for row in store.all("SELECT id FROM place WHERE access='public'")}
            text, report = export_gedcom(store, version=args.gedcom_version, allowed=allowed,
                                         project_name=project.config.name, export_date=args.date,
                                         workbench_version=workbench_version())
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
            loss = args.output.with_suffix(args.output.suffix + ".report.json")
            loss.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            print(f"Wrote GEDCOM {args.gedcom_version} to {args.output}; loss report {loss}")
            return 0
        if command == "proposal":
            from .store import proposals
            document = proposals.load(json.loads(args.file.read_text(encoding="utf-8")))
            if args.proposal_command == "check":
                stale = proposals.check(store, document)
                _print({"stale": stale, "ok": not stale})
                return 1 if stale else 0
            if args.proposal_command == "diff":
                print("\n".join(proposals.diff(store, document)))
                return 0
            _print(proposals.apply(store, document, actor=_actor(args), approved_by=args.approved_by))
            return 0
        if command == "wikitree":
            from .store.wikitree_sync import compare
            if args.wikitree_command == "capture":
                data = json.loads(args.file.read_text(encoding="utf-8"))
                profile = data.get("Name") or data.get("profile")
                if not profile:
                    raise StoreError("the capture needs a WikiTree 'Name' (profile id)")
                entity = (research.find_external("wikitree", profile) or [None])[0]
                with write() as tx:
                    observation, created = research.record_observation(tx, system="wikitree", external_value=profile,
                                                                        fields=data, captured_on=args.captured_on,
                                                                        entity_id=entity)
                    if args.accept_baseline:
                        research.set_baseline(tx, system="wikitree", external_value=profile,
                                              observation_id=observation, accepted_on=args.captured_on)
                print(f"{observation} ({'new' if created else 'already recorded'})")
                return 0
            baseline = store.one("SELECT o.* FROM remote_baseline b JOIN external_observation o ON o.id=b.observation_id "
                                 "WHERE b.system='wikitree' AND b.external_value=?", (args.profile,))
            latest = research.latest_observation("wikitree", args.profile)
            local = json.loads(args.local.read_text(encoding="utf-8"))
            result = compare(args.profile, json.loads(baseline["fields_json"]) if baseline else None, local,
                             latest["fields"] if latest else None)
            output = result.to_dict()
            if args.record_proposal:
                with store.write(actor=args.actor or "cli", tool="genealogy wikitree compare") as tx:
                    output["proposal_id"] = research.create_proposal(
                        tx, kind="wikitree_update", system="wikitree", target=args.profile, status="draft",
                        basis={"baseline": baseline["id"] if baseline else None,
                               "remote": latest["id"] if latest else None},
                        diff=output, authored=False)
            _print(output)
            return 0
        if command == "show":
            kind = store.entity_type(args.entity)
            if kind is None:
                raise StoreError(f"no entity {args.entity!r}")
            row = store.get(kind, args.entity)
            detail: dict[str, Any] = {"type": kind, "row": row,
                                      "links_from": store.all("SELECT * FROM link WHERE from_id=?", (args.entity,)),
                                      "links_to": store.all("SELECT * FROM link WHERE to_id=?", (args.entity,)),
                                      "external_ids": store.all("SELECT * FROM external_id WHERE entity_id=?", (args.entity,)),
                                      "origin": store.all("SELECT * FROM import_origin WHERE entity_id=?", (args.entity,))}
            if kind == "person":
                detail["relationships"] = research.relationship_views(args.entity)
            if kind == "claim":
                detail["history"] = research.assessment_history(args.entity)
            _print(detail)
            return 0
        if command == "publication":
            from .store.projection import public_case
            case, omissions = public_case(project, build_year=args.year)
            _print({"published": {kind: len(records) for kind, records in case.record_sets.items()},
                    "omitted": omissions.counts(), "files": omissions.published_assets})
            return 0
    raise StoreError(f"unhandled command {command}")
