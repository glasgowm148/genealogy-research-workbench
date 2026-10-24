"""Opt-in browser contract for accessible offline map controls."""
from __future__ import annotations

import os
from pathlib import Path
import unittest


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1',
                     'Run make browser-check with the browser extra installed')
class BrowserMapControlTests(unittest.TestCase):
    """The map must remain useful without geocoding or online map services."""

    def test_controls_have_accessible_names_and_keyboard_pan(self):
        # Keep this test alongside the opt-in browser suite; the shared fixture
        # setup is intentionally exercised by the existing map filter contract.
        from test_browser_map_filters import BrowserMapFilterTests
        fixture = BrowserMapFilterTests
        fixture.setUpClass()
        try:
            self.page = fixture.browser.new_page(viewport={'width': 1200, 'height': 800})
            self.page.goto(fixture.base + 'demo/places.html', wait_until='networkidle')
            self.assertEqual('Zoom map in', self.page.get_by_role('button', name='Zoom map in').get_attribute('aria-label'))
            self.assertEqual('Zoom map out', self.page.get_by_role('button', name='Zoom map out').get_attribute('aria-label'))
            self.assertEqual('Reset map to world view', self.page.get_by_role('button', name='Reset map to world view').get_attribute('aria-label'))
            marker = self.page.locator('#map-output .map-point[aria-label*="Willowmere"]')
            self.assertIn('55.95, -3.19', marker.get_attribute('aria-label'))
            svg = self.page.locator('#map-output svg')
            svg.focus()
            before = svg.get_attribute('viewBox')
            svg.press('ArrowRight')
            self.assertNotEqual(before, svg.get_attribute('viewBox'))
            self.page.get_by_role('button', name='Reset map to world view').click()
            self.assertEqual('0 0 900 470', svg.get_attribute('viewBox'))
        finally:
            self.page.close()
            fixture.tearDownClass()


if __name__ == '__main__':
    unittest.main()
