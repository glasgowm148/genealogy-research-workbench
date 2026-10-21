"""The statistics page layout: a KPI panel, chart cards with bars on a track, linked rows and a minimum count for names."""
from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase
from genealogy.config import ProjectConfig
from genealogy.models import AccessLevel as A, ResearchQuestion
from genealogy.site import build_site

from test_statistics import config, person, rows, statistics_case


def kpis(html):
    """(value, label, href) for each figure in the panel, as a reader sees them."""
    panel = html.split('<section class="stat-panel"', 1)[1].split("</section>", 1)[0]
    return [(value, label, href) for href, label, value in re.findall(r'<div><dt><a href="([^"]+)">([^<]+)</a></dt><dd>([^<]+)</dd></div>', panel)]


class StatisticsLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        case = statistics_case()
        case.add_many([ResearchQuestion("q-1", "Where was Ada born?", sensitivity=A.PUBLIC),
                       ResearchQuestion("q-2", "Answered already?", status="answered", sensitivity=A.PUBLIC),
                       ResearchQuestion("q-secret", "SECRET-question", sensitivity=A.PRIVATE)])
        cls.paths = build_site(case, config(), cls.root)
        cls.html = (cls.root / "statistics.html").read_text()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_the_panel_leads_with_six_linked_figures_of_the_public_record(self):
        # Six public links: r-1 documented, r-5 disproved, r-6 and r-7 graded are assessed; r-3 and r-4 are not.
        # The withheld child's link, the private question and the answered one are not counted.
        self.assertEqual([("6", "people", "catalogue.html"), ("11", "events", "timeline.html"), ("3", "places", "places.html"),
                          ("0", "sources", "sources.html"), ("67%", "of 6 family links assessed", "progress.html"),
                          ("1", "open question", "research.html")], kpis(self.html))
        self.assertLess(self.html.index('class="stat-panel"'), self.html.index('class="chart-grid"'))
        self.assertIn('<h2 id="at-a-glance" class="sr-only">At a glance</h2>', self.html)
        for path in self.paths.values():
            if path.suffix in (".html", ".json", ".js"):
                self.assertNotIn("SECRET-", path.read_text(), path)

    def test_each_table_is_a_card_in_the_grid(self):
        grid = self.html.split('<div class="chart-grid">', 1)[1]
        cards = re.findall(r'<section class="chart-card"><h3 id="([a-z-]+)">', grid)
        self.assertEqual(["birth-centuries", "birth-regions", "given-names", "surnames", "families", "places", "migrations", "event-kinds"], cards)
        self.assertEqual(grid.count('<td class="count">'), grid.count('<div class="bar-track" aria-hidden="true">'))  # every row draws on a track
        self.assertEqual(self.html.count('<table class="statistics"'), self.html.count('<section class="chart-card">'))

    def test_row_labels_link_to_a_filtered_view_where_one_exists(self):
        self.assertIn('href="catalogue.html?surname=Vale">Vale</a>', self.html)
        places = self.html.split('aria-labelledby="places"', 1)[1].split("</table>", 1)[0]
        self.assertEqual(3, places.count("<a href="))
        regions = self.html.split('aria-labelledby="birth-regions"', 1)[1].split("</table>", 1)[0]
        self.assertEqual(3, regions.count('<a href="places.html#'))
        # The timeline has no event-type address to link to, so event kinds and centuries stay plain text.
        for key in ("event-kinds", "birth-centuries", "given-names"):
            table = self.html.split(f'aria-labelledby="{key}"', 1)[1].split("</table>", 1)[0]
            self.assertNotIn("<a ", table, key)

    def test_names_borne_once_are_counted_not_listed(self):
        case = ResearchCase("fictional-names", "Fictional names")
        case.add_many([*person("p0001", "Ada Fable"), *person("p0002", "Bram Vale"), *person("p0003", "Ada Vale")])
        with tempfile.TemporaryDirectory() as temp:
            build_site(case, ProjectConfig(name="Names"), Path(temp))
            html = (Path(temp) / "statistics.html").read_text()
        self.assertEqual([(("Ada",), 2)], rows(html, "given-names"))
        self.assertEqual([(("Vale",), 2)], rows(html, "surnames"))
        self.assertIn("1 name recorded once.", html)
        # When no name is shared the card says so instead of drawing an empty table.
        case = ResearchCase("fictional-unique", "Fictional unique")
        case.add_many([*person("p0001", "Ada Fable"), *person("p0002", "Bram Vale")])
        with tempfile.TemporaryDirectory() as temp:
            build_site(case, ProjectConfig(name="Unique"), Path(temp))
            html = (Path(temp) / "statistics.html").read_text()
        card = html.split('<h3 id="given-names">', 1)[1].split("</section>", 1)[0]
        self.assertIn('<p class="empty-state">2 names recorded once; none is shared by two or more people.</p>', card)
        self.assertNotIn('aria-labelledby="given-names"', html)

    def test_an_empty_site_still_shows_the_panel_without_a_grid(self):
        with tempfile.TemporaryDirectory() as temp:
            build_site(ResearchCase("fictional-empty", "Empty"), ProjectConfig(name="Empty"), Path(temp))
            html = (Path(temp) / "statistics.html").read_text()
        self.assertIn(("—", "of 0 family links assessed", "progress.html"), kpis(html))
        self.assertNotIn('class="chart-grid"', html)


if __name__ == "__main__":
    unittest.main()
