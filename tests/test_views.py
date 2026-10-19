from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from genealogy.case import ResearchCase
from genealogy.config import ProjectConfig
from genealogy.exports import build_public_views, configured_views
from genealogy.models import AccessLevel, Event, Finding, LivingStatus, Person, Place


class ViewTests(unittest.TestCase):
    def case(self) -> ResearchCase:
        case = ResearchCase(id="view-case", title="Private case title")
        case.add(Person(
            id="person-1",
            names=[],
            living=LivingStatus.DECEASED,
            sensitivity=AccessLevel.PUBLIC,
        ))
        case.add(Place(
            id="place-1", name="North Quay", latitude=52.5, longitude=-3.2,
            sensitivity=AccessLevel.PUBLIC,
        ))
        case.add(Event(
            id="event-1", kind="residence", date="1888", place_id="place-1",
            participant_ids=["person-1"], description="Harbour register </script>",
            sensitivity=AccessLevel.PUBLIC,
        ))
        case.add(Finding(
            id="finding-1", conclusion="The residence is documented.",
            related_ids=["person-1"], sensitivity=AccessLevel.PUBLIC,
        ))
        return case

    def test_builds_configured_offline_html_views(self) -> None:
        config = ProjectConfig(
            name="Fictional coastal study",
            catalogue={"format": "html", "output": "catalogue/index.html"},
            timelines={"format": "html", "output": "timeline/index.html"},
            maps={"format": "html", "output": "map/index.html"},
        )
        with tempfile.TemporaryDirectory() as temporary:
            paths = build_public_views(self.case(), config, Path(temporary))
            catalogue = paths["catalogue"].read_text(encoding="utf-8")
            timeline = paths["timelines"].read_text(encoding="utf-8")
            map_html = paths["maps"].read_text(encoding="utf-8")
        self.assertIn("catalogue-filter", catalogue)
        self.assertIn("Research questions", catalogue)
        self.assertIn("timeline-data", timeline)
        self.assertNotIn("Harbour register </script>", timeline)
        self.assertIn("Harbour register &lt;/script&gt;", timeline)
        self.assertIn("map-data", map_html)
        self.assertIn("North Quay", map_html)

    def test_json_views_and_invalid_formats(self) -> None:
        project = {"project": {"title": "Synthetic"}, "people": [], "events": [], "places": []}
        views = configured_views(
            project,
            ProjectConfig(
                catalogue={"format": "json"}, timelines={"format": "json"},
                maps={"format": "geojson"},
            ),
        )
        payloads = {section: json.loads(content) for section, _, content in views}
        self.assertIn("counts", payloads["catalogue"])
        self.assertEqual(payloads["timelines"], [])
        self.assertEqual(payloads["maps"]["type"], "FeatureCollection")
        with self.assertRaisesRegex(ValueError, "unsupported catalogue.format"):
            configured_views(project, ProjectConfig(catalogue={"format": "pdf"}))


if __name__ == "__main__":
    unittest.main()
