"""Opt-in browser contract: the places map filters its markers and clusters close ones."""
from __future__ import annotations

from functools import partial
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urljoin
from urllib.parse import urlsplit

from genealogy.case import CaseStore
from genealogy.config import ProjectConfig
from genealogy.models import AccessLevel, Event, LivingStatus, Name, Person
from genealogy.site import build_site
from test_browser_site import ROOT, QuietHandler  # tests/ is on the path under unittest discovery


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1',
                     'Run make browser-check with the browser extra installed')
class BrowserMapFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        from test_scale import PEOPLE, large_case
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        config = ProjectConfig.load(ROOT / 'examples/demo/genealogy.toml')
        config.names = {'variants': {'Hale': ['Hayle']}}
        config.validate()
        case = CaseStore(ROOT / 'examples/demo/cases').load(config.default_case)
        # A fictional variant spelling with an event at a mapped place: counted with the Hale family.
        case.add_many([Person('person:43', names=[Name('Iona Hayle', surname='Hayle')], living=LivingStatus.DECEASED,
                              event_ids=['person:43-birth'], sensitivity=AccessLevel.PUBLIC),
                       Event('person:43-birth', 'birth', date='1851', place_id='place:willow', participant_ids=['person:43'],
                             sensitivity=AccessLevel.PUBLIC)])
        build_site(case, config, cls.root / 'demo')
        cls.located = PEOPLE // 2  # every other place in the large fixture has coordinates
        build_site(large_case(), ProjectConfig(name='Fictional large tree'), cls.root / 'large')
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(cls.root)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}/'
        cls.pw = sync_playwright().start()
        executable = os.environ.get('GENEALOGY_BROWSER_EXECUTABLE')
        cls.browser = cls.pw.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 1000})
        self.page = self.context.new_page()
        self.errors, self.external = [], []
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        def route(request):
            if urlsplit(request.request.url).hostname not in ('127.0.0.1', None):
                self.external.append(request.request.url)
                request.abort()
            else:
                request.continue_()
        self.page.route('**/*', route)

    def tearDown(self):
        self.context.close()
        self.assertEqual([], self.errors, 'Browser runtime errors')
        self.assertEqual([], self.external, 'Public site must work without outside requests')

    def status(self):
        return self.page.locator('#map-output [role="status"]').inner_text()

    def visible_markers(self):
        """Every place the map draws, counted once: a single marker counts 1, a cluster its badge."""
        singles = self.page.locator('#map-output .map-marker:not(.map-cluster) .map-point:visible').count()
        badges = [int(n) for n in self.page.locator('#map-output .map-cluster-count').all_text_contents()]
        return singles, badges

    def axe(self):
        self.page.add_script_tag(content=Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8'))
        return self.page.evaluate("async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                                  "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                                  ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")

    def test_demo_filters_count_places_and_events(self):
        self.page.goto(self.base + 'demo/places.html', wait_until='networkidle')
        self.assertEqual('3 of 3 places shown · 95 events', self.status())
        kind = self.page.get_by_label('Event type')
        self.assertEqual(['All event types', 'birth', 'death', 'marriage'], kind.locator('option').all_inner_texts())
        kind.select_option('marriage')
        self.assertEqual('3 of 3 places shown · 10 events', self.status())
        kind.select_option('')
        self.page.get_by_label('Event year from').fill('1808')
        self.page.get_by_label('Event year to').fill('1808')
        self.assertEqual('1 of 3 places shown · 2 events', self.status())  # a death and a marriage at Willowmere
        self.page.get_by_label('Event year from').fill('')
        self.page.get_by_label('Event year to').fill('')
        # The surname filter counts a variant spelling under its canonical surname.
        surname = self.page.get_by_label('Surname')
        self.assertIn('Hale (3 places, incl. Hayle)', surname.locator('option').all_inner_texts())
        surname.select_option('Hale')
        self.assertEqual('3 of 3 places shown · 11 events', self.status())
        self.page.get_by_role('searchbox', name='Search places').fill('willow')
        self.assertEqual('1 of 3 places shown · 5 events', self.status())
        self.assertEqual((1, []), self.visible_markers())
        self.page.locator('#map-output .map-point:visible').focus()
        self.assertEqual('Willowmere (fictional) · 5 of 33 recorded events match the filters · 55.95, -3.19 · located to settlement level',
                         self.page.locator('.map-caption').inner_text())
        self.page.get_by_role('searchbox', name='Search places').fill('no-such-synthetic-place')
        self.assertEqual('0 of 3 places shown · 0 events', self.status())
        self.assertEqual((0, []), self.visible_markers())

    def test_demo_cluster_lists_its_places_and_splits_when_framed(self):
        self.page.goto(self.base + 'demo/places.html', wait_until='networkidle')
        # The map opens framed on its places, so the three fictional places are drawn apart.
        self.assertEqual((3, []), self.visible_markers())
        self.page.locator('[data-map-world]').click()
        # They lie within a few pixels of each other at world zoom.
        self.assertEqual((0, [3]), self.visible_markers())
        cluster = self.page.locator('.map-cluster-point')
        self.assertEqual('3 places: Lanternford (fictional); Reedhaven (fictional); Willowmere (fictional)', cluster.get_attribute('aria-label'))
        self.assertEqual(cluster.get_attribute('aria-label'), cluster.locator('title').text_content())
        cluster.focus()
        self.assertIn('3 places close together at this zoom · 95 events', self.page.locator('.map-caption').inner_text())
        links = self.page.locator('.map-cluster-places a')
        self.assertEqual(['Lanternford (fictional)', 'Reedhaven (fictional)', 'Willowmere (fictional)'], links.all_inner_texts())
        for href in [links.nth(i).get_attribute('href') for i in range(3)]:
            # A place with events links to its own page.
            self.assertRegex(href, r'^places/pl-[0-9a-f]{64}\.html$')
            self.assertEqual(200, self.page.request.get(urljoin(self.page.url, href)).status, href)
        self.page.locator('[data-map-fit]').click()
        self.assertEqual((3, []), self.visible_markers())
        # The list described a cluster that has now split, so it is withdrawn.
        self.assertTrue(self.page.locator('.map-cluster-places').is_hidden())
        self.assertEqual('Select a marker to inspect its recorded place.', self.page.locator('.map-caption').inner_text())
        self.page.locator('[data-map-world]').click()
        self.assertEqual((0, [3]), self.visible_markers())
        self.page.locator('.map-cluster-point').press('Enter')
        links.first.click()
        self.assertTrue(self.page.locator('h1').inner_text().startswith('Lanternford'))

    def test_large_site_clusters_at_world_zoom_and_splits_when_zoomed_in(self):
        self.page.goto(self.base + 'large/places.html', wait_until='networkidle')
        self.assertEqual(f'{self.located} of {self.located} places shown · {self.located} events', self.status())
        # Every located place keeps its own marker in the page; merged ones are hidden behind their cluster.
        self.assertEqual(self.located, self.page.locator('#map-output .map-point').count())
        self.page.locator('[data-map-world]').click()  # the map opens framed on the places; start from the world
        singles, world = self.visible_markers()
        self.assertGreaterEqual(len(world), 1)
        self.assertEqual(self.located, singles + sum(world))
        for _ in range(8):
            self.page.get_by_role('button', name='Zoom map in').click()
        singles, zoomed = self.visible_markers()
        self.assertGreater(len(zoomed), len(world))
        self.assertLess(max(zoomed), max(world))
        self.assertEqual(self.located, singles + sum(zoomed))
        # Places with identical coordinates stay together however far the map zooms.
        positions = {(40 + n % 20, -5 + n % 30) for n in range(2 * self.located) if n % 2}  # as large_case() places them
        self.assertEqual(len(positions), singles + len(zoomed))
        # Filters regroup the markers; the event types offered are those at mapped places.
        self.assertEqual(['All event types', 'birth'], self.page.get_by_label('Event type').locator('option').all_inner_texts())
        self.assertEqual(['All surnames', f'Fable ({self.located} places)'], self.page.get_by_label('Surname').locator('option').all_inner_texts())
        self.page.get_by_label('Event year from').fill('1700')
        self.page.get_by_label('Event year to').fill('1709')
        expected = sum(1 for n in range(2 * self.located) if n % 2 and n % 150 < 10)
        self.assertEqual(f'{expected} of {self.located} places shown · {expected} events', self.status())
        singles, filtered = self.visible_markers()
        self.assertEqual(expected, singles + sum(filtered))
        self.page.get_by_role('searchbox', name='Search places').fill('Town 0001')
        self.assertEqual(f'1 of {self.located} places shown · 1 event', self.status())
        # A cluster's places link to the region pages that list them.
        self.page.get_by_role('searchbox', name='Search places').fill('')
        self.page.get_by_label('Event year from').fill('')
        self.page.get_by_label('Event year to').fill('')
        self.page.locator('[data-map-world]').click()
        self.page.locator('.map-cluster-point').first.focus()
        link = self.page.locator('.map-cluster-places a').first
        self.assertRegex(link.get_attribute('href'), r'^places/pl-[0-9a-f]{64}\.html$')
        name = link.inner_text()
        link.click()
        self.assertEqual(name, self.page.locator('h1').inner_text())

    def test_map_toolbar_wraps_and_passes_axe_at_both_widths(self):
        for width in (1440, 390):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for site in ('demo', 'large'):
                with self.subTest(width=width, site=site):
                    self.page.goto(self.base + f'{site}/places.html', wait_until='networkidle')
                    self.page.locator('[data-map-world]').click()  # at world zoom the places cluster
                    self.page.locator('.map-cluster-point').first.focus()  # the cluster's place list is part of what axe checks
                    self.assertTrue(self.page.locator('.map-cluster-places').is_visible())
                    self.assertTrue(self.page.locator('.map-filters').is_visible())
                    self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
                    if width == 390:  # the toolbar wraps onto several rows
                        tops = self.page.locator('.map-filters > label').evaluate_all('ns => ns.map(n => n.getBoundingClientRect().top)')
                        self.assertGreater(len(set(round(t) for t in tops)), 1)
                    if os.environ.get('GENEALOGY_AXE_PATH'):
                        self.assertEqual([], self.axe())


if __name__ == '__main__':
    unittest.main()
