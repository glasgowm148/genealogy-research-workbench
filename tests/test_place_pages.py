"""Each place with a public event or a sub-place has a page: its parents, sub-places and the events and people recorded there."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import AccessLevel as A, Event, LivingStatus as L, Name, Person, Place, Study
from genealogy.site import PLACE_LIST_LIMIT, _anchor, _key, _owned, build_site
from genealogy.sitecheck import check_site


def page(pid: str) -> str:
    return f"places/pl-{_key(pid)}.html"


def person(pid: str, name: str, surname: str, events: list[str], sensitivity=A.PUBLIC) -> Person:
    return Person(pid, names=[Name(name, surname=surname)], living=L.DECEASED, event_ids=events, sensitivity=sensitivity)


def case(*, town_events: bool = True) -> ResearchCase:
    c = ResearchCase("fictional-places", "Fictional places")
    records = [
        # Four levels: a country with no events of its own, a shire, a parish and a town in it.
        Place("fableland", "Fableland", sensitivity=A.PUBLIC),
        Place("shire", "Invented Shire, Fableland", parent_id="fableland", sensitivity=A.PUBLIC),
        Place("parish", "Invented Parish, Invented Shire, Fableland", parent_id="shire", latitude=55.9, longitude=-4.2,
              precision="parish", sensitivity=A.PUBLIC),
        Place("town", "Invented Town, Invented Parish, Invented Shire, Fableland", parent_id="parish", sensitivity=A.PUBLIC),
        Place("quiet", "Quiet Hamlet, Fableland", sensitivity=A.PUBLIC),  # no events, no sub-places: no page
        Place("secret-place", "SECRET-PLACE Manor", sensitivity=A.PRIVATE),
        Place("under-secret", "SECRET-CHILD Cottage", parent_id="secret-place", sensitivity=A.PUBLIC),
        # A loop in parent_id must not hang the build.
        Place("loop-a", "Loop A", parent_id="loop-b", sensitivity=A.PUBLIC),
        Place("loop-b", "Loop B", parent_id="loop-a", sensitivity=A.PUBLIC),
        person("ada", "Ada Fable", "Fable", ["ada-b", "ada-bur"]),
        person("bram", "Bram Fable", "Fable", ["bram-b"]),
        person("cora", "Cora Vale", "Vale", ["cora-b"]),
        person("hidden", "SECRET-PERSON Fable", "SECRET-SURNAME", ["hidden-b"], A.PRIVATE),
        Event("bram-b", "birth", date="1799", place_id="parish", participant_ids=["bram"], sensitivity=A.PUBLIC),
        Event("ada-b", "birth", date="ABT 1801", place_id="parish", participant_ids=["ada"], sensitivity=A.PUBLIC),
        Event("ada-bur", "burial", date="1870", place_id="parish", participant_ids=["ada"], sensitivity=A.PUBLIC),
        Event("cora-b", "birth", date="1805", place_id="town" if town_events else "parish", participant_ids=["cora"], sensitivity=A.PUBLIC),
        Event("hidden-b", "birth", date="1950", place_id="parish", participant_ids=["hidden"], sensitivity=A.PUBLIC),
        Event("secret-event", "residence", date="1960", place_id="parish", description="SECRET-EVENT", sensitivity=A.PRIVATE),
        Event("manor-event", "residence", date="1820", place_id="secret-place", participant_ids=["bram"], sensitivity=A.PUBLIC),
        Event("loop-event", "residence", date="1830", place_id="loop-a", participant_ids=["bram"], sensitivity=A.PUBLIC),
        Study("parish-study", "The parish registers", summary="Why the parish matters.", related_ids=["parish"], sensitivity=A.PUBLIC),
        Study("town-study", "A walk through the town", body="The register for [[town|the town]] survives.", sensitivity=A.PUBLIC),
        Study("secret-study", "SECRET-STUDY title", related_ids=["parish"], sensitivity=A.PRIVATE),
    ]
    c.add_many(records)
    return c


def main(html: str) -> str:
    return html.split('<main id="main-content">', 1)[1].split("</main>", 1)[0]


class PlacePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.out = Path(cls.directory.name) / "site"
        cls.case = case()
        assert validate_case(cls.case) == [], validate_case(cls.case)
        build_site(cls.case, ProjectConfig(name="Fictional places"), cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def text(self, path: str) -> str:
        return (self.out / path).read_text(encoding="utf-8")

    def test_a_page_for_each_place_with_an_event_or_a_sub_place(self):
        for pid in ("fableland", "shire", "parish", "town", "loop-a", "loop-b"):
            self.assertTrue((self.out / page(pid)).is_file(), pid)
            self.assertTrue(_owned(page(pid)))
        self.assertFalse((self.out / page("quiet")).exists())
        routes = json.loads(self.text("data/routes.json"))
        self.assertIn(page("fableland"), routes)
        self.assertIn("<title>Invented Parish, Invented Shire, Fableland — Fictional places</title>", self.text(page("parish")))
        self.assertIn("<h1>Fableland</h1>", self.text(page("fableland")))
        self.assertEqual([], check_site(self.out)["broken"])

    def test_the_parent_chain_is_linked_broadest_first(self):
        town = main(self.text(page("town")))
        chain = re.search(r'<p class="place-chain">(.*?)</p>', town)[1]
        self.assertEqual([f"../{page(pid)}" for pid in ("fableland", "shire", "parish")], re.findall(r'href="([^"]+)"', chain))
        self.assertIn(">Fableland</a> › <a", chain)
        self.assertNotIn("place-chain", self.text(page("fableland")))
        # A loop in parent_id stops at the first place seen twice.
        chain = re.search(r'<p class="place-chain">(.*?)</p>', main(self.text(page("loop-a"))))[1]
        self.assertEqual([f"../{page('loop-b')}"], re.findall(r'href="([^"]+)"', chain))

    def test_a_place_with_no_events_lists_its_sub_places(self):
        fableland = main(self.text(page("fableland")))
        self.assertIn("No public events are recorded here", fableland)
        self.assertIn(f'<a href="../{page("shire")}">Invented Shire, Fableland</a> <span class="meta">one place within</span>', fableland)
        self.assertNotIn("Quiet Hamlet", fableland)  # a place with no parent_id is not within Fableland
        shire = main(self.text(page("shire")))
        self.assertIn(f'<a href="../{page("parish")}">Invented Parish, Invented Shire, Fableland</a> <span class="meta">three events, one place within</span>', shire)
        self.assertIn("No public events are recorded at this place.", shire)
        self.assertNotIn("data-place-events", shire)

    def test_people_surnames_years_coordinates_and_studies(self):
        parish = main(self.text(page("parish")))
        # The events as a Year · Event · Person · Source table in date order; an approximate year keeps "c.".
        self.assertIn('<th scope="col" aria-sort="ascending">Year</th><th scope="col">Event</th><th scope="col">Person</th><th scope="col">Source</th>', parish)
        rows = re.findall(r'<tr data-year="(\d*)"><td>([^<]+)</td><td>([^<]+)</td><td><a href="\.\./people/[^"]+">([^<]+)</a></td>', parish)
        self.assertEqual([("1799", "1799", "Birth", "Bram Fable"), ("1801", "c. 1801", "Birth", "Ada Fable"), ("1870", "1870", "Burial", "Ada Fable")], rows)
        self.assertIn("Three public events are recorded here, involving two people; recorded years 1799–1870.", parish)
        self.assertIn('<a href="../catalogue.html?surname=Fable">Fable</a> <span class="meta">(2)</span>', parish)
        self.assertIn("55.9, -4.2 · located to parish level", parish)
        self.assertIn('<figure class="place-locator"><svg class="place-map"', parish)
        self.assertIn('href="../assets/world.svg"', parish)
        self.assertIn('class="broad"', parish)
        self.assertIn(">The parish registers</a>", parish)
        self.assertIn(f'href="../{page("town")}"', parish)
        town = main(self.text(page("town")))
        self.assertNotIn("place-locator", town)
        self.assertIn("Coordinates not supplied", town)
        self.assertIn(">A walk through the town</a>", town)  # a prose reference
        self.assertIn('<a href="../catalogue.html?surname=Vale">Vale</a>', town)

    def test_event_lists_and_dossiers_link_to_the_place_page(self):
        dossier = next(p for p in (self.out / "people").glob("*.html") if 'data-person-id="ada"' in p.read_text()).read_text()
        self.assertIn(f'<a href="../{page("parish")}">Invented Parish, Invented Shire, Fableland</a>', dossier)
        self.assertIn(f'<a href="{page("parish")}">', self.text("timeline.html"))
        places = self.text("places.html")
        self.assertIn(f'<h3><a href="{page("parish")}">', places)
        # A place without a page keeps its entry on the places page, and the place page links back to its entry.
        self.assertIn(f'<li class="place-card" id="{_anchor("quiet")}"><h3>Quiet Hamlet, Fableland</h3>', places)
        self.assertIn(f'href="../places.html#{_anchor("parish")}">Listed with its region</a>', self.text(page("parish")))
        study = next(p for p in (self.out / "studies").glob("*.html") if "A walk through the town" in p.read_text()).read_text()
        self.assertIn(f'<a href="../{page("town")}"', study)

    def test_withheld_records_never_reach_any_file(self):
        for path in self.out.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                for sentinel in ("SECRET-PLACE", "SECRET-CHILD", "SECRET-PERSON", "SECRET-SURNAME", "SECRET-EVENT", "SECRET-STUDY"):
                    self.assertNotIn(sentinel, text, f"{sentinel} in {path}")
        self.assertFalse((self.out / page("secret-place")).exists())
        self.assertFalse((self.out / page("under-secret")).exists())
        self.assertNotIn("1950", main(self.text(page("parish"))))

    def test_a_rebuild_removes_pages_no_longer_needed(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(case(), ProjectConfig(name="Fictional places"), out)
            self.assertTrue((out / page("town")).is_file())
            build_site(case(town_events=False), ProjectConfig(name="Fictional places"), out)
            self.assertFalse((out / page("town")).exists())
            self.assertTrue((out / page("parish")).is_file())
            self.assertIn(f'href="../places.html#{_anchor("town")}"', (out / page("parish")).read_text())
            self.assertEqual([], check_site(out)["broken"])


class BusyPlaceTests(unittest.TestCase):
    """A place with hundreds of people and sub-places stays one small page."""

    def test_lists_are_capped_and_the_page_stays_small(self):
        people, subs = PLACE_LIST_LIMIT + 150, PLACE_LIST_LIMIT + 60
        c = ResearchCase("fictional-busy", "Fictional busy place")
        records = [Place("city", "Busy City, Inventia", latitude=10.0, longitude=20.0, sensitivity=A.PUBLIC)]
        for n in range(people):
            records += [person(f"p{n:04d}", f"Person {n:04d} Fable{n % 30}", f"Fable{n % 30}", [f"p{n:04d}-b"]),
                        Event(f"p{n:04d}-b", "birth", date=str(1700 + n), place_id="city", participant_ids=[f"p{n:04d}"], sensitivity=A.PUBLIC)]
        records += [Place(f"ward{n:04d}", f"Ward {n:04d}, Busy City, Inventia", parent_id="city", sensitivity=A.PUBLIC) for n in range(subs)]
        c.add_many(records)
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(c, ProjectConfig(name="Fictional busy place"), out)
            html = (out / page("city")).read_text()
            self.assertLess(len(html.encode("utf-8")), 100_000)
            body = main(html)
            listed = re.findall(r'<a href="\.\./people/[^"]+">Person (\d{4})', body)
            self.assertEqual(listed, sorted(listed))  # date order
            self.assertLessEqual(len(listed), PLACE_LIST_LIMIT)
            self.assertIn(f"and {people - len(listed):,} more events", body)  # one event a person here
            self.assertIn("and ", body.split("<h2>Places within it</h2>", 1)[1].split("<h2>", 1)[0])
            self.assertIn("more places", body)
            self.assertIn("<h2>Surnames recorded here</h2>", body)
            self.assertIn('Fable0</a> <span class="meta">(12)</span>', body)
            for path in (out / "places").glob("pl-*.html"):
                self.assertLess(path.stat().st_size, 100_000, path)
            self.assertEqual([], check_site(out)["broken"])


if __name__ == "__main__":
    unittest.main()
