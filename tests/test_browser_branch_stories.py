"""Opt-in browser contract: the family studies on the branches page read without JavaScript, fit both widths and pass axe."""
from __future__ import annotations

from functools import partial
from http.server import ThreadingHTTPServer
import os
import re
from pathlib import Path
import tempfile
import threading
import unittest

from genealogy.case import CaseStore
from genealogy.config import ProjectConfig
from genealogy.models import AccessLevel
from genealogy.site import build_site
from test_browser_site import ROOT, QuietHandler  # tests/ is on the path under unittest discovery


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1',
                     'Run make browser-check with the browser extra installed')
class BrowserBranchStoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        from test_scale import large_case
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        config = ProjectConfig.load(ROOT / 'examples/demo/genealogy.toml')
        build_site(CaseStore(ROOT / 'examples/demo/cases').load(config.default_case), config, cls.root / 'demo')
        large = large_case()
        for study in large.records('Study'):
            if study.sensitivity is AccessLevel.PUBLIC:
                study.kind = 'family'
        build_site(large, ProjectConfig(name='Fictional large tree'), cls.root / 'large')
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
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))

    def tearDown(self):
        self.context.close()

    def axe(self):
        self.page.add_script_tag(content=Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8'))
        return self.page.evaluate("async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                                  "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                                  ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")

    @unittest.skipUnless(os.environ.get('GENEALOGY_AXE_PATH'), 'set GENEALOGY_AXE_PATH to an axe-core axe.min.js')
    def test_branches_pass_axe_and_fit_both_widths(self):
        for width in (1440, 390):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for site in ('demo', 'large'):
                with self.subTest(width=width, site=site):
                    self.page.goto(f'{self.base}{site}/branches.html', wait_until='networkidle')
                    self.assertTrue(self.page.locator('#family-studies').is_visible())
                    self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
                    self.assertEqual([], self.axe())
        self.assertEqual([], self.errors)

    def test_without_javascript_each_story_opens_its_study(self):
        context = self.browser.new_context(java_script_enabled=False, viewport={'width': 390, 'height': 900})
        try:
            page = context.new_page()
            page.goto(self.base + 'demo/branches.html')
            card = page.locator('.story-card').first
            self.assertEqual('Family study', card.locator('.story-kicker').text_content())
            self.assertTrue(card.is_visible())
            row = page.locator('tr[data-surname] .branch-story').first
            self.assertTrue(row.is_visible())
            title = row.locator('.branch-story-title').inner_text()
            row.get_by_role('link', name=re.compile(r'^Read the study\s*:\s*' + re.escape(title))).click()  # the title is in the link's name
            page.wait_for_url('**/studies/s-*.html')
            self.assertEqual(title, page.locator('h1').inner_text())
        finally:
            context.close()


if __name__ == '__main__':
    unittest.main()
