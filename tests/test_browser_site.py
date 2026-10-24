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
from genealogy.site import SOURCES_PER_PAGE, build_site

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
        # The demo study compares three fictional groups and draws how they connect.
        demo = next(s for s in case.records('Study') if s.id == 'study:households')
        demo.groups = [{'id': 'lantern', 'title': 'Lanternford register children', 'member_ids': ['person:01', 'person:05'], 'note': 'One register entry.'},
                       {'id': 'willow', 'title': 'Willowmere household', 'member_ids': ['person:13', 'person:14']},
                       {'id': 'ember', 'title': 'Ember lodgers', 'member_ids': ['person:09', 'person:10']}]
        demo.links = [{'from': 'lantern', 'to': 'willow', 'status': 'probable', 'evidence_ids': ['evidence:parent:5']},
                      {'from': 'willow', 'to': 'ember', 'status': 'possible', 'note': 'A shared surname only.'}]
        demo.next_records = ['The Willowmere returns for 1811.']
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

    def filter(self, control):
        """A catalogue filter control, its filter group (a details pill) opened first."""
        group = self.page.locator('details.filter-group', has=control)
        if group.count() and not group.evaluate('d => d.open'):
            group.locator('summary').click()
        return control

    def surname_filter(self):
        """The surname a ?surname= link filters on, shown in the Name menu ("Surname: Hale (5, incl. Hayle) Remove")."""
        return self.filter(self.page.locator('.catalogue-surname-filter'))

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
                # A section's link opens its first page, where the section lists its pages.
                self.page.locator('.site-sidebar a[data-group="people"]').click()
                self.assertIn('catalogue.html', self.page.url)
                self.assertEqual('page', self.page.locator('.site-sidebar a[data-view="people"]').get_attribute('aria-current'))
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
        self.page.goto((site / 'catalogue.html').as_uri() + '?surname=Alder')
        self.page.locator('.pagination').wait_for()
        self.assertEqual('Surname: Alder (6) Remove', self.surname_filter().text_content())
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
        self.assertEqual('Surname: Cairn (6) Remove', self.surname_filter().text_content())
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
        # The demo study draws a chronology of its people.
        pages.append(next(r for r in routes if r.startswith('studies/s-') and 'class="chronology"' in (self.root / 'nested' / r).read_text()))
        # And its households, connection diagram and records still to inspect.
        pages.append(next(r for r in routes if r.startswith('studies/s-') and 'class="groups-chart"' in (self.root / 'nested' / r).read_text()))
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
        # The full menus stay in the form, out of sight behind the type-to-find boxes; setting one still draws.
        self.page.goto(large + 'compare.html')
        self.assertEqual(0, self.page.locator('details.picker-menu').count())
        self.page.locator('[data-compare-a]').select_option('p0001', force=True)
        self.page.locator('[data-compare-b]').select_option('p0002', force=True)
        self.assertIn('Person 0002 Fable', self.page.locator('#compare-result').inner_text())
        self.page.goto(large + 'connections.html')
        self.page.locator('[data-connection-a]').select_option('p0001', force=True)
        self.page.locator('[data-connection-b]').select_option('p0003', force=True)
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
        self.assertEqual(50, rows.count())  # 50 a page, as site.py writes the first page
        self.assertIn(f'Browsing all {people:,} people · 1–50 shown', self.page.locator('.result-count').inner_text())
        self.assertFalse(self.page.locator('[data-catalogue-pages]').is_visible())
        self.assertIn(f'Page 1 of {-(-people // 50)}', self.page.locator('.pagination').inner_text())
        # Someone not written into the page is found, shown like the written rows, and linked.
        self.page.get_by_role('searchbox', name='Search people').fill('Person 0399')
        self.assertEqual(2, rows.count())  # the person, and their parent, whose search covers recorded relatives
        row = self.page.locator('[data-person-id="p0399"]')
        # Birth, birth location, and the recorded parent with the link's badge.
        self.assertEqual(['1799', 'Town 0399, Shire 0, Fableland'], row.locator('td').all_inner_texts()[1:3])
        self.assertIn('Person 0199 Fable', row.locator('td').nth(6).inner_text())
        self.assertIn('Unassessed tree link', row.locator('td').nth(6).inner_text())
        row.get_by_role('link', name='Person 0399 Fable').click()
        self.assertEqual('Person 0399 Fable', self.page.locator('h1').inner_text())
        self.page.goto(large + 'catalogue.html?surname=Fable', wait_until='networkidle')
        self.assertIn(f'{people:,} matches of {people:,} people', self.page.locator('.result-count').inner_text())
        self.page.get_by_role('button', name='Birth', exact=True).click()
        self.assertEqual('1700', rows.first.locator('td').nth(1).inner_text())
        # One citation in five is an original record, so a fifth of the people are backed by one.
        self.filter(self.page.get_by_label('Claims')).select_option('original')
        self.assertIn(f'{people // 5:,} matches of {people:,} people', self.page.locator('.result-count').inner_text())
        self.assertEqual('1702', rows.first.locator('td').nth(1).inner_text())

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
        self.assertIn(f'{people + 1:,} sources, {SOURCES_PER_PAGE} on this page', self.page.locator('.result-count').inner_text())
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
        # A plain page: no study search of its own, only the sidebar's site search.
        self.assertEqual(['Search the site'], [box.get_attribute('aria-label') or box.evaluate('i => i.labels[0].textContent') for box in self.page.get_by_role('searchbox').all()])
        self.page.get_by_role('link', name='Study of person 0150').click()
        self.assertEqual('Study of person 0150', self.page.locator('h1').inner_text())
        self.page.goto(large + 'timeline/1700s.html', wait_until='networkidle')
        self.assertIn('Timeline: 1700s', self.page.locator('h1').inner_text())
        self.assertEqual([], self.errors)

    def test_search_pagination_tree_compare_and_connections(self):
        self.page.goto(self.base + 'catalogue.html')
        self.assertEqual(43, self.page.locator('[data-person-id]:visible').count())  # 43 people, 50 a page
        self.assertIn('Page 1 of 1', self.page.locator('.pagination').inner_text())
        self.assertTrue(self.page.get_by_role('button', name='Next').is_disabled())
        self.page.get_by_role('searchbox', name='Search people').fill('Ada Alder')
        self.assertGreater(self.page.locator('[data-person-id]:visible').count(), 0)
        self.assertLess(self.page.locator('[data-person-id]:visible').count(), 42)
        self.page.get_by_role('searchbox', name='Search people').fill('no-such-synthetic-name')
        self.assertEqual(0, self.page.locator('[data-person-id]:visible').count())
        # Eight people have supported parent claims; the seven resting on the register's original entry are
        # "backed by an original record", and the one resting on the letters is not.
        self.page.get_by_role('searchbox', name='Search people').fill('')
        self.filter(self.page.get_by_label('Claims')).select_option('supported')
        self.assertIn('8 matches of 43 people', self.page.locator('.result-count').inner_text())
        self.page.get_by_label('Claims').select_option('original')
        self.assertIn('7 matches of 43 people', self.page.locator('.result-count').inner_text())
        self.assertEqual(0, self.page.locator('[data-person-id="person:10"]:visible').count())
        self.assertEqual(1, self.page.locator('[data-person-id="person:05"]:visible').count())
        self.page.get_by_label('Claims').select_option('')
        self.page.goto(self.base + 'tree.html')
        # The atlas is the first view and opens by default; the whole tree is one press away.
        self.assertTrue(self.page.locator('[data-atlas-canvas]').is_visible())
        self.assertEqual('true', self.page.locator('[data-tree-view="atlas"]').get_attribute('aria-pressed'))
        self.page.locator('[data-tree-view="whole"]').click()
        self.assertTrue(self.page.locator('[data-whole-tree]').is_visible())
        self.page.locator('[data-tree-view="family"]').click()
        self.assertGreater(self.page.locator('#tree-output svg').count(), 0)
        self.page.locator('[data-tree-view="branches"]').click()
        self.assertGreater(self.page.locator('#tree-output a').count(), 0)
        self.page.goto(self.base + 'compare.html')
        self.page.locator('[data-compare-a]').select_option('person:01', force=True)
        self.page.locator('[data-compare-b]').select_option('person:02', force=True)
        self.assertIn('Ada Alder', self.page.locator('#compare-result').inner_text())
        self.assertIn('Bram Alder', self.page.locator('#compare-result').inner_text())
        self.page.goto(self.base + 'connections.html')
        self.page.locator('[data-connection-a]').select_option('person:01', force=True)
        self.page.locator('[data-connection-b]').select_option('person:02', force=True)
        self.assertIn('Ada Alder', self.page.locator('#connection-result').inner_text())
        self.assertIn('Bram Alder', self.page.locator('#connection-result').inner_text())

    def test_dossier_menu_and_explore_links_prefill_the_tools(self):
        dossier = next(p for p in (self.root / 'nested' / 'people').glob('*.html') if 'data-person-id="person:01"' in p.read_text())
        self.page.goto(self.base + 'people/' + dossier.name)
        self.page.locator('p.explore').get_by_role('link', name='Find a connection').click()
        self.page.wait_for_url('**/connections.html?a=person%3A01')
        self.assertEqual('person:01', self.page.locator('[data-connection-a]').input_value())
        self.assertTrue(self.page.get_by_role('combobox', name='Find the second person').evaluate('e => e === document.activeElement'))  # the empty box is next
        self.page.locator('[data-connection-b]').select_option('person:02', force=True)
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
        self.assertTrue(self.page.get_by_role('combobox', name='Find the first person').evaluate('e => e === document.activeElement'))
        self.assertEqual(0, self.page.locator('#compare-result .comparison').count())
        # A large site fills its menus from the data before preselecting.
        large = self.base.replace('/nested/', '/large/')
        self.page.goto(large + 'compare.html?a=p0001&b=p0002', wait_until='networkidle')
        self.assertIn('Person 0002 Fable', self.page.locator('#compare-result').inner_text())
        self.page.goto(large + 'connections.html?a=p0001&b=p0003', wait_until='networkidle')
        self.assertIn('Person 0003 Fable', self.page.locator('#connection-result').inner_text())
        self.page.goto(self.base + 'people/' + dossier.name)
        self.page.locator('p.explore').get_by_role('link', name='Family tree').click()
        # The link opens the reading room (Branch cards) on the person.
        self.page.locator('#tree-output [data-reading-room]').wait_for()
        self.assertEqual('true', self.page.locator('[data-tree-view="branches"]').get_attribute('aria-pressed'))
        self.assertEqual('person:01', self.page.locator('#tree-root').input_value())
        # Wide screens keep the numbered menu in view as a column beside the sections; a jump
        # leaves its heading clear of it. Narrow screens leave it in the flow, above the sections.
        for width, position in ((1600, 'sticky'), (1280, 'sticky'), (390, 'static')):
            self.page.set_viewport_size({'width': width, 'height': 900})
            self.page.goto(self.base + 'people/' + dossier.name)
            nav = self.page.locator('nav.page-sections')
            self.assertEqual(position, nav.evaluate('n => getComputedStyle(n).position'))
            nav.get_by_role('link', name='Events').click()
            self.page.wait_for_function("location.hash === '#events'")
            heading, menu = self.page.locator('#events').bounding_box(), nav.bounding_box()
            if position == 'sticky':
                self.assertLess(abs(menu['y']), 1)  # held at the top of the window
                self.assertGreaterEqual(heading['x'], menu['x'] + menu['width'] - 1)  # beside the menu, never under it
                self.assertGreaterEqual(heading['y'], -1)
                self.assertLess(heading['y'], 100)  # the jump lands at the top of the window
                # Numbered 01, 02 … by a counter outside each link, so the link's name stays the section's.
                self.assertEqual('counter(toc, decimal-leading-zero)', nav.locator('ol > li').first.evaluate("li => getComputedStyle(li, '::before').content"))
            else:
                self.assertGreaterEqual(heading['y'], -1)
                self.assertGreaterEqual(heading['y'], menu['y'] + menu['height'] - 1)  # the menu stays above the sections
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
        surname = self.surname_filter()
        self.assertEqual('Surname: Hale (5, incl. Hayle) Remove', surname.text_content())
        self.assertEqual(5, visible.count())
        iona = self.page.locator('[data-person-id="person:43"]')
        self.assertTrue(iona.is_visible())
        self.assertTrue(iona.locator('td').first.inner_text().startswith('Iona Hayle'))  # shown as recorded, grouped as Hale
        self.assertEqual('Hale', iona.get_attribute('data-surname'))
        surname.get_by_role('button', name='Remove the surname filter').click()
        self.assertEqual(43, visible.count())
        # The Name menu's Last name box folds the listed spellings too.
        self.page.get_by_label('Last name', exact=True).fill('hayle')
        self.assertEqual(5, visible.count())
        self.page.get_by_label('Last name', exact=True).fill('')
        for query in ('Iona Hale', 'Iona Hail', 'iona hayle'):  # any listed spelling finds her
            self.page.get_by_role('searchbox', name='Search people').fill(query)
            self.assertTrue(iona.is_visible(), query)
        self.page.goto(self.base + 'catalogue.html?surname=Hayle')
        self.page.locator('.pagination').wait_for()
        self.assertEqual('Surname: Hale (5, incl. Hayle) Remove', self.surname_filter().text_content())
        self.assertEqual(5, visible.count())

        large = self.base.replace('/nested/', '/large-variants/')
        everyone = self.large_people + 1
        self.page.goto(large + 'catalogue.html?surname=Fabel', wait_until='networkidle')
        self.assertEqual(f'Surname: Fable ({everyone}, incl. Fabel) Remove', self.surname_filter().text_content())
        self.assertIn(f'{everyone:,} matches of {everyone:,} people', self.page.locator('.result-count').inner_text())
        self.page.get_by_role('searchbox', name='Search people').fill('Odo Fable')
        self.assertEqual(1, visible.count())
        odo = self.page.locator('[data-person-id="p9999"]')
        self.assertTrue(odo.locator('td').first.inner_text().startswith('Odo Fabel'))  # shown as recorded, grouped as Fable
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

    @unittest.skipUnless(os.environ.get('GENEALOGY_AXE_PATH'), 'set GENEALOGY_AXE_PATH to an axe-core axe.min.js')
    def test_link_reasons_rejected_links_and_opening_pass_axe(self):
        from test_family_reasons import GRADES, family_case
        build_site(family_case(), ProjectConfig(name='Fictional reasons', grades=GRADES), self.root / 'reasons')
        axe = Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8')
        dossier = next(p for p in (self.root / 'reasons' / 'people').glob('*.html') if 'data-person-id="ada"' in p.read_text())
        for width in (1440, 390):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width': width, 'height': 900})
                self.page.goto(urljoin(self.base, f'../reasons/people/{dossier.name}'), wait_until='networkidle')
                for selector in ('.lead.intro', '.latest-finding', '.link-reason', '.link-records', '.rejected-links'):
                    self.assertTrue(self.page.locator(selector).first.is_visible(), selector)
                self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
                self.page.add_script_tag(content=axe)
                violations = self.page.evaluate(
                    "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                    "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                    ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
                self.assertEqual([], violations)

    def test_moved_person_page_sends_the_reader_on_and_passes_axe(self):
        from test_former_ids import case as merges_case, config as merges_config, page as person_page
        build_site(merges_case(), merges_config(), self.root / 'merges')
        stub_url = urljoin(self.base, f'../merges/{person_page("p0009")}')
        self.page.goto(stub_url)
        self.page.wait_for_url(urljoin(self.base, f'../merges/{person_page("p0001")}'))
        self.assertEqual('Ada Fable', self.page.locator('h1').inner_text())
        if os.environ.get('GENEALOGY_AXE_PATH'):
            # The stub itself, held still: served without its refresh so axe can read it.
            html = (self.root / 'merges' / person_page('p0009')).read_text(encoding='utf-8')
            still = html.replace(html[html.index('<meta http-equiv="refresh"'):].split('>', 1)[0] + '>', '')
            self.page.route(stub_url, lambda route: route.fulfill(body=still, content_type='text/html'))
            try:
                self.page.goto(stub_url, wait_until='networkidle')
                self.assertEqual("This person's page has moved", self.page.locator('h1').inner_text())
                self.page.add_script_tag(content=Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8'))
                violations = self.page.evaluate(
                    "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                    "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                    ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
                self.assertEqual([], violations)
            finally:
                self.page.unroute(stub_url)

    def test_map_controls_and_source_timeline_filters(self):
        self.page.goto(self.base + 'places.html')
        svg = self.page.locator('#map-output svg')
        # The map opens framed on its places; World shows the whole map and Fit places frames them again.
        framed = svg.get_attribute('viewBox')
        self.assertNotEqual('0 0 900 470', framed)
        self.page.locator('[data-map-world]').click()
        self.assertEqual('0 0 900 470', svg.get_attribute('viewBox'))
        self.page.locator('[data-map-fit]').click()
        self.assertEqual(framed, svg.get_attribute('viewBox'))
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
            self.page.locator('.site-sidebar a[data-group="people"]').click()
            self.page.locator('.pagination').wait_for()
            self.assertEqual(42, self.page.locator('[data-person-id]:visible').count())  # 50 a page
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

    @unittest.skipUnless(os.environ.get('GENEALOGY_AXE_PATH'), 'set GENEALOGY_AXE_PATH to an axe-core axe.min.js')
    def test_research_log_passes_axe(self):
        from test_research_log import LOG, log_case
        build_site(log_case(*LOG), ProjectConfig(name='Fictional research log'), self.root / 'research-log')
        axe = Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8')
        dossier = next(p for p in (self.root / 'research-log' / 'people').glob('*.html') if 'data-person-id="ada"' in p.read_text())
        for width in (1440, 390):
            for route in (f'people/{dossier.name}', 'research.html'):
                with self.subTest(width=width, route=route):
                    self.page.set_viewport_size({'width': width, 'height': 900})
                    self.page.goto(urljoin(self.base, f'../research-log/{route}'), wait_until='networkidle')
                    self.assertEqual(3, self.page.locator('.research-log .search-details').count())
                    self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
                    self.page.add_script_tag(content=axe)
                    violations = self.page.evaluate(
                        "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                        "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                        ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
                    self.assertEqual([], violations)

    @unittest.skipUnless(os.environ.get('GENEALOGY_AXE_PATH'), 'Set GENEALOGY_AXE_PATH for accessibility checks')
    def test_place_pages_pass_axe(self):
        from test_place_pages import case as places_case, page as place_page
        build_site(places_case(), ProjectConfig(name='Fictional places'), self.root / 'place-pages')
        axe = Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8')
        for width in (1440, 390):
            self.page.set_viewport_size({'width': width, 'height': 900})
            # A country with only a sub-place, a parish with a marker map and people, a town three levels down.
            for pid in ('fableland', 'parish', 'town'):
                with self.subTest(width=width, place=pid):
                    self.page.goto(urljoin(self.base, f'../place-pages/{place_page(pid)}'), wait_until='networkidle')
                    self.assertEqual(1, self.page.locator('h1').count())
                    if pid == 'parish':
                        self.assertTrue(self.page.locator('.place-locator svg').is_visible())
                    self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
                    self.page.add_script_tag(content=axe)
                    violations = self.page.evaluate(
                        "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                        "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                        ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
                    self.assertEqual([], violations)

    @unittest.skipUnless(os.environ.get('GENEALOGY_AXE_PATH'), 'Set GENEALOGY_AXE_PATH for accessibility checks')
    def test_guide_basis_and_examples_line_up_and_pass_axe(self):
        from test_guide_examples import case as guide_case, config as guide_config
        (self.root / 'guide-project').mkdir(exist_ok=True)
        build_site(guide_case(), guide_config(self.root / 'guide-project'), self.root / 'guide')
        axe = Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8')
        for width in (1440, 390):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width': width, 'height': 900})
                self.page.goto(urljoin(self.base, '../guide/evidence.html'), wait_until='networkidle')
                meaning = self.page.locator('#confidence-documented + dd').bounding_box()
                for selector in ('.guide-basis', '.guide-example'):
                    extra = self.page.locator(f'#confidence-documented ~ dd{selector}').first
                    self.assertTrue(extra.is_visible(), selector)
                    # Under the meaning, in its column, at both widths.
                    self.assertAlmostEqual(meaning['x'], extra.bounding_box()['x'], delta=1)
                    self.assertGreater(extra.bounding_box()['y'], meaning['y'])
                self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
                self.page.add_script_tag(content=axe)
                violations = self.page.evaluate(
                    "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                    "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                    ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
                self.assertEqual([], violations)
        self.page.locator('.guide-example a').first.click()
        self.page.wait_for_url('**/people/*.html#family-heading')
        self.assertEqual('Ada Fable', self.page.locator('h1').inner_text())


    @unittest.skipUnless(os.environ.get('GENEALOGY_AXE_PATH'), 'set GENEALOGY_AXE_PATH to an axe-core axe.min.js')
    def test_progress_page_and_its_history_chart_pass_axe(self):
        from test_progress_page import C, build, case, finding
        out = self.root / 'progress'
        build(out)
        build(out, case([finding('f1', '2026-03-01'), finding('f9', '2026-10-02', [('gwen-finn', 'unknown', 'probable')])], C.PROBABLE))
        axe = Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8')
        for width in (1440, 390):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width': width, 'height': 900})
                self.page.goto(urljoin(self.base, '../progress/progress.html'), wait_until='networkidle')
                self.assertTrue(self.page.locator('svg.progress-chart').is_visible())
                self.page.locator('.progress-history-text summary').click()
                self.assertTrue(self.page.locator('.progress-history-text table').is_visible())
                self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
                self.page.add_script_tag(content=axe)
                violations = self.page.evaluate(
                    "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                    "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                    ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
                self.assertEqual([], violations)


    def test_statistics_page_reads_without_javascript_and_passes_axe(self):
        from test_statistics import config as statistics_config, statistics_case
        build_site(statistics_case(), statistics_config(), self.root / 'statistics')
        sites = {'statistics': 8, 'nested': None, 'large': None}
        axe = Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8') if os.environ.get('GENEALOGY_AXE_PATH') else None
        for width in (1440, 390):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for site, tables in sites.items():
                with self.subTest(width=width, site=site):
                    self.page.goto(urljoin(self.base, f'../{site}/statistics.html'), wait_until='networkidle')
                    self.assertEqual('Statistics', self.page.locator('h1').inner_text())
                    if tables:
                        self.assertEqual(tables, self.page.locator('table.statistics').count())
                    # Every bar is drawn, at its share of the largest row, inside the page width.
                    bar = self.page.locator('table.statistics .bar').first
                    self.assertGreater(bar.bounding_box()['width'], 0)
                    # The KPI panel leads; chart cards sit two to a row on a wide screen and one to a row on a phone.
                    self.assertTrue(self.page.locator('.stat-panel').is_visible())
                    cards = [self.page.locator('.chart-card').nth(n).bounding_box() for n in range(2)]
                    self.assertEqual(width > 1100, abs(cards[0]['y'] - cards[1]['y']) < 1)
                    self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
                    if axe:
                        self.page.add_script_tag(content=axe)
                        violations = self.page.evaluate(
                            "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                            "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                            ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
                        self.assertEqual([], violations)
        nojs = self.browser.new_context(java_script_enabled=False)
        try:
            page = nojs.new_page()
            page.goto(urljoin(self.base, '../statistics/statistics.html'))
            self.assertEqual(8, page.locator('table.statistics').count())
            self.assertIn('Tobin Fable', page.locator('#families + p + .table-wrap').inner_text())
        finally:
            nojs.close()

    @unittest.skipUnless(os.environ.get('GENEALOGY_AXE_PATH'), 'Set GENEALOGY_AXE_PATH for accessibility checks')
    def test_competing_hypotheses_pass_axe(self):
        from test_hypotheses_compare import case as hypotheses_case
        build_site(hypotheses_case(), ProjectConfig(name='Fictional hypotheses'), self.root / 'hypotheses')
        axe = Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8')
        dossier = next(p for p in (self.root / 'hypotheses' / 'people').glob('*.html') if 'data-person-id="p0001"' in p.read_text())
        for width in (1440, 390):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for route in ('research.html', f'people/{dossier.name}'):
                with self.subTest(width=width, route=route):
                    self.page.goto(urljoin(self.base, f'../hypotheses/{route}'), wait_until='networkidle')
                    cards = self.page.locator('.hypotheses-compare .hypothesis-card')
                    self.assertEqual(2, cards.count())
                    self.assertTrue(self.page.locator('.points-note').first.is_visible())
                    first, second = cards.nth(0).bounding_box(), cards.nth(1).bounding_box()
                    # Side by side where there is room, stacked on a phone.
                    self.assertEqual(width > 900, abs(first['y'] - second['y']) < 1, (first, second))
                    self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
                    self.page.add_script_tag(content=axe)
                    violations = self.page.evaluate(
                        "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                        "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                        ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
                    self.assertEqual([], violations)

    @unittest.skipUnless(os.environ.get('GENEALOGY_AXE_PATH'), 'set GENEALOGY_AXE_PATH to an axe-core axe.min.js')
    def test_possible_duplicates_pages_pass_axe_and_open_the_comparison(self):
        from test_duplicates import config as duplicates_config, crowd
        build_site(crowd(), duplicates_config(duplicates=True), self.root / 'duplicates')
        axe = Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8')
        for width in (1440, 390):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for route in ('duplicates.html', 'duplicates/page-2.html'):
                with self.subTest(width=width, route=route):
                    self.page.goto(urljoin(self.base, f'../duplicates/{route}'), wait_until='networkidle')
                    self.assertEqual(100, self.page.locator('table.duplicate-pairs tbody tr').count())
                    self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
                    self.page.add_script_tag(content=axe)
                    violations = self.page.evaluate(
                        "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                        "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                        ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
                    self.assertEqual([], violations)
        self.page.goto(urljoin(self.base, '../duplicates/duplicates.html'))
        self.page.locator('table.duplicate-pairs a', has_text='Compare').first.click()
        self.page.locator('#compare-result .comparison').wait_for()
        self.assertEqual(['q000', 'q001'], [self.page.locator(s).input_value() for s in ('[data-compare-a]', '[data-compare-b]')])

    def search_box(self):
        return self.page.get_by_role('searchbox', name='Search the site')

    def search_links(self):
        return self.page.locator('.site-search-results a')

    def test_site_search_finds_a_study_and_a_place_by_keyboard(self):
        self.page.goto(self.base + 'index.html')
        # Loaded on first use, not with the page.
        self.assertFalse(self.page.evaluate('"GENEALOGY_SEARCH_INDEX" in window'))
        box = self.search_box()
        box.fill('Lanternford')
        self.page.locator('.site-search-results:not([hidden])').wait_for()
        self.assertTrue(self.page.evaluate('Array.isArray(window.GENEALOGY_SEARCH_INDEX)'))
        groups = self.page.locator('.site-search-kind').all_text_contents()
        for kind in ('Places', 'Studies', 'Sources'):
            self.assertIn(kind, groups)
        self.assertEqual('Places', groups[0])  # a title starting with the query comes first
        self.assertRegex(self.page.locator('.site-search-count').inner_text(), r'^\d+ match')
        self.assertEqual('polite', self.page.locator('.site-search-count').get_attribute('aria-live'))
        self.page.locator('.site-search-group a', has_text='Two households, one family').click()
        self.page.wait_for_url('**/studies/s-*.html')
        # From a page one folder down, links still resolve from the site root.
        box = self.search_box()
        box.fill('willowmere')
        first = self.search_links().first
        first.wait_for()
        self.assertEqual('Willowmere (fictional)', first.locator('.site-search-title').inner_text())
        self.assertEqual('Places', self.page.locator('.site-search-kind').first.text_content())
        box.press('ArrowDown')
        self.assertTrue(first.evaluate('a => a === document.activeElement'))
        self.page.keyboard.press('ArrowDown')
        self.assertTrue(self.search_links().nth(1).evaluate('a => a === document.activeElement'))
        self.page.keyboard.press('ArrowUp')
        self.page.keyboard.press('ArrowUp')
        self.assertTrue(box.evaluate('i => i === document.activeElement'))
        box.press('Escape')
        self.assertTrue(self.page.locator('.site-search-results').is_hidden())
        self.assertEqual('willowmere', box.input_value())
        box.fill('')
        box.fill('willowmere')
        self.search_links().first.wait_for()
        box.press('ArrowDown')
        self.page.keyboard.press('Enter')
        self.page.wait_for_url('**/places/pl-*.html')  # a place with events has a page of its own
        self.assertIn('Willowmere', self.page.locator('h1').inner_text())

    def test_site_search_enter_opens_the_best_match_offline_and_on_a_phone(self):
        site = self.root / 'nested'
        self.page.set_viewport_size({'width': 390, 'height': 900})
        self.page.goto(next((site / 'people').glob('p-*.html')).as_uri())
        box = self.search_box()
        self.assertTrue(box.is_visible())  # outside the folded menu
        box.fill('Iona Hayle')
        self.search_links().first.wait_for()
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 391)
        self.assertEqual(['People'], self.page.locator('.site-search-kind').all_text_contents())
        more = self.page.locator('.site-search-more a')
        self.assertEqual('catalogue.html?q=Iona%20Hayle', more.get_attribute('href').split('/')[-1])
        box.press('Enter')
        self.page.wait_for_url('**/people/p-*.html')
        self.assertEqual('Iona Hayle', self.page.locator('h1').inner_text())
        # No match: Enter searches the catalogue instead.
        box = self.search_box()
        box.fill('no-such-synthetic-record')
        self.page.locator('.site-search-count', has_text='No titles match').wait_for()
        box.press('Enter')
        self.page.wait_for_url(lambda url: url.endswith('/catalogue.html?q=no-such-synthetic-record'))
        nojs = self.browser.new_context(java_script_enabled=False)
        try:
            page = nojs.new_page()
            page.goto(self.base + 'studies.html')
            page.get_by_label('Search the site').fill('Alder')
            page.get_by_label('Search the site').press('Enter')
            page.wait_for_url(lambda url: url.endswith('/catalogue.html?q=Alder'))
            self.assertEqual(43, page.locator('[data-person-id]').count())  # the full catalogue, still readable
        finally:
            nojs.close()

    def test_site_search_on_a_large_site(self):
        large = self.base.replace('/nested/', '/large/')
        self.page.goto(large + 'catalogue.html')
        box = self.search_box()
        box.fill('fable')
        self.search_links().first.wait_for()
        self.assertEqual(12 + 1, self.search_links().count())  # the best twelve, then the catalogue link
        self.assertRegex(self.page.locator('.site-search-count').inner_text(), r'^The best 12 of \d{3,}')
        box.fill('study of person 0042')
        study = self.page.locator('.site-search-group a', has_text='Study of person 0042')
        study.wait_for()
        self.assertEqual('Studies', self.page.locator('.site-search-kind').first.text_content())
        study.click()
        self.page.wait_for_url('**/studies/s-*.html')
        box = self.search_box()
        box.fill('town 0007')
        place = self.search_links().first
        place.wait_for()
        self.assertEqual(('Town 0007', 'Shire 0, Inventia'), (place.locator('.site-search-title').inner_text(), place.locator('.site-search-line').inner_text()))
        box.press('ArrowDown')
        self.page.keyboard.press('Enter')
        self.page.wait_for_url('**/places/pl-*.html')
        self.assertEqual('Town 0007, Shire 0, Inventia', self.page.locator('h1').inner_text())

    @unittest.skipUnless(os.environ.get('GENEALOGY_AXE_PATH'), 'set GENEALOGY_AXE_PATH to an axe-core axe.min.js')
    def test_site_search_results_pass_axe(self):
        axe = Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8')
        for width in (1440, 390):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for site, route, query in (('nested', 'index.html', 'Lanternford'), ('nested', 'sources.html', 'willow'), ('large', 'tree.html', 'fable')):
                with self.subTest(width=width, route=route):
                    self.page.goto(self.base.replace('/nested/', f'/{site}/') + route, wait_until='networkidle')
                    self.search_box().fill(query)
                    self.search_links().first.wait_for()
                    self.page.keyboard.press('ArrowDown')
                    self.page.add_script_tag(content=axe)
                    violations = self.page.evaluate(
                        "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                        "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                        ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
                    self.assertEqual([], violations)

    def axe_violations(self):
        self.page.add_script_tag(content=Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8'))
        return self.page.evaluate(
            "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
            "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
            ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")

    def test_person_pickers_find_people_by_typing_on_small_and_large_sites(self):
        page, axe = self.page, bool(os.environ.get('GENEALOGY_AXE_PATH'))
        first = page.get_by_role('combobox', name='Find the first person')
        second = page.get_by_role('combobox', name='Find the second person')
        options = page.locator('[role=listbox]:visible').get_by_role('option')  # a menu's own options are options too
        # The tree keeps its full menu in view beside the box on a small site; the compare and connections
        # forms keep theirs out of sight (still in the form, so it submits ?a=&b=). Typing and a click choose a person.
        page.goto(self.base + 'tree.html')
        self.assertTrue(page.locator('#tree-root').is_visible())
        page.goto(self.base + 'compare.html')
        self.assertFalse(page.locator('[data-compare-a]').is_visible())
        self.assertEqual(1, page.locator('form[data-person-form] select[name=a][data-compare-a]').count())
        self.assertEqual(0, page.locator('details.picker-menu').count())
        first.fill('ada ald')
        self.assertEqual('true', first.get_attribute('aria-expanded'))
        self.assertEqual(['Ada Alder'], [t.split('\n')[0] for t in options.all_inner_texts()])
        self.assertIn('b. 1754', options.first.inner_text())  # name and lifespan
        if axe:
            self.assertEqual([], self.axe_violations(), 'open listbox')
        options.first.click()
        self.assertEqual('person:01', page.locator('[data-compare-a]').input_value())
        self.assertEqual('false', first.get_attribute('aria-expanded'))
        self.assertEqual('Ada Alder', first.input_value())
        self.assertIn('Choose two people', page.locator('#compare-result').inner_text())
        # Keyboard only: Tab past the swap button, type, arrows move the active option, Escape closes, Enter chooses.
        first.focus()
        page.keyboard.press('Tab')
        page.keyboard.press('Tab')
        self.assertTrue(page.evaluate("document.activeElement.matches('[role=combobox][aria-controls]')"))
        page.keyboard.type('alder')
        count = options.count()
        self.assertGreater(count, 1)
        active = lambda: page.evaluate("document.getElementById(document.activeElement.getAttribute('aria-activedescendant'))?.textContent")
        self.assertTrue(active().startswith('Ada Alder'))
        page.keyboard.press('ArrowDown')
        self.assertTrue(active().startswith('Bram Alder'))
        self.assertEqual(1, page.locator('[role=listbox]:visible [aria-selected=true]').count())
        page.keyboard.press('ArrowUp')
        page.keyboard.press('ArrowUp')  # wraps to the last match
        self.assertEqual(f'{page.locator("[role=listbox]:visible").get_attribute("id")}-{count - 1}',
                         second.get_attribute('aria-activedescendant'))
        page.keyboard.press('Escape')
        self.assertEqual('false', second.get_attribute('aria-expanded'))
        self.assertIsNone(second.get_attribute('aria-activedescendant'))
        self.assertEqual('', page.locator('[data-compare-b]').input_value())
        page.keyboard.press('ArrowDown')  # reopens on the first match
        page.keyboard.press('ArrowDown')
        page.keyboard.press('Enter')
        self.assertEqual('person:02', page.locator('[data-compare-b]').input_value())
        self.assertIn('Bram Alder', page.locator('#compare-result').inner_text())
        self.assertEqual(2, page.locator('#compare-result .comparison .card').count())
        # Choosing from the menu updates the box; a grouped spelling finds the whole surname group.
        page.locator('[data-compare-b]').select_option('person:43', force=True)
        self.assertEqual('Iona Hayle', second.input_value())
        second.fill('iona hale')
        self.assertEqual(['Iona Hayle'], [t.split('\n')[0] for t in options.all_inner_texts()])
        second.fill('hayle')
        self.assertGreater(options.count(), 1)
        second.fill('person:02')  # the ID
        self.assertEqual(['Bram Alder'], [t.split('\n')[0] for t in options.all_inner_texts()])
        second.fill('no-such-synthetic-person')
        self.assertEqual('false', second.get_attribute('aria-expanded'))
        self.assertIn('No public person matches', page.locator('.picker-status').nth(1).inner_text())
        page.goto(self.base + 'connections.html')
        first.fill('ada alder')
        page.keyboard.press('Enter')
        second.fill('bram')
        options.first.click()
        self.assertTrue(page.locator('#connection-result .connection-path').is_visible())
        # The tree: a choice redraws it, and a person chosen in the drawing fills the box.
        page.goto(self.base + 'tree.html?person=person%3A02')
        tree_box = page.get_by_role('combobox', name='Find a person to explore from')
        self.assertEqual('Bram Alder', tree_box.input_value())
        tree_box.fill('ada alder')
        page.keyboard.press('Enter')
        self.assertEqual('person:01', page.locator('#tree-root').input_value())
        self.assertEqual('Family connections around Ada Alder', page.locator('#tree-output svg').get_attribute('aria-label'))
        relative = page.locator('#tree-output .tree-node:not(.focus)').first
        chosen = relative.get_attribute('aria-label').removeprefix('Focus on ')
        relative.click()
        self.assertEqual(chosen, tree_box.input_value())
        # A large site's form keeps its menus out of sight too; matches stop at twelve.
        large = self.base.replace('/nested/', '/large/')
        for width in (1440, 390):
            page.set_viewport_size({'width': width, 'height': 900})
            page.goto(large + 'compare.html', wait_until='networkidle')
            self.assertEqual(0, page.locator('details.picker-menu').count())
            self.assertFalse(page.locator('[data-compare-a]').is_visible())
            first.fill('person 01')
            self.assertEqual(12, options.count())
            self.assertIn('the first 12 shown', page.locator('.picker-status').first.inner_text())
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width + 1)
            if axe:
                self.assertEqual([], self.axe_violations(), f'large compare, open listbox, {width}')
            page.keyboard.press('Enter')
            self.assertEqual('p0001', page.locator('[data-compare-a]').input_value())
            second.fill('person 0002 fable')
            options.first.click()
            self.assertIn('Person 0002 Fable', page.locator('#compare-result').inner_text())
            self.assertEqual('p0001', page.locator('[data-compare-a]').input_value())
            # The tree folds its full menu under "or choose from the list".
            page.goto(large + 'tree.html', wait_until='networkidle')
            self.assertEqual(1, page.locator('details.picker-menu:not([open])').count())
            page.locator('details.picker-menu summary').first.click()
            self.assertTrue(page.locator('#tree-root').is_visible())
            if axe:
                self.assertEqual([], self.axe_violations(), f'large tree, list open, {width}')
        # With one person given, the box for the other takes focus, since its menu is out of sight.
        page.goto(large + 'connections.html?a=p0001', wait_until='networkidle')
        self.assertEqual('Person 0001 Fable', first.input_value())
        self.assertTrue(page.evaluate("document.activeElement.matches('[role=combobox]')"))
        page.keyboard.type('p0003')
        page.keyboard.press('Enter')
        self.assertIn('Person 0003 Fable', page.locator('#connection-result').inner_text())
        page.goto(large + 'tree.html', wait_until='networkidle')
        tree_box.fill('person 0007')
        page.keyboard.press('Enter')
        self.assertEqual('p0007', page.locator('#tree-root').input_value())
        # The atlas, the default view, selects the person chosen in the box.
        self.assertIn('Person 0007 Fable', page.locator('[data-atlas-panel]').inner_text())
        if axe:
            self.assertEqual([], self.axe_violations(), 'large tree')
        # Any listed spelling of a surname finds the group's people.
        page.goto(self.base.replace('/nested/', '/large-variants/') + 'compare.html', wait_until='networkidle')
        first.fill('fabel 0003')
        self.assertEqual(['Person 0003 Fable'], [t.split('\n')[0] for t in options.all_inner_texts()])
        first.fill('odo fable')
        self.assertEqual(['Odo Fabel'], [t.split('\n')[0] for t in options.all_inner_texts()])
