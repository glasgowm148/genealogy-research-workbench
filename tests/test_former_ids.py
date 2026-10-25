"""Former person ids: validation, moved-page stubs, redirect files, cleanup, privacy and re-import."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from db_helpers import private_view

from genealogy.case import CaseStore, ResearchCase, validate_case
from genealogy.cli import main
from genealogy.config import ProjectConfig
from genealogy.importing import import_file
from genealogy.models import AccessLevel as A, Event, Finding, LivingStatus as L, Name, Person, Study
from genealogy.site import DATA_FILES, _owned, build_site
from genealogy.sitecheck import check_site


def page(pid):
    return "people/p-" + sha256(pid.encode()).hexdigest() + ".html"


def case(ada_former=("p0009", "fable-old-1"), **extra):
    result = ResearchCase("fictional-merges", "Fictional merges")
    result.add_many([
        Person("p0001", names=[Name("Ada Fable", surname="Fable")], living=L.DECEASED, sensitivity=A.PUBLIC, former_ids=list(ada_former)),
        Person("p0002", names=[Name("Tobin Fable", surname="Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        # Withheld: living, so neither the person nor their former id may appear anywhere.
        Person("SECRET-ID", names=[Name("SECRET-NAME")], living=L.LIVING, sensitivity=A.PUBLIC, former_ids=["SECRET-FORMER"]),
        Event("e1", "birth", date="1801", participant_ids=["p0001"], sensitivity=A.PUBLIC),
        Study("s1", "The Fable merge", body="[[p0001]] and [[p0002]] were once recorded twice.", related_ids=["p0001"], sensitivity=A.PUBLIC),
        *extra.get("records", []),
    ])
    return result


def config(base_url=None):
    return ProjectConfig(name="Fictional merges", raw={"site": {"base_url": base_url}} if base_url else {})


class ValidationTests(unittest.TestCase):
    def test_fixture_is_valid(self):
        self.assertEqual([], validate_case(case()))

    def test_former_ids_are_a_list_of_non_empty_strings(self):
        for bad in (["p0009", ""], "p0009", [7]):
            broken = case()
            broken.records(Person)[0].former_ids = bad
            self.assertIn("p0001.former_ids must be a list of non-empty ids", validate_case(broken))

    def test_a_former_id_is_never_a_current_id_of_any_type(self):
        for current in ("p0002", "e1", "s1", "p0001"):
            errors = validate_case(case(ada_former=[current]))
            self.assertIn(f"p0001.former_ids lists {current}, which is a current record id", errors)

    def test_two_people_cannot_claim_one_former_id(self):
        clash = case()
        clash.records(Person)[1].former_ids = ["p0009"]
        self.assertEqual(["p0002.former_ids lists p0009, which p0001 also lists"], validate_case(clash))
        # A withheld person counts too: the id would otherwise lead to the wrong page once they are published.
        clash = case()
        clash.records(Person)[2].former_ids = ["fable-old-1"]
        self.assertEqual(["SECRET-ID.former_ids lists fable-old-1, which p0001 also lists"], validate_case(clash))

    def test_references_must_use_the_current_id_and_say_which(self):
        stale = case(records=[Finding("f1", "Merged", related_ids=["p0009"], sensitivity=A.PUBLIC)])
        stale.records(Study)[0].body = "See [[fable-old-1]]."
        errors = validate_case(stale)
        self.assertIn("f1.related_ids references missing record: p0009 (a former id of p0001; refer to p0001)", errors)
        self.assertIn("s1.body refers to missing record [[fable-old-1]] (a former id of p0001; refer to p0001)", errors)

    def test_former_ids_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            CaseStore(temp).save(case())
            self.assertEqual(["p0009", "fable-old-1"], CaseStore(temp).load("fictional-merges").records(Person)[0].former_ids)


class StubTests(unittest.TestCase):
    def build(self, base_url=None, built=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        build_site(built or case(), config(base_url), root)
        return root

    def test_each_former_id_has_a_stub_that_leads_to_the_current_page(self):
        root = self.build()
        current = page("p0001").split("/")[1]
        for former in ("p0009", "fable-old-1"):
            stub = (root / page(former)).read_text()
            self.assertTrue(stub.startswith('<!doctype html><html lang="en">'))
            self.assertIn(f'<meta http-equiv="refresh" content="0; url={current}">', stub)
            self.assertIn('<meta name="robots" content="noindex">', stub)
            self.assertIn("<h1>This person's page has moved</h1>", stub)
            self.assertIn(f'<a href="{current}">Ada Fable</a>', stub)
            self.assertNotIn("canonical", stub)
            self.assertNotIn(former, stub)
        self.assertTrue((root / page("p0001")).is_file())
        self.assertFalse((root / "_redirects").exists())

    def test_redirect_map_and_host_rules(self):
        root = self.build("https://example.invalid/family/")
        stub = (root / page("p0009")).read_text()
        self.assertIn(f'<link rel="canonical" href="https://example.invalid/family/{page("p0001")}">', stub)
        expected = {page("p0009"): page("p0001"), page("fable-old-1"): page("p0001")}
        self.assertEqual(expected, json.loads((root / "data/redirects.json").read_text()))
        self.assertEqual(sorted(f"/family/{old} /family/{new} 301" for old, new in expected.items()),
                         (root / "_redirects").read_text().splitlines())

    def test_stubs_are_not_routes_or_sitemap_entries_but_are_owned(self):
        root = self.build("https://example.invalid/")
        routes = json.loads((root / "data/routes.json").read_text())
        self.assertIn(page("p0001"), routes)
        self.assertNotIn(page("p0009"), routes)
        sitemap = (root / "sitemap.xml").read_text()
        self.assertIn(page("p0001"), sitemap)
        self.assertNotIn(page("p0009"), sitemap)
        manifest = json.loads((root / ".genealogy-site-manifest.json").read_text())
        for name in (page("p0009"), page("fable-old-1"), "data/redirects.json", "_redirects"):
            self.assertIn(name, manifest)
            self.assertTrue(_owned(name), name)
        self.assertLessEqual({"data/redirects.json", "_redirects"}, DATA_FILES)

    def test_rebuild_removes_a_stub_whose_former_id_was_removed(self):
        root = self.build("https://example.invalid/")
        build_site(case(ada_former=["p0009"]), config("https://example.invalid/"), root)
        self.assertTrue((root / page("p0009")).is_file())
        self.assertFalse((root / page("fable-old-1")).exists())
        self.assertEqual({page("p0009"): page("p0001")}, json.loads((root / "data/redirects.json").read_text()))
        build_site(case(ada_former=[]), config("https://example.invalid/"), root)
        self.assertFalse((root / page("p0009")).exists())
        self.assertFalse((root / "data/redirects.json").exists())
        self.assertFalse((root / "_redirects").exists())
        self.assertTrue((root / page("p0001")).is_file())

    def test_a_site_without_former_ids_has_no_redirect_files(self):
        root = self.build("https://example.invalid/", case(ada_former=[]))
        self.assertFalse((root / "data/redirects.json").exists())
        self.assertFalse((root / "_redirects").exists())

    def test_withheld_former_ids_leave_no_trace(self):
        root = self.build("https://example.invalid/")
        self.assertFalse((root / page("SECRET-FORMER")).exists())
        hashed = sha256(b"SECRET-FORMER").hexdigest()
        for path in root.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                for sentinel in ("SECRET-ID", "SECRET-NAME", "SECRET-FORMER", hashed):
                    self.assertNotIn(sentinel, text, f"{sentinel} leaked into {path.relative_to(root)}")

    def test_link_check_is_clean_and_follows_the_refresh(self):
        for base_url in (None, "https://example.invalid/"):
            root = self.build(base_url)
            result = check_site(root)
            self.assertEqual([], result["broken"])
            self.assertEqual([], result["missing_anchors"])
        # The refresh target itself is checked, not only the visible link.
        (root / page("p0001")).unlink()
        broken = {(row["page"], row["tag"], row["attr"]) for row in check_site(root)["broken"]}
        self.assertIn((page("p0009"), "meta", "content"), broken)
        self.assertIn((page("p0009"), "a", "href"), broken)


class ReimportTests(unittest.TestCase):
    TREE = "0 @I1@ INDI\n1 NAME Ada /Fable/\n1 DEAT Y\n0 @I2@ INDI\n1 NAME Rowan /Fable/\n1 DEAT Y\n"

    def test_a_recorded_merge_survives_later_imports(self):
        from genealogy.store import Research, open_project
        from genealogy.store.operations import import_genealogy_file
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            self.assertEqual(main(["init", str(root), "--name", "Fictional"]), 0)
            source = Path(temp) / "tree.ged"

            def run(text):
                source.write_text(text, encoding="utf-8")
                with open_project(root) as project:
                    import_genealogy_file(project, source, publish_deceased=True, lineage="tree")

            run(self.TREE)
            with open_project(root) as project:
                research = Research(project.store)
                ada = research.find_external("xref:tree", "I1", statuses=("alias",))[0]
                rowan = research.find_external("xref:tree", "I2", statuses=("alias",))[0]
                with project.store.write(actor="test") as tx:
                    research.map_external(tx, rowan, "wikitree", "Fable-2")
                    research.merge_people(tx, survivor_id=ada, retired_id=rowan, reason="merged in the tree program")
            # The next exports lack I2.
            run("0 @I1@ INDI\n1 NAME Ada /Fable/\n1 DEAT Y\n")
            run("0 @I1@ INDI\n1 NAME Ada /Fable/\n1 DEAT Y\n1 NOTE A later export\n")
            with open_project(root) as project:
                research = Research(project.store)
                self.assertEqual(research.find_external("wikitree", "Fable-2", statuses=("former",)), [ada])
            people = {person.id: person for person in private_view(root)[0].records(Person)}
            self.assertIn("Fable-2", people[ada].former_ids)


if __name__ == "__main__":
    unittest.main()
