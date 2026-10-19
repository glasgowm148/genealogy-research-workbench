from __future__ import annotations

import json
import io
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from genealogy import read_case_artifact_bundle
from genealogy.case import ResearchCase
from genealogy.cli import main, public_project, validate_case
from genealogy.config import ProjectConfig
from genealogy.artifacts import (
    BUNDLE_MANIFEST_FILENAME, build_case_artifact_bundle, write_case_artifact_bundle,
)
from genealogy.exports import build_public_views, render, safe_output_path, write_public_export
from genealogy.models import Event, Finding, Place, ResearchQuestion

EXAMPLE = Path(__file__).parents[1] / "examples" / "fictional-harbour"


class CliAndOutputTests(unittest.TestCase):
    def test_fictional_example_validates_builds_and_exports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.assertEqual(0, main(["--project", str(EXAMPLE), "validate"]))
            self.assertEqual(0, main(["--project", str(EXAMPLE), "build", "--output", str(directory / "views")]))
            self.assertTrue((directory / "views" / "catalogue.md").is_file())
            self.assertIn("Rowan Marin", (directory / "views" / "catalogue.md").read_text())
            self.assertTrue(json.loads((directory / "views" / "places.geojson").read_text())["features"])
            output = directory / "records.ndjson"
            self.assertEqual(0, main(["--project", str(EXAMPLE), "export", "ndjson", "--output", str(output)]))
            self.assertIn('"record_type": "people"', output.read_text())

    def test_exports_have_standard_formats(self) -> None:
        case_data = json.loads((EXAMPLE / "cases" / "fictional-harbour.json").read_text())
        project = public_project(ResearchCase.from_dict(case_data), ProjectConfig.load(EXAMPLE / "genealogy.toml"))
        self.assertIn('"type": "FeatureCollection"', render(project, "geojson"))
        self.assertIn("record_type", render(project, "csv").splitlines()[0])
        self.assertTrue(render(project, "json").endswith("\n"))

    def test_local_bundle_preserves_case_state_and_research_indexes(self) -> None:
        case_data = json.loads((EXAMPLE / "cases" / "fictional-harbour.json").read_text())
        case = ResearchCase.from_dict(case_data)
        contents = build_case_artifact_bundle(case)
        self.assertEqual({
            BUNDLE_MANIFEST_FILENAME, "case.json", "case-state.json", "claim-index.json", "evidence-index.json",
            "reference-index.json", "unresolved-work.json", "research-brief.md",
        }, set(contents))
        manifest = json.loads(contents[BUNDLE_MANIFEST_FILENAME])
        self.assertEqual(1, manifest["bundle_schema_version"])
        self.assertEqual("private-by-default", manifest["privacy"])
        self.assertEqual(case.id, json.loads(contents["case.json"])["id"])
        self.assertIn("record_counts", json.loads(contents["case-state.json"]))
        self.assertIn("references", json.loads(contents["reference-index.json"]))
        self.assertIn("Evidence coverage", contents["research-brief.md"])
        with tempfile.TemporaryDirectory() as temporary:
            written = write_case_artifact_bundle(case, Path(temporary) / "bundle")
            self.assertEqual(set(contents), set(written))
            self.assertTrue(written["unresolved-work.json"].is_file())
            self.assertEqual(0o700, stat.S_IMODE((Path(temporary) / "bundle").stat().st_mode))
            self.assertEqual(0o600, stat.S_IMODE(written["case.json"].stat().st_mode))
            self.assertEqual(case.id, read_case_artifact_bundle(Path(temporary) / "bundle").id)

    def test_bundle_reader_rejects_modified_synthetic_artifact(self) -> None:
        case = ResearchCase(id="synthetic-case", title="Synthetic Case")
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "bundle"
            write_case_artifact_bundle(case, bundle)
            (bundle / "research-brief.md").write_text("modified\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match manifest"):
                read_case_artifact_bundle(bundle)

    def test_cli_writes_a_complete_local_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "fictional-bundle"
            self.assertEqual(0, main(["--project", str(EXAMPLE), "bundle", "--output", str(output)]))
            self.assertTrue((output / "case.json").is_file())
            self.assertTrue((output / "research-brief.md").is_file())
            self.assertTrue((output / BUNDLE_MANIFEST_FILENAME).is_file())
            self.assertEqual(0, main([
                "--project", str(EXAMPLE), "bundle", "--output", str(output), "--verify",
            ]))

    def test_empty_case_is_valid(self) -> None:
        self.assertEqual([], validate_case(ResearchCase(id="case", title="Test")))

    def test_init_uses_packaged_starter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "new-project"
            self.assertEqual(0, main(["init", str(target)]))
            self.assertTrue((target / "genealogy.toml").is_file())
            self.assertTrue((target / "AGENTS.md").is_file())
            self.assertTrue((target / "skills" / "genealogy-research" / "SKILL.md").is_file())
            self.assertEqual(0, main(["--project", str(target), "validate"]))
            self.assertEqual(0, main(["--project", str(target), "build"]))
            self.assertTrue((target / "dist" / "catalogue.html").is_file())
            self.assertTrue((target / "dist" / "timeline.html").is_file())
            self.assertTrue((target / "dist" / "places.html").is_file())

    def test_cli_ingests_adapter_data_into_the_durable_case(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "new-project"
            source = Path(temporary) / "people.csv"
            source.write_text(
                "id,entity_type,name,living,sensitivity\n"
                "harbour-clerk,person,Fictional Harbour Clerk,false,public\n",
                encoding="utf-8",
            )
            self.assertEqual(0, main(["init", str(target)]))
            self.assertEqual(
                0,
                main(["--project", str(target), "ingest", "tabular", str(source)]),
            )
            case = ResearchCase.from_dict(
                json.loads((target / "cases" / "research-case.json").read_text())
            )
            self.assertEqual(len(case.records("Person")), 1)
            self.assertEqual(0, main(["--project", str(target), "validate"]))
            self.assertEqual(0, main(["--project", str(target), "export", "json"]))
            self.assertTrue((target / "dist" / "research.json").is_file())

    def test_cli_creates_lists_cases_and_records_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "project"
            self.assertEqual(0, main(["init", str(target)]))
            self.assertEqual(0, main([
                "--project", str(target), "case", "create", "second-case",
                "--title", "Second synthetic case",
            ]))
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, main(["--project", str(target), "case", "list"]))
            self.assertIn("research-case *", output.getvalue())
            self.assertIn("second-case", output.getvalue())
            self.assertEqual(0, main([
                "--project", str(target), "finding", "add", "finding-1",
                "A durable synthetic conclusion", "--confidence", "documented",
            ]))
            case = ResearchCase.from_dict(json.loads(
                (target / "cases" / "research-case.json").read_text(encoding="utf-8")
            ))
            self.assertEqual(case.finding_ids, ["finding-1"])
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, main([
                    "--project", str(target), "search", "durable", "--kind", "Finding",
                ]))
            search = json.loads(output.getvalue())
            self.assertEqual(search[0]["record"]["id"], "finding-1")
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, main(["--project", str(target), "report"]))
            report = json.loads(output.getvalue())
            self.assertEqual(report["unresolved_work"]["draft_finding_ids"], ["finding-1"])

    def test_cli_manages_generic_typed_records_with_strict_json_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "project"
            source_input = Path(temporary) / "source.json"
            source_input.write_text(json.dumps({
                "id": "synthetic-source", "title": "Invented harbour notebook", "source_type": "note",
                "sensitivity": "private",
            }), encoding="utf-8")
            self.assertEqual(0, main(["init", str(target)]))
            self.assertEqual(0, main([
                "--project", str(target), "record", "add", "Source", "--input", str(source_input),
            ]))
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, main([
                    "--project", str(target), "record", "list", "--kind", "Source",
                ]))
            listed = json.loads(output.getvalue())
            self.assertEqual(["synthetic-source"], [item["record"]["id"] for item in listed])
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, main([
                    "--project", str(target), "record", "show", "synthetic-source",
                ]))
            self.assertEqual("Source", json.loads(output.getvalue())["record_type"])
            invalid = Path(temporary) / "invalid.json"
            invalid.write_text('{"id": "bad-source"}', encoding="utf-8")
            self.assertEqual(1, main([
                "--project", str(target), "record", "add", "Source", "--input", str(invalid),
            ]))
            self.assertNotIn("bad-source", (target / "cases" / "research-case.json").read_text())

    def test_validation_checks_references_indices_and_coordinates(self) -> None:
        case = ResearchCase(id="case", title="Case", question_ids=["missing"], finding_ids=["finding", "finding"])
        case.record_sets = {
            "Event": [Event(id="event", kind="birth", place_id="missing-place", participant_ids=["missing-person"])],
            "Place": [Place(id="place", name="Nowhere", latitude=91, longitude=0)],
            "Finding": [Finding(id="finding", conclusion="Not yet established")],
            "ResearchQuestion": [ResearchQuestion(id="question", question="What happened?")],
        }
        errors = validate_case(case)
        self.assertTrue(any("missing-place" in error for error in errors))
        self.assertTrue(any("coordinates" in error for error in errors))
        self.assertTrue(any("question_ids" in error for error in errors))
        self.assertTrue(any("finding_ids" in error for error in errors))

    def test_findings_are_in_every_tabular_machine_export(self) -> None:
        case = ResearchCase(id="case", title="Case")
        case.add(Finding(id="finding", conclusion="A documented conclusion", sensitivity="public"))
        project = public_project(case, ProjectConfig())
        self.assertIn("findings", render(project, "json"))
        self.assertIn('"record_type": "findings"', render(project, "ndjson"))
        self.assertIn("findings", render(project, "csv"))

    def test_build_rejects_unsafe_configured_filenames(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "out"
            with self.assertRaises(ValueError):
                safe_output_path(output, "../outside.md")
            case = ResearchCase(id="case", title="Case")
            config = ProjectConfig(catalogue={"output": "../outside.md"})
            with self.assertRaises(ValueError):
                build_public_views(case, config, output)

    def test_public_api_rejects_invalid_case_before_rendering(self) -> None:
        case = ResearchCase(id="case", title="Case")
        case.record_sets = {"Event": [Event(id="event", kind="birth", place_id="missing")]}
        with self.assertRaisesRegex(ValueError, "cannot export invalid"):
            public_project(case, ProjectConfig())

    def test_public_metadata_and_writer_use_the_privacy_boundary(self) -> None:
        case = ResearchCase(id="case", title="Protected Person", summary="Restricted quotation")
        config = ProjectConfig(name="Public project")
        project = public_project(case, config)
        self.assertEqual({"title": "Public project"}, project["project"])
        with tempfile.TemporaryDirectory() as temporary:
            path = write_public_export(case, config, Path(temporary), "public.json", "json")
            content = path.read_text(encoding="utf-8")
        self.assertNotIn("Protected Person", content)
        self.assertNotIn("Restricted quotation", content)

    def test_configured_case_and_export_paths_cannot_escape_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "genealogy.toml"
            config.write_text("[project]\ncase_directory = '../outside'\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "project.case_directory"):
                ProjectConfig.load(config)
            config.write_text("[exports]\ndirectory = '../outside'\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exports.directory"):
                ProjectConfig.load(config)


if __name__ == "__main__":
    unittest.main()
