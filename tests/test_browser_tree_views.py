"""Opt-in browser contract for the hourglass, family sun and lanes views of tree.html."""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
import threading
import unittest

from genealogy.case import CaseStore, ResearchCase
from genealogy.config import ProjectConfig
from genealogy.models import AccessLevel as A, Confidence as C, Event, LivingStatus as L, Name, Person, Relationship
from genealogy.site import build_site

ROOT = Path(__file__).resolve().parents[1]
SECRET = "SECRET-Hidden Fable"


def person(pid, name, born, died=None, access=A.PUBLIC):
    records = [Person(pid, names=[Name(name, surname=name.split()[-1])], living=L.DECEASED, sensitivity=access,
                      event_ids=[f"{pid}-b"] + ([f"{pid}-d"] if died else [])),
               Event(f"{pid}-b", "birth", date=str(born), participant_ids=[pid], sensitivity=access)]
    if died:
        records.append(Event(f"{pid}-d", "death", date=str(died), participant_ids=[pid], sensitivity=access))
    return records


def parent(rid, child, of, confidence=C.DOCUMENTED, access=A.PUBLIC):
    return Relationship(rid, child, of, "parent", confidence=confidence, sensitivity=access)


def views_case():
    """Ada Fable: three competing parents, 8 children with 8 children each, a cousin couple's child and a withheld child."""
    case = ResearchCase("fictional-tree-views", "Fictional tree views")
    records = [*person("p0001", "Ada Fable", 1850, 1920), *person("p0002", "Tobin Fable", 1820, 1880),
               *person("p0003", "Wren Fable", 1822, 1890), *person("p0004", "Corin Vale", 1819),
               parent("r-at", "p0001", "p0002"), parent("r-aw", "p0001", "p0003"), parent("r-ac", "p0001", "p0004", C.POSSIBLE),
               # A marriage with no year is listed under the lanes, not drawn on them.
               Event("e-wed", "marriage", date="unknown", participant_ids=["p0001"], sensitivity=A.PUBLIC),
               *person("p0005", "Bram Fable", 1848, 1915),
               Relationship("r-ab", "p0001", "p0005", "spouse", confidence=C.PROBABLE, sensitivity=A.PUBLIC),
               *person("p0900", SECRET, 1880, access=A.PRIVATE), parent("r-secret", "p0900", "p0001", access=A.PRIVATE)]
    for c in range(8):
        cid = f"p01{c:02d}"
        records += [*person(cid, f"Child{c} Fable", 1875 + c, 1940 + c), parent(f"r-{cid}", cid, "p0001")]
        for g in range(8):
            gid = f"p1{c}{g:02d}"
            records += [*person(gid, f"Grand{c}x{g} Fable", 1900 + g), parent(f"r-{gid}", gid, cid)]
    # Two cousins' child descends from Ada through both lines.
    records += [*person("p9001", "Cousin Fable", 1930), parent("r-c1", "p9001", "p1000"), parent("r-c2", "p9001", "p1100")]
    for record in records:
        case.add(record)
    return case


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1',
                     'Run make browser-check with the browser extra installed')
class TreeViewBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        config = ProjectConfig.load(ROOT / 'examples/demo/genealogy.toml')
        build_site(CaseStore(ROOT / 'examples/demo/cases').load(config.default_case), config, cls.root / 'demo')
        build_site(views_case(), ProjectConfig(name='Fictional tree views'), cls.root / 'views')
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
        self.page.on('console', lambda m: self.errors.append(m.text) if m.type == 'warning' else None)

    def tearDown(self):
        self.context.close()
        self.assertEqual([], self.errors, 'Browser runtime errors')

    def open(self, site, person, view):
        self.page.goto(f'{self.base}{site}/tree.html?person={person}', wait_until='networkidle')
        self.page.locator(f'[data-tree-view="{view}"]').click()
        self.assertEqual('true', self.page.locator(f'[data-tree-view="{view}"]').get_attribute('aria-pressed'))

    def test_hourglass_rows_expand_fold_and_dashed_parents(self):
        nodes = self.page.locator('[data-hourglass] .tree-node')
        # Vera Cairn: her parent and grandparent above, her daughter below.
        self.open('demo', 'person:21', 'hourglass')
        self.assertEqual(4, nodes.count())
        self.assertIn('2 ancestors in 2 generations above, 1 descendant in 1 generation below, 0 spouses or partners',
                      self.page.locator('[data-hourglass]').get_attribute('aria-label'))
        # Ada Alder: Bram beside her, four children with their spouses, eight grandchildren; great-grandchildren folded.
        self.page.locator('#tree-root').select_option('person:01', force=True)
        self.assertEqual(18, nodes.count())
        vera = self.page.locator('[data-hourglass] [data-person="person:21"]')
        self.assertEqual('false', vera.get_attribute('aria-expanded'))
        self.assertIn('Show 1 child', vera.get_attribute('aria-label'))
        vera.focus()
        self.page.keyboard.press('Enter')
        self.assertEqual(19, nodes.count())
        self.assertEqual('true', self.page.locator('[data-hourglass] [data-person="person:21"]').get_attribute('aria-expanded'))
        self.assertEqual('person:21', self.page.evaluate('document.activeElement.dataset.person'))
        self.page.locator('[data-hourglass] [data-person="person:21"]').click()
        self.assertEqual(18, nodes.count())
        # The text version lists every generation drawn.
        text = self.page.locator('details.tree-text')
        text.locator('summary').click()
        self.assertEqual(['Focus person', 'Spouses and partners', 'Children', 'Grandchildren'], text.locator('h2').all_inner_texts())
        # Zoom buttons drive the view.
        self.page.get_by_role('button', name='Zoom in').click()
        self.assertIn('scale(1.25)', self.page.locator('[data-hourglass] > g').get_attribute('transform'))
        # Quill Ember's link to Arden is only possible: dashed.
        self.page.locator('#tree-root').select_option('person:42', force=True)
        self.assertEqual(1, self.page.locator('[data-hourglass] path.tree-edge.uncertain').count())
        self.assertIn('Possible', self.page.locator('[data-hourglass] [data-person="person:26"]').get_attribute('aria-label'))

    def test_hourglass_caps_at_sixty_and_marks_candidate_parents(self):
        self.open('views', 'p0001', 'hourglass')
        self.assertEqual(60, self.page.locator('[data-hourglass] .tree-node').count())
        self.assertIn('more not drawn (60-person limit)', self.page.locator('#tree-output .hint').inner_text())
        candidate = self.page.locator('[data-hourglass] [data-person="p0004"]')
        self.assertIn('candidate', candidate.get_attribute('class'))
        self.assertIn('candidate parent', candidate.get_attribute('aria-label'))
        self.assertEqual(1, self.page.locator('[data-hourglass] path.tree-edge.candidate').count())
        self.assertNotIn(SECRET, self.page.content())

    def test_family_sun_rings_and_refocus(self):
        slices = self.page.locator('[data-sun] .sun-slice')
        self.open('demo', 'person:01', 'sun')
        self.assertEqual(18, slices.count())
        self.assertEqual(['1', '2', '3'], sorted({s.get_attribute('data-generation') for s in slices.all()}))
        self.assertIn('Generation 3 · great-grandchildren: 6', self.page.locator('.sun-legend').inner_text())
        elara = self.page.locator('[data-sun] .sun-slice[data-person="person:05"]')
        # Ada's four children share the ring by descendants: each has four or two below them.
        elara.focus()
        self.assertIn('Elara Cairn', self.page.locator('.sun-readout').inner_text())
        self.assertIn('generation 1', self.page.locator('.sun-readout').inner_text())
        elara.click()
        self.assertEqual('person:05', self.page.locator('#tree-root').input_value())
        self.assertEqual(4, slices.count())
        self.assertIn('Family sun for Elara Cairn', self.page.locator('[data-sun]').get_attribute('aria-label'))
        # Keyboard refocus; Liora Cairn has no children.
        self.page.locator('[data-sun] .sun-slice[data-person="person:37"]').focus()
        self.page.keyboard.press('Enter')
        self.assertEqual(0, slices.count())
        self.assertIn('No descendants of Liora Cairn', self.page.locator('#tree-output').inner_text())

    def test_family_sun_draws_a_second_line_as_an_outline(self):
        self.open('views', 'p0001', 'sun')
        slices = self.page.locator('[data-sun] .sun-slice')
        self.assertEqual(8 + 64 + 2, slices.count())
        self.assertEqual(1, self.page.locator('[data-sun] .sun-slice.again').count())
        self.assertIn('and 1 reached again through another line', self.page.locator('.sun-legend').inner_text())
        self.assertNotIn(SECRET, self.page.content())

    def test_lanes_bars_and_events_without_years(self):
        bars = self.page.locator('[data-lanes] rect.lane-bar')
        self.open('demo', 'person:21', 'lanes')
        self.assertEqual(5, bars.count())
        self.assertEqual(['Parents\' family: Elara Cairn', 'Own family: Vera Cairn'], self.page.locator('[data-lanes] .lane-head').all_text_contents())
        # Elara: Ada's family (5), her own (4) and her two children's families (2 each).
        self.page.locator('#tree-root').select_option('person:05', force=True)
        self.assertEqual(4, self.page.locator('[data-lanes] .lane-head').count())
        self.assertEqual(13, bars.count())
        self.open('views', 'p0001', 'lanes')
        self.assertEqual(1 + 1 + 8, self.page.locator('[data-lanes] .lane-head').count())  # parents', own, each child's
        self.assertEqual(['Ada Fable · marriage (unknown)'], self.page.locator('.lanes-undated li').all_inner_texts())
        # Corin Vale and the 64 grandchildren have a birth and no death: faded bars.
        self.assertEqual(1 + 64, self.page.locator('[data-lanes] rect.lane-bar.open').count())
        self.assertNotIn(SECRET, self.page.content())

    def test_withheld_child_is_absent_from_every_file(self):
        for path in (self.root / 'views').rglob('*'):
            if path.is_file():
                self.assertNotIn(SECRET, path.read_text(encoding='utf-8', errors='ignore'), path)

    @unittest.skipUnless(os.environ.get('GENEALOGY_AXE_PATH'), 'set GENEALOGY_AXE_PATH to an axe-core axe.min.js')
    def test_wcag_aa_in_each_view_at_both_widths(self):
        axe = Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8')
        for width in (1440, 390):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for view, person in (('hourglass', 'person:01'), ('sun', 'person:01'), ('lanes', 'person:05')):
                with self.subTest(width=width, view=view):
                    self.page.goto(f'{self.base}demo/tree.html?person={person}&view={view}', wait_until='networkidle')
                    self.assertEqual('true', self.page.locator(f'[data-tree-view="{view}"]').get_attribute('aria-pressed'))
                    self.page.locator('details.tree-text summary').click()
                    self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
                    self.page.add_script_tag(content=axe)
                    violations = self.page.evaluate(
                        "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                        "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                        ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
                    self.assertEqual([], violations)


if __name__ == '__main__':
    unittest.main()
