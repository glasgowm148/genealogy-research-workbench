"""Opt-in browser contract: the places page filters its cards by region and by place or surname; a place page sorts its events by year."""
from __future__ import annotations

from functools import partial
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urlsplit

from genealogy.case import CaseStore
from genealogy.config import ProjectConfig
from genealogy.site import PLACE_CARDS, _key, build_site
from test_browser_site import ROOT, QuietHandler  # tests/ is on the path under unittest discovery


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1',
                     'Run make browser-check with the browser extra installed')
class BrowserPlaceCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        from test_scale import COUNTRIES, PEOPLE, large_case
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        config = ProjectConfig.load(ROOT / 'examples/demo/genealogy.toml')
        config.names = {'variants': {'Hale': ['Hayle']}}
        config.validate()
        build_site(CaseStore(ROOT / 'examples/demo/cases').load(config.default_case), config, cls.root / 'demo')
        build_site(large_case(), ProjectConfig(name='Fictional large tree'), cls.root / 'large')
        cls.places = PEOPLE  # one place a person in the large fixture
        cls.inventia = sum(1 for n in range(PEOPLE) if n % 50 and COUNTRIES[n % 3] == 'Inventia')
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
        return self.page.locator('#place-count').inner_text()

    def shown(self):
        return self.page.locator('.place-card:visible h3').all_inner_texts()

    def axe(self):
        self.page.add_script_tag(content=Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8'))
        return self.page.evaluate("async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                                  "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                                  ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")

    def test_demo_cards_filter_by_place_or_any_spelling_of_a_surname(self):
        self.page.goto(self.base + 'demo/places.html', wait_until='networkidle')
        self.assertEqual('3 places', self.status())
        self.assertEqual(['Lanternford (fictional)', 'Reedhaven (fictional)', 'Willowmere (fictional)'], self.shown())
        # One region only: no region menu to choose from.
        self.assertEqual(0, self.page.get_by_label('Region').count())
        search = self.page.get_by_role('searchbox', name='Find a place')
        search.fill('willow')
        self.assertEqual('1 of 3 places', self.status())
        self.assertEqual(['Willowmere (fictional)'], self.shown())
        self.assertTrue(self.page.locator('[data-place-cards]').is_hidden())
        card = self.page.locator('.place-card:visible')
        self.assertIn('28 people · 32 events · 1755–1899', card.inner_text())  # as the card written into the page says
        written = self.page.locator('[data-place-cards] .place-card', has_text='Willowmere').text_content()
        self.assertEqual(written, card.text_content())
        # A variant spelling finds the places of the whole surname group.
        search.fill('Hayle')
        self.assertEqual('3 of 3 places', self.status())
        search.fill('no-such-synthetic-place')
        self.assertEqual('0 of 3 places', self.status())
        self.assertEqual([], self.shown())
        search.fill('')
        self.assertEqual('3 places', self.status())
        self.assertTrue(self.page.locator('[data-place-cards]').is_visible())
        search.fill('reed')
        self.page.locator('.place-card:visible h3 a').click()
        self.page.wait_for_url('**/places/pl-*.html')
        self.assertEqual('Reedhaven (fictional)', self.page.locator('h1').inner_text())

    def test_large_site_region_menu_counts_and_caps_the_cards(self):
        self.page.goto(self.base + 'large/places.html', wait_until='networkidle')
        self.assertEqual(f'{self.places:,} places · the {PLACE_CARDS} with the most people shown', self.status())
        self.assertEqual(PLACE_CARDS, len(self.shown()))
        region = self.page.get_by_label('Region')
        self.assertIn(f'Inventia ({self.inventia})', region.locator('option').all_inner_texts())
        self.assertEqual('Places without a broader jurisdiction (8)', region.locator('option').all_inner_texts()[-1])
        region.select_option('Inventia')
        self.assertEqual(f'{self.inventia} of {self.places:,} places · first {PLACE_CARDS} shown', self.status())
        self.assertEqual(PLACE_CARDS, len(self.shown()))
        self.assertTrue(all(name.endswith(', Inventia') for name in self.shown()))
        self.page.get_by_role('searchbox', name='Find a place').fill('Town 0007')
        self.assertEqual(f'1 of {self.places:,} places', self.status())
        link = self.page.locator('.place-card:visible h3 a')
        self.assertEqual(f'places/pl-{_key("pl0007")}.html', link.get_attribute('href'))
        # The region menu and the search combine.
        region.select_option('Places without a broader jurisdiction')
        self.page.get_by_role('searchbox', name='Find a place').fill('Hamlet 0050')
        self.assertEqual(f'1 of {self.places:,} places', self.status())
        link.click()
        self.page.wait_for_url('**/places/pl-*.html')
        self.assertEqual('Hamlet 0050', self.page.locator('h1').inner_text())

    def test_place_page_events_sort_by_year(self):
        self.page.goto(self.base + 'demo/places.html', wait_until='networkidle')
        self.page.get_by_role('link', name='Reedhaven (fictional)').first.click()
        self.page.wait_for_url('**/places/pl-*.html')
        header = self.page.locator('table[data-place-events] th').first
        first_year = lambda: self.page.locator('table[data-place-events] tbody tr').first.locator('td').first.inner_text()
        self.assertEqual('ascending', header.get_attribute('aria-sort'))
        self.assertEqual('1756', first_year())
        header.get_by_role('button', name='Year').click()
        self.assertEqual('descending', header.get_attribute('aria-sort'))
        self.assertEqual('1899', first_year())
        header.get_by_role('button', name='Year').click()
        self.assertEqual('ascending', header.get_attribute('aria-sort'))
        self.assertEqual('1756', first_year())

    def test_cards_without_javascript(self):
        context = self.browser.new_context(java_script_enabled=False)
        try:
            page = context.new_page()
            page.goto(self.base + 'demo/places.html')
            self.assertEqual(3, page.locator('.place-card').count())
            self.assertEqual(0, page.locator('.place-filter input').count())
            self.assertEqual('3 places', page.locator('#place-count').inner_text())
            page.goto(self.base + 'large/places/fableland.html')
            self.assertEqual(100, page.locator('.place-card').count())
        finally:
            context.close()

    def test_both_widths_pass_axe_without_sideways_scrolling(self):
        for width in (1440, 390):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for path, fill in (('demo/places.html', 'willow'), ('large/places.html', 'Town 00'), ('large/places/fableland.html', None)):
                with self.subTest(width=width, path=path):
                    self.page.goto(self.base + path, wait_until='networkidle')
                    if fill:
                        self.page.get_by_role('searchbox', name='Find a place').fill(fill)
                        self.assertGreater(len(self.shown()), 0)
                    self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
                    if os.environ.get('GENEALOGY_AXE_PATH'):
                        self.assertEqual([], self.axe())
            self.page.goto(self.base + 'demo/places.html', wait_until='networkidle')
            self.page.locator('.place-card h3 a').first.click()
            self.page.wait_for_url('**/places/pl-*.html')
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
            if os.environ.get('GENEALOGY_AXE_PATH'):
                self.assertEqual([], self.axe())


if __name__ == '__main__':
    unittest.main()
