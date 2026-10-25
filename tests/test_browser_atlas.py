"""Opt-in browser contract for the whole-tree atlas, the first view of tree.html."""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest

from genealogy.config import ProjectConfig
from genealogy.site import build_site

from test_atlas import SECRET, atlas_case
from test_scale import large_case


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1',
                     'Run make browser-check with the browser extra installed')
class AtlasBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        build_site(atlas_case(), ProjectConfig(name='Fictional atlas', raw={'site': {'tree_name': 'FableTree'}}), cls.root / 'atlas')
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

    def open(self, address, width=1440, javascript=True):
        self.context = self.browser.new_context(viewport={'width': width, 'height': 1000}, java_script_enabled=javascript)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        self.page.on('console', lambda m: self.errors.append(m.text) if m.type in ('warning', 'error') else None)
        self.page.goto(self.base + address, wait_until='networkidle')
        return self.page

    def tearDown(self):
        if hasattr(self, 'context'):
            self.context.close()
        self.assertEqual([], self.errors, 'Browser runtime errors')

    def hash(self):
        return self.page.evaluate('location.hash')

    def axe(self, label):
        if not os.environ.get('GENEALOGY_AXE_PATH'):
            return
        self.page.add_script_tag(content=Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8'))
        violations = self.page.evaluate(
            "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
            "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
            ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
        self.assertEqual([], violations, label)

    def test_atlas_is_the_default_view_with_its_controls(self):
        page = self.open('atlas/tree.html')
        self.assertEqual('Atlas', page.locator('[data-tree-view]').first.inner_text())
        self.assertEqual('true', page.locator('[data-tree-view="atlas"]').get_attribute('aria-pressed'))
        canvas = page.locator('[data-atlas-canvas]')
        self.assertTrue(canvas.is_visible())
        self.assertIn('Atlas of the whole tree: 7 people', canvas.get_attribute('aria-label'))
        self.assertTrue(page.locator('[data-atlas-panel]').is_hidden())
        # The shared zoom row belongs to the other views; the atlas has its own.
        self.assertTrue(page.locator('.tree-controls').is_hidden())
        self.assertEqual('7 people shown of 7 · 1 family group around the edge, and those with no recorded relatives',
                         page.locator('.atlas-count').inner_text())
        # Filters & tools starts folded, as on the Glasgow site, and opens over the drawing.
        tools = page.get_by_role('button', name='Filters & tools')
        self.assertEqual('false', tools.get_attribute('aria-expanded'))
        self.assertTrue(page.locator('.atlas-tools').is_hidden())
        tools.click()
        self.assertEqual('true', tools.get_attribute('aria-expanded'))
        for name in ('Everyone', 'Year', 'Country'):
            self.assertEqual('true', page.get_by_role('button', name=name, exact=True).get_attribute('aria-pressed'))
        self.assertEqual('all years', page.locator('.atlas-years output').inner_text())
        # Colour by family: the key names the surnames; the choice is kept in the address.
        page.get_by_role('button', name='Family', exact=True).click()
        self.assertEqual('true', page.get_by_role('button', name='Family', exact=True).get_attribute('aria-pressed'))
        self.assertEqual(['Fable 5', 'Vale 1', 'Wanderer 1'], page.locator('.atlas-swatches li').all_inner_texts())
        self.assertIn('colour=family', self.hash())
        page.get_by_role('button', name='Evidence', exact=True).click()
        self.assertEqual(['Documented 2', 'Possible 1', 'No recorded parent 4'], page.locator('.atlas-swatches li').all_inner_texts())
        # Grandparents only: Ada and Bram, whose grandson Eli is recorded.
        page.get_by_role('button', name='Grandparents only').click()
        self.assertIn('2 people shown of 7', page.locator('.atlas-count').inner_text())
        page.get_by_role('button', name='Everyone', exact=True).click()
        page.get_by_role('button', name='Generation', exact=True).click()
        self.assertIn('arrange=generation', self.hash())
        # Born by 1826: Eli (1850) and Cora's later cousins drop out.
        page.get_by_label('Born by').evaluate("s => { s.value = '1826'; s.dispatchEvent(new Event('input', {bubbles: true})); }")
        self.assertEqual('1826', page.locator('.atlas-years output').inner_text())
        self.assertIn('5 people shown of 7', page.locator('.atlas-count').inner_text())
        self.assertIn('born=1826', self.hash())
        page.get_by_role('button', name='All', exact=True).click()
        self.assertEqual('all years', page.locator('.atlas-years output').inner_text())
        # Play grows the tree from the earliest decade; Pause stops it.
        play = page.locator('[data-atlas-play]')
        play.click()
        self.assertEqual('true', play.get_attribute('aria-pressed'))
        page.wait_for_timeout(300)
        play.click()
        self.assertEqual('false', play.get_attribute('aria-pressed'))
        self.assertNotEqual('all years', page.locator('.atlas-years output').inner_text())
        # Zoom and fit.
        level = page.locator('[data-atlas-zoom]')
        page.get_by_role('button', name='Zoom in').click()
        self.assertEqual('140%', level.inner_text())
        page.get_by_role('button', name='Move left').click()
        page.get_by_role('button', name='Fit the whole tree').click()
        self.assertEqual('100%', level.inner_text())
        canvas.focus()
        page.keyboard.press('+')
        self.assertEqual('140%', level.inner_text())
        page.keyboard.press('0')
        self.assertEqual('100%', level.inner_text())
        # Filters & tools folds the controls away again.
        tools.click()
        self.assertEqual('false', tools.get_attribute('aria-expanded'))
        self.assertTrue(page.locator('.atlas-tools').is_hidden())
        self.assertNotIn(SECRET, page.content())

    def test_person_panel_from_the_address_tabs_and_relatives(self):
        page = self.open('atlas/tree.html#view=atlas&person=p0003')
        panel = page.locator('[data-atlas-panel]')
        self.assertEqual('Corin Fable', panel.locator('h3').inner_text())
        self.assertEqual('p0003', page.locator('#tree-root').input_value())
        # The atlas has its own search, so the tree's search box is out of sight here but keeps the choice.
        self.assertEqual('Corin Fable', page.locator('.tree-toolbar [role=combobox]').input_value())
        self.assertTrue(page.locator('.tree-toolbar [role=combobox]').is_hidden())
        self.assertTrue(panel.get_by_role('link', name='Read current assessment & sources →').get_attribute('href').startswith('people/p-'))
        self.assertEqual('catalogue.html?q=p0003', panel.get_by_role('link', name='Catalogue').get_attribute('href'))
        self.assertEqual(0, panel.get_by_role('link', name='FableTree ↗').count())  # Corin has no tree profile
        tabs = panel.get_by_role('tab')
        self.assertEqual(['Overview', 'Family', 'Research'], tabs.all_inner_texts())
        self.assertEqual('true', tabs.first.get_attribute('aria-selected'))
        self.assertIn('Birth', panel.get_by_role('tabpanel').inner_text())
        tabs.first.focus()
        page.keyboard.press('ArrowRight')
        self.assertEqual('true', panel.get_by_role('tab', name='Family').get_attribute('aria-selected'))
        self.assertEqual('Family', page.evaluate('document.activeElement.textContent'))
        family = panel.get_by_role('tabpanel')
        self.assertIn('Documented', family.inner_text())
        self.assertEqual(['Select Bram Fable in the atlas', 'Select Ada Fable in the atlas', 'Select Cora Vale in the atlas', 'Select Eli Fable in the atlas'],
                         [b.get_attribute('aria-label') for b in family.locator('button.atlas-relative').all()])
        family.get_by_role('button', name='Select Ada Fable in the atlas').click()
        self.assertEqual('Ada Fable', panel.locator('h3').inner_text())
        self.assertIn('person=p0001', self.hash())
        self.assertEqual('https://example.invalid/Fable-1', panel.get_by_role('link', name='FableTree ↗').get_attribute('href'))
        # Close, then select the person at the centre of the drawing with a click.
        panel.get_by_role('button', name='Close the person profile').click()
        self.assertTrue(panel.is_hidden())
        self.assertNotIn('person=', self.hash())
        box = page.locator('[data-atlas-canvas]').bounding_box()
        page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        self.assertEqual('Ada Fable', panel.locator('h3').inner_text())
        page.locator('[data-atlas-canvas]').focus()
        page.keyboard.press('Escape')
        self.assertTrue(panel.is_hidden())
        # Explore this family opens the branch cards on the person.
        page.goto(self.base + 'atlas/index.html')
        page.goto(self.base + 'atlas/tree.html#view=atlas&person=p0003', wait_until='networkidle')
        panel.get_by_role('button', name='Explore this family →').click()
        self.assertEqual('true', page.locator('[data-tree-view="branches"]').get_attribute('aria-pressed'))
        self.assertEqual('p0003', page.locator('#tree-root').input_value())
        self.assertEqual(0, page.locator('[data-atlas-canvas]').count())

    def test_search_within_the_tree(self):
        page = self.open('atlas/tree.html')
        search = page.get_by_role('searchbox', name='Search within the family tree')
        search.fill('fable')
        self.assertIn('5 people match', page.locator('.atlas-results [role=status]').inner_text())
        self.assertEqual(5, page.locator('.atlas-results li').count())
        search.fill('dora')
        page.keyboard.press('Enter')
        self.assertEqual('Dora Fable', page.locator('[data-atlas-panel] h3').inner_text())
        self.assertTrue(page.evaluate("document.activeElement.matches('[data-atlas-panel] h3')"))
        search.fill('nobody here')
        self.assertIn('No public person in the tree matches', page.locator('.atlas-results').inner_text())
        # The readable family list is the page's text without scripts only; with them it is not on the page.
        self.assertEqual(0, page.locator('[data-atlas-families]').count())
        self.assertEqual(0, page.get_by_role('button', name='Readable family list').count())

    def test_without_javascript_the_family_list_is_the_tree(self):
        page = self.open('atlas/tree.html', javascript=False)
        families = page.locator('[data-atlas-families]')
        self.assertTrue(families.is_visible())
        self.assertEqual(['Group of 6 people around Bram Fable', 'No recorded relatives (1 person)'], families.locator('h3').all_inner_texts())
        self.assertIn('Bram Fable b. 1799 with Ada Fable b. 1801', families.locator('li[data-person-id="p0002"]').first.inner_text())
        self.assertEqual(0, page.locator('canvas').count())

    def test_dossier_atlas_link_opens_the_person(self):
        page = self.open('atlas/catalogue.html')
        page.get_by_role('link', name='Eli Fable').first.click()
        page.locator('p.explore').get_by_role('link', name='Atlas').click()
        page.locator('[data-atlas-panel] h3').wait_for()
        self.assertEqual('Eli Fable', page.locator('[data-atlas-panel] h3').inner_text())
        self.assertEqual('true', page.locator('[data-tree-view="atlas"]').get_attribute('aria-pressed'))

    def test_large_tree_at_both_widths(self):
        for width in (1440, 390):
            page = self.open('large/tree.html', width)
            self.assertIn('400 people shown of 400', page.locator('.atlas-count').inner_text())
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width, width)
            # A redraw of 400 people stays quick: ten zoom steps, each painted.
            started = time.monotonic()
            for _ in range(10):
                page.get_by_role('button', name='Zoom in').click()
                page.evaluate('new Promise(r => requestAnimationFrame(() => r()))')
            self.assertLess(time.monotonic() - started, 5, width)
            search = page.get_by_role('searchbox', name='Search within the family tree')
            search.fill('person 0123')
            page.keyboard.press('Enter')
            self.assertEqual('Person 0123 Fable', page.locator('[data-atlas-panel] h3').inner_text())
            self.assertTrue(page.locator('[data-atlas-panel]').is_visible())
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width, width)
            self.axe(f'large atlas, person selected, {width}')
            self.context.close()
            self.assertEqual([], self.errors, width)
            del self.context


if __name__ == '__main__':
    unittest.main()
