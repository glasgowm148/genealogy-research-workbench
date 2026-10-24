"""The DNA page: Haplogroup branches, people placed on them, dna.html and a page per branch."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.exports import project_for_public_export
from genealogy.models import (AccessLevel as A, Event, Haplogroup, LivingStatus as L, Name, Person, Study, record_from_dict)
from genealogy.shell import NAV_GROUPS
from genealogy.site import ROUTES, _key, build_site
from genealogy.sitecheck import check_site
from test_scale import large_case

SECRETS = ("SECRET-BRANCH", "SECRET-CHILD-BRANCH", "SECRET-PERSON", "SECRET-PLACEMENT", "SECRET-NOTE", "SECRET-STUDY")


def person(pid, name, branch=None, note=None, sensitivity=A.PUBLIC, born=None):
    return Person(pid, names=[Name(name, surname=name.split()[-1])], living=L.DECEASED, sensitivity=sensitivity,
                  haplogroup_id=branch, haplogroup_note=note, event_ids=[f"{pid}-b"] if born else [])


def dna_case() -> ResearchCase:
    case = ResearchCase("fictional-dna", "Fictional DNA")
    case.add_many([
        Haplogroup("h-root", "R-FABLE1", date="c. 1044 CE", note="The deepest branch the project uses.", sensitivity=A.PUBLIC),
        Haplogroup("h-mid", "R-FABLE2", parent_id="h-root", date="c. 1300 CE", sensitivity=A.PUBLIC),
        Haplogroup("h-tip", "R-FABLE3", parent_id="h-mid", note="A downstream family branch.", sensitivity=A.PUBLIC),
        Haplogroup("h-side", "R-FABLE4", parent_id="h-root", date="c. 1500 CE", sensitivity=A.PUBLIC),
        # Withheld, and its child with it: the child would disclose its parent's id.
        Haplogroup("h-secret", "SECRET-BRANCH", parent_id="h-root", note="SECRET-NOTE", sensitivity=A.PRIVATE),
        Haplogroup("h-secret-child", "SECRET-CHILD-BRANCH", parent_id="h-secret", sensitivity=A.PUBLIC),
        person("ada", "Ada Fable", "h-tip", "reported root", born="1801"),
        person("bram", "Bram Fable", "h-tip", "tested descendant line"),
        person("cora", "Cora Fable", "h-mid"),
        # A public person on a withheld branch keeps their page, without the branch or the note.
        person("dov", "Dov Fable", "h-secret", "SECRET-PLACEMENT"),
        person("eli", "Eli Fable"),
        person("secret", "SECRET-PERSON Fable", "h-tip", "SECRET-PLACEMENT", sensitivity=A.PRIVATE),
        Event("ada-b", "birth", date="1801", participant_ids=["ada"], sensitivity=A.PUBLIC),
        Study("s-dna", "Reading the Fable branches", summary="How the two tested lines meet.", kind="dna",
              related_ids=["h-mid", "ada"], updated_on="2026-08-01", sensitivity=A.PUBLIC),
        Study("s-place", "The Fable mill", summary="A place study.", kind="place", related_ids=["eli"], sensitivity=A.PUBLIC),
        Study("s-secret", "SECRET-STUDY", kind="dna", related_ids=["h-secret"], sensitivity=A.PUBLIC),
    ])
    assert validate_case(case) == [], validate_case(case)
    return case


def main_of(html: str) -> str:
    return html.split('<main id="main-content">', 1)[1].split("</main>", 1)[0]


class HaplogroupModelTests(unittest.TestCase):
    def test_round_trips_through_to_dict_and_the_case_file(self):
        branch = Haplogroup("h1", "R-FABLE1", parent_id=None, date="c. 1044 CE", note="Root.", sensitivity=A.PUBLIC)
        self.assertEqual(branch, record_from_dict("Haplogroup", branch.to_dict()))
        case = dna_case()
        again = ResearchCase.from_dict(json.loads(json.dumps(case.to_dict())))
        ada = next(p for p in again.records(Person) if p.id == "ada")
        self.assertEqual(("h-tip", "reported root"), (ada.haplogroup_id, ada.haplogroup_note))
        self.assertEqual([h.to_dict() for h in case.records(Haplogroup)], [h.to_dict() for h in again.records(Haplogroup)])

    def test_validation_names_the_problem(self):
        def errors(*records):
            case = ResearchCase("v", "v")
            case.add_many(list(records))
            return "\n".join(validate_case(case))
        self.assertIn("h2.parent_id references missing record: nowhere", errors(Haplogroup("h2", "R-X", parent_id="nowhere")))
        self.assertIn("p.haplogroup_id references missing record: h9", errors(person("p", "Ada Fable", "h9")))
        self.assertIn("p.haplogroup_id must reference a Haplogroup: q", errors(person("p", "Ada Fable", "q"), person("q", "Bram Fable")))
        self.assertIn("h2.parent_id must reference a Haplogroup: p", errors(person("p", "Ada Fable"), Haplogroup("h2", "R-X", parent_id="p")))
        self.assertIn("makes a cycle of branches: a -> c -> b -> a",
                      errors(Haplogroup("a", "R-A", parent_id="c"), Haplogroup("b", "R-B", parent_id="a"), Haplogroup("c", "R-C", parent_id="b")))
        self.assertIn("makes a cycle of branches: a -> a", errors(Haplogroup("a", "R-A", parent_id="a")))
        self.assertEqual(1, errors(Haplogroup("a", "R-A", parent_id="b"), Haplogroup("b", "R-B", parent_id="a")).count("cycle"))
        self.assertIn("h.name must be a non-empty string", errors(Haplogroup("h", " ")))
        self.assertIn("h.date must be a string or null", errors(Haplogroup("h", "R-A", date=1044)))
        self.assertIn("p.haplogroup_note needs a haplogroup_id", errors(person("p", "Ada Fable", note="reported root")))
        self.assertIn("p.haplogroup_note must be a string or null", errors(Haplogroup("h", "R-A"), person("p", "Ada Fable", "h", note=["root"])))
        self.assertEqual("", errors(Haplogroup("h", "R-A"), Haplogroup("h2", "R-B", parent_id="h"), person("p", "Ada Fable", "h2", "reported root")))

    def test_raw_dna_stays_forbidden(self):
        with self.assertRaisesRegex(ValueError, "raw DNA"):
            ResearchCase("r", "r").add(Haplogroup("h", "R-A", sensitivity=A.RAW_DNA))

    def test_public_projection_withholds_a_branch_with_its_parent_and_a_placement_with_its_branch(self):
        project = project_for_public_export(dna_case(), ProjectConfig(name="Fictional DNA"))
        self.assertEqual(["h-mid", "h-root", "h-side", "h-tip"], sorted(h["id"] for h in project["haplogroups"]))
        people = {p["id"]: p for p in project["people"]}
        self.assertNotIn("secret", people)
        self.assertEqual((None, None), (people["dov"]["haplogroup_id"], people["dov"]["haplogroup_note"]))
        self.assertEqual("h-tip", people["ada"]["haplogroup_id"])
        self.assertNotIn("s-secret", {s["id"] for s in project["studies"]})


class DnaConfigTests(unittest.TestCase):
    def test_heading_defaults_to_dna_and_is_validated(self):
        self.assertEqual("DNA", ProjectConfig(name="x").dna_heading)
        self.assertEqual("Y-DNA", ProjectConfig(name="x", raw={"site": {"dna_heading": " Y-DNA "}}).dna_heading)
        for bad in ("", "  ", 5, "x" * 61, "Y​-DNA"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "site.dna_heading"):
                ProjectConfig(name="x", raw={"site": {"dna_heading": bad}}).validate()


class DnaPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.temp.name)
        build_site(dna_case(), ProjectConfig(name="Fictional DNA", raw={"site": {"dna_heading": "Y-DNA", "base_url": "https://example.invalid/"}}), cls.out)
        cls.routes = json.loads((cls.out / "data/routes.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def text(self, path):
        return (self.out / path).read_text()

    def test_one_page_per_public_branch_and_the_dna_page_in_the_research_section(self):
        self.assertEqual(["dna.html", "dna/r-fable1.html", "dna/r-fable2.html", "dna/r-fable3.html", "dna/r-fable4.html"],
                         sorted(r for r in self.routes if r.startswith("dna")))
        self.assertEqual(5, len(re.findall(r"/dna(?:\.html|/r-fable\d\.html)</loc>", self.text("sitemap.xml"))))
        research = next(members for key, _, members in NAV_GROUPS if key == "research")
        self.assertEqual("dna.html", research[-1])
        page = self.text("dna.html")
        self.assertIn("<title>Y-DNA — Fictional DNA</title>", page)
        self.assertIn('<a data-view="dna" href="dna.html" aria-current="page">Y-DNA</a></li></ul>', page)
        self.assertIn('<li><span>Research</span></li><li><span aria-current="page">Y-DNA</span></li>', page)
        # A branch page sits under the DNA page in the breadcrumb and the sidebar.
        branch = self.text("dna/r-fable2.html")
        self.assertIn('<li><a href="../dna.html">Y-DNA</a></li>', branch)
        self.assertIn('<a data-view="dna" href="../dna.html" aria-current="true">Y-DNA</a>', branch)
        self.assertIn('<a href="dna.html">Y-DNA</a>', self.text("sitemap.html"))
        # Readable without JavaScript: the page needs no data script.
        self.assertNotIn("site-data.js", page)

    def test_the_three_layers(self):
        page = main_of(self.text("dna.html"))
        self.assertIn("<h1>Y-DNA</h1>", page)
        self.assertEqual(["The genetic structure", "Documentary lines", "Interpretation"], re.findall(r'<h2 id="dna-[a-z]+">([^<]+)</h2>', page))
        self.assertIn('<a href="#dna-structure">The genetic structure</a>', page)
        # 01: the branches as nested lists, each with its date, note and people, and as an SVG chain of links.
        tree = page.split('<ul class="dna-tree">', 1)[1].split('</div>', 1)[0]
        self.assertEqual(["R-FABLE1", "R-FABLE2", "R-FABLE3", "R-FABLE4"], re.findall(r"<strong>([^<]+)</strong>", tree))
        self.assertRegex(tree, r'r-fable1\.html"><strong>R-FABLE1</strong></a> <span class="meta">c\. 1044 CE</span> <span class="meta">· 3 people on the branches below</span></p>'
                               r'<p class="dna-note">The deepest branch the project uses\.</p><ul><li>.*R-FABLE2.*<ul><li>.*R-FABLE3.*</li></ul></li><li>.*R-FABLE4')
        self.assertIn("R-FABLE2</strong></a> <span class=\"meta\">c. 1300 CE</span> <span class=\"meta\">· 1 person · 3 with the branches below</span>", tree)
        chain = page.split('<svg class="dna-chain"', 1)[1].split("</svg>", 1)[0]
        self.assertEqual(["dna/r-fable1.html", "dna/r-fable2.html", "dna/r-fable3.html", "dna/r-fable4.html"], re.findall(r'<a href="([^"]+)"', chain))
        self.assertEqual(2, chain.count('class="dna-node placed"'))  # R-FABLE2 and R-FABLE3 have people
        # 02: each public person on a branch, in branch order, with how they are attached.
        lines = page.split('<table class="dna-lines">', 1)[1].split("</table>", 1)[0]
        rows = [re.sub(r"<[^>]+>", "", row) for row in re.findall(r"<tr>(.*?)</tr>", lines)[1:]]
        self.assertEqual(["Cora FableR-FABLE2 c. 1300 CENot stated", "Ada Fable b. 1801R-FABLE3reported root",
                          "Bram FableR-FABLE3tested descendant line"], rows)
        # 03: studies of kind "dna" only.
        interpretation = page.split('id="dna-interpretation"', 1)[1]
        self.assertIn("Reading the Fable branches", interpretation)
        self.assertIn('<p class="eyebrow">Y-DNA study</p>', interpretation)
        self.assertNotIn("The Fable mill", interpretation)

    def test_a_branch_page_lists_its_people_and_child_branches(self):
        page = main_of(self.text("dna/r-fable2.html"))
        self.assertIn('<p class="back-link"><a href="../dna.html">← Y-DNA</a></p><p class="eyebrow">Y-DNA branch</p><h1>R-FABLE2</h1><p class="lead">Reported date: c. 1300 CE</p>', page)
        self.assertIn('Descends from <a href="../dna/r-fable1.html"><strong>R-FABLE1</strong></a> <span class="meta">c. 1044 CE</span>.', page)
        chain = page.split('<svg class="dna-chain"', 1)[1].split("</svg>", 1)[0]
        self.assertEqual(["../dna/r-fable1.html", "../dna/r-fable2.html", "../dna/r-fable3.html"], re.findall(r'<a href="([^"]+)"', chain))
        self.assertIn('<a href="../dna/r-fable2.html" aria-current="page" class="dna-node placed current" aria-label="R-FABLE2, c. 1300 CE">', chain)
        people = page.split('id="people"', 1)[1].split("<h2", 1)[0]
        self.assertIn(f'<a href="../people/p-{_key("cora")}.html">Cora Fable</a>', people)
        self.assertNotIn("Ada Fable", people)  # on the branch below
        below = page.split('id="below"', 1)[1].split("<h2", 1)[0]
        self.assertIn('<a href="../dna/r-fable3.html"><strong>R-FABLE3</strong></a> <span class="meta">· 2 people</span>', below)
        self.assertNotIn("R-FABLE4", below)
        self.assertIn("Reading the Fable branches", page.split('id="studies"', 1)[1])
        tip = main_of(self.text("dna/r-fable3.html"))
        self.assertIn("No branch below this one is recorded.", tip)
        self.assertIn("tested descendant line", tip)
        self.assertIn("A root branch: no branch above it is recorded.", main_of(self.text("dna/r-fable1.html")))
        self.assertIn("No public person is placed on this branch itself.", main_of(self.text("dna/r-fable4.html")))

    def test_the_dossier_hero_names_the_branch(self):
        hero = self.text(f"people/p-{_key('ada')}.html").split('<header class="dossier-hero">', 1)[1].split("</header>", 1)[0]
        self.assertIn('<p class="dna-line"><span class="meta">Y-DNA:</span> <a href="../dna/r-fable3.html">R-FABLE3</a> <span class="meta">· reported root</span></p>', hero)
        cora = self.text(f"people/p-{_key('cora')}.html")
        self.assertIn('<a href="../dna/r-fable2.html">R-FABLE2</a> <span class="meta">· branch dated c. 1300 CE</span></p>', cora)
        for pid in ("dov", "eli"):
            self.assertNotIn('class="dna-line"', self.text(f"people/p-{_key(pid)}.html"))
        # A study relating a branch links to the branch page by its name.
        study = self.text(next(r for r in self.routes if r.startswith("studies/s-") and "Reading the Fable branches" in self.text(r)))
        self.assertIn('<a href="../dna/r-fable2.html">R-FABLE2</a>', study)

    def test_withheld_branches_people_and_placements_reach_no_output(self):
        files = [path for path in self.out.rglob("*") if path.is_file()]
        self.assertGreater(len(files), 20)
        for path in files:
            text = path.read_text(encoding="utf-8")
            for secret in SECRETS + ("h-secret",):
                self.assertNotIn(secret, text, f"{secret} leaked into {path.relative_to(self.out)}")
        data = json.loads(self.text("data/site.json"))
        self.assertEqual(4, len(data["haplogroups"]))
        self.assertEqual([], check_site(self.out)["broken"])

    def test_public_branch_model_download_is_reviewed_and_raw_free(self):
        csv = self.text("data/dna-branches.csv")
        self.assertIn("branch_id,branch_name,parent_branch_id,reported_date,person_id,person_name,attachment_note", csv)
        self.assertIn("h-tip,R-FABLE3,h-mid,,ada,Ada Fable,reported root", csv)
        self.assertNotIn("SECRET", csv)
        self.assertNotIn("kit", csv.casefold())
        self.assertNotIn("marker", csv.casefold())
        self.assertNotIn("raw", csv.casefold())
        self.assertIn("data/dna-branches.csv", self.text("sitemap.html"))
        self.assertIn("data/dna-branches.csv", self.text(".genealogy-site-manifest.json"))

    def test_no_branches_no_page_and_a_rebuild_removes_the_old_pages(self):
        case = dna_case()
        case.record_sets["Haplogroup"] = []
        case.record_sets["Study"] = [s for s in case.records(Study) if s.kind != "dna"]
        for p in case.records(Person):
            p.haplogroup_id = p.haplogroup_note = None
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            build_site(dna_case(), ProjectConfig(name="Fictional DNA"), out)
            self.assertTrue((out / "dna/r-fable3.html").is_file())
            build_site(case, ProjectConfig(name="Fictional DNA"), out)
            self.assertFalse((out / "dna.html").exists())
            self.assertFalse((out / "data/dna-branches.csv").exists())
            self.assertEqual([], list((out / "dna").glob("*.html")) if (out / "dna").exists() else [])
            self.assertNotIn("dna.html", (out / "index.html").read_text())
            self.assertNotIn('class="dna-line"', (out / f"people/p-{_key('ada')}.html").read_text())
        self.assertNotIn("dna.html", ROUTES)  # optional: never a page of its own without branches

    def test_branch_addresses_are_stable_and_distinct(self):
        case = ResearchCase("slugs", "Slugs")
        case.add_many([Haplogroup("b", "R-A1", sensitivity=A.PUBLIC), Haplogroup("a", "r a1", sensitivity=A.PUBLIC),
                       Haplogroup("c", "ᚠ", sensitivity=A.PUBLIC)])
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            build_site(case, ProjectConfig(name="Slugs"), out)
            pages = sorted(p.name for p in (out / "dna").glob("*.html"))
            self.assertEqual(sorted(["r-a1.html", f"r-a1-{_key('b')[:8]}.html", f"branch-{_key('c')[:8]}.html"]), pages)
            self.assertEqual([], check_site(out)["broken"])


class LargeDnaTreeTests(unittest.TestCase):
    def test_pages_stay_small_with_hundreds_of_branches_and_people(self):
        case = large_case()
        branches = [Haplogroup(f"h{n:03d}", f"R-FABLE{n:03d}", parent_id=f"h{(n - 1) // 2:03d}" if n else None, date=f"c. {800 + n} CE",
                               note=f"Branch note {n:03d}, as the testing company reports it.", sensitivity=A.PUBLIC) for n in range(400)]
        case.add_many(branches)
        for n, p in enumerate(case.records(Person)):
            p.haplogroup_id, p.haplogroup_note = ("h000" if n % 4 else f"h{n % 400:03d}"), "tested descendant line"
        self.assertEqual([], validate_case(case))
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            build_site(case, ProjectConfig(name="Fictional"), out)
            for path in [out / "dna.html", *(out / "dna").glob("*.html")]:
                self.assertLess(path.stat().st_size, 100_000, path.name)
            root = (out / "dna/r-fable000.html").read_text()
            self.assertIn("each person's page names their branch", root)
            page = (out / "dna.html").read_text()
            self.assertIn("The first 80 of 400 branches are drawn", page)
            self.assertEqual(80, main_of(page).split("</svg>", 1)[0].count('class="dna-node'))
            self.assertIn("more branches, listed on the pages of the branches above them", page)
            self.assertEqual([], check_site(out)["broken"])


if __name__ == "__main__":
    unittest.main()
