"""The page shell: grouped sidebar sections, the breadcrumb top bar, the build stamp and the top-bar search."""
from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import AccessLevel as A, Finding, LivingStatus as L, Name, Person, Study
from genealogy.shell import NAV_GROUPS, readable_date
from genealogy.site import ROUTES, build_site


def person(pid, name, sensitivity=A.PUBLIC):
    return Person(pid, names=[Name(name, surname=name.split()[-1])], living=L.DECEASED, sensitivity=sensitivity)


def case(findings=True, studies=True):
    c = ResearchCase("fictional-shell", "Fictional shell")
    c.add_many([person("ada", "Ada Fable"), person("bram", "Bram Fable"), person("secret", "SECRET-PERSON", A.PRIVATE)])
    if findings:
        c.add_many([Finding("f1", "Ada was a weaver.", related_ids=["ada"], recorded_on="2026-09-27", sensitivity=A.PUBLIC),
                    Finding("f0", "Bram was a miller.", related_ids=["bram"], recorded_on="2026-03", sensitivity=A.PUBLIC),
                    # Withheld: its newer date must not date the public site.
                    Finding("f-secret", "SECRET-FINDING", related_ids=["secret"], recorded_on="2027-01-05", sensitivity=A.PRIVATE)])
    if studies:
        c.add(Study("s1", "The Fable weavers", related_ids=["ada"], updated_on="2026-08-02", sensitivity=A.PUBLIC))
    assert validate_case(c) == []
    return c


class Parts(HTMLParser):
    """The sidebar's links (with data-group / data-view / aria-current) and the breadcrumb's items."""

    def __init__(self):
        super().__init__()
        self.where, self.nav, self.crumbs, self._link = [], [], [], None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "nav":
            self.where.append(attrs.get("aria-label"))
        if tag == "a" and self.where:
            self._link = [attrs, ""]
        if tag in ("a", "span") and self.where and self.where[-1] == "Breadcrumb":
            self.crumbs.append([tag, attrs, ""])

    def handle_endtag(self, tag):
        if tag == "nav" and self.where:
            self.where.pop()
        if tag == "a" and self._link and self.where and self.where[-1] == "Main navigation":
            self.nav.append(tuple(self._link))
        if tag == "a":
            self._link = None

    def handle_data(self, data):
        if self._link:
            self._link[1] += data
        if self.where and self.where[-1] == "Breadcrumb" and self.crumbs:
            self.crumbs[-1][2] += data


def parts(html):
    parser = Parts()
    parser.feed(html)
    return parser


class ShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.temp.name)
        config = ProjectConfig(name="Fictional shell", raw={"site": {"contact_email": "fix@example.invalid"}})
        build_site(case(), config, cls.out)
        cls.pages = {route: (cls.out / route).read_text() for route in json.loads((cls.out / "data/routes.json").read_text())}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def page_for(self, prefix):
        return next(text for route, text in self.pages.items() if route.startswith(prefix))

    def test_every_route_is_in_one_section_and_each_section_has_an_icon(self):
        grouped = [route for _, _, members in NAV_GROUPS for route in members]
        self.assertEqual(len(grouped), len(set(grouped)))
        self.assertEqual(set(ROUTES) - {"index.html"}, set(grouped) & set(ROUTES))
        nav = parts(self.pages["index.html"]).nav
        groups = [(a["data-group"], a["href"], text) for a, text in nav if "data-group" in a]
        self.assertEqual([("people", "catalogue.html", "People"), ("family", "tree.html", "Family"), ("places", "places.html", "Places"),
                          ("records", "records.html", "Records"), ("research", "research.html", "Research"),
                          ("about", "sitemap.html", "About")], groups)
        sidebar = self.pages["index.html"].split('<nav aria-label="Main navigation">', 1)[1].split("</nav>", 1)[0]
        self.assertEqual(7, len(re.findall(r'<svg class="nav-icon" viewBox="0 0 20 20" aria-hidden="true"><path d="[^"]+"/></svg>', sidebar)))
        # Home is current on the home page; the shortcuts follow the sections.
        self.assertEqual([({"class": "nav-home", "data-view": "overview", "href": "index.html", "aria-current": "page"}, "Home")], nav[:1])
        self.assertEqual([("connections.html", "Find a connection →"), ("sitemap.html", "Site map")], [(a["href"], t) for a, t in nav[-2:]])

    def test_the_current_section_lists_its_pages_and_marks_the_current_one(self):
        for route, (view, title) in ROUTES.items():
            if route == "index.html":
                continue
            nav = parts(self.pages[route]).nav
            current = [(a["href"], a["aria-current"]) for a, _ in nav if "aria-current" in a]
            self.assertEqual([(route, "page")], current, route)
            members = next(m for _, _, m in NAV_GROUPS if route in m)
            listed = [a["href"] for a, _ in nav if "data-view" in a and a["data-view"] != "overview"]
            self.assertEqual([m for m in members if m in self.pages], listed, route)
        # Optional pages join their sections only when built: Corrections is, duplicates are not switched on.
        about = [a["href"] for a, _ in parts(self.pages["sitemap.html"]).nav if "data-view" in a]
        self.assertIn("corrections.html", about)
        people = [a["href"] for a, _ in parts(self.pages["catalogue.html"]).nav if "data-view" in a]
        self.assertNotIn("duplicates.html", people)
        self.assertIn('>People catalogue</a>', self.pages["branches.html"])

    def test_a_record_page_sits_under_its_listing(self):
        dossier = self.page_for("people/p-")
        nav = parts(dossier).nav
        self.assertEqual([("../catalogue.html", "true")], [(a["href"], a["aria-current"]) for a, _ in nav if "aria-current" in a])
        study = self.page_for("studies/s-")
        self.assertEqual([("../studies.html", "true")], [(a["href"], a["aria-current"]) for a, _ in parts(study).nav if "aria-current" in a])

    def test_breadcrumbs(self):
        def crumbs(html):
            return [(tag, attrs.get("href"), attrs.get("aria-current"), text) for tag, attrs, text in parts(html).crumbs]
        self.assertEqual([("span", None, "page", "Home")], crumbs(self.pages["index.html"]))
        self.assertEqual([("a", "../index.html", None, "Home"), ("a", "../catalogue.html", None, "People"), ("span", None, "page", "Ada Fable")],
                         crumbs(next(t for r, t in self.pages.items() if r.startswith("people/") and 'data-person-id="ada"' in t)))
        self.assertEqual([("a", "../index.html", None, "Home"), ("a", "../studies.html", None, "Studies"), ("span", None, "page", "The Fable weavers")],
                         crumbs(self.page_for("studies/s-")))
        # A section page sits under its section's name, which is not a link; a page named like its section stands alone.
        self.assertEqual([("a", "index.html", None, "Home"), ("span", None, None, "Family"), ("span", None, "page", "Family tree")],
                         crumbs(self.pages["tree.html"]))
        self.assertEqual([("a", "index.html", None, "Home"), ("span", None, "page", "Research")], crumbs(self.pages["research.html"]))

    def test_the_build_stamp_is_the_newest_public_research_date(self):
        for route, html in self.pages.items():
            self.assertIn('<p class="build-stamp" title="The newest recorded finding or study update">Catalogue · '
                          '<time datetime="2026-09-27">27 Sep 2026</time></p>', html, route)
            self.assertNotIn("2027", html.split("<main", 1)[0], route)
        for path in self.out.rglob("*"):
            if path.is_file():
                self.assertNotIn("SECRET-", path.read_text(errors="ignore"), path)

    def test_the_stamp_falls_back_to_studies_and_is_left_out_without_dates(self):
        with tempfile.TemporaryDirectory() as directory:
            build_site(case(findings=False), ProjectConfig(name="Fictional"), Path(directory))
            self.assertIn('<time datetime="2026-08-02">2 Aug 2026</time>', (Path(directory) / "index.html").read_text())
        with tempfile.TemporaryDirectory() as directory:
            build_site(case(findings=False, studies=False), ProjectConfig(name="Fictional"), Path(directory))
            self.assertNotIn("build-stamp", (Path(directory) / "index.html").read_text())

    def test_readable_dates(self):
        self.assertEqual(["27 Sep 2026", "2 Oct 2026", "Mar 2026", "2026", "not-a-date", "2026-13"],
                         [readable_date(v) for v in ("2026-09-27", "2026-10-02", "2026-03", "2026", "not-a-date", "2026-13")])

    def test_search_is_in_the_top_bar_and_the_sidebar_still_works_without_script(self):
        for route, html in self.pages.items():
            header = html.split('<header class="site-header">', 1)[1].split("</header>", 1)[0]
            self.assertTrue(header.startswith('<button id="menu-toggle" aria-controls="site-sidebar" aria-expanded="false">Menu</button>'), route)
            self.assertIn('<form class="site-search" role="search"', header, route)
            self.assertNotIn("site-search", html.split("</aside>", 1)[0], route)
            self.assertIn("<noscript><style>.site-sidebar nav{display:grid!important}#menu-toggle{display:none!important}</style></noscript>", html, route)


if __name__ == "__main__":
    unittest.main()
