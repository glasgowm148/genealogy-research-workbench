"""Opt-in browser contract: installed site, mobile navigation, tools and real uploads."""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urljoin, urlsplit

from genealogy.case import CaseStore
from genealogy.config import ProjectConfig
from genealogy.models import AccessLevel, Event, LivingStatus, Name, Person
from genealogy.server import UploadServer
from genealogy.site import build_site

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1',
                     'Run make browser-check with the browser extra installed')
class BrowserSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        config = ProjectConfig.load(ROOT / 'examples/demo/genealogy.toml')
        # The demo sets no contact; a fictional one adds the corrections page and dossier links.
        config.raw.setdefault('site', {})['contact_email'] = 'corrections@example.invalid'
        # A fictional spelling variant: Iona Hayle is grouped and found with the Hale family.
        config.names = {'variants': {'Hale': ['Hayle', 'Hail']}}
        config.validate()
        case = CaseStore(ROOT / 'examples/demo/cases').load(config.default_case)
        case.add_many(cls.variant_person('person:43', 'Iona Hayle', 'Hayle'))
        build_site(case, config, cls.root / 'nested')
        from test_scale import PEOPLE, large_case  # tests/ is on the path under unittest discovery
        cls.large_people = PEOPLE
        build_site(large_case(), ProjectConfig(name='Fictional large tree'), cls.root / 'large')
        # The same on a large site, whose catalogue rows are built from the shared data.
        variants = large_case()
        variants.add_many(cls.variant_person('p9999', 'Odo Fabel', 'Fabel'))
        build_site(variants, ProjectConfig(name='Fictional large variants', names={'variants': {'Fable': ['Fabel']}}), cls.root / 'large-variants')
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0),
            partial(QuietHandler, directory=str(cls.root)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}/nested/'
        cls.upload = UploadServer(cls.root / 'workspace', port=0)
        cls.upload_thread = threading.Thread(target=cls.upload.serve_forever, daemon=True)
        cls.upload_thread.start()
        cls.pw = sync_playwright().start()
        # Playwright's managed Chromium by default; GENEALOGY_BROWSER_EXECUTABLE
        # selects a locally installed Chromium/Chrome instead.
        executable = os.environ.get('GENEALOGY_BROWSER_EXECUTABLE')
        cls.browser = cls.pw.chromium.launch(headless=True,
            **({'executable_path': executable} if executable else {}))

    @staticmethod
    def variant_person(pid, name, surname):
        return [Person(pid, names=[Name(name, surname=surname)], living=LivingStatus.DECEASED, event_ids=[f'{pid}-birth'],
                       sensitivity=AccessLevel.PUBLIC),
                Event(f'{pid}-birth', 'birth', date='1851', participant_ids=[pid], sensitivity=AccessLevel.PUBLIC)]

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.upload.shutdown()
        cls.upload.server_close()
        cls.thread.join()
        cls.upload_thread.join()
        cls.temp.cleanup()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 1000})
        self.page = self.context.new_page()
        self.errors = []
        self.external = []
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

    def evidence_dossier(self, routes):
        """A dossier whose claims show their records and assessments as a table."""
        return next(r for r in routes if r.startswith('people/') and 'class="evidence-table"' in (self.root / 'nested' / r).read_text())

    def test_routes_images_mobile_and_no_javascript(self):
        dossier = json.loads((self.root / 'nested' / 'data' / 'routes.json').read_text())
        routes = ['index.html', 'catalogue.html', 'tree.html', 'timeline.html', 'places.html',
                  'sources.html', 'research.html', 'compare.html', 'connections.html', 'evidence.html',
                  'studies.html', 'findings.html', 'branches.html', 'sitemap.html', 'corrections.html',
                  next(route for route in dossier if route.startswith('people/')),
                  next(route for route in dossier if route.startswith('studies/')), self.evidence_dossier(dossier)]
        for width in (1440, 390):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for route in routes:
                response = self.page.goto(self.base + route, wait_until='networkidle')
                self.assertEqual(200, response.status, (width, route))
                self.assertEqual(1, self.page.locator('h1').count(), route)
                self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1, route)
            if width == 390:
                self.page.locator('#menu-toggle').click()
                self.assertEqual('true', self.page.locator('#menu-toggle').get_attribute('aria-expanded'))
                self.assertTrue(self.page.locator('.site-sidebar').is_visible())
                self.page.locator('.site-sidebar a[data-view="people"]').click()
                self.assertIn('catalogue.html', self.page.url)
        nojs = self.browser.new_context(java_script_enabled=False)
        try:
            page = nojs.new_page()
            page.goto(self.base + 'catalogue.html')
            self.assertEqual(43, page.locator('[data-person-id]').count())  # the demo's 42 and Iona Hayle
            page.goto(self.base + 'sources.html')
            self.assertEqual(3, page.locator('[data-source-id]').count())
        finally:
            nojs.close()

    def test_offline_file_navigation_surname_filter_and_family_dossier(self):
        site = self.root / 'nested'
        self.page.goto((site / 'catalogue.html').as_uri())
        self.page.locator('.pagination').wait_for()
        surname = self.page.get_by_label('Surname')
        options = surname.locator('option').all_inner_texts()
        self.assertIn('Alder (6)', options)
        surname.select_option('Alder')
        self.assertEqual(6, self.page.locator('[data-person-id]:visible').count())
        self.page.locator('[data-person-id]:visible a').first.click()
        self.assertIn('/people/', self.page.url)
        family = self.page.locator('.family-summary')
        self.assertTrue(family.is_visible())
        self.assertGreater(family.locator('a.evidence-badge').count(), 0)
        family.locator('a.evidence-badge').first.click()
        self.page.wait_for_url('**/evidence.html#*')
        self.page.locator('dt:target').wait_for(state='visible')
        self.page.goto((site / 'branches.html').as_uri())
        self.page.locator('a[href="catalogue.html?surname=Cairn"]').click()
        self.page.locator('.pagination').wait_for()
        self.assertEqual('Cairn', self.page.get_by_label('Surname').input_value())
        self.assertEqual(6, self.page.locator('[data-person-id]:visible').count())
        self.page.goto((site / 'branches.html').as_uri())
        self.page.locator('a[href^="tree.html?person="]').first.click()
        self.page.locator('#tree-output svg').wait_for()
        self.assertEqual('true', self.page.locator('[data-tree-view="family"]').get_attribute('aria-pressed'))
        self.page.set_viewport_size({'width': 390, 'height': 900})
        self.page.go_back()
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 391)

    @unittest.skipUnless(os.environ.get('GENEALOGY_AXE_PATH'), 'set GENEALOGY_AXE_PATH to an axe-core axe.min.js')
    def test_wcag_aa_on_every_page_type_at_both_widths(self):
        axe = Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8')
        routes = json.loads((self.root / 'nested' / 'data' / 'routes.json').read_text())
        pages = [r for r in routes if not r.startswith(('people/', 'studies/'))]
        pages += [next(r for r in routes if r.startswith(prefix)) for prefix in ('people/', 'studies/')]
        self.assertIn('corrections.html', pages)
        pages.append(self.evidence_dossier(routes))
        for width in (1440, 390):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for route in pages:
                with self.subTest(width=width, route=route):
                    self.page.goto(self.base + route, wait_until='networkidle')
                    if route.startswith('people/'):  # the section menu and explore links are part of what axe checks
                        self.assertEqual(1, self.page.locator('nav.page-sections').count(), route)
                        self.assertEqual(1, self.page.locator('p.explore').count(), route)
                    self.page.add_script_tag(content=axe)
                    violations = self.page.evaluate(
                        "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                        "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                        ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
                    self.assertEqual([], violations)

    def test_large_site_menus_fill_from_the_data_and_pass_axe(self):
        large = self.base.replace('/nested/', '/large/')
        for page, menus in (('compare.html', ('[data-compare-a]', '[data-compare-b]')),
                            ('connections.html', ('[data-connection-a]', '[data-connection-b]')), ('tree.html', ('#tree-root',))):
            self.page.goto(large + page, wait_until='networkidle')
            for menu in menus:
                self.assertEqual(self.large_people + 1, self.page.locator(f'{menu} option').count(), page)
        self.page.goto(large + 'compare.html')
        self.page.locator('[data-compare-a]').select_option('p0001')
        self.page.locator('[data-compare-b]').select_option('p0002')
        self.assertIn('Person 0002 Fable', self.page.locator('#compare-result').inner_text())
        self.page.goto(large + 'connections.html')
        self.page.locator('[data-connection-a]').select_option('p0001')
        self.page.locator('[data-connection-b]').select_option('p0003')
        self.assertIn('Person 0003 Fable', self.page.locator('#connection-result').inner_text())
        if os.environ.get('GENEALOGY_AXE_PATH'):
            axe = Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8')
            for route in ('tree.html', 'compare.html', 'research.html', 'sitemap.html', 'findings.html', 'findings/page-1.html',
                          'catalogue.html', 'catalogue/page-2.html', 'timeline.html', 'timeline/1700s.html', 'places.html', 'places/fableland.html',
                          'sources.html', 'sources/page-2.html', 'sources/type-register.html', 'studies.html', 'studies/page-2.html'):
                with self.subTest(route=route):
                    self.page.goto(large + route, wait_until='networkidle')
                    self.page.add_script_tag(content=axe)
                    violations = self.page.evaluate(
                        "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                        "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                        ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
                    self.assertEqual([], violations)
        self.assertEqual([], self.errors)

    def test_large_site_catalogue_and_timeline_search_everyone_from_the_data(self):
        large = self.base.replace('/nested/', '/large/')
        people = self.large_people
        self.page.goto(large + 'catalogue.html', wait_until='networkidle')
        rows = self.page.locator('[data-person-id]:visible')
        self.assertEqual(40, rows.count())
        self.assertIn(f'{people:,} of {people:,} people', self.page.locator('.result-count').inner_text())
        self.assertFalse(self.page.locator('[data-catalogue-pages]').is_visible())
        self.assertIn(f'Page 1 of {-(-people // 40)}', self.page.locator('.pagination').inner_text())
        # Someone not written into the page is found, shown like the written rows, and linked.
        self.page.get_by_role('searchbox', name='Search people').fill('Person 0399')
        self.assertEqual(2, rows.count())  # the person, and their parent, whose search covers recorded relatives
        row = self.page.locator('[data-person-id="p0399"]')
        self.assertIn('b. 1799', row.inner_text())
        self.assertIn('birth: 1799', row.inner_text())
        row.get_by_role('link').click()
        self.assertEqual('Person 0399 Fable', self.page.locator('h1').inner_text())
        self.page.goto(large + 'catalogue.html?surname=Fable', wait_until='networkidle')
        self.assertIn(f'{people:,} of {people:,} people', self.page.locator('.result-count').inner_text())
        self.page.get_by_label('Sort by').select_option('birth')
        self.assertIn('b. 1700', rows.first.inner_text())

        self.page.goto(large + 'timeline.html', wait_until='networkidle')
        self.assertTrue(self.page.locator('.decade-list').first.is_visible())
        self.page.get_by_role('searchbox', name='Search timeline').fill('Person 0399')
        found = self.page.locator('[data-timeline] ul.timeline li')
        self.assertEqual(1, found.count())
        self.assertIn('1799 · birth', found.first.inner_text())
        self.assertFalse(self.page.locator('.decade-list').first.is_visible())
        self.page.get_by_role('searchbox', name='Search timeline').fill('')
        self.page.get_by_label('Event type').select_option('residence')
        self.assertEqual(people // 40, found.count())
        self.page.get_by_label('Event type').select_option('birth')
        self.assertEqual(100, found.count())
        self.assertIn(f'The first 100 of {people:,} matching events', self.page.locator('[data-timeline]').evaluate('n => n.previousElementSibling.textContent'))
        found.first.get_by_role('link').click()
        self.assertTrue(self.page.locator('h1').inner_text().startswith('Person '))

        self.page.goto(large + 'places.html', wait_until='networkidle')
        self.assertEqual(people // 2, self.page.locator('#map-output .map-point').count())
        self.page.goto(large + 'sources.html', wait_until='networkidle')
        self.assertIn(f'{people + 1:,} sources, 100 on this page', self.page.locator('.result-count').inner_text())
        self.page.get_by_role('searchbox', name='Search sources').fill('volume 0390')
        self.assertFalse(self.page.locator('[data-sources]').is_visible())
        self.assertFalse(self.page.locator('[data-source-pages]').is_visible())
        result = self.page.get_by_role('link', name='Invented register volume 0390')
        self.assertEqual(1, result.count())
        result.click()
        self.assertTrue(self.page.locator(':target').inner_text().startswith('Invented register volume 0390'))

        # Studies: the newest are written out; the search covers every study, including linked people's names.
        self.page.goto(large + 'studies.html', wait_until='networkidle')
        self.assertIn(f'{people:,} studies, the 100 most recently updated on this page', self.page.locator('.result-count').inner_text())
        self.assertEqual('status', self.page.locator('.result-count').get_attribute('role'))
        self.assertEqual(100, self.page.locator('[data-study-id]:visible').count())
        self.page.get_by_role('searchbox', name='Search studies').fill('0390 Fable')  # "Fable" is only in the linked person's name
        self.assertFalse(self.page.locator('[data-studies]').is_visible())
        self.assertFalse(self.page.locator('[data-study-pages]').is_visible())
        self.assertIn(f'1 of {people:,} studies shown', self.page.locator('.result-count').inner_text())
        result = self.page.get_by_role('link', name='Study of person 0390')
        self.assertEqual(1, result.count())
        self.assertIn('Updated 2025-07-27', result.locator('..').inner_text())
        result.click()
        self.assertEqual('Study of person 0390', self.page.locator('h1').inner_text())
        self.page.go_back(wait_until='networkidle')
        self.page.get_by_role('searchbox', name='Search studies').fill('weaver')
        self.assertIn(f'The first 100 of {people:,} matching studies', self.page.locator('.result-count').inner_text())
        self.page.get_by_role('searchbox', name='Search studies').fill('')
        self.assertTrue(self.page.locator('[data-study-pages]').is_visible())
        self.page.goto(large + 'studies/page-2.html', wait_until='networkidle')
        self.assertEqual(0, self.page.get_by_role('searchbox').count())
        self.page.get_by_role('link', name='Study of person 0150').click()
        self.assertEqual('Study of person 0150', self.page.locator('h1').inner_text())
        self.page.goto(large + 'timeline/1700s.html', wait_until='networkidle')
        self.assertIn('Timeline: 1700s', self.page.locator('h1').inner_text())
        self.assertEqual([], self.errors)

    def test_search_pagination_tree_compare_and_connections(self):
        self.page.goto(self.base + 'catalogue.html')
        self.assertEqual(40, self.page.locator('[data-person-id]:visible').count())
        self.page.get_by_role('button', name='Next').click()
        self.assertEqual(3, self.page.locator('[data-person-id]:visible').count())  # 43 people, 40 a page
        self.page.get_by_role('searchbox', name='Search people').fill('Ada Alder')
        self.assertGreater(self.page.locator('[data-person-id]:visible').count(), 0)
        self.assertLess(self.page.locator('[data-person-id]:visible').count(), 42)
        self.page.get_by_role('searchbox', name='Search people').fill('no-such-synthetic-name')
        self.assertEqual(0, self.page.locator('[data-person-id]:visible').count())
        self.page.goto(self.base + 'tree.html')
        self.assertTrue(self.page.locator('[data-whole-tree]').is_visible())
        self.page.locator('[data-tree-view="family"]').click()
        self.assertGreater(self.page.locator('#tree-output svg').count(), 0)
        self.page.locator('[data-tree-view="branches"]').click()
        self.assertGreater(self.page.locator('#tree-output a').count(), 0)
        self.page.goto(self.base + 'compare.html')
        self.page.locator('[data-compare-a]').select_option('person:01')
        self.page.locator('[data-compare-b]').select_option('person:02')
        self.assertIn('Ada Alder', self.page.locator('#compare-result').inner_text())
        self.assertIn('Bram Alder', self.page.locator('#compare-result').inner_text())
        self.page.goto(self.base + 'connections.html')
        self.page.locator('[data-connection-a]').select_option('person:01')
        self.page.locator('[data-connection-b]').select_option('person:02')
        self.assertIn('Ada Alder', self.page.locator('#connection-result').inner_text())
        self.assertIn('Bram Alder', self.page.locator('#connection-result').inner_text())

    def test_dossier_menu_and_explore_links_prefill_the_tools(self):
        dossier = next(p for p in (self.root / 'nested' / 'people').glob('*.html') if 'data-person-id="person:01"' in p.read_text())
        self.page.goto(self.base + 'people/' + dossier.name)
        self.page.locator('p.explore').get_by_role('link', name='Find a connection').click()
        self.page.wait_for_url('**/connections.html?a=person%3A01')
        self.assertEqual('person:01', self.page.locator('[data-connection-a]').input_value())
        self.assertTrue(self.page.evaluate("document.activeElement.matches('[data-connection-b]')"))  # the empty menu is next
        self.page.locator('[data-connection-b]').select_option('person:02')
        self.assertIn('Bram Alder', self.page.locator('#connection-result').inner_text())
        # Both people in the address: the result renders without a choice.
        self.page.goto(self.base + 'connections.html?a=person%3A01&b=person%3A02')
        self.assertTrue(self.page.locator('#connection-result .connection-path').is_visible())
        self.assertIn('Ada Alder', self.page.locator('#connection-result').inner_text())
        self.assertIn('Bram Alder', self.page.locator('#connection-result').inner_text())
        self.page.goto(self.base + 'compare.html?a=person%3A01&b=person%3A02')
        self.assertEqual(2, self.page.locator('#compare-result .comparison .card').count())
        self.assertIn('Bram Alder', self.page.locator('#compare-result').inner_text())
        # An id that is not a public person is ignored; the menu it named is the one left to choose.
        self.page.goto(self.base + 'compare.html?a=no-such-person&b=person%3A02')
        self.assertEqual('', self.page.locator('[data-compare-a]').input_value())
        self.assertTrue(self.page.evaluate("document.activeElement.matches('[data-compare-a]')"))
        self.assertEqual(0, self.page.locator('#compare-result .comparison').count())
        # A large site fills its menus from the data before preselecting.
        large = self.base.replace('/nested/', '/large/')
        self.page.goto(large + 'compare.html?a=p0001&b=p0002', wait_until='networkidle')
        self.assertIn('Person 0002 Fable', self.page.locator('#compare-result').inner_text())
        self.page.goto(large + 'connections.html?a=p0001&b=p0003', wait_until='networkidle')
        self.assertIn('Person 0003 Fable', self.page.locator('#connection-result').inner_text())
        self.page.goto(self.base + 'people/' + dossier.name)
        self.page.locator('p.explore').get_by_role('link', name='Family tree').click()
        self.page.locator('#tree-output svg').wait_for()
        self.assertEqual('person:01', self.page.locator('#tree-root').input_value())
        # Wide screens keep the menu in view; a jump leaves its heading clear of it. Narrow screens leave it in the flow.
        for width, position in ((1600, 'sticky'), (390, 'static')):
            self.page.set_viewport_size({'width': width, 'height': 900})
            self.page.goto(self.base + 'people/' + dossier.name)
            nav = self.page.locator('nav.page-sections')
            self.assertEqual(position, nav.evaluate('n => getComputedStyle(n).position'))
            nav.get_by_role('link', name='Events').click()
            self.page.wait_for_function("location.hash === '#events'")
            heading, menu = self.page.locator('#events').bounding_box(), nav.bounding_box()
            if position == 'sticky':
                self.assertLess(abs(menu['y']), 1)  # held at the top of the window
                self.assertGreaterEqual(heading['y'], menu['y'] + menu['height'] - 1)
            else:
                self.assertGreaterEqual(heading['y'], -1)
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
            if os.environ.get('GENEALOGY_AXE_PATH'):
                self.page.add_script_tag(content=Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8'))
                violations = self.page.evaluate(
                    "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                    "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                    ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
                self.assertEqual([], violations, width)

    def test_surname_variants_group_the_filter_and_fold_the_search(self):
        visible = self.page.locator('[data-person-id]:visible')
        self.page.goto(self.base + 'branches.html')
        row = self.page.locator('tr[data-surname="Hale"]')
        self.assertIn('Recorded as Hale (4), Hayle (1)', row.inner_text())
        self.assertEqual(0, self.page.locator('tr[data-surname="Hayle"]').count())
        row.locator('a[href="catalogue.html?surname=Hale"]').click()
        self.page.locator('.pagination').wait_for()
        surname = self.page.get_by_label('Surname')
        self.assertEqual('Hale', surname.input_value())
        self.assertIn('Hale (5, incl. Hayle)', surname.locator('option').all_inner_texts())
        self.assertEqual(5, visible.count())
        iona = self.page.locator('[data-person-id="person:43"]')
        self.assertTrue(iona.is_visible())
        self.assertEqual('Hayle', iona.locator('td').nth(1).inner_text())  # shown as recorded
        surname.select_option('')
        for query in ('Iona Hale', 'Iona Hail', 'iona hayle'):  # any listed spelling finds her
            self.page.get_by_role('searchbox', name='Search people').fill(query)
            self.assertTrue(iona.is_visible(), query)
        self.page.goto(self.base + 'catalogue.html?surname=Hayle')
        self.page.locator('.pagination').wait_for()
        self.assertEqual('Hale', self.page.get_by_label('Surname').input_value())
        self.assertEqual(5, visible.count())

        large = self.base.replace('/nested/', '/large-variants/')
        everyone = self.large_people + 1
        self.page.goto(large + 'catalogue.html?surname=Fabel', wait_until='networkidle')
        surname = self.page.get_by_label('Surname')
        self.assertEqual('Fable', surname.input_value())
        self.assertEqual(['All surnames', f'Fable ({everyone}, incl. Fabel)'], surname.locator('option').all_inner_texts())
        self.assertIn(f'{everyone:,} of {everyone:,} people', self.page.locator('.result-count').inner_text())
        self.page.get_by_role('searchbox', name='Search people').fill('Odo Fable')
        self.assertEqual(1, visible.count())
        odo = self.page.locator('[data-person-id="p9999"]')
        self.assertEqual('Fabel', odo.locator('td').nth(1).inner_text())
        self.assertEqual('Fable', odo.get_attribute('data-surname'))

    def test_family_view_draws_recorded_siblings(self):
        from test_siblings import sibling_case
        build_site(sibling_case(), ProjectConfig(name='Fictional siblings'), self.root / 'siblings')
        self.page.goto(urljoin(self.base, '../siblings/tree.html?person=p0001'))
        self.page.locator('#tree-output svg').wait_for()
        # Bram, Iris, Pip and Lark; the disproved link to Nell is not drawn.
        self.assertEqual(4, self.page.locator('#tree-output path.tree-edge.sibling').count())
        self.assertEqual(1, self.page.locator('.tree-node[aria-label="Focus on Bram Fable"]').count())
        self.assertEqual(0, self.page.locator('.tree-node[aria-label="Focus on Nell Fable"]').count())

    @unittest.skipUnless(os.environ.get('GENEALOGY_AXE_PATH'), 'set GENEALOGY_AXE_PATH to an axe-core axe.min.js')
    def test_assessment_changes_pass_axe(self):
        from test_finding_changes import case as changes_case, config as changes_config, history
        (self.root / 'changes-project').mkdir(exist_ok=True)
        build_site(changes_case(history()), changes_config(self.root / 'changes-project'), self.root / 'changes')
        axe = Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8')
        dossier = next(p for p in (self.root / 'changes' / 'people').glob('*.html') if 'data-person-id="ada"' in p.read_text())
        for route in (f'people/{dossier.name}', 'findings.html', 'research.html'):
            with self.subTest(route=route):
                self.page.goto(urljoin(self.base, f'../changes/{route}'), wait_until='networkidle')
                self.assertGreater(self.page.locator('.assessment-change, .badge.change').count(), 0)
                self.page.add_script_tag(content=axe)
                violations = self.page.evaluate(
                    "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                    "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                    ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
                self.assertEqual([], violations)

    def test_map_controls_and_source_timeline_filters(self):
        self.page.goto(self.base + 'places.html')
        svg = self.page.locator('#map-output svg')
        original = svg.get_attribute('viewBox')
        self.page.locator('[data-map-fit]').click()
        self.assertNotEqual(original, svg.get_attribute('viewBox'))
        self.page.locator('[data-map-world]').click()
        self.assertEqual(original, svg.get_attribute('viewBox'))
        self.page.goto(self.base + 'timeline.html')
        self.page.get_by_role('searchbox', name='Search timeline').fill('no-such-synthetic-event')
        self.assertEqual(0, self.page.locator('[data-event-id]:visible').count())
        self.page.get_by_role('searchbox', name='Search timeline').fill('')
        self.page.get_by_role('combobox', name='Event type').select_option('death')
        self.assertEqual(42, self.page.locator('[data-event-id]:visible').count())
        self.page.goto(self.base + 'sources.html')
        self.page.get_by_role('searchbox', name='Search sources').fill('no-such-synthetic-source')
        self.assertEqual(0, self.page.locator('[data-source-id]:visible').count())
        self.assertEqual(0, self.page.locator('[data-source-type]:visible').count())
        # A record type's section is shown only while one of its sources matches.
        self.page.get_by_role('searchbox', name='Search sources').fill('Family Letters')
        self.assertEqual(1, self.page.locator('[data-source-id]:visible').count())
        self.assertEqual(['Fictional letter collection'], self.page.locator('[data-source-type]:visible > h2').all_inner_texts())
        self.page.goto(self.base + 'studies.html')
        studies = self.page.locator('[data-study-id]')
        self.assertGreater(studies.count(), 0)
        self.page.get_by_role('searchbox', name='Search studies').fill('no-such-synthetic-study')
        self.assertEqual(0, self.page.locator('[data-study-id]:visible').count())
        self.page.get_by_role('searchbox', name='Search studies').fill('Mara Grove')  # a linked person named only in the data
        self.assertEqual(1, self.page.locator('[data-study-id]:visible').count())
        self.page.get_by_role('searchbox', name='Search studies').fill('')
        self.assertEqual(studies.count(), self.page.locator('[data-study-id]:visible').count())

    def test_upload_gedcom_and_onetree_create_private_local_projects(self):
        for filename in ('family.ged', 'one-tree.json'):
            path = ROOT / 'examples/demo/input' / filename
            self.assertTrue(path.is_file(), path)
            self.page.goto(self.upload.origin)
            self.page.locator('#name').fill('Browser synthetic upload')
            self.page.locator('#file').set_input_files(str(path))
            self.page.locator('#review').check()
            if filename.endswith('.ged'):
                self.page.locator('#sources').check()
            self.page.locator('#submit').click()
            preview = self.page.locator('#result a.preview')
            preview.wait_for(timeout=30000)
            self.assertIn('Imported 42 people', self.page.locator('#result').inner_text())
            preview.click()
            self.assertIn('Browser synthetic upload', self.page.locator('h1').inner_text())
            self.page.locator('.site-sidebar a[data-view="people"]').click()
            self.page.locator('.pagination').wait_for()
            self.assertEqual(40, self.page.locator('[data-person-id]:visible').count())
            self.assertEqual(42, len(self.page.evaluate('window.GENEALOGY_SITE_DATA')['people']))
            # The full public export sits beside the pages; the browser script carries a subset.
            payload = self.page.request.get(urljoin(self.page.url, 'data/site.json')).json()
            self.assertEqual(42, len(payload['people']))
            self.assertTrue(all(p['sensitivity'] == 'public' for p in payload['people']))
            if filename.endswith('.ged'):
                self.assertGreater(len(payload['sources']), 0)
                self.assertTrue(all(c['status'] == 'asserted' for c in payload['claims']))
            denied = self.page.request.get(self.upload.origin + '/private/previews/')
            self.assertEqual(404, denied.status)
