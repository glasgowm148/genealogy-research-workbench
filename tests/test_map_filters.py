"""The places map links each located place to where it is listed, and never a withheld one."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import AccessLevel as A, Event, LivingStatus as L, Name, Person, Place
from genealogy.site import _anchor, _key, build_site
from test_scale import PEOPLE, large_case  # tests/ is on the path under unittest discovery


def shared_data(out: Path) -> dict:
    script = (out / "data/site-data.js").read_text()
    return json.loads(script[script.index("{"):script.rindex("}") + 1])


class MapPlaceLinkTests(unittest.TestCase):
    def test_located_public_places_link_to_their_entries_and_a_withheld_place_is_in_no_output(self):
        case = ResearchCase("fictional-map", "Fictional map")
        case.add_many([
            Place("pl1", "Fableford, Inventia", latitude=51.5, longitude=-1.2),
            Place("pl2", "Unmapped Hollow, Inventia"),
            # Withheld, with coordinates: neither it nor its event may reach the map data or any page.
            Place("pl-secret", "SECRET-PLACE Hollow", latitude=52.0, longitude=-1.0, sensitivity=A.PRIVATE),
            Person("p0001", names=[Name("Ada Fable", surname="Fable")], living=L.DECEASED, event_ids=["p0001-b"], sensitivity=A.PUBLIC),
            Event("p0001-b", "birth", date="1801", place_id="pl1", participant_ids=["p0001"], sensitivity=A.PUBLIC),
            Event("p0001-x", "residence", date="1830", place_id="pl-secret", participant_ids=["p0001"], description="SECRET-PLACE residence",
                  sensitivity=A.PRIVATE),
        ])
        self.assertEqual([], validate_case(case))
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(case, ProjectConfig(name="Fictional map"), out)
            urls = shared_data(out)["site"]["place_urls"]
            # A place with events has a page of its own; the map links there.
            self.assertEqual({"pl1": f"places/pl-{_key('pl1')}.html"}, urls)
            self.assertTrue((out / urls["pl1"]).is_file())
            for path in out.rglob("*"):
                if path.is_file():
                    text = path.read_text(errors="replace")
                    self.assertNotIn("SECRET-PLACE", text, path)
                    self.assertNotIn("pl-secret", text, path)

    def test_a_large_site_links_each_place_to_its_region_page(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(large_case(), ProjectConfig(name="Fictional large tree"), out)
            urls = shared_data(out)["site"]["place_urls"]
            self.assertEqual(PEOPLE // 2, len(urls))  # every other fixture place has coordinates
            for pid, url in urls.items():
                page, _, anchor = url.partition("#")
                self.assertTrue(page.startswith("places/"), url)
                if anchor:  # a place without a page of its own keeps its anchor on the region page
                    self.assertEqual(_anchor(pid), anchor)
                    self.assertIn(f'id="{anchor}"', (out / page).read_text(), url)
                else:
                    self.assertEqual(f"places/pl-{_key(pid)}.html", page)
                    self.assertTrue((out / page).is_file(), url)


if __name__ == "__main__":
    unittest.main()
