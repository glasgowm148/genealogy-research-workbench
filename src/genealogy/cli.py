"""Command line interface for configured, durable genealogy research cases."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from importlib.resources import files
from importlib.metadata import version, PackageNotFoundError
import sys
from pathlib import Path
from typing import Any, Mapping

from .adapters import resolve_adapter
from .case import CaseStore, ResearchCase, validate_case
from .config import ProjectConfig, safe_relative_path
from .exports import (
    build_public_views, configured_views, project_for_public_export, render, safe_output_path,
)
from .artifacts import read_case_artifact_bundle, write_case_artifact_bundle
from .models import AccessLevel, Confidence, Finding, MODEL_TYPES, Record, record_from_dict
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
        case, config = load_case(target)
        case.title = name.strip()
        CaseStore(project_path(target, config.case_directory, "project.case_directory")).save(case)


def build_project(case: ResearchCase, config: ProjectConfig, output: Path) -> None:
    from .site import build_site
    build_public_views(case, config, output)
    build_site(case, config, output)


def parser() -> argparse.ArgumentParser:
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
    imported = commands.add_parser("import", help="import GEDCOM or OneTree JSON into an empty case")
    imported.add_argument("input", type=Path)
    imported.add_argument("--format", choices=("auto", "gedcom", "one-tree"), default="auto")
    imported.add_argument("--publish-deceased", action="store_true",
                          help="confirm reviewed basic deceased/historical facts may be public; protected records stay private")
    imported.add_argument("--publish-reviewed-sources", action="store_true",
                          help="with --publish-deceased, confirm linked bibliographic titles/locators are reviewed; quotations stay private")
    imported.add_argument("--replace", action="store_true", help="replace all selected case records; never merge unrelated trees")
    imported.add_argument("--update", action="store_true",
                          help="refresh a previous import of the same tree from a newer export, keeping research added to the case")
    serve = commands.add_parser("serve", help="open a local-only file upload and site preview server")
    serve.add_argument("--port", type=int, default=8000, help="loopback port (default: 8000)")
    commands.add_parser("validate", help="validate the selected durable research case")
    build_parser = commands.add_parser("build", help="create privacy-filtered catalogue, timeline and map")
    build_parser.add_argument("--output", type=Path, default=Path("dist"))
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
    records = commands.add_parser("record", help="list, inspect, or add one typed durable record")
    record_commands = records.add_subparsers(dest="record_command", required=True)
    list_records = record_commands.add_parser("list", help="list records in the selected case")
    list_records.add_argument("--kind", choices=tuple(sorted(MODEL_TYPES)), help="optional core record type")
    show_record = record_commands.add_parser("show", help="show one record by id")
    show_record.add_argument("record_id")
    add_record = record_commands.add_parser("add", help="add one strict JSON core record")
    add_record.add_argument("record_type", choices=tuple(sorted(MODEL_TYPES)))
    add_record.add_argument("--input", type=Path, required=True, help="JSON object matching the selected record type")
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
    add_finding.add_argument("--status", default="draft")
    add_finding.add_argument("--confidence", choices=tuple(Confidence), default=Confidence.UNKNOWN)
    add_finding.add_argument(
        "--sensitivity",
        choices=(AccessLevel.PUBLIC, AccessLevel.PRIVATE, AccessLevel.RESTRICTED, AccessLevel.LICENSED),
        default=AccessLevel.PRIVATE,
    )
    search = commands.add_parser("search", help="search typed records in the selected case")
    search.add_argument("query")
    search.add_argument("--kind", help="optional model type, such as Person or Source")
    report = commands.add_parser("report", help="summarise unresolved work and evidence completeness")
    report.add_argument("--format", choices=("json", "markdown"), default="json")
    report.add_argument("--output", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
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
            service = ResearchService(store)
            if args.case_command == "list":
                for loaded in service.list_cases():
                    marker = " *" if loaded.id == config.default_case else ""
                    print(f"{loaded.id}{marker}\t{loaded.title}")
                return 0
            service.create_case(args.case_id, args.title, args.summary)
            print(f"Created research case at {store.path_for(args.case_id)}")
            return 0
        case, config = load_case(args.project, args.case)
        errors = validate_case(case)
        if args.command == "validate":
            if errors:
                print("\n".join(f"error: {error}" for error in errors), file=sys.stderr)
                return 1
            print("Research case is valid.")
            return 0
        if errors:
            raise ValueError("Validation failed:\n" + "\n".join(f"- {error}" for error in errors))
        if args.command == "import":
            from .importing import import_file
            report = import_file(args.project, case, config, args.input, format=args.format,
                                 publish_deceased=args.publish_deceased, replace=args.replace, update=args.update,
                                 publish_reviewed_sources=args.publish_reviewed_sources)
            for warning in report["warnings"]:
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
            imported = batch.add_to_case(case)
            errors = validate_case(case)
            if errors:
                raise ValueError("Imported records failed validation:\n" + "\n".join(f"- {error}" for error in errors))
            CaseStore(project_path(args.project, config.case_directory, "project.case_directory")).save(case)
            for warning in batch.warnings:
                print(f"warning: {warning}", file=sys.stderr)
            print(f"Imported {imported} neutral records through {adapter.name}.")
            return 0
        if args.command == "finding":
            service = ResearchService(CaseStore(
                project_path(args.project, config.case_directory, "project.case_directory")
            ))
            service.add_finding(case.id, Finding(
                id=args.finding_id,
                conclusion=args.conclusion,
                related_ids=args.related,
                evidence_ids=args.evidence,
                status=args.status,
                confidence=Confidence(args.confidence),
                sensitivity=AccessLevel(args.sensitivity),
            ))
            print(f"Recorded finding {args.finding_id} in case {case.id}.")
            return 0
        service = ResearchService(CaseStore(
            project_path(args.project, config.case_directory, "project.case_directory")
        ))
        if args.command == "record":
            if args.record_command == "list":
                records = service.query_records(case.id, kind=args.kind)
                print(json.dumps([
                    {"record_type": type(record).__name__, "record": record.to_dict()}
                    for record in records
                ], indent=2, ensure_ascii=False))
                return 0
            if args.record_command == "show":
                matches = service.query_records(case.id, ids=(args.record_id,))
                if not matches:
                    raise ValueError(f"record not found: {args.record_id}")
                record = matches[0]
                print(json.dumps({"record_type": type(record).__name__, "record": record.to_dict()},
                                 indent=2, ensure_ascii=False))
                return 0
            record = record_payload(args.input, args.record_type)
            service.add_record(case.id, record)
            print(f"Recorded {args.record_type} {record.id} in case {case.id}.")
            return 0
        if args.command == "search":
            matches = service.search_records(case.id, args.query, kind=args.kind)
            print(json.dumps([
                {
                    "record_type": type(match.record).__name__,
                    "matched_fields": match.matched_fields,
                    "record": match.record.to_dict(),
                }
                for match in matches
            ], indent=2, ensure_ascii=False))
            return 0
        if args.command == "report":
            content = (
                service.research_brief(case.id)
                if args.format == "markdown"
                else json.dumps({
                    "evidence_completeness": asdict(service.evidence_completeness(case.id)),
                    "unresolved_work": asdict(service.unresolved_work(case.id)),
                }, indent=2, sort_keys=True) + "\n"
            )
            if args.output:
                output = args.output if args.output.is_absolute() else args.project / args.output
                write_text(output, content)
                print(f"Wrote research report to {output}")
            else:
                print(content, end="")
            return 0
        if args.command == "bundle":
            output = args.output if args.output.is_absolute() else args.project / args.output
            if args.verify:
                bundled_case = read_case_artifact_bundle(output)
                print(f"Verified private artifact bundle for case {bundled_case.id} at {output}")
                return 0
            write_case_artifact_bundle(case, output)
            print(f"Wrote private local research-case artifact bundle to {output}")
            return 0
        safe_project = public_project(case, config)
        if args.command == "build":
            output = args.output if args.output.is_absolute() else args.project / args.output
            build_project(case, config, output)
            print(f"Built privacy-filtered views in {output}")
            return 0
        if args.output is None:
            export_directory = project_path(
                args.project,
                config.exports.get("directory", "dist"),
                "exports.directory",
            )
            configured_name = config.exports.get(args.format, "research.ged" if args.format == "gedcom" else f"research.{args.format}")
            output = safe_output_path(export_directory, configured_name)
        else:
            output = args.output if args.output.is_absolute() else args.project / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render(safe_project, args.format), encoding="utf-8")
        print(f"Wrote privacy-filtered {args.format} export to {output}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
