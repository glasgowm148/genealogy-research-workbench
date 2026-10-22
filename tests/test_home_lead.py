"""The home page's second half: priority studies, a featured question, featured studies and lead-in panels, from data and [home]."""
from __future__ import annotations

from html import unescape
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

from genealogy import site
from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig, home_settings
from genealogy.models import (AccessLevel as A, Event, Finding, LivingStatus as L, Name, Person, Place, ResearchQuestion as Question, Study)
from genealogy.site import build_site
from genealogy.sitecheck import check_site


def lead_case():
    """Ada Fable lived at Oakmere and Brindle; Bram Vale at Brindle; Cora Wren at Saltby, which has no coordinates.
    Two studies concern Brindle, one Oakmere, one Saltby; a withheld study and question name SECRET text."""
    case = ResearchCase("fictional-lead", "Fictional lead")
    events = [("1801", "birth", "pl-oak"), ("1820", "marriage", "pl-brin"), ("1825", "residence", "pl-brin"), ("1830", "residence", "pl-oak"),
              ("1841", "census", "pl-brin"), ("1860", "death", "pl-brin")]
    case.add_many([
        Place("pl-oak", "Oakmere, Fableshire", latitude=54.1, longitude=-2.3, sensitivity=A.PUBLIC),
        Place("pl-brin", "Brindle, Fableshire", latitude=54.4, longitude=-2.9, precision="parish", sensitivity=A.PUBLIC),
        Place("pl-salt", "Saltby, Fableshire", sensitivity=A.PUBLIC),
        Person("p0001", names=[Name("Ada Fable", surname="Fable")], living=L.DECEASED, sensitivity=A.PUBLIC, event_ids=[f"e{n}" for n in range(len(events))]),
        *(Event(f"e{n}", kind, date=date, place_id=place, participant_ids=["p0001"], sensitivity=A.PUBLIC) for n, (date, kind, place) in enumerate(events)),
        Person("p0002", names=[Name("Bram Vale", surname="Vale")], living=L.DECEASED, sensitivity=A.PUBLIC, event_ids=["e-bram"]),
        Event("e-bram", "birth", date="1790", place_id="pl-brin", participant_ids=["p0002"], sensitivity=A.PUBLIC),
        Person("p0003", names=[Name("Cora Wren", surname="Wren")], living=L.DECEASED, sensitivity=A.PUBLIC, event_ids=["e-cora"]),
        Event("e-cora", "birth", date="1795", place_id="pl-salt", participant_ids=["p0003"], sensitivity=A.PUBLIC),
        Person("p-secret", names=[Name("SECRET-Living Fable", surname="Fable")], living=L.LIVING, sensitivity=A.PUBLIC),
        Study("st-brindle", "The Brindle households", kind="family_study", summary="Two households at Brindle.", related_ids=["pl-brin"],
              updated_on="2026-05-01", sensitivity=A.PUBLIC),
        Study("st-vale", "The Vale line", kind="family-study", summary="Bram Vale's line.", related_ids=["p0002"], updated_on="2026-06-01", sensitivity=A.PUBLIC),
        Study("st-ada", "Ada Fable's two homes", kind="place study", related_ids=["p0001"], updated_on="2026-04-01", sensitivity=A.PUBLIC),
        Study("st-wren", "The Wren baptism", related_ids=["p0003"], updated_on="2026-03-01", sensitivity=A.PUBLIC),
        Study("st-secret", "SECRET-Study title", summary="SECRET-Study summary", related_ids=["p-secret"], updated_on="2026-09-01", sensitivity=A.PUBLIC),
        Question("q-low", "Was Cora baptised at Saltby?", related_ids=["p0003"], priority="low", sensitivity=A.PUBLIC),
        Question("q-high", "Who were Ada Fable's parents?", related_ids=["p0001"], priority="high", next_record="Oakmere register, baptisms 1795–1805",
                 sensitivity=A.PUBLIC),
        Question("q-done", "Did Bram Vale marry twice?", related_ids=["p0002"], priority="high", status="answered", sensitivity=A.PUBLIC),
        Question("q-secret", "SECRET-Question about a living person", related_ids=["p-secret"], priority="high", sensitivity=A.PUBLIC),
        Finding("f1", "Ada Fable was at Brindle in 1841.", related_ids=["p0001", "pl-brin"], recorded_on="2026-02-01", sensitivity=A.PUBLIC),
    ])
    return case


def build(raw=None, case=None):
    directory = tempfile.TemporaryDirectory()
    root = Path(directory.name)
    build_site(case or lead_case(), ProjectConfig(name="Fictional lead", raw=raw or {}), root)
    return directory, root


def main_of(root):
    return (root / "index.html").read_text().split('<main id="main-content">', 1)[1].split("</main>", 1)[0]


def words(html):
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


class HomeLeadDefaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert validate_case(lead_case()) == []
        cls.temp, cls.root = build()
        cls.main = main_of(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def section(self, cls):
        return re.search(rf'<section class="{cls}".*?</section>', self.main)[0]

    def test_sections_follow_the_reading_guide_in_order(self):
        order = ["<h2>How to read this site</h2>", 'id="home-priority-heading"', 'id="home-question-heading"', "<h2>Featured studies</h2>",
                 "<h2>Latest findings</h2>", 'id="home-related-heading"']
        positions = [self.main.index(marker) for marker in order]
        self.assertEqual(sorted(positions), positions)
        levels = [int(n) for n in re.findall(r"<h([1-6])", self.main)]
        self.assertTrue(all(b - a <= 1 for a, b in zip(levels, levels[1:])), levels)

    def test_priority_places_are_numbered_by_studies_then_notes(self):
        priority = self.section("home-priority")
        self.assertIn('<p class="eyebrow">Priority studies</p><h2 id="home-priority-heading">Where the research is concentrated</h2>', priority)
        places = re.findall(r'<li class="home-priority-place"><span class="home-priority-number">(\d+)</span><div><h3><a href="[^"]+">([^<]+)</a></h3>'
                            r'<p class="meta">([^<]+)</p>', priority)
        # Brindle: Ada's and Bram's studies and its own, and the questions about both and the finding naming it; Oakmere: Ada's; Saltby: Cora's.
        self.assertEqual([("1", "Brindle, Fableshire", "3 studies · 3 research notes · 2 people"),
                          ("2", "Oakmere, Fableshire", "1 study · 2 research notes · 1 person"),
                          ("3", "Saltby, Fableshire", "1 study · 1 research note · 1 person")], places)
        brindle = priority.split('class="home-priority-place"')[1]
        # Newest first, each with its kind as written by the project.
        self.assertEqual(["The Vale line", "The Brindle households", "Ada Fable's two homes"],
                         [unescape(t) for t in re.findall(r'<li><a href="studies/[^"]+">([^<]+)</a>', brindle)])
        self.assertIn('<span class="meta">Family study</span>', brindle)
        self.assertIn('<span class="meta">Place study</span>', brindle)

    def test_the_map_numbers_the_located_places_and_says_which_are_not(self):
        priority = self.section("home-priority")
        svg = re.search(r'<svg class="home-priority-map"[^>]*>', priority)[0]
        self.assertIn('role="img"', svg)
        self.assertIn('aria-label="Map of the 2 places with the most research, numbered as in the list"', svg)
        self.assertIn('href="assets/world.svg"', priority)
        self.assertEqual(["2", "1"], re.findall(r'<g class="home-priority-mark[^"]*">.*?>(\d+)</text></g>', priority))  # Saltby has no coordinates
        self.assertEqual(1, priority.count('class="home-priority-mark broad"'))  # Brindle is located to its parish
        self.assertIn("1 of the places have none and are listed only", priority)

    def test_the_featured_question_is_the_highest_priority_open_one(self):
        panel = self.section("home-featured-question")
        self.assertIn('<p class="eyebrow">A question we are investigating</p><h2 id="home-question-heading">Who were Ada Fable&#x27;s parents?</h2>', panel)
        self.assertIn("Concerns Ada Fable (b. 1801 – d. 1860).", words(panel))
        facts = re.findall(r"<li[^>]*>(.*?)</li>", re.search(r'<ol class="home-question-facts".*?</ol>', panel)[0])
        # Up to four dated events, the first three and the last, then what is still open.
        self.assertEqual(["1801 Birth at Oakmere, Fableshire", "1820 Marriage at Brindle, Fableshire", "1825 Residence at Brindle, Fableshire",
                          "1860 Death at Brindle, Fableshire", "Still open Next record to check: Oakmere register, baptisms 1795–1805"],
                         [words(f) for f in facts])
        self.assertIn('<time datetime="1801">1801</time>', panel)
        self.assertRegex(panel, r'<a href="people/p-[0-9a-f]+\.html#research">Read the research →</a>')
        self.assertIn('<a href="research.html#open-questions">See all open questions →</a>', panel)
        self.assertNotIn("<script", panel)

    def test_featured_studies_are_the_newest_three_with_kind_and_people(self):
        featured = re.search(r"<h2>Featured studies</h2>(.*?)<h2>", self.main)[1]
        cards = re.findall(r'<p class="home-study-kicker"><span class="home-study-number">(\d\d)</span> ([^<]+)</p><h3><a href="studies/[^"]+">([^<]+)</a></h3>'
                           r'(?:<p>[^<]*</p>)?<p class="meta">([^<·]+) ·', featured)
        self.assertEqual([("01", "Family study", "The Vale line", "1 person"), ("02", "Family study", "The Brindle households", "0 people"),
                          ("03", "Place study", "Ada Fable&#x27;s two homes", "1 person")], [tuple(c.strip() for c in card) for card in cards])
        self.assertIn("The most recently updated written studies", featured)
        self.assertIn('<a href="studies.html">All 4 studies →</a>', featured)

    def test_lead_in_panels_without_resources_or_a_dna_page(self):
        self.assertIn('<a href="connections.html">Find a connection →</a> <a href="compare.html">Compare two people</a>', self.main)
        self.assertNotIn("home-dna-heading", self.main)
        self.assertNotIn("<!--home:", self.main)
        self.assertNotIn("Continue the research", self.main)

    def test_withheld_records_stay_out_of_every_file(self):
        for path in self.root.rglob("*"):
            if path.is_file():
                self.assertNotIn("SECRET-", path.read_text(errors="ignore"), path)
        self.assertEqual([], check_site(self.root)["broken"])


class HomeLeadConfiguredTests(unittest.TestCase):
    def test_a_named_question_studies_and_resources(self):
        raw = {"home": {"featured_question": "q-done", "studies": ["st-wren", "st-secret", "st-ada"], "resources": [
            {"label": "Name study", "title": "The Fable one-name study", "description": "An invented discussion group.", "url": "https://example.invalid/fable"},
            {"title": "About the data", "url": "about-data.html#withheld"}]}}
        temp, root = build(raw)
        with temp:
            main = main_of(root)
            panel = re.search(r'<section class="home-featured-question".*?</section>', main)[0]
            # An answered question can be chosen; it is then one we investigated, with nothing left open.
            self.assertIn('<p class="eyebrow">A question we investigated</p><h2 id="home-question-heading">Did Bram Vale marry twice?</h2>', panel)
            self.assertNotIn("Still open", panel)
            self.assertEqual(["1790 Birth at Brindle, Fableshire"], [words(f) for f in re.findall(r"<li[^>]*>(.*?)</li>", panel)])
            featured = re.search(r"<h2>Featured studies</h2>(.*?)<h2>", main)[1]
            # In the order given; the withheld study is skipped.
            self.assertEqual(["The Wren baptism", "Ada Fable&#x27;s two homes"], re.findall(r'<h3><a href="studies/[^"]+">([^<]+)</a>', featured))
            self.assertIn("Written studies chosen for this page", featured)
            self.assertIn('<span class="home-study-number">01</span> Study</p>', featured)  # no kind recorded
            resources = re.search(r'<section class="home-lead home-continue".*?</section>', main)[0]
            self.assertIn('<h2 id="home-continue-heading">Continue the research</h2>', resources)
            self.assertIn('<p class="eyebrow">Name study</p><h3><a href="https://example.invalid/fable">The Fable one-name study'
                          '<span class="external-mark" aria-hidden="true"> ↗</span><span class="sr-only"> (another website)</span></a></h3>'
                          '<p>An invented discussion group.</p>', resources)
            self.assertIn('<h3><a href="about-data.html#withheld">About the data</a></h3>', resources)  # a page of the site: no mark
            self.assertNotIn("target=", resources)  # external links open in the same tab
            for path in root.rglob("*"):
                if path.is_file():
                    self.assertNotIn("SECRET-", path.read_text(errors="ignore"), path)

    def test_withheld_or_unknown_choices_fall_back_to_the_defaults(self):
        temp, root = build({"home": {"featured_question": "q-secret", "studies": ["st-secret", "st-nowhere"]}})
        with temp:
            main = main_of(root)
            self.assertIn("Who were Ada Fable&#x27;s parents?</h2>", main)
            self.assertEqual(["The Vale line", "The Brindle households", "Ada Fable&#x27;s two homes"],
                             re.findall(r'<h3><a href="studies/[^"]+">([^<]+)</a>', re.search(r"<h2>Featured studies</h2>(.*?)<h2>", main)[1]))

    def test_a_question_about_no_person_links_its_own_card(self):
        case = lead_case()
        case.add(Question("q-place", "Which Brindle church kept the earliest register?", related_ids=["pl-brin"], priority="high",
                          resolves="A register naming its church.", sensitivity=A.PUBLIC))
        temp, root = build({"home": {"featured_question": "q-place"}}, case)
        with temp:
            panel = re.search(r'<section class="home-featured-question".*?</section>', main_of(root))[0]
        self.assertNotIn("Concerns", panel)
        self.assertIn('aria-label="What is still open"', panel)
        self.assertIn("Still open What would answer it: A register naming its church.", words(panel))
        self.assertRegex(panel, r'<a href="research\.html#r-[0-9a-f]+">Read the research →</a>')

    def test_an_empty_study_list_leaves_the_grid_out(self):
        temp, root = build({"home": {"studies": []}})
        with temp:
            self.assertNotIn("Featured studies", main_of(root))

    def test_a_dna_route_adds_its_panel_with_the_projects_heading(self):
        with mock.patch.dict(site.ROUTES, {"dna.html": ("dna", "Y-DNA")}):
            temp, root = build({"site": {"dna_heading": "Y-DNA"}})
        with temp:
            main = main_of(root)
        panel = re.search(r'<section class="home-lead" aria-labelledby="home-dna-heading">.*?</section>', main)[0]
        self.assertIn('<h2 id="home-dna-heading">What can Y-DNA tell us?</h2>', panel)
        self.assertIn('<a href="dna.html">Read the Y-DNA page →</a>', panel)
        self.assertLess(main.index('id="home-related-heading"'), main.index('id="home-dna-heading"'))

    def test_without_questions_studies_or_places_the_sections_are_left_out(self):
        case = ResearchCase("fictional-bare", "Fictional bare")
        case.add(Person("p0001", names=[Name("Ada Fable")], living=L.DECEASED, sensitivity=A.PUBLIC))
        temp, root = build(case=case)
        with temp:
            main = main_of(root)
        for absent in ("home-priority", "home-featured-question", "Featured studies"):
            self.assertNotIn(absent, main)
        self.assertIn("How are two people related?", main)

    def test_places_without_coordinates_are_a_numbered_list_without_a_map(self):
        case = lead_case()
        for place in case.records(Place):
            place.latitude = place.longitude = None
        temp, root = build(case=case)
        with temp:
            main = main_of(root)
        self.assertNotIn("home-priority-map", main)
        self.assertIn('<div class="home-priority-body"><ol class="home-priority-list" role="list">', main)
        self.assertEqual(3, main.count('class="home-priority-place"'))

    def test_the_large_fixture_home_page_stays_small(self):
        from test_scale import large_case
        raw = {"home": {"resources": [{"title": f"Resource {n}", "description": "An invented resource. " * 8, "url": f"https://example.invalid/{n}"}
                                      for n in range(12)]}}
        temp, root = build(raw, large_case())
        with temp:
            html = (root / "index.html").read_text()
        self.assertLess(len(html.encode("utf-8")), 100_000)
        self.assertEqual(site.HOME_PRIORITY_PLACES, html.count('class="home-priority-place"'))
        self.assertIn('<h2 id="home-continue-heading">Continue the research</h2>', html)


class HomeSettingsTests(unittest.TestCase):
    def test_valid_settings_are_read(self):
        self.assertEqual({"featured_question": None, "studies": None, "resources": []}, home_settings({}))
        settings = home_settings({"featured_question": " q1 ", "studies": ["s1", "s2"], "resources": [{"title": "T", "url": "sources.html"}]})
        self.assertEqual(("q1", ["s1", "s2"], [{"title": "T", "url": "sources.html"}]),
                         (settings["featured_question"], settings["studies"], settings["resources"]))

    def test_invalid_settings_are_rejected(self):
        bad = [
            ("not a table", "[home] must be a table"),
            ({"featured": "q1"}, "home has unknown settings: featured"),
            ({"featured_question": ""}, "home.featured_question"),
            ({"featured_question": 3}, "home.featured_question"),
            ({"studies": "s1"}, "home.studies"),
            ({"studies": ["s1", "s1"]}, "home.studies"),
            ({"studies": [f"s{n}" for n in range(13)]}, "home.studies"),
            ({"resources": {"title": "T"}}, "home.resources"),
            ({"resources": [{"url": "sources.html"}]}, "home.resources[1].title"),
            ({"resources": [{"title": "T", "url": "sources.html", "label": ""}]}, "home.resources[1].label"),
            ({"resources": [{"title": "T", "url": "sources.html", "icon": "x"}]}, "home.resources[1] has unknown settings: icon"),
        ]
        for url in ("javascript:alert(1)", "/rooted.html", "../outside.html", "//example.org/x", "https://user:pw@example.org/", "ftp://example.org/",
                    "two words.html", "", 'a"b.html'):
            bad.append(({"resources": [{"title": "T", "url": url}]}, "home.resources[1].url"))
        for value, message in bad:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, re.escape(message)):
                home_settings(value)

    def test_the_project_file_is_validated_on_load(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "genealogy.toml"
            path.write_text('[home]\nstudies = "s1"\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "home.studies"):
                ProjectConfig.load(path)
            path.write_text('[home]\nfeatured_question = "q1"\n\n[[home.resources]]\ntitle = "T"\nurl = "https://example.invalid/"\n', encoding="utf-8")
            self.assertEqual("q1", home_settings(ProjectConfig.load(path).raw["home"])["featured_question"])


if __name__ == "__main__":
    unittest.main()
