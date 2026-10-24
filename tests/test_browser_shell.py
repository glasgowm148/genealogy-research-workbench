"""Opt-in browser checks for the page shell: search shortcuts, overlay results, sections and the phone menu."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from genealogy.case import CaseStore
from genealogy.config import ProjectConfig
from genealogy.site import build_site

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1', 'Run make browser-check with the browser extra installed')
class BrowserShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        config = ProjectConfig.load(ROOT / 'examples/demo/genealogy.toml')
        build_site(CaseStore(ROOT / 'examples/demo/cases').load(config.default_case), config, cls.root)
        cls.dossier = next((cls.root / 'people').glob('p-*.html')).as_uri()
        cls.pw = sync_playwright().start()
        executable = os.environ.get('GENEALOGY_BROWSER_EXECUTABLE')
        cls.browser = cls.pw.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.temp.cleanup()

    def setUp(self):
        self.page = self.browser.new_page(viewport={'width': 1280, 'height': 900})

    def tearDown(self):
        self.page.close()

    def box(self):
        return self.page.get_by_role('searchbox', name='Search the site')

    def focused(self):
        return self.box().evaluate('i => i === document.activeElement')

    def test_slash_and_command_k_move_to_the_search(self):
        self.page.goto(self.dossier)
        key = self.page.locator('.site-search-key')
        self.assertTrue(key.is_visible())
        self.assertEqual('true', key.get_attribute('aria-hidden'))
        self.assertIn('Control+K', self.box().get_attribute('aria-keyshortcuts'))
        self.page.keyboard.press('/')
        self.assertTrue(self.focused())
        self.assertFalse(key.is_visible())  # the hint steps aside while the box has focus
        # Typed inside the box, / is a character, not the shortcut.
        self.page.keyboard.type('a/b')
        self.assertEqual('a/b', self.box().input_value())
        self.page.locator('main a').first.focus()
        self.page.keyboard.press('ControlOrMeta+k')
        self.assertTrue(self.focused())
        # The shortcut selects what was typed, so typing replaces it.
        self.page.keyboard.type('Alder')
        self.assertEqual('Alder', self.box().input_value())

    def test_results_open_over_the_page_without_moving_it(self):
        self.page.goto(self.dossier)
        heading = self.page.locator('h1').bounding_box()
        self.box().fill('Alder')
        results = self.page.locator('.site-search-results:not([hidden])')
        results.wait_for()
        self.assertEqual(heading, self.page.locator('h1').bounding_box())
        panel = self.page.locator('.site-search-panel')
        self.assertEqual('absolute', panel.evaluate('p => getComputedStyle(p).position'))
        under = self.box().bounding_box()
        self.assertGreaterEqual(panel.bounding_box()['y'], under['y'] + under['height'])
        # The panel is on top: the point at its centre belongs to it.
        self.assertTrue(panel.evaluate('p => { const r = p.getBoundingClientRect(); return p.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)); }'))
        self.box().press('Escape')
        self.assertTrue(panel.is_hidden())

    def test_the_sections_and_the_phone_menu(self):
        self.page.goto(self.dossier)
        sidebar = self.page.locator('.site-sidebar')
        self.assertEqual('true', sidebar.locator('a[data-view="people"]').get_attribute('aria-current'))
        self.assertTrue(sidebar.locator('a[data-view="branches"]').is_visible())
        self.assertEqual(0, sidebar.locator('a[data-view="tree"]').count())  # another section's pages are not listed
        sidebar.locator('a[data-group="family"]').click()
        self.assertTrue(self.page.url.endswith('/tree.html'))
        self.assertEqual('page', sidebar.locator('a[data-view="tree"]').get_attribute('aria-current'))
        self.assertEqual(['Home', 'Family', 'Family tree'], self.page.locator('.site-breadcrumb li').all_text_contents())
        self.page.set_viewport_size({'width': 390, 'height': 800})
        self.page.goto(self.dossier)
        nav = self.page.get_by_role('navigation', name='Main navigation')
        self.assertTrue(nav.is_hidden())
        self.assertTrue(self.box().is_visible())
        self.page.locator('#menu-toggle').click()
        self.assertTrue(nav.locator('a[data-group="records"]').is_visible())
        self.assertTrue(nav.get_by_role('link', name='Site map').is_visible())
        self.box().fill('Alder')
        self.page.locator('.site-search-results:not([hidden])').wait_for()
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 391)

    def test_without_javascript_the_menu_is_open_on_a_phone(self):
        context = self.browser.new_context(java_script_enabled=False, viewport={'width': 390, 'height': 800})
        try:
            page = context.new_page()
            page.goto(self.dossier)
            self.assertTrue(page.get_by_role('navigation', name='Main navigation').locator('a[data-group="family"]').is_visible())
            self.assertTrue(page.locator('#menu-toggle').is_hidden())
            self.assertTrue(page.locator('.site-search-panel').is_hidden())
        finally:
            context.close()

    def open_phone_menu(self):
        self.page.set_viewport_size({'width': 390, 'height': 800})
        self.page.goto(self.dossier)
        toggle = self.page.locator('#menu-toggle')
        toggle.click()
        self.assertEqual('true', toggle.get_attribute('aria-expanded'))
        return toggle

    def test_phone_menu_escape_returns_focus_to_toggle(self):
        toggle = self.open_phone_menu()
        self.page.locator('.site-sidebar a').first.focus()
        self.page.keyboard.press('Escape')
        self.assertEqual('false', toggle.get_attribute('aria-expanded'))
        self.assertTrue(toggle.evaluate('i => i === document.activeElement'))

    def test_phone_menu_closes_on_outside_interaction(self):
        toggle = self.open_phone_menu()
        self.page.locator('#main-content').click(position={'x': 8, 'y': 8})
        self.assertEqual('false', toggle.get_attribute('aria-expanded'))
        self.assertTrue(self.page.locator('.site-sidebar').evaluate("i => !i.classList.contains('menu-open')"))

    def test_phone_menu_closes_when_navigation_starts(self):
        toggle = self.open_phone_menu()
        link = self.page.locator('.site-sidebar a').first
        link.click()
        self.assertEqual('false', toggle.get_attribute('aria-expanded'))

    def test_phone_menu_state_syncs_across_breakpoint_resize(self):
        toggle = self.open_phone_menu()
        self.page.set_viewport_size({'width': 800, 'height': 800})
        self.page.wait_for_timeout(50)
        self.assertEqual('false', toggle.get_attribute('aria-expanded'))
        self.page.set_viewport_size({'width': 640, 'height': 800})
        self.page.wait_for_timeout(50)
        self.assertEqual('false', toggle.get_attribute('aria-expanded'))
        toggle.click()
        self.assertEqual('true', toggle.get_attribute('aria-expanded'))


if __name__ == '__main__':
    unittest.main()
