"""The home page, written in full by the build, and the site index's ways in and described downloads."""
from __future__ import annotations

from html import unescape
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase
from genealogy.config import ProjectConfig
from genealogy.home import SUN_SLICES, file_size
from genealogy.models import (AccessLevel as A, Citation, Confidence as C, Event, Finding, LivingStatus as L, Name, Person, ResearchQuestion as Question,
                              Relationship, Source, Study)
from genealogy.site import build_site
from genealogy.sitecheck import check_site


def person(pid, name, born=None):
    return [Person(pid, names=[Name(name, surname=name.split()[-1])], living=L.DECEASED, sensitivity=A.PUBLIC,
                   event_ids=[f"{pid}-b"] if born else []),
            *([Event(f"{pid}-b", "birth", date=born, participant_ids=[pid], sensitivity=A.PUBLIC)] if born else [])]


def parent(child, of, rid=None, **kw):
    return Relationship(rid or f"r-{child}-{of}", child, of, "parent", sensitivity=A.PUBLIC, **kw)


def home_case():
    """Ada Fable has two children, three grandchildren and one great-grandchild; Bram Vale has one child.
    A disproved child of Ada and a withheld grandchild are not counted or drawn."""
    case = ResearchCase("fictional-home", "Fictional home")
    case.add_many([
        *person("p0001", "Ada Fable", "1760"), *person("p0002", "Cora Fable", "1790"), *person("p0003", "Dun Fable", "1792"),
        *person("p0004", "Eda Fable", "1815"), *person("p0005", "Finn Fable", "1818"), *person("p0006", "Gale Fable", "1820"),
        *person("p0007", "Hob Fable", "1845"), *person("p0008", "Bram Vale"), *person("p0009", "Ivo Vale"), *person("p0010", "Jem Wren"),
        parent("p0002", "p0001", confidence=C.DOCUMENTED), parent("p0003", "p0001"), parent("p0004", "p0002"), parent("p0005", "p0002"),
        parent("p0006", "p0003"), parent("p0007", "p0004"), parent("p0009", "p0008"),
        parent("p0010", "p0001", confidence=C.DISPROVED),
        Person("p-secret", names=[Name("SECRET-Grandchild Fable", surname="Fable")], living=L.LIVING, sensitivity=A.PUBLIC),
        parent("p-secret", "p0003", "r-secret"),
        Source("s1", "Invented register", "register", sensitivity=A.PUBLIC), Citation("c1", "s1", locator="entry 1", sensitivity=A.PUBLIC),
        Citation("c2", "s1", locator="entry 2", sensitivity=A.PUBLIC),
        Question("q1", "Who were Ada's parents?", related_ids=["p0001"], sensitivity=A.PUBLIC),
        Question("q2", "Was Cora baptised?", related_ids=["p0002"], status="answered", sensitivity=A.PUBLIC),
        Finding("f1", "Cora was Ada's daughter.", related_ids=["p0002"], recorded_on="2026-03-01", sensitivity=A.PUBLIC),
        *(Study(f"st{n}", f"Study number {n}", summary=f"Summary {n}.", related_ids=["p0001"], updated_on=f"2026-0{n}-01", sensitivity=A.PUBLIC)
          for n in range(1, 5)),
        Study("st-secret", "SECRET-Study", related_ids=["p0001"], updated_on="2026-09-01", sensitivity=A.PRIVATE),
    ])
    return case


class HomePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        config = ProjectConfig(name="Fictional home", raw={"site": {"description": "An invented family, recorded for testing."}})
        build_site(home_case(), config, cls.root)
        cls.html = (cls.root / "index.html").read_text()
        cls.main = cls.html.split('<main id="main-content">', 1)[1].split("</main>", 1)[0]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_the_hero_has_the_name_description_and_reliability_callout(self):
        self.assertIn("<h1>Fictional home</h1>", self.main)
        self.assertIn('<p class="lead">An invented family, recorded for testing.</p>', self.main)
        callout = re.search(r'<p class="home-reliability">(.*?)</p>', self.main)[1]
        self.assertIn("Every link carries its evidence label", callout)
        self.assertIn('<a href="evidence.html">How to read the labels →</a>', callout)

    def test_the_tree_preview_is_a_static_family_sun_with_a_text_version(self):
        figure = re.search(r'<figure class="home-preview">.*?</figure>', self.main)[0]
        self.assertIn('href="tree.html?person=p0001&amp;view=sun"', figure)
        self.assertIn('<a href="tree.html">Open the tree →</a>', figure)
        self.assertIn("The family tree · 10 people", figure)
        # Two children, three grandchildren and one great-grandchild: the disproved and withheld children are not drawn.
        self.assertEqual(6, figure.count('class="home-sun-slice'))
        self.assertIn('>6</text>', figure)
        caption = unescape(re.sub(r"<[^>]+>", "", re.search(r"<figcaption>(.*?)</figcaption>", figure)[1]))
        self.assertIn("Ada Fable (b. 1760) has the most recorded descendants: 2 children, 3 grandchildren and 1 great-grandchild in 3 generations.", caption)
        self.assertIn('aria-hidden="true"', re.search(r"<svg[^>]*>", figure)[0])
        self.assertIn('aria-label="Open the family sun for Ada Fable on the tree page"', figure)
        # Slices keep their line's colour: Cora's line (two children, one grandchild) and Dun's (one child).
        self.assertEqual(4, figure.count("sun-line-0"))
        self.assertEqual(2, figure.count("sun-line-1"))

    def test_question_cards_link_with_their_counts(self):
        cards = re.findall(r'<li class="home-question"><h3><a href="([^"]+)">([^<]+)</a></h3><p class="home-count">(.*?)</p>', self.main)
        self.assertEqual([
            ("catalogue.html", "Who is in the tree?", "10 people"),
            ("tree.html", "How are they connected?", "7 family links"),  # the disproved link is not counted
            ("places.html", "Where did they live?", "0 places"),
            ("sources.html", "What do the records say?", "1 source · 2 citations"),
            ("findings.html", "What has the research found?", "1 finding"),
            ("research.html", "What is still open?", "1 open question"),
        ], [(href, unescape(q), re.sub(r"<[^>]+>", "", n)) for href, q, n in cards])

    def test_steps_studies_and_findings(self):
        steps = re.search(r'<h2>How to read this site</h2><ol class="home-steps" role="list">(.*?)</ol>', self.main)[1]
        self.assertEqual(4, steps.count("<li>"))
        self.assertIn('href="evidence.html"', steps)
        self.assertIn('href="connections.html"', steps)  # no corrections contact, so the last step offers a connection
        featured = re.search(r"<h2>Featured studies</h2>(.*?)<h2>", self.main)[1]
        self.assertEqual(["Study number 4", "Study number 3", "Study number 2"], re.findall(r'<h3><a href="studies/[^"]+">([^<]+)</a>', featured))
        self.assertIn('<a href="studies.html">All 4 studies →</a>', featured)
        self.assertIn("<h2>Latest findings</h2>", self.main)
        self.assertIn("Cora was Ada&#x27;s daughter.", self.main)

    def test_the_home_page_needs_no_script_data_and_keeps_heading_order(self):
        self.assertNotIn("data/site-data.js", self.html)
        self.assertEqual(1, self.main.count("<h1>"))
        levels = [int(n) for n in re.findall(r"<h([1-6])", self.main)]
        self.assertTrue(all(b - a <= 1 for a, b in zip(levels, levels[1:])), levels)

    def test_withheld_records_stay_out_of_every_file(self):
        for path in self.root.rglob("*"):
            if path.is_file():
                text = path.read_text(errors="ignore")
                self.assertNotIn("SECRET-", text, path)
        self.assertEqual([], check_site(self.root)["broken"])

    def test_corrections_contact_makes_the_last_step_ask_for_records(self):
        with tempfile.TemporaryDirectory() as directory:
            build_site(home_case(), ProjectConfig(name="Fictional home", raw={"site": {"contact_email": "c@example.invalid"}}), Path(directory))
            html = (Path(directory) / "index.html").read_text()
        self.assertIn('<a href="corrections.html">Send it →</a>', html)
        self.assertIn('<p class="lead">A public collection of people, records and research.</p>', html)

    def test_a_tree_without_parent_links_has_no_preview(self):
        case = ResearchCase("fictional-alone", "Fictional alone")
        case.add_many(person("p0001", "Ada Fable"))
        with tempfile.TemporaryDirectory() as directory:
            build_site(case, ProjectConfig(name="Fictional alone"), Path(directory))
            html = (Path(directory) / "index.html").read_text()
        self.assertNotIn("home-preview", html)
        self.assertIn("1 person", re.sub(r"<[^>]+>", "", html))
        self.assertNotIn("Featured studies", html)

    def test_a_crowded_ring_is_counted_not_drawn(self):
        case = ResearchCase("fictional-crowded", "Fictional crowded")
        case.add_many(person("p0000", "Ada Fable"))
        for n in range(1, 61):
            case.add_many([*person(f"c{n:03d}", f"Child {n:03d} Fable"), parent(f"c{n:03d}", "p0000")])
            for m in range(3):
                case.add_many([*person(f"g{n:03d}{m}", f"Grandchild {n:03d}{m} Fable"), parent(f"g{n:03d}{m}", f"c{n:03d}")])
        with tempfile.TemporaryDirectory() as directory:
            build_site(case, ProjectConfig(name="Fictional crowded"), Path(directory))
            html = (Path(directory) / "index.html").read_text()
        self.assertLessEqual(60, SUN_SLICES)
        self.assertEqual(60, html.count('class="home-sun-slice'))  # 60 children fit; their 180 children would pass the limit
        self.assertIn("60 children and 180 grandchildren in 2 generations", html)
        self.assertIn("the outer 1 ring is too crowded to draw here", html)
        self.assertIn(">240</text>", html)


class SiteIndexTests(unittest.TestCase):
    def test_ways_in_and_described_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_site(home_case(), ProjectConfig(name="Fictional home", raw={"site": {"base_url": "https://example.invalid/home/"}}), root)
            html = (root / "sitemap.html").read_text()
            self.assertLess(html.index("<h2>Choose a way in</h2>"), html.index("<h2>Explore</h2>"))
            tiles = re.findall(r'<li><a href="([^"]+)"><span class="way-in-number" aria-hidden="true">(\d\d)</span>.*?<span class="way-in-title">([^<]+)</span>', html)
            self.assertEqual(["01", "02", "03", "04", "05", "06"], [n for _, n, _ in tiles])
            self.assertEqual(["catalogue.html", "tree.html", "branches.html", "connections.html", "timeline.html", "places.html"], [h for h, _, _ in tiles])
            rows = re.findall(r'<tr><td data-label="File"><a href="([^"]+)">[^<]+</a><br><span class="record-id">[^<]+</span></td><td data-label="Format">([^<]*)</td><td data-label="Size">([^<]*)</td><td data-label="What it holds">([^<]*)</td></tr>', html)
            paths = [path for path, *_ in rows]
            self.assertEqual(["data/site.json", "data/site.csv", "data/places.geojson", "data/public-tree.ged", "data/routes.json", "sitemap.xml", "findings.xml"], paths)
            for path, form, size, holds in rows:
                self.assertTrue(form and holds, path)
                self.assertEqual(file_size((root / path).stat().st_size), size, path)
            self.assertIn("GEDCOM 5.5.1", dict((p, f) for p, f, _, _ in rows)["data/public-tree.ged"])
            self.assertLess(html.index("<h2>Machine-readable data</h2>"), html.index("<h2>People</h2>"))
            self.assertNotIn("<!--size:", html)
            self.assertEqual([], check_site(root)["broken"])

    def test_file_sizes_read_naturally(self):
        self.assertEqual("840 bytes", file_size(840))
        self.assertEqual("12 KB", file_size(12_400))
        self.assertEqual("1.4 MB", file_size(1_420_000))


if __name__ == "__main__":
    unittest.main()
