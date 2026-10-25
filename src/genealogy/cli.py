"""Command line interface for configured, durable genealogy research cases."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from importlib.resources import files
from importlib.metadata import version, PackageNotFoundError
import sys
from pathlib import Path
from typing import Any, Mapping

from .adapters import resolve_adapter
from .case import CaseStore, ResearchCase, grade_errors, validate_case
from .config import ProjectConfig, safe_relative_path
from .exports import (
    build_public_views, configured_views, project_for_public_export, render, safe_output_path,
)
from .artifacts import read_case_artifact_bundle, write_case_artifact_bundle
from .models import AccessLevel, Confidence, Finding, MODEL_TYPES, Record, Search, record_from_dict
from .research import ResearchService

def load_case(directory: Path, case_id: str | None = None) -> tuple[ResearchCase, ProjectConfig]:
    config_path = directory / "genealogy.toml"
    if not config_path.is_file():
        if (directory / "genealogy.json").is_file():
            raise ValueError("genealogy.json is a legacy interchange input; migrate it to a configured case")
        raise ValueError(f"No project configuration at {config_path}")
    config = ProjectConfig.load(config_path)
    selected = case_id or config.default_case
    if not selected:
        raise ValueError("Set project.default_case in genealogy.toml or pass --case")
    return CaseStore(project_path(directory, config.case_directory, "project.case_directory")).load(selected), config


def load_config(directory: Path) -> ProjectConfig:
    config_path = directory / "genealogy.toml"
    if not config_path.is_file():
        raise ValueError(f"No project configuration at {config_path}")
    return ProjectConfig.load(config_path)


def check_links(args: argparse.Namespace) -> int:
    from .sitecheck import check_site, pairs_of, ratchet, read_baseline, write_baseline
    site = args.site or (args.project / "dist")
    if not site.is_dir():
        raise ValueError(f"site folder not found: {site}; build it first")
    result = check_site(site)
    current = pairs_of(result["broken"])
    baseline = read_baseline(args.baseline) if args.baseline else None
    new, fixed = ratchet(current, baseline)
    if args.update_baseline:
        if not args.baseline:
            raise ValueError("--update-baseline needs --baseline PATH")
        write_baseline(args.baseline, current if baseline is None else baseline & current)
        new = [] if baseline is None else new
        fixed = []
    print(f"Checked {result['pages']} pages and {result['internal_references']} internal references: "
          f"{len(result['broken'])} broken links ({len(current)} page-target pairs), {len(result['missing_anchors'])} missing anchors.")
    for row in result["broken"][:20]:
        print(f"  broken  {row['page']} -> {row['target']} ({row['how']})")
    for row in result["missing_anchors"][:20]:
        print(f"  anchor  {row['page']} -> {row['target']}#{row['anchor']}")
    if baseline is not None:
        print(f"Baseline: {len(new)} new pairs, {len(fixed)} fixed pairs.")
    return 1 if new or (baseline is None and result["missing_anchors"]) else 0


def project_path(directory: Path, configured: str, setting: str) -> Path:
    """Resolve a configured path and reject traversal or symlink escapes."""
    safe_relative_path(configured, setting=setting)
    root = directory.resolve()
    candidate = (root / configured).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"{setting} escapes the project directory")
    return candidate


def public_project(case: ResearchCase, config: ProjectConfig) -> dict[str, Any]:
    """Compatibility wrapper; prefer :func:`project_for_public_export`."""
    return project_for_public_export(case, config)


def adapter_payload(path: Path, adapter_name: str) -> Any:
    """Read a caller-selected input in the adapter's native interchange form."""
    if adapter_name in {"gedcom", "ocr", "spreadsheets", "tabular"}:
        return path.read_text(encoding="utf-8-sig")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{adapter_name} input must be valid JSON: {path}") from error


def record_payload(path: Path, record_type: str) -> Record:
    """Load one strict core-record JSON object; adapters are not involved."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{record_type} input must be valid JSON: {path}") from error
    if not isinstance(data, dict):
        raise ValueError(f"{record_type} input must be a JSON object: {path}")
    try:
        return record_from_dict(record_type, data)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid {record_type} record: {error}") from error


def adapter_is_enabled(config: ProjectConfig, adapter_name: str) -> bool:
    enabled = config.adapters.get("enabled")
    if enabled is None:
        return True
    if not isinstance(enabled, list) or not all(isinstance(value, str) for value in enabled):
        raise ValueError("adapters.enabled must be a list of adapter names")
    normalised = {value.casefold().replace("_", "-") for value in enabled}
    return adapter_name in normalised


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build(project: Mapping[str, Any], output: Path, config: ProjectConfig | None = None) -> None:
    """Compatibility builder for an already privacy-filtered project mapping."""
    config = config or ProjectConfig()
    for section, default_name, content in configured_views(project, config):
        configured_name = getattr(config, section).get("output", default_name)
        write_text(safe_output_path(output, configured_name), content)


def copy_starter(target: Path) -> None:
    """Copy the packaged starter tree without depending on a source checkout."""
    template = files("genealogy").joinpath("starter")
    for source in template.iterdir():
        if source.name in ("cases", "__pycache__"):
            continue  # research lives in the project database, not in JSON case files
        destination = target / source.name
        if source.is_dir():
            copy_starter_tree(source, destination)
        else:
            destination.write_bytes(source.read_bytes())


def copy_starter_tree(source: Any, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        target = destination / child.name
        if child.is_dir():
            copy_starter_tree(child, target)
        else:
            target.write_bytes(child.read_bytes())


def initialize_project(target: Path, name: str | None = None) -> None:
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError(f"Refusing to overwrite non-empty directory: {target}")
    if name is not None and (not name.strip() or len(name) > 120 or any(ord(c) < 32 for c in name)):
        raise ValueError("Project name must contain 1–120 printable characters")
    target.mkdir(parents=True, exist_ok=True)
    copy_starter(target)
    if name is not None:
        config_path = target / "genealogy.toml"
        content = config_path.read_text(encoding="utf-8")
        old_name = ProjectConfig.load(config_path).name
        config_path.write_text(content.replace(
            f'name = "{old_name}"', f'name = {json.dumps(name.strip(), ensure_ascii=False)}', 1
        ), encoding="utf-8")
    from .store import open_project
    open_project(target, create=True).close()


def build_project(case: ResearchCase, config: ProjectConfig, output: Path) -> None:
    from .site import build_site
    build_public_views(case, config, output)
    build_site(case, config, output)


def logs_search(argv: list[str]) -> bool:
    """Whether the command is ``search add ID TEXT ...`` rather than a search for the word "add"."""
    index = 0
    while index < len(argv):
        word = argv[index]
        if word in ("--project", "--case"):
            index += 2
        elif word.startswith("-"):
            index += 1
        else:
            return word == "search" and argv[index + 1:index + 2] == ["add"] and len(argv) > index + 2
    return False


def parser(log_search: bool = False) -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="genealogy", description="Portable genealogy research toolkit")
    try:
        installed_version = version("genealogy-research-workbench")
    except PackageNotFoundError:
        installed_version = "0.1.0"
    result.add_argument("--version", action="version", version=f"%(prog)s {installed_version}")
    result.add_argument("--project", type=Path, default=Path("."), help="project directory (default: current directory)")
    result.add_argument("--case", help="case identifier (defaults to project.default_case)")
    commands = result.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="create a starter research project")
    init.add_argument("directory", type=Path)
    init.add_argument("--name", help="public project/site title (no private personal details)")
    imported = commands.add_parser("import", help="import GEDCOM or OneTree JSON into the project database")
    imported.add_argument("input", type=Path)
    imported.add_argument("--format", choices=("auto", "gedcom", "gedzip", "one-tree"), default="auto")
    imported.add_argument("--publish-deceased", action="store_true",
                          help="confirm reviewed basic deceased/historical facts may be public; protected records stay private")
    imported.add_argument("--publish-reviewed-sources", action="store_true",
                          help="with --publish-deceased, confirm linked bibliographic titles/locators are reviewed; quotations stay private")
    imported.add_argument("--replace", action="store_true", help=argparse.SUPPRESS)
    imported.add_argument("--update", action="store_true",
                          help="refresh an earlier import of the same tree from a newer export; research is kept and "
                               "changed values are listed for review")
    imported.add_argument("--lineage", help="name for this tree's import lineage (default: format and file name)")
    serve = commands.add_parser("serve", help="open a local-only file upload and site preview server")
    serve.add_argument("--port", type=int, default=8000, help="loopback port (default: 8000)")
    commands.add_parser("validate", help="validate the selected durable research case")
    build_parser = commands.add_parser("build", help="create privacy-filtered catalogue, timeline and map")
    build_parser.add_argument("--output", type=Path, help="output folder (default: [exports] directory, normally dist)")
    links = commands.add_parser("check-links", help="report broken internal links and anchors in a built site")
    links.add_argument("site", nargs="?", type=Path, help="site folder (default: the project's dist/)")
    links.add_argument("--baseline", type=Path, help="JSON of known broken (page, target) pairs; new pairs fail")
    links.add_argument("--update-baseline", action="store_true", help="create the baseline, or remove pairs that are fixed")
    export = commands.add_parser("export", help="write a privacy-filtered machine-readable export")
    export.add_argument("format", choices=("json", "ndjson", "csv", "geojson", "gedcom"))
    export.add_argument("--output", type=Path)
    bundle = commands.add_parser("bundle", help="write or verify a complete private local artifact bundle")
    bundle.add_argument("--output", type=Path, default=Path("bundle"))
    bundle.add_argument("--verify", action="store_true", help="verify an existing bundle instead of writing one")
    ingest = commands.add_parser("ingest", help="normalise an explicit adapter input into the selected case")
    ingest.add_argument("adapter", help="configured adapter name")
    ingest.add_argument("input", type=Path, help="explicit source file; no input discovery is performed")
    cases = commands.add_parser("case", help="list or create durable research cases")
    case_commands = cases.add_subparsers(dest="case_command", required=True)
    case_commands.add_parser("list", help="list configured case files")
    create_case = case_commands.add_parser("create", help="create an empty durable case")
    create_case.add_argument("case_id", help="simple case identifier")
    create_case.add_argument("--title", required=True)
    create_case.add_argument("--summary", default="")
    findings = commands.add_parser("finding", help="add a durable finding to the selected case")
    finding_commands = findings.add_subparsers(dest="finding_command", required=True)
    add_finding = finding_commands.add_parser("add", help="record an evidence-linked conclusion")
    add_finding.add_argument("finding_id")
    add_finding.add_argument("conclusion")
    add_finding.add_argument("--related", action="append", default=[])
    add_finding.add_argument("--evidence", action="append", default=[])
    add_finding.add_argument("--cite", action="append", default=[], metavar="CITATION_ID",
                             help="a citation the finding rests on directly; repeat for several")
    add_finding.add_argument("--limitations", help="what the finding does not establish")
    add_finding.add_argument("--kind", help="your own grouping, e.g. vital, relationship or record")
    add_finding.add_argument("--change", action="append", default=[], metavar="RECORD_ID:BEFORE:AFTER",
                             help="a relationship or claim this finding reassessed, e.g. ada-parent:possible:documented "
                                  "(confidence values or grade keys; leave BEFORE empty for a new link); repeat for several")
    add_finding.add_argument("--status", default="draft")
    add_finding.add_argument("--recorded-on", help="ISO date the finding was reached (YYYY, YYYY-MM or YYYY-MM-DD); dates the findings log")
    add_finding.add_argument("--confidence", choices=tuple(Confidence), default=Confidence.UNKNOWN)
    add_finding.add_argument(
        "--sensitivity",
        choices=(AccessLevel.PUBLIC, AccessLevel.PRIVATE, AccessLevel.RESTRICTED, AccessLevel.LICENSED),
        default=AccessLevel.PRIVATE,
    )
    search = commands.add_parser("search", help="search typed records in the selected case; 'search add' logs a search you made")
    if log_search:
        # Kept apart from the record search so "genealogy search TEXT" still works.
        search_commands = search.add_subparsers(dest="search_command", required=True)
        add_search = search_commands.add_parser("add", help="log a search made, including one that found nothing")
        add_search.add_argument("search_id")
        add_search.add_argument("search", help="what was searched: repository, collection, years and names")
        add_search.add_argument("--result", required=True, help='what was found, including "nothing"')
        add_search.add_argument("--on", dest="searched_on", help="ISO date of the search (YYYY, YYYY-MM or YYYY-MM-DD)")
        add_search.add_argument("--for", dest="related", nargs="+", action="extend", required=True, metavar="RELATED_ID",
                                help="the people, places or sources searched for")
        add_search.add_argument("--cite", nargs="+", action="extend", default=[], metavar="CITATION_ID",
                                help="a record the search found")
        add_search.add_argument("--limitation", help="what the search could not cover, e.g. an index only, or missing years")
        add_search.add_argument(
            "--sensitivity",
            choices=(AccessLevel.PUBLIC, AccessLevel.PRIVATE, AccessLevel.RESTRICTED, AccessLevel.LICENSED),
            default=AccessLevel.PRIVATE,
        )
    else:
        search.add_argument("query")
        search.add_argument("--kind", help="optional model type, such as Person or Source")
    report = commands.add_parser("report", help="summarise unresolved work and evidence completeness")
    report.add_argument("--format", choices=("json", "markdown"), default="json")
    report.add_argument("--output", type=Path)
    from .cli_db import add_parsers
    add_parsers(commands)
    return result


def private_case_store(project: Any) -> tuple[ResearchCase, CaseStore, Any]:
    """The complete private view of the database as a read-only temporary case (for reports and searches)."""
    import tempfile
    from .store.projection import public_case
    case, _ = public_case(project, everything=True)
    directory = tempfile.TemporaryDirectory(prefix="genealogy-view-")
    store = CaseStore(Path(directory.name))
    store.save(case)
    return case, store, directory


def run_project_command(args: argparse.Namespace) -> int:
    """Project commands in database mode: every write goes through the domain services."""
    from .store import Research, open_project
    from .store.build import build_from_database
    from .store.importer import new_loader
    from .store.operations import import_genealogy_file
    from .store.projection import public_case
    from .store.services import stable_id
    with open_project(args.project) as project:
        config = project.config
        research = Research(project.store)
        actor = "cli"
        if args.command == "validate":
            case, _ = public_case(project, everything=True)
            errors = validate_case(case) + grade_errors(case, config.grades)
            # A grade label is kept as recorded; it needs a [grades] definition to be published with a meaning.
            for row in project.store.all(
                    "SELECT a.claim_id, r.grade FROM assessment a JOIN assessment_revision r ON r.assessment_id=a.id "
                    "AND r.revision=a.current_revision WHERE r.grade IS NOT NULL AND r.vocabulary='project-grades' "
                    "ORDER BY a.claim_id"):
                if row["grade"] not in config.grades:
                    errors.append(f"{row['claim_id']}.grade is not defined under [grades] in genealogy.toml: {row['grade']}")
            integrity = project.store.one("PRAGMA integrity_check")
            broken = project.store.all("PRAGMA foreign_key_check")
            if list(integrity.values())[0] != "ok":
                errors.append("database failed SQLite integrity_check")
            if broken:
                errors.append(f"database has {len(broken)} broken references")
            from .store.assets import verify_assets
            files = verify_assets(project, orphans=False)
            errors += [f"referenced file missing: {item['path']}" for item in files["missing"][:20]]
            errors += [f"referenced file changed: {item['path']}" for item in files["changed"][:20]]
            if errors:
                print("\n".join(f"error: {error}" for error in errors), file=sys.stderr)
                return 1
            review = research.review_queue()
            print("Research database is valid." + (f" {len(review)} conclusions need review after changed premises "
                                                   "('genealogy review list')." if review else ""))
            return 0
        if args.command == "import":
            if args.replace:
                raise ValueError("--replace is not supported for a research database: research is never discarded. "
                                 "Create a new project for an unrelated tree, or use --update for a newer export.")
            lineage = args.lineage
            previous = project.store.all("SELECT options_json FROM import_batch WHERE adapter=? AND options_json IS NOT NULL",
                                         (detect_import_format(args.input, args.format),))
            lineages = sorted({json.loads(row["options_json"]).get("lineage") for row in previous} - {None})
            if args.update:
                if not lineage:
                    if len(lineages) != 1:
                        raise ValueError("--update needs one earlier import of this format; found "
                                         f"{len(lineages)}. Name it with --lineage ({', '.join(lineages) or 'none'})")
                    lineage = lineages[0]
            elif lineages and not lineage and project.store.one("SELECT 1 FROM person LIMIT 1"):
                raise ValueError("The project already holds an imported tree; use --update to refresh it from a newer "
                                 "export (research is kept), or --lineage NAME to import a separate tree")
            report = import_genealogy_file(project, args.input, format=args.format, lineage=lineage,
                                           publish_deceased=args.publish_deceased,
                                           publish_reviewed_sources=args.publish_reviewed_sources)
            for warning in report.get("warnings", []):
                print(f"warning: {warning}", file=sys.stderr)
            print(json.dumps(report, ensure_ascii=False))
            print("Run genealogy --project <directory> build to generate the local site.")
            return 0
        if args.command == "ingest":
            adapter = resolve_adapter(args.adapter)
            if not adapter_is_enabled(config, adapter.name):
                raise ValueError(f"adapter is not enabled by project configuration: {adapter.name}")
            batch = adapter.ingest(adapter_payload(args.input, adapter.name))
            if batch.records and not batch.entities:
                raise ValueError(f"{adapter.name} input produced no neutral records")
            digest = hashlib.sha256(args.input.read_bytes()).hexdigest()
            batch_id = stable_id("imp", "ingest", adapter.name, digest)
            with project.store.write(actor=actor, tool="genealogy ingest", source=str(args.input)) as tx:
                if not project.store.get("import_batch", batch_id):
                    tx.insert("import_batch", {"id": batch_id, "adapter": adapter.name, "input_label": args.input.name,
                                               "input_sha256": digest, "imported_at": project.store.clock()})
                loader = new_loader(research, tx, batch_id=batch_id, input_path=args.input.name, origin="imported",
                                    input_sha256=digest)
                loader.load([e for e in batch.entities if type(e).__name__ != "ImportProvenance"])
                loader.finish()
                for item in batch.records:
                    research.record_observation(tx, system=adapter.name, external_value=item.external_id.value,
                                                fields={"raw": item.raw, "payload": item.payload},
                                                import_batch_id=batch_id)
            for warning in batch.warnings:
                print(f"warning: {warning}", file=sys.stderr)
            print(f"Imported {sum(v for k, v in loader.report.items() if not k.startswith(('conflict', 'unsupported')) and 'already' not in k)} "
                  f"neutral records through {adapter.name}.")
            return 0
        if args.command == "finding":
            changes = []
            for value in args.change:
                parts = value.rsplit(":", 2)
                if len(parts) != 3 or not parts[0] or not parts[2]:
                    raise ValueError(f"--change must be RECORD_ID:BEFORE:AFTER: {value}")
                changes.append({"record_id": parts[0], "before": parts[1] or None, "after": parts[2], "note": None})
            finding = Finding(id=args.finding_id, conclusion=args.conclusion, related_ids=args.related,
                              evidence_ids=args.evidence, status=args.status, confidence=Confidence(args.confidence),
                              sensitivity=AccessLevel(args.sensitivity), recorded_on=args.recorded_on,
                              limitations=args.limitations, citation_ids=args.cite, kind=args.kind, changes=changes)
            case, _ = public_case(project, everything=True)
            case.add(finding)
            errors = validate_case(case) + grade_errors(case, config.grades)
            if errors:
                raise ValueError("Validation failed:\n" + "\n".join(f"- {error}" for error in errors))
            with project.store.write(actor=actor, tool="genealogy finding add") as tx:
                loader = new_loader(research, tx, batch_id=None, input_path="cli", origin="research")
                loader.trace = lambda *a, **k: None
                loader.load([finding])
                loader.finish()
                if loader.conflicts:
                    raise ValueError(f"a record with id {args.finding_id} already exists")
            print(f"Recorded finding {args.finding_id}.")
            return 0
        if args.command == "search" and getattr(args, "search_command", None) == "add":
            search = Search(id=args.search_id, search=args.search, result=args.result, related_ids=args.related,
                            searched_on=args.searched_on, limitation=args.limitation, citation_ids=args.cite,
                            sensitivity=AccessLevel(args.sensitivity))
            case, _ = public_case(project, everything=True)
            case.add(search)
            errors = validate_case(case)
            if errors:
                raise ValueError("Validation failed:\n" + "\n".join(f"- {error}" for error in errors))
            with project.store.write(actor=actor, tool="genealogy search add") as tx:
                loader = new_loader(research, tx, batch_id=None, input_path="cli", origin="research")
                loader.trace = lambda *a, **k: None
                loader.load([search])
                loader.finish()
                if loader.conflicts:
                    raise ValueError(f"a record with id {args.search_id} already exists")
            print(f"Logged search {args.search_id}.")
            return 0
        if args.command in ("search", "report"):
            case, store, holder = private_case_store(project)
            with holder:
                service = ResearchService(store)
                if args.command == "search":
                    matches = service.search_records(case.id, args.query, kind=args.kind)
                    print(json.dumps([{"record_type": type(m.record).__name__, "matched_fields": m.matched_fields,
                                       "record": m.record.to_dict()} for m in matches], indent=2, ensure_ascii=False))
                    return 0
                content = (service.research_brief(case.id) if args.format == "markdown" else json.dumps({
                    "evidence_completeness": asdict(service.evidence_completeness(case.id)),
                    "unresolved_work": asdict(service.unresolved_work(case.id))}, indent=2, sort_keys=True) + "\n")
            if args.output:
                output = args.output if args.output.is_absolute() else args.project / args.output
                write_text(output, content)
                print(f"Wrote research report to {output}")
            else:
                print(content, end="")
            return 0
        if args.command == "bundle":
            from .store.native import verify_package, write_package
            output = args.output if args.output.is_absolute() else args.project / args.output
            if args.verify:
                problems = verify_package(output)
                if problems:
                    raise ValueError("bundle does not verify: " + "; ".join(problems[:5]))
                print(f"Verified private native package at {output}")
                return 0
            write_package(project, output)
            print(f"Wrote private native package (database export and files) to {output}")
            return 0
        if args.command == "build":
            output = None if args.output is None else (args.output if args.output.is_absolute() else args.project / args.output)
            report = build_from_database(project, output)
            output = report["output"]
            print(f"Built privacy-filtered views in {output} ({report['people']} people; "
                  f"{report['omission_count']} items withheld, listed in {report['report']})")
            return 0
        if args.command == "export":
            case, _ = public_case(project)
            safe_project = public_project(case, config)
            if args.output is None:
                export_directory = project_path(args.project, config.exports.get("directory", "dist"), "exports.directory")
                configured_name = config.exports.get(args.format, "research.ged" if args.format == "gedcom" else f"research.{args.format}")
                output = safe_output_path(export_directory, configured_name)
            else:
                output = args.output if args.output.is_absolute() else args.project / args.output
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(render(safe_project, args.format), encoding="utf-8")
            print(f"Wrote privacy-filtered {args.format} export to {output}")
            return 0
    raise ValueError(f"unsupported command: {args.command}")


def detect_import_format(path: Path, selected: str) -> str:
    from .importing import detect_format
    return detect_format(path.name, selected)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = parser(logs_search(argv)).parse_args(argv)
    try:
        if args.command == "init":
            target = args.directory
            initialize_project(target, args.name)
            print(f"Created research project at {target}")
            return 0
        if args.command == "serve":
            from .server import serve
            serve(args.project, args.port)
            return 0
        if args.command == "check-links":
            return check_links(args)
        if args.command == "case":
            config = load_config(args.project)
            store = CaseStore(project_path(args.project, config.case_directory, "project.case_directory"))
            if args.case_command == "list":
                for loaded in ResearchService(store).list_cases():
                    marker = " *" if loaded.id == config.default_case else ""
                    print(f"{loaded.id}{marker}\t{loaded.title}\t(legacy JSON case; 'genealogy upgrade' moves it "
                          "into the database)")
                return 0
            raise ValueError("JSON case files are no longer created: research cases, questions and findings live in "
                             "the project database. Use 'genealogy question add', 'genealogy note add --kind case' "
                             "and related commands")
        from .cli_db import DB_COMMANDS, run as run_database_command
        from .store import has_database
        if args.command == "upgrade" or (args.command == "db" and args.db_command == "init") or args.command in (
                "native", "backup") and getattr(args, "native_command", getattr(args, "backup_command", None)) in (
                "import", "verify", "restore"):
            return run_database_command(args)
        if not has_database(args.project):
            legacy = list((args.project / load_config(args.project).case_directory).glob("*.json"))
            raise ValueError(
                "this project has no research database yet; run 'genealogy --project "
                f"{args.project} upgrade' to move its {len(legacy)} JSON case file(s) into one"
                if legacy else f"no research database in {args.project}; run 'genealogy init DIRECTORY' or "
                "'genealogy db init'")
        if args.command in DB_COMMANDS:
            return run_database_command(args)
        return run_project_command(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
