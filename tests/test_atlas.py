"""The whole-tree atlas on tree.html: its script, its layout data and its readable family list."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Confidence as C, Event, ExternalIdentifier, LivingStatus as L, Name, Person,
                              Relationship)
from genealogy.site import ATLAS_LIST_LIMIT, build_site
from genealogy.sitecheck import check_site

from test_scale import large_case

SECRET = "SECRET-Atlas Hidden"


def person(pid, name, born=None, access=A.PUBLIC, **extra):
    records = [Person(pid, names=[Name(name, surname=name.split()[-1])], living=L.DECEASED, sensitivity=access,
                      event_ids=[f"{pid}-b"] if born else [], **extra)]
    if born:
        records.append(Event(f"{pid}-b", "birth", date=str(born), participant_ids=[pid], sensitivity=access))
    return records


def link(rid, child, parent, confidence=C.DOCUMENTED, access=A.PUBLIC):
    return Relationship(rid, child, parent, "parent", confidence=confidence, sensitivity=access)


def atlas_case():
    """Ada Fable and Bram Fable (no parents) with two children; Cora Vale marries in; a loner; a withheld child."""
    case = ResearchCase("fictional-atlas", "Fictional atlas")
    records = [
        *person("p0001", "Ada Fable", 1801, external_ids=[ExternalIdentifier("FableTree", "Fable-1", url="https://example.invalid/Fable-1")]),
        *person("p0002", "Bram Fable", 1799, external_ids=[ExternalIdentifier("FableTree", "Fable-2", url="javascript:alert(1)")]),
        *person("p0003", "Corin Fable", 1825), *person("p0004", "Dora Fable", 1828),
        *person("p0005", "Cora Vale", 1826), *person("p0006", "Eli Fable", 1850),
        *person("p0007", "Lone Wanderer", 1810),
        *person("p0900", SECRET, 1830, access=A.PRIVATE),
        Relationship("r-ab", "p0001", "p0002", "spouse", confidence=C.PROBABLE, sensitivity=A.PUBLIC),
        link("r-ca", "p0003", "p0001"), link("r-cb", "p0003", "p0002"), link("r-da", "p0004", "p0001", C.POSSIBLE),
        Relationship("r-cc", "p0003", "p0005", "spouse", confidence=C.DOCUMENTED, sensitivity=A.PUBLIC),
        link("r-ec", "p0006", "p0003"), link("r-ev", "p0006", "p0005"),
        # A disproved link joins no one; a withheld child is never drawn.
        link("r-wrong", "p0007", "p0001", C.DISPROVED), link("r-secret", "p0900", "p0001", access=A.PRIVATE),
    ]
    case.add_many(records)
    return case


def shared_data(out: Path) -> dict:
    text = (out / "data/site-data.js").read_text(encoding="utf-8")
    return json.loads(text[text.index("=") + 1:].rstrip().rstrip(";"))


class AtlasPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.out = Path(cls.directory.name)
        case = atlas_case()
        assert validate_case(case) == []
        build_site(case, ProjectConfig(name="Fictional atlas", raw={"site": {"tree_name": "FableTree"}}), cls.out)
        cls.tree = (cls.out / "tree.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_the_atlas_script_loads_on_the_tree_page_only_and_before_site_js(self):
        self.assertTrue((self.out / "assets/atlas.js").is_file())
        self.assertIn('<script defer src="assets/atlas.js"></script><script defer src="assets/site.js"></script>', self.tree)
        for path in ("index.html", "catalogue.html", "branches.html", "timeline.html"):
            self.assertNotIn("atlas.js", (self.out / path).read_text(encoding="utf-8"), path)
        script = (self.out / "assets/atlas.js").read_text(encoding="utf-8")
        self.assertIn("window.GenealogyAtlas=", script)
        self.assertNotIn("innerHTML", script)
        self.assertNotRegex(script, r"fetch\(|XMLHttpRequest|https?://")

    def test_readable_family_list_nests_children_under_a_parent_with_partners_beside(self):
        section = re.search(r'<section class="atlas-families".*?</section>', self.tree, re.S)[0]
        self.assertIn('<h2 id="atlas-families-heading">Readable family list</h2>', section)
        groups = re.findall(r"<h3>(.*?)</h3>", section)
        self.assertEqual(["Group of 6 people around Bram Fable", "No recorded relatives (1 person)"], groups)
        # Bram (the elder) heads the family with Ada beside him; Corin and Dora under him, Cora beside Corin, Eli under Corin.
        bram = re.search(r'<li data-person-id="p0002">(.*)</li></ul></li><li><h3>', section, re.S)[1]
        self.assertRegex(bram, r'^<a [^>]*>Bram Fable</a> <span class="meta">b\. 1799</span> <span class="meta">with</span> <a [^>]*>Ada Fable</a>')
        self.assertNotIn('data-person-id="p0001"', section)
        corin = bram.index('data-person-id="p0003"')
        self.assertLess(corin, bram.index('data-person-id="p0004"'))
        self.assertIn("Cora Vale", bram[corin:bram.index('data-person-id="p0006"')])
        self.assertRegex(section, r'data-person-id="p0003">.*?<ul><li data-person-id="p0006">')
        self.assertIn('<li data-person-id="p0007">', section.split("No recorded relatives")[1])
        self.assertNotIn("not listed here", section)

    def test_shared_data_carries_the_layout_profiles_and_tree_name(self):
        atlas = shared_data(self.out)["site"]["atlas"]
        self.assertEqual([["Group of 6 people around Bram Fable", ["p0002"], 6, "p0002"], ["No recorded relatives (1 person)", ["p0007"], 1]],
                         atlas["groups"])
        self.assertEqual({"p0002": ["p0003", "p0004"], "p0003": ["p0006"]}, atlas["kids"])
        self.assertEqual({"p0002": ["p0001"], "p0003": ["p0005"]}, atlas["beside"])
        # Only a web address is offered as a profile link.
        self.assertEqual({"p0001": ["FableTree", "https://example.invalid/Fable-1"]}, atlas["profiles"])
        self.assertEqual("FableTree", atlas["tree_name"])

    def test_dossier_explore_row_opens_the_atlas_on_the_person(self):
        dossier = next(p for p in (self.out / "people").glob("*.html") if ">Corin Fable</h1>" in p.read_text(encoding="utf-8")).read_text(encoding="utf-8")
        explore = re.search(r'<p class="explore">.*?</p>', dossier)[0]
        self.assertIn('<a href="../tree.html#view=atlas&amp;person=p0003">Atlas</a>', explore)
        self.assertLess(explore.index(">Family tree<"), explore.index(">Atlas<"))

    def test_link_check_reads_the_atlas_address_as_script_state(self):
        # "#view=atlas&person=…" is the atlas's own address, not an element id; real fragments are still checked.
        result = check_site(self.out)
        self.assertEqual([], result["broken"])
        self.assertEqual([], result["missing_anchors"])
        self.assertGreater(result["anchor_references"], 0)

    def test_withheld_person_is_absent_from_every_file(self):
        for path in self.out.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="ignore")
                self.assertNotIn(SECRET, text, path)
                self.assertNotIn("p0900", text, path)

    def test_a_loop_of_parent_links_still_gets_a_root(self):
        case = ResearchCase("fictional-loop", "Fictional loop")
        case.add_many([*person("p0001", "Ann Loop", 1800), *person("p0002", "Ben Loop", 1830), link("r1", "p0002", "p0001"), link("r2", "p0001", "p0002")])
        with tempfile.TemporaryDirectory() as directory:
            build_site(case, ProjectConfig(name="Loop"), directory)
            tree = (Path(directory) / "tree.html").read_text(encoding="utf-8")
            self.assertRegex(tree, r'<li data-person-id="p0001">.*?<ul><li data-person-id="p0002">')
            self.assertEqual([["Group of 2 people around Ann Loop", ["p0001"], 2, "p0001"]], shared_data(Path(directory))["site"]["atlas"]["groups"])


class LargeAtlasTests(unittest.TestCase):
    def test_large_site_lists_each_groups_first_generations_and_stays_small(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(large_case(), ProjectConfig(name="Fictional"), out)
            tree = (out / "tree.html").read_text(encoding="utf-8")
            self.assertLess(len(tree.encode("utf-8")), 100_000)
            # The binary tree's first three generations: p0000, its two children and four grandchildren.
            self.assertEqual(["p0000", "p0001", "p0003", "p0004", "p0002", "p0005", "p0006"], re.findall(r'<li data-person-id="(p\d+)">', tree))  # nested, each under their parent
            people = len(shared_data(out)["people"])
            self.assertIn(f"This list names 7 of the {people:,} people", tree)
            self.assertEqual(4, tree.count("more descendants not listed here"))  # under each grandchild
            # The atlas itself still draws everyone from the shared data.
            atlas = shared_data(out)["site"]["atlas"]
            self.assertEqual([["Group of 400 people around Person 0000 Fable", ["p0000"], 400, "p0000"]], atlas["groups"])
            self.assertEqual(399, sum(len(row) for row in atlas["kids"].values()))

    def test_small_sites_list_every_generation_up_to_the_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(large_case(ATLAS_LIST_LIMIT - 10), ProjectConfig(name="Fictional"), out)
            tree = (out / "tree.html").read_text(encoding="utf-8")
            self.assertEqual(ATLAS_LIST_LIMIT - 10, tree.count("<li data-person-id="))
            self.assertNotIn("not listed here", tree)
            self.assertNotIn("This list names", tree)


if __name__ == "__main__":
    unittest.main()
