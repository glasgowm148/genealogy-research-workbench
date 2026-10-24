"""The research log: searches made, with what they found, including nothing."""
from __future__ import annotations

import csv
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.artifacts import build_case_artifact_bundle
from genealogy.case import CaseStore, ResearchCase, validate_case
from genealogy.cli import main
from genealogy.config import ProjectConfig
from genealogy.exports import project_for_public_export, to_csv
from genealogy.models import (AccessLevel as A, Citation, Finding, LivingStatus as L, Name, Person, Place, Search, Source,
                              record_from_dict)
from genealogy.research import ResearchService
from genealogy.site import build_site
from genealogy.sitecheck import check_site


def search(sid, text, result, *, on=None, related=("ada",), cite=(), limitation=None, sensitivity=A.PUBLIC):
    return Search(sid, search=text, result=result, related_ids=list(related), searched_on=on, citation_ids=list(cite),
                  limitation=limitation, sensitivity=sensitivity)


def log_case(*searches):
    c = ResearchCase("fictional-log", "Fictional research log")
    c.add_many([
        Person("ada", names=[Name("Ada Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Person("bram", names=[Name("Bram Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Place("harbour", "Invented Harbour", sensitivity=A.PUBLIC),
        Source("register", "Invented Harbour parish register", sensitivity=A.PUBLIC),
        Citation("burial-1870", "register", locator="burials 1870, folio 4", sensitivity=A.PUBLIC),
        *searches,
    ])
    return c


LOG = (
    search("s-baptisms", "Invented Harbour parish register, baptisms 1795–1810, Fable and Fabel", "Nothing found for Ada.",
           on="2026-03-02", limitation="Pages for 1799 are missing from the film.", related=("ada", "harbour")),
    search("s-burials", "Invented Harbour parish register, burials 1860–1880", "One burial entry: Ada Fable, 1870.",
           on="2026-05-10", related=("ada", "bram"), cite=("burial-1870",)),
    search("s-undated", "Invented county newspaper index, Fable", "Nothing found.", related=("ada",)),
)


def page_for(out, pid):
    return next(p.read_text() for p in (out / "people").glob("*.html") if f'data-person-id="{pid}"' in p.read_text())


class ValidationTests(unittest.TestCase):
    def test_a_search_round_trips_and_a_log_is_valid(self):
        record = LOG[1]
        self.assertEqual(record, record_from_dict("Search", json.loads(json.dumps(record.to_dict()))))
        self.assertEqual([], validate_case(log_case(*LOG)))

    def test_text_dates_and_references_are_checked(self):
        bad = [
            search("s1", "", "Nothing."),
            search("s2", "A register", ""),
            search("s3", "A register", "Nothing.", on="2026-13-01"),
            search("s4", "A register", "Nothing.", related=("nobody",)),
            search("s5", "A register", "Found it.", cite=("register",)),
            Search("s6", search="A register", result="Nothing.", related_ids=[""], limitation=3),
        ]
        errors = validate_case(log_case(*bad))
        for expected in ("s1.search must be a non-empty string", "s2.result must be a non-empty string",
                         "s3.searched_on must be an ISO date", "s4.related_ids references missing record: nobody",
                         "s5.citation_ids must reference a Citation: register", "s6.related_ids must be a list of non-empty ids",
                         "s6.limitation must be a string or null"):
            self.assertTrue(any(error.startswith(expected) for error in errors), (expected, errors))

    def test_the_research_service_and_private_bundle_see_searches(self):
        c = log_case(*LOG)
        with tempfile.TemporaryDirectory() as directory:
            CaseStore(directory).save(c)
            service = ResearchService(directory)
            self.assertEqual(["s-baptisms"], [r.id for r in service.query_records(c.id, kind="Search", related_to="harbour")])
            self.assertEqual(["s-burials"], [r.id for r in service.query_records(c.id, related_to="burial-1870")])
            service.add_search(c.id, search("s-new", "A register", "Nothing."))
            self.assertEqual(4, len(service.get_case(c.id).records(Search)))
        bundle = json.loads(build_case_artifact_bundle(c)["reference-index.json"])
        inbound = next(row for row in bundle["referenced_by"] if row["id"] == "burial-1870")["references"]
        self.assertEqual([{"field": "citation_ids", "id": "s-burials", "record_type": "Search"}], inbound)

    def test_exports_carry_public_searches(self):
        project = project_for_public_export(log_case(*LOG), ProjectConfig(name="Fictional"))
        self.assertEqual({"s-baptisms", "s-burials", "s-undated"}, {row["id"] for row in project["searches"]})
        rows = list(csv.DictReader(io.StringIO(to_csv(project))))
        self.assertEqual(3, sum(row["record_type"] == "searches" for row in rows))


class SiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.temp.name)
        build_site(log_case(*LOG), ProjectConfig(name="Fictional"), cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_each_dossier_lists_its_searches_newest_first_after_research(self):
        page = page_for(self.out, "ada")
        section = page[page.index('<h2 id="research-log">'):page.index('<h2 id="relationships">')]
        self.assertLess(page.index('<h2 id="research">'), page.index('<h2 id="research-log">Research log</h2>'))
        dates = re.findall(r'<p class="search-date"><strong>(?:<time[^>]*>)?([^<]+)', section)
        self.assertEqual(["10 May 2026", "2 Mar 2026", "Date not recorded"], dates)
        self.assertIn('<time datetime="2026-05-10">10 May 2026</time>', section)
        self.assertIn("<dt>Result</dt><dd>Nothing found for Ada.</dd>", section)
        self.assertIn("<dt>Limits</dt><dd>Pages for 1799 are missing from the film.</dd>", section)
        self.assertRegex(section, r'<dt>Records found</dt><dd><ul class="finding-records"><li><a href="\.\./sources\.html#r-[0-9a-f]+">'
                                  r'Invented Harbour parish register \(burials 1870, folio 4\)</a></li></ul></dd>')
        # The other people and places searched for, not the person whose page it is.
        self.assertRegex(section, r'<dt>Also for</dt><dd><a href="\.\./places\.html#r-[0-9a-f]+">Invented Harbour</a></dd>')
        self.assertRegex(section, r'<dt>Also for</dt><dd><a href="\.\./people/p-[0-9a-f]+\.html">Bram Fable</a></dd>')

    def test_the_section_menu_links_the_log_only_when_there_is_one(self):
        menu = lambda page: re.findall(r'<a href="#([^"]+)">', re.search(r'<nav class="page-sections"[^>]*>(.*?)</nav>', page).group(1))
        self.assertEqual(["names", "research-log"], menu(page_for(self.out, "ada")))
        with tempfile.TemporaryDirectory() as directory:
            build_site(log_case(), ProjectConfig(name="Fictional"), Path(directory))
            page = page_for(Path(directory), "ada")
            self.assertIn('<h2 id="research-log">Research log</h2><p class="empty-state">No public searches recorded for this person.</p>', page)
            self.assertEqual(["names"], menu(page))

    def test_research_page_has_the_log_and_each_search_has_an_address(self):
        research = (self.out / "research.html").read_text()
        block = research[research.index('<h2 id="research-log">'):]
        self.assertIn('<p class="result-count">3 searches, newest first.</p>', block)
        self.assertRegex(block, r'<dt>For</dt><dd><a href="people/p-[0-9a-f]+\.html">Ada Fable</a>, <a href="places\.html#r-[0-9a-f]+">Invented Harbour</a></dd>')
        site = json.loads((self.out / "data/site.json").read_text())
        self.assertEqual(3, len(site["searches"]))


class LargeLogTests(unittest.TestCase):
    def test_research_page_lists_the_newest_fifty_and_counts_the_rest(self):
        many = [search(f"s{n:03}", f"Invented register, year {1800 + n}", "Nothing found.", on=f"{1900 + n}-01-01",
                       related=("ada",) if n % 2 else ("harbour",)) for n in range(120)]
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(log_case(*many), ProjectConfig(name="Fictional"), out)
            research = (out / "research.html").read_text()
            block = research[research.index('<h2 id="research-log">'):]
            self.assertIn("The newest 50 of 120 searches.", block)
            self.assertEqual(50, block.count('<p class="search-date">'))
            self.assertIn("year 1919", block)  # s119, the newest
            self.assertNotIn("year 1869", block)  # s069, the 51st
            # The dossier keeps every search made for the person.
            self.assertEqual(60, page_for(out, "ada").count('<p class="search-date">'))
            self.assertNotIn("year 1868", research)  # s068, older and for a place only: in data/site.json, not listed

    def test_older_searches_have_paged_no_script_pages_and_stable_unattached_links(self):
        many = [search(f"s{n:03}", f"Register year {1800 + n}", "Nothing found.", on=f"{1900 + n}-01-01",
                       related=()) for n in range(123)]
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            c = log_case(*many)
            c.add(Finding("review-old-search", conclusion="The earliest search still needs review.",
                          related_ids=["s000"], sensitivity=A.PUBLIC))
            build_site(c, ProjectConfig(name="Fictional"), out)
            page = (out / "research-log" / "page-3.html").read_text()
            self.assertIn('id="r-', page)
            self.assertIn('href="../research.html"', page)
            self.assertIn('aria-label="Research log pages"', page)
            self.assertIn("Register year 1800", page)
            routes = json.loads((out / "data" / "routes.json").read_text())
            self.assertTrue(any(str(row).startswith("research-log/page-3.html") for row in routes))
            self.assertEqual([], check_site(out)["broken"])
            self.assertIn('href="research-log/page-3.html#', (out / "research.html").read_text())
            self.assertIn('href="../research.html#research-log"', page)
            build_site(log_case(many[0]), ProjectConfig(name="Fictional"), out)
            self.assertFalse((out / "research-log" / "page-3.html").exists())
            self.assertFalse((out / "research-log" / "page-2.html").exists())
            self.assertEqual([], check_site(out)["broken"])


class PrivacyTests(unittest.TestCase):
    def test_a_search_naming_a_withheld_person_or_record_is_withheld_everywhere(self):
        c = log_case(*LOG)
        c.add_many([
            Person("living", names=[Name("SECRET-LIVING-NAME")], living=L.LIVING, sensitivity=A.PUBLIC),
            Citation("private-cite", "register", locator="SECRET-LOCATOR"),
            search("s-living", "SECRET-SEARCH-LIVING register", "SECRET-RESULT-LIVING", related=("ada", "living")),
            search("s-cites-private", "SECRET-SEARCH-CITE register", "SECRET-RESULT-CITE", cite=("private-cite",)),
            search("s-private", "SECRET-SEARCH-PRIVATE", "SECRET-RESULT-PRIVATE", limitation="SECRET-LIMIT", sensitivity=A.PRIVATE),
        ])
        self.assertEqual([], validate_case(c))
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(c, ProjectConfig(name="Fictional", raw={"site": {"base_url": "https://example.invalid/"}}), out)
            files = [p for p in out.rglob("*") if p.is_file()]
            for path in files:
                self.assertNotIn("SECRET-", path.read_text(errors="ignore"), path)
                self.assertNotIn("s-living", path.read_text(errors="ignore"), path)
            self.assertIn("Nothing found for Ada.", (out / "research.html").read_text())


class CommandTests(unittest.TestCase):
    def test_search_add_logs_a_search_and_search_text_still_searches(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()) as out:
            root = Path(directory) / "p"
            self.assertEqual(0, main(["init", str(root), "--name", "Fictional"]))
            records = (("Person", {"id": "ada", "names": [{"value": "Ada Fable"}], "living": "deceased", "sensitivity": "public"}),
                       ("Place", {"id": "harbour", "name": "Invented Harbour", "sensitivity": "public"}),
                       ("Source", {"id": "register", "title": "Invented register", "sensitivity": "public"}),
                       ("Citation", {"id": "burial-1870", "source_id": "register", "sensitivity": "public"}))
            for kind, record in records:
                path = Path(directory) / f"{record['id']}.json"
                path.write_text(json.dumps(record))
                self.assertEqual(0, main(["--project", str(root), "record", "add", kind, "--input", str(path)]))
            project = ["--project", str(root)]
            self.assertEqual(0, main([*project, "search", "add", "s-baptisms", "Invented register, baptisms 1795–1810",
                                      "--result", "nothing", "--on", "2026-03-02", "--for", "ada", "harbour",
                                      "--limitation", "1799 missing", "--sensitivity", "public"]))
            self.assertEqual(0, main([*project, "search", "add", "s-burials", "Invented register, burials",
                                      "--result", "One entry", "--for", "ada", "--cite", "burial-1870"]))
            stored = json.loads(next((root / "cases").glob("*.json")).read_text())["record_sets"]["Search"]
            self.assertEqual({"id": "s-baptisms", "search": "Invented register, baptisms 1795–1810", "result": "nothing",
                              "related_ids": ["ada", "harbour"], "searched_on": "2026-03-02", "limitation": "1799 missing",
                              "citation_ids": [], "sensitivity": "public"}, stored[0])
            self.assertEqual((["burial-1870"], "private"), (stored[1]["citation_ids"], stored[1]["sensitivity"]))
            # The record search is unchanged, including a search for the word "add".
            out.truncate(0), out.seek(0)
            self.assertEqual(0, main([*project, "search", "baptisms", "--kind", "Search"]))
            self.assertEqual(["s-baptisms"], [m["record"]["id"] for m in json.loads(out.getvalue())])
            out.truncate(0), out.seek(0)
            self.assertEqual(0, main([*project, "search", "add"]))
            json.loads(out.getvalue())
            with redirect_stderr(io.StringIO()) as err:
                self.assertEqual(1, main([*project, "search", "add", "s-bad", "A register", "--result", "nothing", "--for", "nobody"]))
                self.assertEqual(1, main([*project, "search", "add", "s-bad", "A register", "--result", "nothing", "--for", "ada", "--on", "2026-02-30"]))
                self.assertEqual(1, main([*project, "search", "add", "s-burials", "Again", "--result", "nothing", "--for", "ada"]))
            self.assertIn("s-bad.related_ids references missing record: nobody", err.getvalue())
            self.assertIn("s-bad.searched_on must be an ISO date", err.getvalue())
            self.assertIn("duplicate record id: s-burials", err.getvalue())
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main([*project, "search", "add", "s-bad", "A register", "--for", "ada"])  # --result is required
            self.assertEqual(0, main([*project, "validate"]))


if __name__ == "__main__":
    unittest.main()
