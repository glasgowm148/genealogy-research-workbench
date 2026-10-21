"""Large projects: no page writes out a list of thousands of records."""
from __future__ import annotations

from pathlib import Path
import json
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Citation, Claim, ClaimStatus, Event, Evidence, Finding,
                              LivingStatus as L, Name, Person, Place, Relationship, Source, Study)
from genealogy.site import (BROWSER_FIELDS, CATALOGUE_PER_PAGE, INLINE_LIMIT, PLACES_PER_PAGE, SOURCES_PER_PAGE, STUDIES_PER_PAGE,
                            _anchor, build_site)
from genealogy.sitecheck import check_site

PEOPLE = INLINE_LIMIT + 100
COUNTRIES = ("Fableland", "Inventia", "Nowhere Isles")
SOURCE_TYPES = ("census-transcription", "Will", "register", "register", "register")
CENSUS_NOTE = "A transcription can misread a name or an age; check the original schedule."


def large_case(people: int = PEOPLE) -> ResearchCase:
    case = ResearchCase("fictional-large", "Fictional large tree")
    records = [Source("register", "Invented register", "register", sensitivity=A.PUBLIC),
               Citation("register-1", "register", locator="entry 1", sensitivity=A.PUBLIC)]
    for n in range(people):
        pid = f"p{n:04d}"
        # Every 50th place has no broader jurisdiction; every other place has coordinates.
        place = Place(f"pl{n:04d}", f"Hamlet {n:04d}" if n % 50 == 0 else f"Town {n:04d}, Shire {n % 7}, {COUNTRIES[n % 3]}",
                      latitude=40 + n % 20 if n % 2 else None, longitude=-5 + n % 30 if n % 2 else None)
        records += [
            place,
            Person(pid, names=[Name(f"Person {n:04d} Fable", surname="Fable")], living=L.DECEASED,
                   event_ids=[f"{pid}-b"], sensitivity=A.PUBLIC),
            Event(f"{pid}-b", "birth", date=str(1700 + n % 150), place_id=place.id, participant_ids=[pid], sensitivity=A.PUBLIC),
            # Three record types; "register" has enough sources for several type pages.
            Source(f"{pid}-src", f"Invented register volume {n:04d}", SOURCE_TYPES[n % 5], repository=f"Archive {n % 4}", sensitivity=A.PUBLIC),
            # One citation in five is an original record, and each census transcription a derivative.
            Citation(f"{pid}-cit", f"{pid}-src", locator=f"folio {n}", sensitivity=A.PUBLIC,
                     quality="original" if n % 5 == 2 else "derivative" if n % 5 == 0 else None, information="primary" if n % 5 == 2 else None),
            Claim(f"{pid}-c", pid, "occupation", "weaver", citation_ids=["register-1", f"{pid}-cit"], status=ClaimStatus.SUPPORTED,
                  sensitivity=A.PUBLIC),
            Evidence(f"{pid}-e", f"{pid}-c", f"{pid}-cit", "The register names the trade.", sensitivity=A.PUBLIC),
            Finding(f"{pid}-f", f"Finding about person {n:04d}.", related_ids=[pid], status="reviewed", citation_ids=[f"{pid}-cit"] if n % 10 == 0 else [],
                    recorded_on=f"2026-{1 + n % 12:02d}-{1 + n % 28:02d}", sensitivity=A.PUBLIC),
            # One study per person, so the studies also pass INLINE_LIMIT.
            Study(f"{pid}-s", f"Study of person {n:04d}", summary="Whether the register entries describe one weaver.",
                  body=f"Study body {n:04d}: BODY-ONLY-ON-THE-STUDY-PAGE.", related_ids=[pid], status="reviewed" if n % 3 else "draft",
                  updated_on=f"2025-{1 + n % 12:02d}-{1 + n % 28:02d}", sensitivity=A.PUBLIC),
        ]
        if n % 40 == 0:
            records.append(Event(f"{pid}-res", "residence", place_id=place.id, participant_ids=[pid], sensitivity=A.PUBLIC))
        if n:
            records.append(Relationship(f"{pid}-r", pid, f"p{(n - 1) // 2:04d}", "parent", sensitivity=A.PUBLIC))
    records.append(Finding("open-1", "An open question still being worked.", related_ids=["p0001"], status="draft",
                           recorded_on="2026-10-20", sensitivity=A.PUBLIC))
    records.append(Study("withheld-study", "SECRET-STUDY title", summary="SECRET-STUDY summary", related_ids=["p0001"],
                         updated_on="2026-01-01", sensitivity=A.PRIVATE))
    case.add_many(records)
    return case


class LargeSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.out = Path(cls.directory.name)
        case = large_case()
        assert validate_case(case) == []
        build_site(case, ProjectConfig(name="Fictional", raw={"site": {"base_url": "https://example.invalid/"}},
                                       source_types={"census_transcription": {"label": "Census transcriptions", "note": CENSUS_NOTE}}), cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def text(self, path):
        return (self.out / path).read_text()

    def test_person_menus_and_lists_are_not_written_out(self):
        for page in ("tree.html", "compare.html", "connections.html"):
            html = self.text(page)
            self.assertLessEqual(html.count("<option"), 3, page)
            self.assertNotIn("Person 0123 Fable", html, page)
        self.assertIn(f"All {PEOPLE:,} people are listed in the", self.text("compare.html"))
        self.assertIn("recorded family connections. Each person's page lists", self.text("tree.html"))
        self.assertNotIn("Person 0123 Fable", self.text("sitemap.html"))

    def test_claims_relationships_and_findings_live_on_their_own_pages(self):
        research = self.text("research.html")
        self.assertNotIn(f'id="{_anchor("p0123-c")}"', research)
        self.assertIn("is shown, with its citations and evidence, on the page of the person", research)
        self.assertIn("An open question still being worked.", research)
        self.assertNotIn("Finding about person 0123.", research)
        # Links to a claim, relationship or finding reach the record where it is shown.
        dossier = next(p for p in (self.out / "people").glob("*.html") if 'data-person-id="p0123"' in p.read_text()).read_text()
        for record in ("p0123-c", "p0123-e", "p0123-r"):
            self.assertIn(f'id="{_anchor(record)}"', dossier)
        self.assertIn(f'#{_anchor("p0123-f")}', dossier)
        self.assertEqual([], check_site(self.out)["broken"])

    def test_pages_stay_small(self):
        sizes = {str(p.relative_to(self.out)): p.stat().st_size for p in self.out.rglob("*.html")}
        for name in ("tree.html", "compare.html", "connections.html", "research.html", "sitemap.html", "findings.html", "index.html",
                     "catalogue.html", "timeline.html", "places.html", "studies.html", "studies/page-1.html"):
            self.assertIn(name, sizes)
        for name, size in sizes.items():
            self.assertLess(size, 100_000, name)

    def test_the_catalogue_writes_one_page_and_keeps_the_rest_on_paged_pages(self):
        catalogue = self.text("catalogue.html")
        self.assertEqual(CATALOGUE_PER_PAGE, catalogue.count("<tr data-person-id="))
        self.assertIn(f'data-total="{PEOPLE}"', catalogue)
        pages = sorted((self.out / "catalogue").glob("page-*.html"))
        self.assertEqual(-(-PEOPLE // CATALOGUE_PER_PAGE) - 1, len(pages))
        listed = re.findall(r'<tr data-person-id="([^"]+)"', catalogue + "".join(p.read_text() for p in pages))
        self.assertEqual(sorted(f"p{n:04d}" for n in range(PEOPLE)), sorted(listed))
        # Every page links to every other, in name order, and the links resolve.
        self.assertIn('href="../catalogue/page-2.html" aria-current="page">Person 0100 Fable – Person 0199 Fable', self.text("catalogue/page-2.html"))
        self.assertIn('<a href="../people/', self.text("catalogue/page-2.html"))
        self.assertEqual([], check_site(self.out)["broken"])

    def test_the_timeline_has_a_page_per_decade(self):
        timeline = self.text("timeline.html")
        self.assertNotIn("data-event-id", timeline)
        self.assertIn('<a href="timeline/1700s.html">1700s</a>', timeline)
        self.assertIn('<a href="timeline/undated.html">Events without a recorded year</a>', timeline)
        decade = self.text("timeline/1700s.html")
        self.assertIn(f'id="{_anchor("p0000-b")}"', decade)
        self.assertNotIn(f'id="{_anchor("p0010-b")}"', decade)
        self.assertIn(f'id="{_anchor("p0010-b")}"', self.text("timeline/1710s.html"))
        self.assertIn(f'id="{_anchor("p0040-res")}"', self.text("timeline/undated.html"))
        self.assertIn('<a href="1710s.html">1710s →</a>', decade)
        self.assertIn("<title>Timeline: 1700s —", decade)

    def test_places_have_pages_per_region(self):
        places = self.text("places.html")
        self.assertNotIn("<circle", places)
        self.assertIn("places have supplied coordinates. The map needs JavaScript", places)
        self.assertIn('<a href="places/fableland.html">Fableland</a>', places)
        self.assertIn('<a href="places/other.html">Places without a broader jurisdiction</a>', places)
        self.assertNotIn(f'id="{_anchor("pl0003")}"', places)
        first, second = self.text("places/fableland.html"), self.text("places/fableland--2.html")
        self.assertEqual(PLACES_PER_PAGE, first.count("<h3>"))
        self.assertIn(f'id="{_anchor("pl0003")}"', first + second)
        self.assertIn('href="fableland--2.html">Page 2</a>', first)
        self.assertIn(f'id="{_anchor("pl0050")}"', self.text("places/other.html"))
        # A place's events are listed with it, linking to the people.
        self.assertIn("../people/", self.text("places/other.html"))

    def test_sources_write_one_page_and_keep_the_rest_on_paged_pages(self):
        sources = self.text("sources.html")
        self.assertEqual(SOURCES_PER_PAGE, sources.count("data-source-id="))
        self.assertIn(f'data-total="{PEOPLE + 1}"', sources)
        pages = sorted((self.out / "sources").glob("page-*.html"))
        self.assertEqual(-(-(PEOPLE + 1) // SOURCES_PER_PAGE) - 1, len(pages))
        listed = re.findall(r'data-source-id="([^"]+)"', sources + "".join(p.read_text() for p in pages))
        self.assertEqual(PEOPLE + 1, len(set(listed)))
        # A dossier's citation links to itself, on the page its source is on.
        dossier = next(p for p in (self.out / "people").glob("*.html") if 'data-person-id="p0390"' in p.read_text()).read_text()
        page = re.search(r'href="\.\./(sources/page-\d+\.html)#' + _anchor("p0390-cit") + '"', dossier)
        self.assertIsNotNone(page)
        self.assertIn(f'id="{_anchor("p0390-src")}"', self.text(page[1]))
        self.assertIn(f'id="{_anchor("p0390-cit")}"', self.text(page[1]))
        script = self.text("data/site-data.js")
        self.assertIn('"title": "Invented register volume 0390"', script)
        self.assertIn("sources/page-", script)

    def test_each_record_type_has_pages_of_its_own(self):
        sources = self.text("sources.html")
        rows = re.findall(r'<tr><td><a href="(sources/type-[a-z0-9-]+\.html)">([^<]+)</a></td><td>([\d,]+)</td><td>([\d,]+)</td><td>([\d,]+)</td></tr>', sources)
        per_type = PEOPLE // 5
        self.assertEqual([("sources/type-register.html", "Register", str(PEOPLE - 2 * per_type + 1), str(PEOPLE - 2 * per_type + 1), str(PEOPLE)),
                          ("sources/type-census-transcription.html", "Census transcriptions", str(per_type), str(per_type), str(per_type)),
                          ("sources/type-will.html", "Will", str(per_type), str(per_type), str(per_type))], rows)
        census = self.text("sources/type-census-transcription.html")
        self.assertIn(f'<h1>Sources: Census transcriptions</h1><p class="note source-type-note"><strong>Reading these records:</strong> {CENSUS_NOTE}</p>', census)
        self.assertIn("<title>Sources: Census transcriptions —", census)
        self.assertEqual(per_type, census.count("data-source-id="))
        self.assertNotIn("site-data.js", census)
        # 241 register sources: three pages of 100, every one listed once, in title order.
        register = [self.text(f"sources/type-register{suffix}.html") for suffix in ("", "--2", "--3")]
        self.assertFalse((self.out / "sources/type-register--4.html").exists())
        listed = [sid for page in register for sid in re.findall(r'data-source-id="([^"]+)"', page)]
        self.assertEqual(SOURCES_PER_PAGE, register[0].count("data-source-id="))
        self.assertEqual(sorted(["register"] + [f"p{n:04d}-src" for n in range(PEOPLE) if n % 5 > 1]), sorted(listed))
        self.assertEqual("register", listed[0])
        self.assertIn('href="type-register--2.html">Page 2</a>', register[0])
        self.assertIn("<title>Sources: Register, page 2 —", register[1])
        self.assertNotIn("Reading these records", register[0])

    def test_a_source_cited_by_everyone_lists_twenty_people(self):
        sources = self.text("sources.html")
        start = sources.index(f'id="{_anchor("register")}"')
        card = sources[start:sources.index('<article class="record-card', start)]
        self.assertEqual(20, card.count('<span class="meta">— occupation</span>'))
        self.assertIn(f'<p class="meta">and {PEOPLE - 20:,} more people</p>', card)
        # A finding citing a record directly is listed with its source.
        census = self.text("sources/type-census-transcription.html")
        self.assertRegex(census, r'<dt>Findings</dt><dd><ul><li><a href="\.\./findings/page-\d+\.html#'
                         + _anchor("p0010-f") + '">Finding about person 0010.</a>')
        self.assertEqual([], check_site(self.out)["broken"])

    def test_studies_write_the_newest_and_keep_every_study_on_title_pages(self):
        studies = self.text("studies.html")
        shown = re.findall(r'data-study-id="([^"]+)"', studies)
        self.assertIn(f'data-total="{PEOPLE}"', studies)
        public = json.loads(self.text("data/site.json"))["studies"]
        newest = sorted(public, key=lambda s: (s["updated_on"], s["title"]), reverse=True)[:STUDIES_PER_PAGE]
        self.assertEqual([s["id"] for s in newest], shown)
        self.assertNotIn("Study of person 0390", studies)
        pages = sorted((self.out / "studies").glob("page-*.html"))
        self.assertEqual(-(-PEOPLE // STUDIES_PER_PAGE), len(pages))
        listed = re.findall(r'data-study-id="([^"]+)"', "".join(p.read_text() for p in pages))
        self.assertEqual(sorted(f"p{n:04d}-s" for n in range(PEOPLE)), sorted(listed))
        # The title pages start at 1: the studies page itself is newest first.
        self.assertIn('href="studies/page-1.html">Study of person 0000 – Study of person 0099', studies)
        second = self.text("studies/page-2.html")
        self.assertIn('href="../studies/page-2.html" aria-current="page">Study of person 0100 – Study of person 0199', second)
        self.assertIn('<a href="../studies/s-', second)
        self.assertIn('<a href="../studies.html">Search the studies</a>', second)
        self.assertIn("<title>Studies by title, page 2 —", second)
        self.assertNotIn("Study of person 0123", self.text("sitemap.html"))
        # The script can search every study, but never carries a study's body.
        script = self.text("data/site-data.js")
        self.assertIn('"title": "Study of person 0390"', script)
        self.assertIn("studies/s-", script)
        self.assertNotIn("BODY-ONLY-ON-THE-STUDY-PAGE", script)
        study = next(p for p in (self.out / "studies").glob("s-*.html") if "<h1>Study of person 0390</h1>" in p.read_text()).read_text()
        self.assertIn("BODY-ONLY-ON-THE-STUDY-PAGE", study)
        self.assertEqual([], check_site(self.out)["broken"])

    def test_a_withheld_study_is_in_no_output(self):
        for path in self.out.rglob("*"):
            if path.is_file():
                text = path.read_text()
                self.assertNotIn("SECRET-STUDY", text, path)
                self.assertNotIn("withheld-study", text, path)

    def test_paged_pages_load_no_data_and_are_removed_when_no_longer_needed(self):
        for page in ("catalogue/page-2.html", "timeline/1700s.html", "places/fableland.html", "sources/page-2.html", "studies/page-2.html"):
            self.assertNotIn("site-data.js", self.text(page), page)
        self.assertIn("site-data.js", self.text("catalogue.html"))
        self.assertIn("site-data.js", self.text("studies.html"))
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            config = ProjectConfig(name="Fictional")
            build_site(large_case(), config, out)
            self.assertTrue((out / "sources/type-register--3.html").is_file())
            build_site(large_case(20), config, out)
            for folder in ("catalogue", "timeline", "places", "sources"):
                pages = list((out / folder).glob("*.html")) if (out / folder).exists() else []
                self.assertEqual([], [p for p in pages if not p.name.startswith("pl-")], folder)
            # Each place with an event keeps its own page; only the region pages go.
            self.assertEqual(20, len(list((out / "places").glob("pl-*.html"))))
            # The study pages stay; only the title pages go.
            self.assertEqual([], list((out / "studies").glob("page-*.html")))
            self.assertEqual(20, len(list((out / "studies").glob("s-*.html"))))
            self.assertEqual(20, (out / "studies.html").read_text().count("data-study-id="))
            self.assertNotIn("data-study-pages", (out / "studies.html").read_text())
            self.assertIn("data-event-id", (out / "timeline.html").read_text())
            self.assertEqual([], check_site(out)["broken"])

    def test_the_browser_script_carries_only_what_the_pages_read(self):
        script = self.text("data/site-data.js")
        data = json.loads(script[script.index("{"):script.rindex("}") + 1])
        self.assertEqual(set(BROWSER_FIELDS) | {"project", "site"}, set(data))
        for key, fields in BROWSER_FIELDS.items():
            self.assertTrue(data[key], key)
            self.assertTrue(all(set(row) <= set(fields) for row in data[key]), key)
        self.assertNotIn("sensitivity", script)
        self.assertEqual({"value", "surname"}, set(data["people"][0]["names"][0]))
        # A study carries what the studies search reads, never its body or reasoning.
        self.assertEqual({"id", "title", "summary", "status", "updated_on", "related_ids"}, set(data["studies"][0]))
        self.assertEqual(PEOPLE, len(data["site"]["study_urls"]))
        # Only citations stating a quality or information are carried, for the catalogue's evidence filter.
        self.assertEqual(2 * PEOPLE // 5, len(data["citations"]))
        self.assertIn({"id": "p0002-cit", "source_id": "p0002-src", "quality": "original", "information": "primary"}, data["citations"])
        self.assertEqual(["register-1", "p0002-cit"], next(c for c in data["claims"] if c["id"] == "p0002-c")["citation_ids"])
        # The full public export is still published beside it.
        full = json.loads(self.text("data/site.json"))
        self.assertEqual(len(full["people"]), len(data["people"]))
        self.assertIn("sensitivity", full["people"][0])
        self.assertLess(len(script), len(self.text("data/site.json")) / 2)


if __name__ == "__main__":
    unittest.main()
