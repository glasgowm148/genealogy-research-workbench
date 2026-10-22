"""Saved catalogue views: ``[[catalogue.views]]`` validated and listed in the sidebar under People."""
from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import CATALOGUE_PARAMETERS, ProjectConfig
from genealogy.models import AccessLevel as A, LivingStatus as L, Name, Person
from genealogy.site import build_site

ROOT = Path(__file__).resolve().parents[1]


def views_config(views):
    return ProjectConfig(name="Fictional views", catalogue={"views": views})


def case():
    c = ResearchCase("fictional-views", "Fictional views")
    c.add_many([Person("ada", names=[Name("Ada Fable", surname="Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
                Person("secret", names=[Name("SECRET-PERSON", surname="Hidden")], living=L.DECEASED, sensitivity=A.PRIVATE)])
    assert validate_case(c) == []
    return c


def people_section(html):
    """The People section's list items in the sidebar, as (class, href, text, aria-current)."""
    nav = html.split('<nav aria-label="Main navigation">', 1)[1].split("</nav>", 1)[0]
    section = re.search(r'<div class="nav-section"><a class="nav-group" data-group="people".*?</ul></div>', nav)
    if not section:
        return []
    return [(m["cls"] or "", m["href"], m["text"], m["current"]) for m in re.finditer(
        r'<li(?: class="(?P<cls>[^"]+)")?><a (?:data-view="[^"]+" )?href="(?P<href>[^"]+)"[^>]*?(?: aria-current="(?P<current>[^"]+)")?>(?P<text>[^<]*)</a></li>',
        section[0])]


class CatalogueViewsConfigTests(unittest.TestCase):
    def test_views_are_label_and_query_pairs_with_the_query_re_encoded(self):
        config = views_config([{"label": "  No WikiTree link ", "query": "no_external=1"},
                               {"label": "Early records", "query": "date_type=birth&year_to=1750&place=Invented%20Parish"}])
        config.validate()
        self.assertEqual([("No WikiTree link", "no_external=1"),
                          ("Early records", "date_type=birth&year_to=1750&place=Invented+Parish")], config.catalogue_views)
        self.assertEqual([], ProjectConfig().catalogue_views)

    def test_invalid_views_are_refused_with_the_setting_named(self):
        bad = {
            "catalogue.views must be a list": {"label": "x", "query": "q=a"},
            "catalogue.views[1] must be a table": ["no_external=1"],
            "catalogue.views[1] has unknown settings: icon": [{"label": "x", "query": "q=a", "icon": "star"}],
            "catalogue.views[1].label must be a non-empty string": [{"label": " ", "query": "q=a"}],
            "of at most 60 characters": [{"label": "x" * 61, "query": "q=a"}],
            "catalogue.views[2].label": [{"label": "ok", "query": "q=a"}, {"query": "q=b"}],
            "catalogue.views[1].query must be a query string": [{"label": "x", "query": "?no_external=1"}],
            "without '?', '#' or spaces": [{"label": "x", "query": "place=Invented Parish"}],
            "must be name=value pairs": [{"label": "x", "query": "no_external"}],
            "must be name=value pairs joined": [{"label": "x", "query": "q=a&&sex=F"}],
            "does not read: colour, page": [{"label": "x", "query": "colour=red&page=2"}],
            # The older keys are rewritten when the page opens, so a view could never match its address.
            "does not read: birth_from": [{"label": "x", "query": "birth_from=1700"}],
            "each parameter once, with a value": [{"label": "x", "query": "sex=F&sex=M"}],
            "with a value": [{"label": "x", "query": "no_external="}],
            "catalogue.views[2].query repeats an earlier view's query": [{"label": "a", "query": "sex=F&no_spouse=1"},
                                                                          {"label": "b", "query": "no_spouse=1&sex=F"}],
        }
        for message, views in bad.items():
            with self.subTest(message), self.assertRaisesRegex(ValueError, re.escape(message)):
                views_config(views).validate()
        with self.assertRaisesRegex(ValueError, "label"):
            views_config([{"label": 5, "query": "q=a"}]).validate()
        with self.assertRaisesRegex(ValueError, "query"):
            views_config([{"label": "x", "query": ""}]).validate()

    def test_every_catalogue_parameter_is_read_by_the_page_and_documented(self):
        script = (ROOT / "src/genealogy/web/site.js").read_text(encoding="utf-8")
        deployment = (ROOT / "docs/deployment.md").read_text(encoding="utf-8")
        catalogue_row = next(line for line in deployment.splitlines() if line.startswith("| `catalogue.html`"))
        for key in sorted(CATALOGUE_PARAMETERS):
            with self.subTest(key):
                self.assertIn(f"'{key}'", script)
                self.assertIn(f"`{key}`", catalogue_row)

    def test_views_load_from_toml_and_survive_to_dict(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "genealogy.toml"
            path.write_text('[project]\nname = "Fictional"\n[catalogue]\nformat = "markdown"\n\n'
                            '[[catalogue.views]]\nlabel = "Held research"\nquery = "needs_update=1"\n', encoding="utf-8")
            config = ProjectConfig.load(path)
            self.assertEqual([("Held research", "needs_update=1")], config.catalogue_views)
            self.assertEqual([{"label": "Held research", "query": "needs_update=1"}], config.to_dict()["catalogue"]["views"])
            path.write_text('[[catalogue.views]]\nlabel = "Held research"\nquery = "held=1"\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not read: held"):
                ProjectConfig.load(path)

    def test_the_demo_project_has_two_example_views(self):
        config = ProjectConfig.load(ROOT / "examples/demo/genealogy.toml")
        self.assertEqual(2, len(config.catalogue_views))


class CatalogueViewsSidebarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        out = Path(cls.temp.name)
        build_site(case(), views_config([{"label": "No WikiTree link", "query": "no_external=1"},
                                         {"label": "Fable & kin <early>", "query": "surname=Fable&year_to=1800"}]), out / "views")
        build_site(case(), ProjectConfig(name="Fictional views"), out / "plain")
        cls.views = {p.relative_to(out / "views").as_posix(): p.read_text(encoding="utf-8") for p in (out / "views").rglob("*") if p.is_file()}
        cls.plain = (out / "plain/catalogue.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_views_follow_the_catalogue_under_people(self):
        items = people_section(self.views["catalogue.html"])
        self.assertEqual([("", "catalogue.html", "People catalogue", "page"),
                          ("nav-view", "catalogue.html?no_external=1", "No WikiTree link", None),
                          ("nav-view", "catalogue.html?surname=Fable&amp;year_to=1800", "Fable &amp; kin &lt;early&gt;", None)], items[:3])
        self.assertEqual("branches.html", items[3][1])
        self.assertIn('data-catalogue-view="surname=Fable&amp;year_to=1800"', self.views["catalogue.html"])
        self.assertNotIn("<early>", self.views["catalogue.html"])

    def test_views_are_listed_wherever_the_people_section_is_open(self):
        dossier = next(text for path, text in self.views.items() if path.startswith("people/p-"))
        self.assertIn(("nav-view", "../catalogue.html?no_external=1", "No WikiTree link", None), people_section(dossier))
        self.assertIn(("nav-view", "catalogue.html?no_external=1", "No WikiTree link", None), people_section(self.views["branches.html"]))
        # Another section's page keeps People folded to its one link.
        self.assertEqual([], people_section(self.views["index.html"]))
        self.assertNotIn("data-catalogue-view", self.views["index.html"])

    def test_without_views_the_sidebar_is_unchanged(self):
        self.assertNotIn("nav-view", self.plain)
        self.assertNotIn("data-catalogue-view", self.plain)
        self.assertEqual(self.plain, self.views["catalogue.html"].replace(re.search(r'<li class="nav-view">.*</li>(?=<li><a data-view="branches")', self.views["catalogue.html"])[0], ""))

    def test_withheld_records_stay_out(self):
        for path, text in self.views.items():
            self.assertNotIn("SECRET-PERSON", text, path)


if __name__ == "__main__":
    unittest.main()
