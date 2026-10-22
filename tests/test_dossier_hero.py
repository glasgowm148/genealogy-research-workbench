"""The dossier's hero card (vitals, actions, latest finding), numbered contents and "Connected pages" grid."""
from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Citation, Claim, Confidence as C, Event, Evidence, Finding, LivingStatus as L, Name, Person,
                              Place, Relationship, Source, Study)
from genealogy.site import CONNECTED_LIMIT, build_site


def hero_case():
    case = ResearchCase("fictional-hero", "Fictional dossier heroes")
    for record in [
        Person("ada", names=[Name("Ada Fable", surname="Fable")], living=L.DECEASED, event_ids=["e-birth", "e-death"], sensitivity=A.PUBLIC),
        Event("e-birth", "birth", date="1801", place_id="pl-parish", participant_ids=["ada"], sensitivity=A.PUBLIC),
        Event("e-death", "death", date="1870", place_id="pl-town", participant_ids=["ada"], sensitivity=A.PUBLIC),
        Event("e-other", "residence", date="1850", place_id="pl-parish", participant_ids=["ada"], sensitivity=A.PUBLIC),
        Place("pl-parish", "Invented Parish", sensitivity=A.PUBLIC),
        Place("pl-town", "Invented Town", sensitivity=A.PUBLIC),
        Person("tobin", names=[Name("Tobin Fable", surname="Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Event("e-tobin", "birth", date="1770", participant_ids=["tobin"], sensitivity=A.PUBLIC),  # no death recorded
        Person("corin", names=[Name("Corin Vale", surname="Vale")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Person("iris", names=[Name("Iris Fable", surname="Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Relationship("r-tobin", "ada", "tobin", "parent", confidence=C.DOCUMENTED, sensitivity=A.PUBLIC),
        Relationship("r-corin", "ada", "corin", "parent", confidence=C.DISPROVED, sensitivity=A.PUBLIC),  # ruled out: not a connected dossier
        Relationship("r-iris", "iris", "ada", "parent", confidence=C.PROBABLE, sensitivity=A.PUBLIC),
        Source("src-reg", "Invented Parish Register", sensitivity=A.PUBLIC),
        Source("src-census", "Invented Census", sensitivity=A.PUBLIC),
        Citation("cit-reg-1", "src-reg", locator="folio 1", sensitivity=A.PUBLIC),
        Citation("cit-reg-2", "src-reg", locator="folio 2", sensitivity=A.PUBLIC),
        Citation("cit-census", "src-census", sensitivity=A.PUBLIC),
        Claim("c-occ", "ada", "occupation", "seamstress", citation_ids=["cit-reg-1", "cit-census"], sensitivity=A.PUBLIC),
        Claim("c-birth", "e-birth", "date", "1801", citation_ids=["cit-reg-2"], sensitivity=A.PUBLIC),
        Evidence("ev-occ", "c-occ", "cit-reg-2", "Names her trade.", sensitivity=A.PUBLIC),
        Study("s-ada", "A fictional study of Ada", related_ids=["ada"], sensitivity=A.PUBLIC),
        Finding("f-ada", "Ada Fable's father is Tobin Fable.", related_ids=["ada"], status="reviewed", recorded_on="2026-09-08", sensitivity=A.PUBLIC),
        # Withheld records Ada leads to: none may surface in the grid, or anywhere.
        Source("src-secret", "SECRET-SOURCE-TITLE", sensitivity=A.PRIVATE),
        Citation("cit-secret", "src-secret", sensitivity=A.PRIVATE),
        Claim("c-secret", "ada", "residence", "SECRET-CLAIM", citation_ids=["cit-secret"], sensitivity=A.PRIVATE),
        Study("s-secret", "SECRET-STUDY-TITLE", related_ids=["ada"], sensitivity=A.PRIVATE),
        Place("pl-secret", "SECRET-PLACE-NAME", sensitivity=A.PRIVATE),
        Event("e-secret", "residence", date="1860", place_id="pl-secret", participant_ids=["ada"], sensitivity=A.PRIVATE),
        Person("kid", names=[Name("SECRET-CHILD-NAME")], living=L.LIVING, sensitivity=A.PUBLIC),
        Relationship("r-kid", "kid", "ada", "parent", confidence=C.DOCUMENTED, sensitivity=A.PUBLIC),
        # Baptised and buried only, no relatives, places, studies or sources.
        Person("pip", names=[Name("Pip")], living=L.DECEASED, event_ids=["e-bap", "e-bur"], sensitivity=A.PUBLIC),
        Event("e-bap", "baptism", date="3 MAY 1804", participant_ids=["pip"], sensitivity=A.PUBLIC),
        Event("e-bur", "burial", date="1880", participant_ids=["pip"], sensitivity=A.PUBLIC),
        Person("quill", names=[Name("Quill")], living=L.DECEASED, sensitivity=A.PUBLIC),  # nothing recorded at all
    ]:
        case.add(record)
    # One person with more children than a connected-pages group lists.
    for n in range(CONNECTED_LIMIT + 3):
        case.add(Person(f"kid{n:02}", names=[Name(f"Child {n:02} Vale", surname="Vale")], living=L.DECEASED, sensitivity=A.PUBLIC))
        case.add(Relationship(f"r-kid{n:02}", f"kid{n:02}", "corin", "parent", confidence=C.DOCUMENTED, sensitivity=A.PUBLIC))
    return case


def text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


class DossierHeroTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        site = ProjectConfig(name="Fictional heroes", raw={"site": {"contact_email": "corrections@example.invalid"}})
        site.validate()
        cls.paths = build_site(hero_case(), site, Path(cls.temp.name))
        cls.pages = {key: path.read_text(encoding="utf-8") for key, path in cls.paths.items() if key.endswith(".html")}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def dossier(self, pid):
        return next(page for key, page in self.pages.items() if key.startswith("people/") and f'data-person-id="{pid}"' in page)

    def hero(self, pid):
        return re.search(r'<header class="dossier-hero">(.*?)</header>', self.dossier(pid), re.S).group(1)

    def group(self, pid, heading):
        found = re.search(rf'<details class="connected-group"><summary>{heading} <span class="meta">([^<]*)</span></summary>(.*?)</details>', self.dossier(pid), re.S)
        return (found[1], found[2]) if found else None

    def test_fixture_is_valid(self):
        self.assertEqual([], validate_case(hero_case()))

    def test_hero_holds_the_name_dates_vitals_actions_and_latest_finding(self):
        hero = self.hero("ada")
        for part in ('<p class="eyebrow">Person dossier</p>', "<h1>Ada Fable</h1>", '<p class="lifespan">b. 1801 – d. 1870</p>', '<p class="record-id meta">Record ID: ada</p>',
                     '<p class="lead intro">', '<p class="explore">', '<p class="suggest-correction">', '<aside class="latest-finding"'):
            self.assertIn(part, hero)
        # The actions sit together, and the latest finding beside the main column, not inside it.
        self.assertIn('<div class="dossier-actions"><p class="explore">', hero)
        main = hero.split('<aside class="latest-finding"', 1)[0]
        self.assertIn('<p class="suggest-correction">', main)
        self.assertEqual(1, self.dossier("ada").count('<p class="explore">'))
        self.assertEqual(1, self.dossier("ada").count('class="suggest-correction"'))
        self.assertEqual(1, self.dossier("ada").count("<h1>"))

    def test_vitals_link_each_place(self):
        vitals = re.search(r'<dl class="vitals">(.*?)</dl>', self.hero("ada")).group(1)
        self.assertEqual(["Born", "Died"], re.findall(r"<dt>(.*?)</dt>", vitals))
        self.assertIn('<dd><time datetime="1801">1801</time> · <a href="../places/pl-', vitals)
        self.assertEqual(["Invented Parish", "Invented Town"], re.findall(r'<a href="\.\./places/pl-[^"]+\.html">([^<]+)</a>', vitals))

    def test_vitals_name_a_baptism_or_burial_and_say_what_is_missing(self):
        vitals = re.search(r'<dl class="vitals">(.*?)</dl>', self.hero("pip")).group(1)
        self.assertEqual("Baptised 3 May 1804 Buried 1880", text(vitals))
        self.assertNotIn("vitals", self.dossier("quill"))  # nothing to show: no empty box
        self.assertEqual("Born 1770 Died Not recorded", text(re.search(r'<dl class="vitals">(.*?)</dl>', self.hero("tobin")).group(1)))

    def test_contents_are_an_ordered_list_ending_with_connected_pages(self):
        page = self.dossier("ada")
        self.assertRegex(page, r'</header><div class="dossier-layout"><nav class="page-sections" aria-label="On this page"><ol><li>')
        links = re.findall(r'<a href="#([^"]+)">', re.search(r'<nav class="page-sections"[^>]*>(.*?)</nav>', page).group(1))
        self.assertEqual("connected", links[-1])
        for key in links:
            self.assertIn(f'<h2 id="{key}">', page)
        # The grid closes the body: nothing but the closing tags follows it.
        self.assertRegex(page, r'<h2 id="connected">Connected pages</h2>.*</div></div></div></main>')

    def test_connected_pages_list_places_studies_sources_surname_and_family(self):
        count, places = self.group("ada", "Places")
        self.assertEqual("2 places", count)
        self.assertIn(">Invented Parish</a> <span class=\"meta\">birth, residence</span>", places)
        self.assertEqual(2, len(re.findall(r'href="\.\./places/pl-', places)))
        count, studies = self.group("ada", "Studies")
        self.assertEqual(("1 study", ["A fictional study of Ada"]), (count, re.findall(r'<a href="\.\./studies/s-[^"]+">([^<]+)</a>', studies)))
        count, cited = self.group("ada", "Sources cited")
        self.assertEqual("2 sources", count)
        # Most cited first: the register through a citation, an assessment and an event's claim.
        self.assertEqual(["Invented Parish Register cited 3 times", "Invented Census cited 1 time"], [text(item) for item in re.findall(r"<li>(.*?)</li>", cited)])
        self.assertEqual(("1 page", [("../catalogue.html?surname=Fable", "Everyone surnamed Fable")]),
                         (self.group("ada", "Surname")[0], re.findall(r'<a href="([^"]+)">([^<]+)</a>', self.group("ada", "Surname")[1])))
        count, parents = self.group("ada", "Parents")
        self.assertEqual("1 dossier", count)  # the ruled-out parent is not offered as a dossier to read on
        self.assertIn(">Tobin Fable</a>", parents)
        self.assertNotIn("Corin Vale", parents)
        count, children = self.group("ada", "Children")
        self.assertEqual("1 dossier", count)
        self.assertIn(">Iris Fable</a>", children)
        self.assertIn("../people/p-", children)

    def test_groups_are_capped_and_counted(self):
        count, children = self.group("corin", "Children")
        self.assertEqual(f"{CONNECTED_LIMIT + 3} dossiers", count)
        self.assertEqual(CONNECTED_LIMIT, children.count("<li>"))
        self.assertIn('<p class="meta">and 3 more, listed in the sections above</p>', children)

    def test_nothing_connected_writes_no_section_and_no_contents_entry(self):
        for pid in ("pip", "quill"):
            page = self.dossier(pid)
            self.assertNotIn('id="connected"', page)
            self.assertNotIn('href="#connected"', page)
        self.assertIsNone(self.group("pip", "Surname"))  # no surname recorded

    def test_withheld_records_never_appear(self):
        for name, path in self.paths.items():
            if path.suffix in {".html", ".js", ".json", ".csv", ".ged", ".xml", ".geojson", ".txt"}:
                body = path.read_text(encoding="utf-8")
                for sentinel in ("SECRET-SOURCE-TITLE", "SECRET-CLAIM", "SECRET-STUDY-TITLE", "SECRET-PLACE-NAME", "SECRET-CHILD-NAME"):
                    self.assertNotIn(sentinel, body, name)
        self.assertEqual("1 dossier", self.group("ada", "Children")[0])  # the living child is not counted either


if __name__ == "__main__":
    unittest.main()
