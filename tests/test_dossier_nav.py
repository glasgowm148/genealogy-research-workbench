"""The dossier's on-this-page menu and its links into the tree, connections and comparison tools."""
from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Claim, Confidence as C, Event, ExternalIdentifier, LivingStatus as L, Name, Person,
                              Relationship, ResearchQuestion, Study)
from genealogy.site import build_site

ALL = ["names", "biography", "family-heading", "events", "claims", "studies", "research", "relationships", "external", "connected"]


def nav_case():
    case = ResearchCase("fictional-nav", "Fictional dossier menus")
    for record in [
        # A colon and a space in the id, and a two-word surname, must survive into the query strings.
        Person("ada:fable 1", names=[Name("Ada Van Fable", surname="Van Fable")], living=L.DECEASED, notes="A fictional seamstress.",
               event_ids=["e-ada"], external_ids=[ExternalIdentifier("Fictional tree", "AF-1")], sensitivity=A.PUBLIC),
        Event("e-ada", "birth", date="1801", participant_ids=["ada:fable 1"], sensitivity=A.PUBLIC),
        Person("p0002", names=[Name("Tobin Van Fable", surname="Van Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Relationship("r-parent", "ada:fable 1", "p0002", "parent", confidence=C.DOCUMENTED, sensitivity=A.PUBLIC),
        Claim("c-occ", "ada:fable 1", "occupation", "seamstress", sensitivity=A.PUBLIC),
        Study("s-ada", "A fictional study", related_ids=["ada:fable 1"], sensitivity=A.PUBLIC),
        ResearchQuestion("q-ada", "Where was Ada baptised?", related_ids=["ada:fable 1"], sensitivity=A.PUBLIC),
        # Names only: no surname, and a disproved sibling link, which the Family section does not list.
        Person("p0003", names=[Name("Wren")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Person("p0004", names=[Name("Nell Fable", surname="Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Relationship("r-nell", "p0003", "p0004", "sibling", confidence=C.DISPROVED, sensitivity=A.PUBLIC),
    ]:
        case.add(record)
    return case


class DossierNavTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.paths = build_site(nav_case(), ProjectConfig(name="Fictional dossier menus"), Path(cls.temp.name))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def dossier(self, pid):
        return next(path.read_text() for key, path in self.paths.items() if key.startswith("people/") and f'data-person-id="{pid}"' in path.read_text())

    def menu(self, page):
        nav = re.search(r'<nav class="page-sections" aria-label="On this page">(.*?)</nav>', page).group(1)
        return re.findall(r'<a href="#([^"]+)">', nav)

    def test_fixture_is_valid(self):
        self.assertEqual([], validate_case(nav_case()))

    def test_every_section_heading_has_its_id_and_a_full_dossier_links_them_all(self):
        page = self.dossier("ada:fable 1")
        self.assertEqual(ALL, self.menu(page))
        for key in ALL:
            self.assertRegex(page, rf'<h2 id="{key}">')
        # The menu follows the hero card directly and opens the two-column body, so the dossier opening stays one insertion point.
        self.assertRegex(page, r'</header><div class="dossier-layout"><nav class="page-sections" aria-label="On this page"><ol>')

    def test_menu_skips_sections_showing_only_their_empty_state(self):
        page = self.dossier("p0003")
        self.assertEqual(["names", "relationships"], self.menu(page))  # the disproved sibling is listed only under all relationships
        self.assertIn('<h2 id="events">Events</h2><p class="empty-state">', page)
        self.assertIn('<h2 id="family-heading">Family</h2>', page)  # the section is still shown, only not linked

    def test_explore_links_quote_the_id_and_canonical_surname(self):
        explore = re.search(r'<p class="explore">(.*?)</p>', self.dossier("ada:fable 1")).group(1)
        self.assertEqual([("../tree.html?person=ada%3Afable%201", "Family tree"), ("../connections.html?a=ada%3Afable%201", "Find a connection"),
                          ("../compare.html?a=ada%3Afable%201", "Compare"), ("../catalogue.html?surname=Van%20Fable", "Everyone surnamed Van Fable")],
                         re.findall(r'<a href="([^"]+)">([^<]+)</a>', explore))
        # No surname recorded: no catalogue filter link.
        self.assertNotIn("catalogue.html?surname=", re.search(r'<p class="explore">(.*?)</p>', self.dossier("p0003")).group(1))

    def test_folded_spelling_links_to_the_canonical_surname(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = build_site(nav_case(), ProjectConfig(name="Fictional variants", names={"variants": {"Fabel": ["Fable"]}}), Path(temp))
            page = next(p.read_text() for k, p in paths.items() if k.startswith("people/") and 'data-person-id="p0004"' in p.read_text())
        self.assertIn('<a href="../catalogue.html?surname=Fabel">Everyone surnamed Fabel</a>', page)


if __name__ == "__main__":
    unittest.main()
