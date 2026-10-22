"""A story for each family branch: family studies on the branches page."""
from __future__ import annotations

from html import unescape
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import AccessLevel as A, LivingStatus as L, Name, Person, Relationship, Study
from genealogy.site import BRANCH_STORIES, build_site

from test_scale import large_case

CONFIG = ProjectConfig(name="Fictional", raw={"site": {"base_url": "https://example.invalid/"}})


def story_case(stories: bool = True) -> ResearchCase:
    case = ResearchCase("fictional-stories", "Fictional stories")
    case.add_many([
        Person("ada", names=[Name("Ada Fable", surname="Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Person("bram", names=[Name("Bram Fable", surname="Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Person("cora", names=[Name("Cora Vale", surname="Vale")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Person("dell", names=[Name("Dell Vale", surname="Vale")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Person("hidden", names=[Name("SECRET-PERSON Fable", surname="Fable")], living=L.LIVING, sensitivity=A.PRIVATE),
        Relationship("r1", "bram", "ada", "parent", sensitivity=A.PUBLIC),
        Relationship("r2", "dell", "cora", "parent", sensitivity=A.PUBLIC),
    ])
    if stories:
        case.add_many([
            Study("s-fable", "The Fable household", kind="family", summary="Who the Fables of the mill were.",
                  related_ids=["ada", "bram"], status="reviewed", updated_on="2026-10-01", sensitivity=A.PUBLIC),
            Study("s-bram", "Bram's second family", kind="Family_Study", summary="Whether Bram married twice.",
                  related_ids=["bram"], status="draft", updated_on="2026-09-01", sensitivity=A.PUBLIC),
            Study("s-group", "Fables filed together", kind="group", summary="A catalogue grouping.",
                  related_ids=["ada", "bram"], updated_on="2026-10-05", sensitivity=A.PUBLIC),
            Study("s-plain", "Fable records overview", summary="No kind recorded.", related_ids=["ada"], sensitivity=A.PUBLIC),
            # Withheld: names a private person, or is private itself.
            Study("s-secret-person", "SECRET-STORY-PERSON title", kind="family", summary="SECRET-STORY-PERSON summary",
                  related_ids=["ada", "hidden"], updated_on="2026-10-20", sensitivity=A.PUBLIC),
            Study("s-secret", "SECRET-STORY title", kind="family", summary="SECRET-STORY summary",
                  related_ids=["cora"], updated_on="2026-10-21", sensitivity=A.PRIVATE),
        ])
    return case


class BranchStoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        case = story_case()
        assert validate_case(case) == []
        build_site(case, CONFIG, cls.root)
        cls.html = (cls.root / "branches.html").read_text()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def row(self, marker: str) -> str:
        start = self.html.index(marker)
        return self.html[start:self.html.index("</tr>", start)]

    def test_the_lead_section_lists_family_studies_newest_first(self):
        section = re.search(r'<section class="family-stories" aria-labelledby="family-studies"><h2 id="family-studies">Family studies</h2>(.*?)</section>', self.html).group(1)
        self.assertLess(self.html.index('id="family-studies"'), self.html.index("<h2>Surnames</h2>"))
        cards = re.findall(r'<article class="card story-card" data-study-id="([^"]+)">(.*?)</article>', section)
        self.assertEqual(["s-fable", "s-bram"], [sid for sid, _ in cards])  # not the group study, nor one with no kind
        first = cards[0][1]
        self.assertIn('<p class="eyebrow story-kicker">Family</p>', first)
        self.assertIn("Who the Fables of the mill were.", first)
        self.assertIn("2 people", first)
        self.assertIn('<p class="eyebrow story-kicker">Family study</p>', cards[1][1])  # the kind as recorded, as a label
        url = re.search(r'<h3><a href="(studies/s-[0-9a-f]{64}\.html)">The Fable household</a></h3>', first).group(1)
        self.assertIn(f'<a href="{url}">Read the study<span class="sr-only">: The Fable household</span> →</a>', first)
        self.assertTrue((self.root / url).exists())

    def test_each_branch_shows_the_study_naming_most_of_its_people(self):
        fable = self.row('<tr data-surname="Fable">')
        story = re.search(r'<div class="branch-story" data-study-id="s-fable">(.*?)</div>', fable).group(1)
        self.assertIn('<p class="eyebrow story-kicker">Family</p><p class="branch-story-title">The Fable household</p>', story)
        self.assertIn("<p>Who the Fables of the mill were.</p>", story)
        self.assertIn("Read the study<span", story)
        self.assertRegex(story, r'<p class="meta">Also: <a href="studies/s-[0-9a-f]{64}\.html">Bram&#x27;s second family</a>\.</p>')
        self.assertNotIn("branch-story", self.row('<tr data-surname="Vale">'))
        groups = self.html[self.html.index("<h2>Connected groups</h2>"):]
        self.assertIn("Group of 2 people around Ada Fable", groups)
        self.assertIn('data-study-id="s-fable"', groups[:groups.index("</tr>", groups.index("<tbody>"))])
        self.assertEqual(1, groups.count('class="branch-story"'))  # the Vale group has no story

    def test_a_withheld_family_study_reaches_no_output(self):
        for path in self.root.rglob("*"):
            if path.is_file() and path.suffix in {".html", ".json", ".js", ".csv", ".geojson", ".xml", ".txt", ".ics", ".ged"}:
                text = path.read_text(errors="replace")
                for sentinel in ("SECRET-STORY", "SECRET-PERSON", "s-secret"):
                    self.assertNotIn(sentinel, text, f"{sentinel} in {path.name}")

    def test_without_family_studies_the_page_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            build_site(story_case(stories=False), CONFIG, Path(directory))
            html = (Path(directory) / "branches.html").read_text()
        self.assertNotIn("family-stories", html)
        self.assertNotIn("branch-story", html)
        self.assertNotIn("Family studies", unescape(re.sub(r"<[^>]+>", " ", html)))


class LargeBranchStoryTests(unittest.TestCase):
    def test_a_large_site_lists_the_newest_and_counts_the_rest(self):
        case = large_case()
        for study in case.records("Study"):
            if study.sensitivity is A.PUBLIC:
                study.kind = "family"
        with tempfile.TemporaryDirectory() as directory:
            build_site(case, CONFIG, Path(directory))
            path = Path(directory) / "branches.html"
            html = path.read_text()
            self.assertLess(path.stat().st_size, 100_000)
        total = len([s for s in case.records("Study") if s.sensitivity is A.PUBLIC])
        self.assertEqual(BRANCH_STORIES, html.count('class="card story-card"'))
        self.assertIn(f"The {BRANCH_STORIES} most recently updated of {total:,} family studies.", html)
        # The one surname row and the one connected group: a story in full, three more by title, the rest counted.
        self.assertEqual(2, html.count('class="branch-story"'))
        self.assertIn(f" and {total - 4:,} more.</p>", html)
        self.assertNotIn("SECRET-STUDY", html)


if __name__ == "__main__":
    unittest.main()
