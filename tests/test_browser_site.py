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
from urllib.parse import urlsplit

from genealogy.case import CaseStore
from genealogy.config import ProjectConfig
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
        case = CaseStore(ROOT / 'examples/demo/cases').load(config.default_case)
        build_site(case, config, cls.root / 'nested')
        from test_scale import PEOPLE, large_case  # tests/ is on the path under unittest discovery
        cls.large_people = PEOPLE
        build_site(large_case(), ProjectConfig(name='Fictional large tree'), cls.root / 'large')
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

    def test_routes_images_mobile_and_no_javascript(self):
        dossier = json.loads((self.root / 'nested' / 'data' / 'routes.json').read_text())
        routes = ['index.html', 'catalogue.html', 'tree.html', 'timeline.html', 'places.html',
                  'sources.html', 'research.html', 'compare.html', 'connections.html', 'evidence.html',
                  'studies.html', 'findings.html', 'branches.html', 'sitemap.html',
                  next(route for route in dossier if route.startswith('people/')),
                  next(route for route in dossier if route.startswith('studies/'))]
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
            self.assertEqual(42, page.locator('[data-person-id]').count())
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
        for width in (1440, 390):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for route in pages:
                with self.subTest(width=width, route=route):
                    self.page.goto(self.base + route, wait_until='networkidle')
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
            for route in ('tree.html', 'compare.html', 'research.html', 'sitemap.html', 'findings.html', 'findings/page-1.html'):
                with self.subTest(route=route):
                    self.page.goto(large + route, wait_until='networkidle')
                    self.page.add_script_tag(content=axe)
                    violations = self.page.evaluate(
                        "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                        "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                        ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
                    self.assertEqual([], violations)
        self.assertEqual([], self.errors)

    def test_search_pagination_tree_compare_and_connections(self):
        self.page.goto(self.base + 'catalogue.html')
        self.assertEqual(40, self.page.locator('[data-person-id]:visible').count())
        self.page.get_by_role('button', name='Next').click()
        self.assertEqual(2, self.page.locator('[data-person-id]:visible').count())
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
            payload = self.page.evaluate('window.GENEALOGY_SITE_DATA')
            self.assertEqual(42, len(payload['people']))
            self.assertTrue(all(p['sensitivity'] == 'public' for p in payload['people']))
            if filename.endswith('.ged'):
                self.assertGreater(len(payload['sources']), 0)
                self.assertTrue(all(c['status'] == 'asserted' for c in payload['claims']))
            denied = self.page.request.get(self.upload.origin + '/private/previews/')
            self.assertEqual(404, denied.status)
