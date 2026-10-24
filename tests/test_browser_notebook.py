"""Saved people stay local, usable across pages, and scoped to one site."""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

from genealogy.case import CaseStore
from genealogy.config import ProjectConfig
from genealogy.site import build_site

ROOT = Path(__file__).resolve().parents[1]


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1', 'Run make browser-check')
class NotebookBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cfg = ProjectConfig.load(ROOT / 'examples/demo/genealogy.toml')
        case = CaseStore(ROOT / 'examples/demo/cases').load(cfg.default_case)
        for name in ('one', 'two'):
            build_site(case, cfg, cls.out / name)
        cls.people = sorted((cls.out / 'one' / 'people').glob('*.html'))[:2]
        cls.ids = [re.search(r'data-person-id="([^"]+)"', p.read_text())[1] for p in cls.people]
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(cls.out)))
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
        cls.tmp.cleanup()

    def setUp(self):
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))

    def tearDown(self):
        self.context.close()
        self.assertEqual([], self.errors)

    def save(self, n=0):
        self.page.goto(self.base + 'one/people/' + self.people[n].name)
        self.page.get_by_role('button', name='Save on this device').click()
        self.assertEqual('true', self.page.locator('[data-bookmark-person]').get_attribute('aria-pressed'))

    def open(self):
        self.page.get_by_role('button', name='Saved people', exact=False).click()
        self.page.wait_for_function("!document.querySelector('.notebook-status').textContent.includes('Loading')")

    def test_save_on_dossiers_compare_export_and_remove_on_home(self):
        self.save(0)
        self.save(1)
        self.page.goto(self.base + 'one/index.html')
        self.open()
        self.assertEqual(2, self.page.locator('.notebook-people li').count())
        self.assertTrue(self.page.get_by_role('link', name='Compare selected').is_hidden())
        self.page.locator('.notebook-people input').nth(0).check()
        self.page.locator('.notebook-people input').nth(1).check()
        href = self.page.get_by_role('link', name='Compare selected').get_attribute('href')
        self.assertEqual({'a': [self.ids[0]], 'b': [self.ids[1]]}, parse_qs(urlsplit(href).query))
        with self.page.expect_download() as pending:
            self.page.get_by_role('button', name='Export notebook').click()
        download = pending.value
        result = Path(download.path()).read_text()
        rows = json.loads(result)
        self.assertEqual(self.ids, [row['id'] for row in rows])
        self.assertTrue(all(row['url'].startswith(self.base + 'one/people/') for row in rows))
        self.page.get_by_role('button', name=re.compile('Remove .* from saved people')).first.click()
        self.assertTrue(self.page.get_by_role('link', name='Compare selected').is_hidden())
        self.assertEqual(1, self.page.locator('.notebook-people li').count())
        self.page.reload()
        self.open()
        self.assertEqual(1, self.page.locator('.notebook-people li').count())

    def test_storage_is_scoped_to_site_and_stale_ids_are_withheld(self):
        self.save()
        self.page.goto(self.base + 'two/index.html')
        self.open()
        self.assertEqual(0, self.page.locator('.notebook-people li').count())
        self.page.goto(self.base + 'one/index.html')
        self.page.evaluate("() => {const key=Object.keys(localStorage).find(k=>k.includes('/one/'));localStorage.setItem(key,JSON.stringify([...JSON.parse(localStorage.getItem(key)),{id:'WITHHELD-STALE-ID',u:'people/withheld.html'}]));}")
        self.page.reload()
        self.open()
        self.assertEqual(1, self.page.locator('.notebook-people li').count())
        self.assertNotIn('WITHHELD-STALE-ID', self.page.locator('.saved-people-panel').inner_text())

    def test_keyboard_phone_and_blocked_storage(self):
        self.context.add_init_script("Object.defineProperty(window,'localStorage',{get(){throw new DOMException('Blocked','SecurityError')}})")
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.save()
        self.assertIn('Saved for this visit', self.page.locator('[data-bookmark-person]').inner_text())
        self.open()
        self.assertIn('storage is unavailable', self.page.locator('.notebook-status').inner_text())
        self.assertEqual(1, self.page.locator('.notebook-people li').count())
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 391)
        self.page.keyboard.press('Escape')
        self.assertTrue(self.page.locator('.saved-people-panel').is_hidden())
        self.assertTrue(self.page.locator('.notebook-toggle').evaluate('n=>n===document.activeElement'))
