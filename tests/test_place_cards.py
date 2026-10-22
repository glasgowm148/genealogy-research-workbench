"""Places are listed as summary cards; a place's events are on its own page as a table."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Citation, Claim, Event, Evidence, LivingStatus as L, Name, Person, Place, Source)
from genealogy.site import PLACE_CARD_SURNAMES, PLACE_CARDS, PLACE_LIST_LIMIT, UNPLACED_REGION, _anchor, _key, build_site
from genealogy.sitecheck import check_site


def page(pid: str) -> str:
    return f"places/pl-{_key(pid)}.html"


def main(html: str) -> str:
    return html.split('<main id="main-content">', 1)[1].split("</main>", 1)[0]


def person(pid: str, name: str, surname: str, events: list[str], sensitivity=A.PUBLIC) -> Person:
    return Person(pid, names=[Name(name, surname=surname)], living=L.DECEASED, event_ids=events, sensitivity=sensitivity)


def case() -> ResearchCase:
    c = ResearchCase("fictional-cards", "Fictional cards")
    records = [
        Place("mill", "Mill End, Fableland", latitude=55.9, longitude=-4.2, precision="parish", sensitivity=A.PUBLIC),
        Place("ford", "Ford Green, Fableland", sensitivity=A.PUBLIC),
        Place("quay", "Quay Row, Inventia", latitude=10.0, longitude=20.0, precision="exact", sensitivity=A.PUBLIC),
        Place("lonely", "Lonely Croft", sensitivity=A.PUBLIC),  # no events: a card without a page
        Source("register", "Invented parish register", "register", sensitivity=A.PUBLIC),
        Source("secret-source", "SECRET-SOURCE ledger", "register", sensitivity=A.PRIVATE),
        Citation("register-1", "register", locator="entry 1", sensitivity=A.PUBLIC),
        Citation("secret-cit", "secret-source", sensitivity=A.PRIVATE),
        person("hidden", "SECRET-PERSON Shade", "SECRET-SURNAME", ["hidden-b"], A.PRIVATE),
        Event("hidden-b", "birth", date="1950", place_id="mill", participant_ids=["hidden"], sensitivity=A.PUBLIC),
        # The marriage's own claim cites the register; nothing else is matched to it.
        Claim("marriage-claim", "ada-m", "documented-in", "register", citation_ids=["register-1"], sensitivity=A.PUBLIC),
        Claim("secret-claim", "ada-m", "documented-in", "secret", citation_ids=["secret-cit"], sensitivity=A.PRIVATE),
        Evidence("marriage-ev", "marriage-claim", "register-1", "The entry names both.", sensitivity=A.PUBLIC),
        Event("ada-m", "marriage", date="1820", place_id="mill", participant_ids=["ada", "bram"], description="By banns",
              sensitivity=A.PUBLIC),
    ]
    # Six surnames at Mill End, one more than a card names; Ford Green has one person.
    for n, surname in enumerate(("Fable", "Fable", "Fable", "Vale", "Vale", "Ash", "Birch", "Cole", "Dune")):
        pid = "ada" if n == 0 else "bram" if n == 1 else f"p{n}"
        records += [person(pid, f"Person {n} {surname}", surname, [f"{pid}-b"]),
                    Event(f"{pid}-b", "birth", date=f"{1790 + n}", place_id="mill", participant_ids=[pid], sensitivity=A.PUBLIC)]
    records += [person("cora", "Cora Wren", "Wren", ["cora-b"]),
                Event("cora-b", "birth", date="ABT 1805", place_id="ford", participant_ids=["cora"], sensitivity=A.PUBLIC)]
    c.add_many(records)
    return c


class PlaceCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.out = Path(cls.directory.name)
        cls.case = case()
        assert validate_case(cls.case) == [], validate_case(cls.case)
        build_site(cls.case, ProjectConfig(name="Fictional cards"), cls.out)
        cls.places = main((cls.out / "places.html").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def card(self, pid: str) -> str:
        return re.search(rf'<li class="place-card" id="{_anchor(pid)}">(.*?)</li>', self.places)[1]

    def test_each_place_has_a_summary_card_and_no_event_list(self):
        mill = self.card("mill")
        self.assertIn(f'<h3><a href="{page("mill")}">Mill End, Fableland</a></h3>', mill)
        self.assertIn('<p class="place-facts">Fableland · 9 people · 10 events · 1790–1820</p>', mill)  # the withheld person is not counted
        self.assertIn('<p class="meta">55.9, -4.2 · located to parish level</p>', mill)
        pills = re.findall(r'<a class="pill" href="catalogue.html\?surname=([^"]+)">', mill)
        self.assertEqual(["Fable", "Vale", "Ash", "Birch", "Cole"], pills)  # most people first, then by name
        self.assertEqual(PLACE_CARD_SURNAMES, len(pills))
        self.assertIn('<span class="meta">and 1 more</span>', mill)
        self.assertIn("Fableland · 1 person · 1 event · 1805", self.card("ford"))
        self.assertIn("Coordinates not supplied", self.card("ford"))
        self.assertIn("exact location", self.card("quay"))
        # A place without a broader jurisdiction names none; a place without events has no page to link.
        self.assertIn('<h3>Lonely Croft</h3><p class="place-facts">No public events recorded</p>', self.card("lonely"))
        # The events themselves are on the place pages, not here.
        self.assertNotIn("data-event-id", self.places)
        self.assertNotIn("people/p-", self.places)
        self.assertNotIn("By banns", self.places)

    def test_busiest_places_first_within_a_region_and_the_filter_hooks(self):
        fableland = self.places.split(f'id="{_anchor("region:Fableland")}"', 1)[1].split("</section>", 1)[0]
        self.assertLess(fableland.index("Mill End"), fableland.index("Ford Green"))
        self.assertIn(f'<div class="place-filter" data-place-filter data-unplaced="{UNPLACED_REGION}"></div>', self.places)
        self.assertIn('<p class="result-count" id="place-count" role="status">4 places</p>', self.places)
        self.assertIn('<p class="eyebrow">Towns, parishes and mapped places</p><h1>Places</h1><p>4 places recorded', self.places)
        self.assertLess(self.places.index("data-place-filter"), self.places.index("data-place-cards"))
        # The script can link every place: the located ones for the map, the others for the filter.
        data = json.loads((self.out / "data/site-data.js").read_text().split("=", 1)[1].rstrip().rstrip(";"))
        self.assertEqual({"mill", "quay"}, set(data["site"]["place_urls"]))
        self.assertEqual({"ford": page("ford"), "lonely": "places.html#" + _anchor("lonely")}, data["site"]["place_routes"])

    def test_the_place_page_lists_its_events_as_a_table(self):
        mill = main((self.out / page("mill")).read_text())
        self.assertNotIn("People recorded here", mill)
        self.assertIn('<h2 id="place-events">Events recorded here</h2>', mill)
        self.assertIn('<table class="place-events" data-place-events>', mill)
        rows = re.findall(r'<tr data-year="(\d*)">(.*?)</tr>', mill)
        self.assertEqual([str(1790 + n) for n in range(9)] + ["1820"], [year for year, _ in rows])  # date order
        marriage = rows[-1][1]
        self.assertIn('<td>Marriage<span class="meta">By banns</span></td>', marriage)
        self.assertEqual(["Person 0 Fable", "Person 1 Fable"], re.findall(r'<a href="\.\./people/[^"]+">([^<]+)</a>', marriage))
        self.assertIn(f'<a href="../sources.html#{_anchor("register")}">Invented parish register</a>', marriage)
        self.assertIn('<span class="meta">None linked</span>', rows[0][1])
        ford = main((self.out / page("ford")).read_text())
        self.assertIn('<tr data-year="1805"><td>c. 1805</td><td>Birth</td>', ford)
        self.assertEqual([], check_site(self.out)["broken"])

    def test_withheld_records_never_reach_any_file(self):
        for path in self.out.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                for sentinel in ("SECRET-PERSON", "SECRET-SURNAME", "SECRET-SOURCE"):
                    self.assertNotIn(sentinel, text, f"{sentinel} in {path}")
        self.assertNotIn("1950", main((self.out / page("mill")).read_text()))


class ManyEventsFewPlacesTests(unittest.TestCase):
    """A site of many events at a few places keeps its places page small: the events are on the place pages."""

    def test_pages_stay_small(self):
        people = 1200
        c = ResearchCase("fictional-crowded", "Fictional crowded places")
        records = [Place("a", "Crowded Town, Fableland", latitude=1.0, longitude=2.0, sensitivity=A.PUBLIC),
                   Place("b", "Busy Port, Inventia", sensitivity=A.PUBLIC)]
        for n in range(people):
            pid = f"p{n:04d}"
            records += [person(pid, f"Person {n:04d} Fable{n % 40}", f"Fable{n % 40}", [f"{pid}-b", f"{pid}-d"]),
                        Event(f"{pid}-b", "birth", date=str(1700 + n % 200), place_id="ab"[n % 2], participant_ids=[pid],
                              description="A long invented note about the entry and its witnesses.", sensitivity=A.PUBLIC),
                        Event(f"{pid}-d", "death", date=str(1760 + n % 200), place_id="a", participant_ids=[pid], sensitivity=A.PUBLIC)]
        c.add_many(records)
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(c, ProjectConfig(name="Fictional crowded places"), out)
            for path in out.rglob("*.html"):
                self.assertLess(path.stat().st_size, 100_000, path)
            places = main((out / "places.html").read_text())
            self.assertIn(f"Fableland · {people:,} people · {people * 3 // 2:,} events · 1700–1959", places)
            town = main((out / page("a")).read_text())
            self.assertLessEqual(town.count("<tr data-year="), PLACE_LIST_LIMIT)
            self.assertRegex(town, r"and [\d,]+ more events")
            self.assertEqual([], check_site(out)["broken"])


class ManyPlacesTests(unittest.TestCase):
    """Past PLACE_CARDS places the places page opens with the busiest; every card is on its region's pages."""

    def test_busiest_cards_and_region_pages(self):
        total = PLACE_CARDS + 30
        c = ResearchCase("fictional-many-places", "Fictional many places")
        records = []
        for n in range(total):
            records.append(Place(f"pl{n:04d}", f"Spot {n:04d}, {'Fableland' if n % 2 else 'Inventia'}", sensitivity=A.PUBLIC))
            # Spot 0007 has the most people, then Spot 0003; the rest have one each or none.
            for k in range(5 if n == 7 else 3 if n == 3 else 1 if n % 3 else 0):
                pid = f"p{n:04d}-{k}"
                records += [person(pid, f"Person {n:04d}-{k} Fable", "Fable", [f"{pid}-b"]),
                            Event(f"{pid}-b", "birth", date=str(1800 + n), place_id=f"pl{n:04d}", participant_ids=[pid], sensitivity=A.PUBLIC)]
        c.add_many(records)
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(c, ProjectConfig(name="Fictional many places"), out)
            places = main((out / "places.html").read_text())
            self.assertIn("<h2>Places with the most people</h2>", places)
            names = re.findall(r'<li class="place-card"><h3>(?:<a href="[^"]+">)?(Spot \d{4})', places)
            self.assertEqual(PLACE_CARDS, len(names))
            self.assertEqual(["Spot 0007", "Spot 0003"], names[:2])
            self.assertNotIn('class="place-card" id=', places)  # the anchors are on the region pages
            self.assertIn(f"{total:,} places · the {PLACE_CARDS:,} with the most people shown", places)
            self.assertIn('<a href="places/fableland.html">Fableland</a>', places)
            region = main((out / "places/fableland.html").read_text())
            self.assertIn(f'<li class="place-card" id="{_anchor("pl0007")}"><h3><a href="../{page("pl0007")}">Spot 0007, Fableland</a></h3>', region)
            self.assertIn(f'<li class="place-card" id="{_anchor("pl0009")}"><h3>Spot 0009, Fableland</h3>', region)  # no events, no page
            self.assertEqual([], check_site(out)["broken"])


if __name__ == "__main__":
    unittest.main()
