"""Opt-in browser contract: the findings log's month list jumps to its month and steps aside while a filter is in use."""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
import threading
import unittest

from genealogy.config import ProjectConfig
from genealogy.site import build_site


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1',
                     'Run make browser-check with the browser extra installed')
class FindingsMonthsBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        from test_findings_months import case, monthly  # tests/ is on the path under unittest discovery
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        # One finding a month for 80 months: the latest page passes 24 months, the archive pages list their own.
        build_site(case(monthly(80)), ProjectConfig(name='Fictional months', raw={'site': {'base_url': 'https://example.invalid/'}}), cls.root / 'log')
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(cls.root)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}/log/'
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
        self.errors = []
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 900})
        self.page = self.context.new_page()
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))

    def tearDown(self):
        self.context.close()
        self.assertEqual([], self.errors, 'Browser runtime errors')

    def narrow(self):
        self.context.close()
        self.context = self.browser.new_context(viewport={'width': 390, 'height': 900})
        self.page = self.context.new_page()
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))

    def axe(self):
        if not os.environ.get('GENEALOGY_AXE_PATH'):
            return
        self.page.add_script_tag(content=Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8'))
        violations = self.page.evaluate(
            "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
            "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations.map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
        self.assertEqual([], violations)

    def test_a_month_link_brings_its_rows_into_view(self):
        page = self.page
        page.goto(self.base + 'findings.html', wait_until='networkidle')
        page.locator('.findings-filters').wait_for()
        months = page.get_by_role('navigation', name='Months')
        self.assertTrue(months.is_visible())
        self.assertEqual('October 2026', months.get_by_role('link').first.inner_text())
        self.assertTrue(months.get_by_text('Earlier years:').is_visible())
        self.axe()
        link = months.get_by_role('link', name='2024', exact=True)
        link.click()
        page.wait_for_function("location.hash === '#month-2024-12'")
        header = page.locator('#month-2024-12 tr.findings-month th')
        self.assertEqual('December 2024', header.text_content())
        box = header.bounding_box()
        self.assertTrue(box and 0 <= box['y'] < 900, box)
        # A filter hides the month groups, and the list with them; Reset brings both back.
        page.get_by_role('searchbox', name='Search findings').fill('Monthly conclusion 3.')
        self.assertFalse(months.is_visible())
        page.get_by_role('button', name='Reset').click()
        self.assertTrue(months.is_visible())

    def test_an_archive_page_and_a_narrow_screen(self):
        self.narrow()
        page = self.page
        page.goto(self.base + 'findings/page-1.html', wait_until='networkidle')
        months = page.get_by_role('navigation', name='Months')
        first = months.get_by_role('link').first
        target = first.get_attribute('href')
        self.assertEqual(1, page.locator(f'tbody{target}').count())
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
        self.axe()
        first.click()
        self.assertTrue(page.locator(f'{target} tr.findings-month th').is_visible())

    def test_without_javascript_the_list_still_leads_to_each_month(self):
        context = self.browser.new_context(java_script_enabled=False)
        page = context.new_page()
        page.goto(self.base + 'findings.html')
        months = page.get_by_role('navigation', name='Months')
        self.assertTrue(months.is_visible())
        hrefs = months.get_by_role('link').evaluate_all('links => links.map(a => a.getAttribute("href"))')
        self.assertTrue(hrefs)
        for href in hrefs:
            self.assertEqual(1, page.locator(f'tbody{href}').count(), href)
        context.close()


if __name__ == '__main__':
    unittest.main()
