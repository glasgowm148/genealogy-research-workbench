"""About the data, the change log and the described downloads on the site index."""
from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.labels import guide_entries
from genealogy.models import (AccessLevel as A, Citation, Confidence as C, Event, Finding, LivingStatus as L, Name, Person, Place,
                              Relationship, Source, Study)
from genealogy.site import ROUTES, build_site

GRADES = {"strongly_supported": {"label": "Strongly supported", "meaning": "Several records agree.", "confidence": "probable"}}


def person(pid, name, events=(), sensitivity=A.PUBLIC):
    return Person(pid, names=[Name(name, surname=name.split()[-1])], living=L.DECEASED, event_ids=list(events), sensitivity=sensitivity)


def case(extra=()):
    """Five public people, counted differently by each view.

    Ada and Bram are linked (in the tree); Ada was born at a place with coordinates
    (on the map), Bram at one without. Cara and Dora are linked only by a disproved
    link, so the tree draws neither. Eli has nothing but a dated finding.
    """
    c = ResearchCase("fictional-about", "Fictional about")
    c.add_many([
        Place("town", "Invented Town, Fableshire", latitude=51.5, longitude=-1.2, sensitivity=A.PUBLIC),
        Place("parish", "Invented Parish, Fableshire", sensitivity=A.PUBLIC),
        Source("register", "Invented register", "register", sensitivity=A.PUBLIC),
        Citation("register-1", "register", locator="entry 1", quality="original", sensitivity=A.PUBLIC),
        Citation("register-secret", "register", locator="SECRET-ABOUT-LOCATOR", information="secondary", sensitivity=A.PRIVATE),
        person("ada", "Ada Fable", ["ada-b"]), person("bram", "Bram Fable", ["bram-b"]),
        person("cara", "Cara Cairn"), person("dora", "Dora Cairn"), person("eli", "Eli Lone"),
        Event("ada-b", "birth", date="1801", place_id="town", participant_ids=["ada"], sensitivity=A.PUBLIC),
        Event("bram-b", "birth", date="1770", place_id="parish", participant_ids=["bram"], sensitivity=A.PUBLIC),
        Relationship("ada-bram", "ada", "bram", "parent", confidence=C.DOCUMENTED, sensitivity=A.PUBLIC),
        Relationship("cara-dora", "cara", "dora", "parent", confidence=C.DISPROVED, sensitivity=A.PUBLIC),
        Finding("f-sep", "Ada's baptism entry names Bram as her father.", related_ids=["ada", "bram"], recorded_on="2026-09-14",
                status="reviewed", sensitivity=A.PUBLIC),
        Finding("f-oct", "Eli Lone appears in the invented register.", related_ids=["eli"], recorded_on="2026-10-02",
                status="reviewed", sensitivity=A.PUBLIC),
        Finding("f-undated", "An undated note about Cara.", related_ids=["cara"], status="draft", sensitivity=A.PUBLIC),
        Study("study", "The Fable household", summary="Who lived with Ada.", related_ids=["ada"], updated_on="2026-08-01",
              status="reviewed", sensitivity=A.PUBLIC),
        # Withheld: a private person, their finding and a private study dated later than everything public.
        person("secret", "SECRET-ABOUT-PERSON", ["secret-b"], sensitivity=A.PRIVATE),
        Event("secret-b", "birth", date="1802", place_id="town", participant_ids=["secret"], sensitivity=A.PRIVATE),
        Finding("f-secret", "SECRET-ABOUT-FINDING", related_ids=["secret"], recorded_on="2026-12-31", sensitivity=A.PRIVATE),
        Study("study-secret", "SECRET-ABOUT-STUDY", summary="SECRET-ABOUT-SUMMARY", updated_on="2027-01-01", sensitivity=A.PRIVATE),
        *extra,
    ])
    assert validate_case(c) == [], validate_case(c)
    return c


def build(directory, c=None):
    build_site(c or case(), ProjectConfig(name="Fictional about", grades=GRADES), Path(directory))
    return Path(directory)


def section(html, anchor):
    start = html.index(f'id="{anchor}"')
    end = html.find("<h2", start + 1)
    return html[start:end if end > 0 else len(html)]


class AboutDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.out = build(cls.directory.name)
        cls.about = (cls.out / "about-data.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_routes_are_registered_and_linked_from_every_page(self):
        self.assertEqual(("about-data", "About the data"), ROUTES["about-data.html"])
        self.assertEqual(("changes", "Change log"), ROUTES["changes.html"])
        for page in ("index.html", "about-data.html", "changes.html"):
            html = (self.out / page).read_text(encoding="utf-8")
            self.assertIn('href="about-data.html"', html, page)
            self.assertIn('href="changes.html"', html, page)
        self.assertIn('<title>About the data — Fictional about</title>', self.about)

    def test_headline_counts_are_dated_by_the_newest_public_finding_or_study(self):
        counts = self.about[self.about.index('class="stats about-counts"'):self.about.index('id="totals"')]
        for number, words in (("5", "People in the catalogue"), ("2", "Events"), ("2", "Places"), ("1", "Sources")):
            self.assertRegex(counts, rf'<strong>{number}</strong><small><a href="[a-z]+\.html">{words}</a></small>')
        # The newest public date is the October finding; the private finding and study are later but withheld.
        self.assertEqual(4, counts.count('<small class="stat-date">as of <time datetime="2026-10-02">2 Oct 2026</time></small>'))
        self.assertIn('study update, <time datetime="2026-10-02">2 Oct 2026</time>, not the date the site was built.', counts)
        self.assertNotIn("2026-12-31", self.about)
        self.assertNotIn("2027", self.about)

    def test_the_stamp_falls_back_to_a_study_date_and_says_when_nothing_is_dated(self):
        c = case()
        for f in list(c.records("Finding")):
            f.recorded_on = None
        with tempfile.TemporaryDirectory() as directory:
            about = (build(directory, c) / "about-data.html").read_text(encoding="utf-8")
            self.assertIn('<time datetime="2026-08-01">1 Aug 2026</time>', about)
        c = ResearchCase("fictional-empty", "Empty")
        c.add_many([person("ada", "Ada Fable")])
        with tempfile.TemporaryDirectory() as directory:
            about = (build(directory, c) / "about-data.html").read_text(encoding="utf-8")
            self.assertIn("No public finding or study is dated yet", about)
            self.assertNotIn("<time", about)

    def test_page_totals_are_reconciled_view_by_view(self):
        totals = section(self.about, "totals")
        rows = dict(re.findall(r'<tr><th scope="row"><a href="[a-z]+\.html">([^<]+)</a></th><td>([\d,]+)</td>', totals))
        self.assertEqual({"In the catalogue": "5", "In the family tree": "2", "On the map": "1", "With a dated finding": "3"}, rows)
        self.assertIn("a disproved link is not drawn", totals)
        self.assertIn("No pin is made from a place name alone", totals)
        self.assertIn("<td>40%</td>", totals)

    def test_the_legend_draws_every_badge_and_links_every_guide_entry(self):
        legend = section(self.about, "legend")
        for anchor, label, _meaning, _group in guide_entries(GRADES):
            if anchor.startswith(("quality-", "information-")):
                continue  # only the terms public citations state; see below
            self.assertIn(f'evidence.html#{anchor}"', legend, anchor)
        # Badges use the same markup as every page, so they carry the same stored values.
        self.assertIn('<a class="badge evidence-badge badge-documented" href="evidence.html#confidence-documented" data-confidence="documented"><span class="badge-glyph" aria-hidden="true">✓</span>Documented</a>', legend)
        self.assertIn('href="evidence.html#grade-strongly_supported" data-confidence="probable" data-grade="strongly_supported"><span class="badge-glyph" aria-hidden="true">~</span>Strongly supported</a>', legend)
        # A tree's own mark is its own badge beside the unassessed link it qualifies.
        self.assertIn('data-tree-status="uncertain"><span class="badge-glyph" aria-hidden="true">○</span>Unassessed tree link</a> '
                      '<a class="badge evidence-badge badge-tree" href="evidence.html#tree-marked"><span class="badge-glyph" aria-hidden="true">◇</span>Tree-marked uncertain</a>', legend)
        self.assertIn('<span class="record-quality"><a class="badge badge-kind" href="evidence.html#quality-original" data-quality="original">Original record</a></span>', legend)
        # A term no public citation states is not listed: the private citation's "secondary" stays unseen.
        self.assertNotIn("quality-derivative", legend)
        self.assertNotIn("Secondary information", legend)
        self.assertIn('href="evidence.html#record-quality"', legend)
        self.assertIn('<a class="badge evidence-badge badge-documented change" href="evidence.html#confidence-documented" data-after="documented" data-before="possible"><span class="badge-glyph" aria-hidden="true">✓</span>Possible → Documented</a>', legend)
        for cls, words in (("tree-edge", "Solid"), ("tree-edge uncertain", "Dashed"), ("tree-edge uncertain candidate", "candidate parent")):
            self.assertIn(f'<path class="{cls}" d="M2 6H46"/>', legend)
            self.assertIn(words, legend)

    def test_the_method_note_links_the_guide_privacy_and_downloads(self):
        method = section(self.about, "method")
        self.assertIn('href="evidence.html#privacy"', method)
        self.assertIn('href="evidence.html"', method)
        self.assertIn('id="privacy"', (self.out / "evidence.html").read_text(encoding="utf-8"))
        downloads = section(self.about, "downloads")
        for path in ("data/site.json", "data/site.csv", "data/places.geojson", "data/public-tree.ged", "data/routes.json"):
            self.assertIn(f'<a class="button" href="{path}">', downloads)
        self.assertIn('href="sitemap.html#downloads"', downloads)

    def test_the_site_index_describes_each_download_with_its_size(self):
        from genealogy.home import file_size
        sitemap = (self.out / "sitemap.html").read_text(encoding="utf-8")
        table = section(sitemap, "downloads")
        self.assertIn("<caption>Downloads: format, size and what each file holds</caption>", table)
        rows = re.findall(r'<tr><td data-label="File"><a href="([^"]+)">[^<]+</a><br><span class="record-id">\1</span></td><td data-label="Format">([^<]*)</td>'
                          r'<td data-label="Size">([^<]*)</td><td data-label="What it holds">([^<]*)</td></tr>', table)
        listed = {path: (fmt, size, what) for path, fmt, size, what in rows}
        self.assertEqual({"data/site.json", "data/site.csv", "data/places.geojson", "data/public-tree.ged", "data/routes.json",
                          "data/progress-history.json"}, set(listed))
        self.assertEqual("GEDCOM 5.5.1", listed["data/public-tree.ged"][0])
        for path, (_fmt, size, what) in listed.items():
            self.assertEqual(file_size((self.out / path).stat().st_size), size, path)
            self.assertTrue(what, path)
        self.assertIn("Downloads contain only the public records shown on this site.", sitemap)

    def test_feeds_are_described_when_a_base_url_is_set(self):
        with tempfile.TemporaryDirectory() as directory:
            build_site(case(), ProjectConfig(name="Fictional about", raw={"site": {"base_url": "https://example.invalid/"}}), Path(directory))
            table = section((Path(directory) / "sitemap.html").read_text(encoding="utf-8"), "downloads")
            self.assertIn('<a href="findings.xml">', table)
            self.assertIn('<td data-label="Format">Atom feed</td>', table)
            self.assertIn('<a href="sitemap.xml">', table)

    def test_a_rebuild_of_the_same_research_is_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            out = build(directory)
            for page in ("about-data.html", "changes.html", "sitemap.html"):
                self.assertEqual((self.out / page).read_text(encoding="utf-8"), (out / page).read_text(encoding="utf-8"), page)
            build(directory)
            for page in ("about-data.html", "changes.html", "sitemap.html"):
                self.assertEqual((self.out / page).read_text(encoding="utf-8"), (out / page).read_text(encoding="utf-8"), page)

    def test_withheld_records_reach_no_output(self):
        for path in self.out.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("SECRET-ABOUT", text, path)


class ChangeLogTests(unittest.TestCase):
    def test_cards_count_what_changed_since_the_previous_snapshot(self):
        later = [person("finn", "Finn Fable"),
                 Relationship("finn-ada", "finn", "ada", "parent", confidence=C.PROBABLE, sensitivity=A.PUBLIC),
                 Finding("f-nov", "Finn Fable was Ada's son.", related_ids=["finn", "ada"], recorded_on="2026-11-05", status="reviewed",
                         sensitivity=A.PUBLIC, changes=[{"record_id": "finn-ada", "before": "possible", "after": "probable", "note": None}])]
        with tempfile.TemporaryDirectory() as directory:
            first = (build(directory) / "changes.html").read_text(encoding="utf-8")
            self.assertEqual(1, first.count("<h2>Catalogue snapshot</h2>"))
            self.assertIn("The first snapshot kept.", first)
            html = (build(directory, case(later)) / "changes.html").read_text(encoding="utf-8")
        self.assertIn('Looking for new facts? <a href="findings.html">Latest findings →</a>', html)
        cards = re.findall(r'<li><article class="card change-card">(.*?)</article></li>', html)
        heads = [re.search(r'<time datetime="([^"]+)">[^<]+</time></p><h2>([^<]+)</h2>', card).groups() for card in cards]
        self.assertEqual([("2026-11-05", "Catalogue snapshot"), ("2026-11-05", "Research, November 2026"),
                          ("2026-10-02", "Catalogue snapshot"), ("2026-10-02", "Research, October 2026"),
                          ("2026-09-14", "Research, September 2026")], heads)
        newest = cards[0]
        self.assertIn("<dt>People</dt><dd>6 <span class=\"meta\">(+1)</span></dd>", newest)
        # The disproved Cairn link counts as assessed, as on the progress page.
        self.assertIn("<dt>Assessed links</dt><dd>3 <span class=\"meta\">(+1)</span></dd>", newest)
        self.assertIn('+1 person, +1 person with an assessed parent, +1 parent link, +1 assessed link since <time datetime="2026-10-02">2 Oct 2026</time>.', newest)
        self.assertIn('href="progress.html#history">Research progress →</a>', newest)
        november = cards[1]
        self.assertIn("<dt>Findings</dt><dd>1</dd>", november)
        self.assertIn("<dt>Grades changed</dt><dd>1</dd>", november)
        self.assertRegex(november, r'<dt>People</dt><dd><a href="people/p-[0-9a-f]{64}\.html">Finn Fable</a>, <a href="people/p-[0-9a-f]{64}\.html">Ada Fable</a></dd>')
        self.assertIn("Newest: Finn Fable was Ada&#x27;s son.", november)
        self.assertRegex(november, r'<a href="research\.html#r-[0-9a-f]{64}">Read the finding →</a>')
        # The undated finding and the withheld ones are in no card.
        self.assertNotIn("undated note", html)
        self.assertNotIn("SECRET", html)

    def test_no_dated_finding_leaves_an_empty_log(self):
        c = ResearchCase("fictional-empty", "Empty")
        c.add_many([person("ada", "Ada Fable")])
        with tempfile.TemporaryDirectory() as directory:
            html = (build(directory, c) / "changes.html").read_text(encoding="utf-8")
        self.assertIn("No public finding is dated yet", html)
        self.assertNotIn("change-grid", html)


if __name__ == "__main__":
    unittest.main()
