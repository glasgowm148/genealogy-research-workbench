"""Opt-in browser contract for the family reading room, the tree page's Branch cards view."""
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
from test_reading_room import SECRET, SECRET_LINK, reading_room_case  # tests/ is on the path under unittest discovery


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1',
                     'Run make browser-check with the browser extra installed')
class ReadingRoomBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        from test_scale import large_case
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        build_site(reading_room_case(), ProjectConfig(name='Fictional reading room'), cls.root / 'room')
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

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 1000})
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        self.page.on('console', lambda m: self.errors.append(m.text) if m.type in ('warning', 'error') else None)

    def tearDown(self):
        self.context.close()
        self.assertEqual([], self.errors, 'Browser runtime errors')

    def open(self, person='p0001', site='room'):
        self.page.goto(f'{self.base}{site}/tree.html#view=branches&person={person}', wait_until='networkidle')
        self.room.wait_for()

    @property
    def room(self):
        return self.page.locator('#tree-output [data-reading-room]')

    def card(self, pid):
        return self.room.locator(f'.rr-person[data-person="{pid}"]')

    def bands(self):
        return self.room.locator('.rr-band-label').all_text_contents()

    def band_of(self, pid):
        return self.card(pid).evaluate("n => n.closest('.rr-band').querySelector('.rr-band-label').textContent")

    def test_dossier_link_opens_the_room_with_one_band_per_generation(self):
        dossier = next(p for p in (self.root / 'room' / 'people').glob('*.html') if 'data-person-id="p0001"' in p.read_text())
        self.page.goto(f'{self.base}room/people/{dossier.name}')
        self.page.locator('p.explore').get_by_role('link', name='Family tree').click()
        self.room.wait_for()
        self.assertTrue(self.page.url.endswith('tree.html#view=branches&person=p0001'))
        self.assertEqual('true', self.page.locator('[data-tree-view="branches"]').get_attribute('aria-pressed'))
        self.assertEqual('Branch cards', self.page.locator('[data-tree-view="branches"]').inner_text())
        self.assertEqual('Ada & family', self.room.locator('h2').inner_text())
        self.assertEqual('The family reading room', self.room.locator('.eyebrow').text_content())
        # Three generations up by default, two down; the great-grandchild waits behind a fold.
        self.assertEqual(['Great-grandparents · born 1760', 'Grandparents · born 1790–1792', 'Parents · born 1819–1822',
                          'This generation · born 1848–1855', 'Children · born 1875–1878', 'Grandchildren · born 1900'], self.bands())
        self.assertEqual('This generation · born 1848–1855', self.band_of('p0005'))  # the husband beside her
        self.assertIn('Partner of Ada', self.card('p0005').inner_text())
        self.assertIn('Spouse: Probable', self.card('p0005').locator('.rr-links').inner_text())
        self.assertEqual(16 - 1, self.room.locator('.rr-person').count())  # all public people but the great-grandchild
        self.assertEqual('15 family profiles', self.room.locator('.rr-foot strong').inner_text())
        # Cards are HTML: name, years and birthplace; the focus card links to the dossier, the others centre the room.
        ada = self.card('p0001')
        self.assertIn('rr-focus', ada.get_attribute('class'))
        self.assertEqual('Ada Fable', ada.locator('.rr-name').evaluate('n => n.firstChild.textContent'))
        self.assertEqual(['b. 1850', 'Lanternford (fictional)'], [ada.locator('.rr-years').inner_text(), ada.locator('.rr-place').inner_text()])
        self.assertTrue(ada.locator('a.rr-name').get_attribute('href').startswith('people/'))
        self.assertEqual(0, self.card('p0002').locator('a.rr-name').count())

    def test_alternative_parent_sets_stand_side_by_side_with_their_own_chips(self):
        self.open()
        self.assertEqual('Parents · born 1819–1822', self.band_of('p0004'))
        parents = self.room.locator('.rr-band[data-generation="1"] .rr-person')
        self.assertEqual(['p0002', 'p0003', 'p0004', 'p0007'], [p.get_attribute('data-person') for p in parents.all()])
        lefts = [self.card(pid).evaluate('n => n.getBoundingClientRect().left') for pid in ('p0002', 'p0003', 'p0004', 'p0007')]
        self.assertEqual(sorted(lefts), lefts)
        # The best-assessed father and mother first; Corin and Mira Vale, a couple, are the alternative set.
        for pid, words in (('p0004', 'Alternative father of Ada'), ('p0007', 'Alternative mother of Ada')):
            self.assertIn('rr-alt', self.card(pid).get_attribute('class'))
            self.assertIn(words, self.card(pid).inner_text())
        self.assertNotIn('rr-alt', self.card('p0002').get_attribute('class'))
        # Each parent link is a chip on the child, named because the parents compete.
        self.assertEqual(['Father (Tobin): Probable · 84%', 'Father (Corin): Possible · 30%', 'Mother (Wren): Documented', 'Mother (Mira): Possible · 20%'],
                         self.card('p0001').locator('.rr-links .rr-chip').all_inner_texts())
        self.assertIn('badge-probable', self.card('p0001').locator('.rr-chip').first.get_attribute('class'))
        # Lines: the alternative set joins Ada by a dashed line of its own; Tobin and Wren by a solid one.
        self.assertEqual(1, self.room.locator('path.rr-link.rr-alt.rr-uncertain').count())
        self.assertEqual(3, self.room.locator('path.rr-join.rr-coparent').count())  # Tobin–Wren, Corin–Mira and Old–Elsa
        # Iris, a sister, has only her two documented links, unnamed on screen but named for a screen reader.
        self.assertEqual(['Father: Documented', 'Mother: Documented'], [t.split(' (')[0] for t in self.card('p0020').locator('.rr-chip').all_text_contents()])
        self.assertIn('(Tobin Fable)', self.card('p0020').locator('.rr-chip').first.text_content())
        # The disproved father is not drawn: he is listed in the Rejected strip under the parents' band.
        self.assertEqual(0, self.card('p0006').count())
        strips = self.room.locator('.rr-rejected')
        self.assertEqual(['Rowan Fable as father of Ada Fable Disproved', 'Ada Fable as mother of Nell Fable Disproved'],
                         [' '.join(s.locator('li').inner_text().split()) for s in strips.all()])
        self.assertEqual('Parents · born 1819–1822', strips.first.evaluate("n => n.closest('.rr-band').querySelector('.rr-band-label').textContent"))
        self.assertEqual('Children · born 1875–1878', strips.nth(1).evaluate("n => n.closest('.rr-band').querySelector('.rr-band-label').textContent"))
        self.assertNotIn(SECRET, self.page.content())
        self.assertNotIn(SECRET_LINK, self.page.content())

    def test_fold_buttons_steppers_siblings_and_direction(self):
        self.open()
        grand = self.card('p0201').locator('[data-fold="down"]')
        self.assertEqual('false', grand.get_attribute('aria-expanded'))
        self.assertEqual('Open the children of Grand Fable (1 child)', grand.get_attribute('aria-label'))
        grand.click()
        self.assertEqual(1, self.card('p0301').count())
        self.assertEqual('Great-grandchildren · born 1925', self.bands()[-1])
        focused = self.page.evaluate("document.activeElement.closest('.rr-person').dataset.person + ' ' + document.activeElement.dataset.fold")
        self.assertEqual('p0201 down', focused)
        self.assertEqual('true', self.card('p0201').locator('[data-fold="down"]').get_attribute('aria-expanded'))
        self.assertIn('Showing the children of Grand Fable', self.room.locator('[role=status]').inner_text())
        self.page.keyboard.press('Enter')  # the same button, still focused, folds the line again
        self.assertEqual(0, self.card('p0301').count())
        # A sibling's line starts folded.
        iris = self.card('p0020').locator('[data-fold="down"]')
        self.assertEqual('false', iris.get_attribute('aria-expanded'))
        iris.click()
        self.assertEqual('Children · born 1870–1878', self.band_of('p0120'))
        # Fold away the parents above Tobin: the grandparents' and great-grandparents' bands go.
        self.card('p0002').locator('[data-fold="up"]').click()
        self.assertEqual('Parents · born 1819–1822', self.bands()[0])
        self.card('p0002').locator('[data-fold="up"]').click()
        self.assertEqual(6, len(self.bands()))
        # Ancestors − / +.
        fewer = self.room.get_by_role('button', name='Fewer ancestors generations')
        fewer.click()
        self.assertEqual('2', self.room.locator('.rr-step output').first.inner_text())
        self.assertEqual('Grandparents · born 1790–1792', self.bands()[0])
        fewer.click()
        fewer.click()
        self.assertTrue(fewer.is_disabled())
        self.assertEqual('This generation · born 1848–1855', self.bands()[0])
        self.assertEqual(0, self.room.locator('.rr-rejected', has_text='Rowan').count())
        self.room.get_by_role('button', name='More ancestors generations').click()
        self.assertEqual('Parents · born 1819–1822', self.bands()[0])
        # A stepper resets the lines opened one by one in its direction: Iris's daughter goes with the grandchildren.
        self.room.get_by_role('button', name='Fewer descendants generations').click()
        self.assertEqual('Children · born 1875–1878', self.bands()[-1])
        # Siblings off: only Ada and her husband in her generation.
        siblings = self.room.get_by_role('button', name='Siblings')
        self.assertEqual('true', siblings.get_attribute('aria-pressed'))
        siblings.click()
        self.assertEqual('false', siblings.get_attribute('aria-pressed'))
        self.assertEqual(0, self.card('p0020').count())
        self.assertEqual('This generation · born 1848–1850', self.band_of('p0001'))
        siblings.click()
        # Horizontal: generations run left to right, ancestors first.
        self.room.get_by_role('button', name='↔ Horizontal').click()
        self.assertEqual('true', self.room.get_by_role('button', name='↔ Horizontal').get_attribute('aria-pressed'))
        self.assertIn('rr-horizontal', self.room.locator('.rr-stage').get_attribute('class'))
        x = lambda pid: self.card(pid).evaluate('n => n.getBoundingClientRect().left')
        self.assertLess(x('p0002'), x('p0001'))
        self.assertLess(x('p0001'), x('p0101'))
        self.assertGreater(self.card('p0004').evaluate('n => n.getBoundingClientRect().top'), self.card('p0003').evaluate('n => n.getBoundingClientRect().top'))
        self.room.get_by_role('button', name='↕ Vertical').click()
        y = lambda pid: self.card(pid).evaluate('n => n.getBoundingClientRect().top')
        self.assertLess(y('p0002'), y('p0001'))
        # The settings outlive centring on someone else.
        self.card('p0005').locator('.rr-name').click()
        self.assertEqual('Bram & family', self.room.locator('h2').inner_text())
        self.assertEqual('1', self.room.locator('.rr-step output').nth(1).inner_text())

    def test_centre_keyboard_zoom_and_address(self):
        self.open()
        # Arrow keys move between cards along a band and to the nearest card in the next band.
        self.card('p0001').locator('.rr-name').focus()
        self.page.keyboard.press('ArrowRight')
        self.assertEqual('p0005', self.page.evaluate("document.activeElement.closest('.rr-person').dataset.person"))
        self.page.keyboard.press('ArrowDown')
        self.assertEqual('p0102', self.page.evaluate("document.activeElement.closest('.rr-person').dataset.person"))
        self.page.keyboard.press('ArrowUp')
        self.page.keyboard.press('ArrowUp')
        self.assertEqual('Parents · born 1819–1822', self.page.evaluate("document.activeElement.closest('.rr-band').querySelector('.rr-band-label').textContent"))
        # Enter on a card centres the room there and the address follows.
        self.page.keyboard.press('Enter')
        self.assertIn(self.page.locator('#tree-root').input_value(), {'p0002', 'p0003', 'p0004', 'p0007'})
        self.card('p0001').locator('.rr-name').click()
        self.assertEqual('p0001', self.page.locator('#tree-root').input_value())
        self.card('p0101').locator('.rr-name').click()
        self.assertTrue(self.page.url.endswith('#view=branches&person=p0101'))
        self.assertEqual('Child One Fable', self.page.get_by_role('combobox', name='Find a person to explore from').input_value())
        self.page.reload(wait_until='networkidle')
        self.assertEqual('Child & family', self.room.locator('h2').inner_text())
        # The shared zoom buttons drive the room.
        self.page.get_by_role('button', name='Zoom in').click()
        self.assertEqual('125%', self.room.locator('.rr-zoom').inner_text())
        self.assertIn('scale(1.25)', self.room.locator('.rr-stage').get_attribute('style'))
        # Back to canopy opens the first view; leaving the room clears its address.
        self.room.get_by_role('button', name='← Back to canopy').click()
        self.assertEqual('true', self.page.locator('.tree-modes button').first.get_attribute('aria-pressed'))
        self.assertEqual(0, self.room.count())
        self.assertNotIn('#', self.page.url)
        # The query form of the address still works.
        self.page.goto(f'{self.base}room/tree.html?person=p0020&view=branches', wait_until='networkidle')
        self.assertEqual('Iris & family', self.room.locator('h2').inner_text())

    def test_large_tree_stays_within_the_profile_limit(self):
        self.page.goto(f'{self.base}large/tree.html', wait_until='networkidle')
        self.page.locator('[data-tree-view="branches"]').click()
        self.room.wait_for()
        count = self.room.locator('.rr-person').count()
        self.assertGreater(count, 1)
        self.assertLessEqual(count, 120)
        for _ in range(3):
            self.room.get_by_role('button', name='More descendants generations').click()
        self.assertLessEqual(self.room.locator('.rr-person').count(), 120)

    def test_withheld_records_reach_no_file(self):
        for path in (self.root / 'room').rglob('*'):
            if path.is_file():
                text = path.read_text(encoding='utf-8', errors='ignore')
                self.assertNotIn(SECRET, text, path)
                self.assertNotIn(SECRET_LINK, text, path)

    @unittest.skipUnless(os.environ.get('GENEALOGY_AXE_PATH'), 'set GENEALOGY_AXE_PATH to an axe-core axe.min.js')
    def test_wcag_aa_at_both_widths_in_both_directions(self):
        axe = Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8')
        for width in (1440, 390):
            for direction in ('↕ Vertical', '↔ Horizontal'):
                with self.subTest(width=width, direction=direction):
                    self.page.set_viewport_size({'width': width, 'height': 900})
                    self.open()
                    self.room.get_by_role('button', name=direction).click()
                    self.card('p0020').locator('[data-fold="down"]').click()
                    self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
                    self.page.add_script_tag(content=axe)
                    violations = self.page.evaluate(
                        "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                        "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                        ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
                    self.assertEqual([], violations)


if __name__ == '__main__':
    unittest.main()
