"""The catalogue's Find a person page: its header, the seven filter menus as a GET form, and the facets they filter on."""
from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, grade_errors, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Citation, Claim, ClaimStatus, Confidence as C, Event, ExternalIdentifier, Finding,
                              Hypothesis, LivingStatus as L, Name, Person, Place, Relationship, ResearchQuestion, Source, Study)
from genealogy.site import build_site

GRADES = {"strongly_supported": {"label": "Strongly supported", "meaning": "Several records agree.", "confidence": "probable"}}


def config(**site):
    return ProjectConfig(name="Fictional finder", grades=GRADES, names={"surname": "Fable", "variants": {"Fable": ["Fabel"]}},
                         source_types={"census": {"label": "Census returns"}},
                         raw={"site": {"tree_name": "FableTree", **site}})


def person(pid, *names, sex=None, events=(), sensitivity=A.PUBLIC, **kwargs):
    records = [Person(pid, names=list(names), living=L.DECEASED, event_ids=[e.id for e in events], sensitivity=sensitivity, **kwargs), *events]
    if sex:
        records.append(Claim(f"{pid}-sex", pid, "sex", sex, sensitivity=sensitivity))
    return records


def born(pid, date, place=None, kind="birth", **kwargs):
    return Event(f"{pid}-{kind}", kind, date=date, place_id=place, participant_ids=[pid], sensitivity=A.PUBLIC, **kwargs)


def link(rid, subject, other, kind, confidence=C.UNKNOWN, **kwargs):
    return Relationship(rid, subject, other, kind, confidence=confidence, sensitivity=A.PUBLIC, **kwargs)


def change(record_id, before, after, note=None):
    return {"record_id": record_id, "before": before, "after": after, "note": note}


def finder_records():
    """Fictional people for every menu: birth and married names, a variant spelling and a suffix; parents by recorded sex,
    a sibling through shared parents, a spouse and children; births, deaths, a marriage and a biography; studies, record
    types and qualities; and pending, reviewed and withheld relationship changes."""
    return [
        Place("fp-lantern", "Lanternby, North Shire, Fableland", latitude=52.0, longitude=-1.0),
        Place("fp-willow", "Willowby, Inventia", latitude=48.0, longitude=3.0),
        Place("fp-moss", "Mossford, Fableland"),
        Place("fp-secret", "SECRET-PLACE Hamlet, Nowhere", sensitivity=A.PRIVATE),
        # Listed first, but withheld: the page's examples come from the first public person.
        *person("f00", Name("SECRET-FIRST Fable", given="SECRET-FIRST", surname="Fable"), sensitivity=A.PRIVATE,
                external_ids=[ExternalIdentifier("FableTree", "SECRET-ID-1")]),
        *person("f01", Name("Ada Fable", kind="birth", given="Ada", surname="Fable"), sex="F", notes="Kept bees near Mossbank.",
                external_ids=[ExternalIdentifier("FableTree", "Fable-1")],
                events=[born("f01", "1801", "fp-lantern"), born("f01", "1870", "fp-willow", "death")]),
        *person("f02", Name("Bram Fabel", surname="Fabel"), sex="M", events=[born("f02", "1775")], external_ids=[ExternalIdentifier("FableTree", "Fabel-2")]),
        *person("f03", Name("Cora Vale", surname="Vale"), sex="F", events=[born("f03", "1778", "fp-willow")]),
        *person("f04", Name("Dov Rook", surname="Rook"), sex="M", events=[born("f04", "1799")]),
        *person("f05", Name("Esme Rook", kind="birth", surname="Rook"), Name("Esme Fable", kind="married", surname="Fable"), sex="F"),
        *person("f06", Name("Finn Fable Jr.", surname="Fable"), sex="M", events=[born("f06", "1826", "fp-lantern")]),
        *person("f07", Name("Gwen Fable", surname="Fable"), sex="F", events=[born("f07", "1803", "fp-lantern")]),
        *person("f08", Name("Hugo Vale", surname="Vale"), sex="M"),
        *person("f09", Name("Iris Rook", surname="Rook"), sex="F", events=[Event("f09-res", "residence", participant_ids=["f09"], sensitivity=A.PUBLIC)]),
        *person("f10", Name("Jory Fable", surname="Fable"), events=[born("f10", "1830")]),
        *person("f99", Name("SECRET-PERSON Fable", surname="Fable"), sex="F", sensitivity=A.PRIVATE),
        Event("f01-marriage", "marriage", date="1825", place_id="fp-moss", participant_ids=["f01", "f04"], sensitivity=A.PUBLIC),
        link("r-father", "f01", "f02", "parent", C.DOCUMENTED),
        link("r-mother", "f01", "f03", "parent", C.PROBABLE),
        link("r-gwen-father", "f07", "f02", "parent", C.DOCUMENTED),
        link("r-gwen-mother", "f07", "f03", "parent", C.DOCUMENTED),
        link("r-spouse", "f01", "f04", "spouse", C.PROBABLE, grade="strongly_supported"),
        link("r-finn-mother", "f06", "f01", "parent", C.DOCUMENTED),
        link("r-finn-father", "f06", "f04", "parent", C.PROBABLE),
        link("r-bram-wife", "f02", "f09", "spouse", C.POSSIBLE),
        link("r-jory-old", "f10", "f08", "parent", C.DISPROVED),
        link("r-jory-new", "f10", "f04", "parent", C.POSSIBLE),
        Relationship("r-secret", "f01", "f99", "sibling", sensitivity=A.PRIVATE),
        # Records: an original register entry, a census transcription, an uncategorised tree, and a withheld source.
        Source("s-register", "Lanternby register", "parish_register", sensitivity=A.PUBLIC),
        Source("s-census", "Fableland census", "census", sensitivity=A.PUBLIC),
        Source("s-tree", "A family tree", "compiled_tree", sensitivity=A.PUBLIC),
        Source("s-secret", "SECRET-SOURCE title", "SECRET-TYPE", sensitivity=A.PRIVATE),
        Citation("c-register", "s-register", locator="entry 1", quality="original", sensitivity=A.PUBLIC),
        Citation("c-census", "s-census", locator="folio 2", quality="derivative", sensitivity=A.PUBLIC),
        Citation("c-tree", "s-tree", locator="page 3", sensitivity=A.PUBLIC),
        Citation("c-secret", "s-secret", locator="SECRET-LOCATOR", quality="authored", sensitivity=A.PRIVATE),
        Claim("f01-born", "f01", "birth", "1801", citation_ids=["c-register"], status=ClaimStatus.SUPPORTED, sensitivity=A.PUBLIC),
        # Resting on a withheld record, the claim is withheld with it.
        Claim("f01-secret", "f01", "occupation", "SECRET-CLAIM", citation_ids=["c-secret"], sensitivity=A.PUBLIC),
        Claim("f04-occ", "f04", "occupation", "miller", citation_ids=["c-census"], sensitivity=A.PUBLIC),
        Claim("f05-occ", "f05", "occupation", "weaver", citation_ids=["c-tree"], sensitivity=A.PUBLIC),
        Study("st-lantern", "Lanternby households", related_ids=["f01", "f07"], sensitivity=A.PUBLIC),
        Study("st-rook", "Rook family", groups=[{"id": "g1", "title": "Millers", "member_ids": ["f04", "f05"]}], sensitivity=A.PUBLIC),
        Study("st-secret", "SECRET-STUDY title", related_ids=["f01"], sensitivity=A.PRIVATE),
        # Pending: a new father link (seen from both sides), a regraded marriage, a replacement by note and by a disproved link.
        Finding("fd-father", "The register names Bram as Ada's father.", related_ids=["f01"], status="draft", recorded_on="2026-01-02",
                changes=[change("r-father", None, "documented")], sensitivity=A.PUBLIC),
        Finding("fd-spouse", "The banns support the marriage.", related_ids=["f01"], status="open", recorded_on="2026-01-03",
                changes=[change("r-spouse", "possible", "strongly_supported")], sensitivity=A.PUBLIC),
        Finding("fd-finn", "Dov, not the tree's guess, is Finn's father.", related_ids=["f06"], status="draft", recorded_on="2026-01-04",
                changes=[change("r-finn-father", None, "probable", "Replaces the father the tree gave.")], sensitivity=A.PUBLIC),
        Finding("fd-jory", "Jory's father was Dov, not Hugo.", related_ids=["f10"], status="draft", recorded_on="2026-01-05",
                changes=[change("r-jory-old", "possible", "disproved"), change("r-jory-new", None, "possible")], sensitivity=A.PUBLIC),
        # Reviewed: already applied, so nothing is pending for Gwen.
        Finding("fd-gwen", "Gwen's parents are confirmed.", related_ids=["f07"], status="reviewed", recorded_on="2026-01-06",
                changes=[change("r-gwen-father", None, "documented")], sensitivity=A.PUBLIC),
        Finding("fd-secret", "SECRET-FINDING about Cora.", related_ids=["f03"], status="draft", recorded_on="2026-01-07",
                changes=[change("r-mother", None, "probable")], sensitivity=A.PRIVATE),
        ResearchQuestion("q-open", "Who were Hugo's parents?", related_ids=["f08"], sensitivity=A.PUBLIC),
        ResearchQuestion("q-closed", "Where did Ada die?", related_ids=["f01"], status="resolved", sensitivity=A.PUBLIC),
        Hypothesis("h-open", "Iris was a Rook by birth.", related_ids=["f09"], sensitivity=A.PUBLIC),
    ]


def finder_case() -> ResearchCase:
    case = ResearchCase("fictional-finder", "Fictional finder")
    case.add_many(finder_records())
    return case


class Form(HTMLParser):
    """The catalogue form's panels in order, each with its controls as (tag, name, label words) and its options."""
    def __init__(self):
        super().__init__()
        self.panels, self.controls, self.options, self.labels, self.text, self.ids = [], [], {}, {}, [], {}
        self.select = self.label_for = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "details" and "data-filter-panel" in attrs:
            self.panels.append(attrs["data-filter-panel"])
        if tag in ("input", "select") and attrs.get("name"):
            self.controls.append((self.panels[-1] if self.panels else "", tag, attrs["name"], attrs.get("type"), attrs.get("placeholder")))
            if attrs.get("id"):
                self.ids[attrs["id"]] = attrs["name"]
        if tag == "select" and attrs.get("name"):
            self.select = attrs["name"]
            self.options[self.select] = []
        if tag == "option" and self.select:
            self.options[self.select].append([attrs.get("value"), ""])

    def handle_endtag(self, tag):
        if tag == "select":
            self.select = None

    def handle_data(self, data):
        if self.select and self.options[self.select]:
            self.options[self.select][-1][1] += data


def parse(html):
    form = re.search(r'<form class="catalogue-finder".*?</form>', html, re.S)[0]
    parser = Form()
    parser.feed(form)
    return form, parser


class FindAPersonPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.out = Path(cls.directory.name)
        case = finder_case()
        assert validate_case(case) == [] and grade_errors(case, GRADES) == [], grade_errors(case, GRADES)
        build_site(case, config(), cls.out)
        cls.html = (cls.out / "catalogue.html").read_text(encoding="utf-8")
        cls.form, cls.parsed = parse(cls.html)
        script = (cls.out / "data/site-data.js").read_text(encoding="utf-8")
        cls.data = json.loads(script.removeprefix("window.GENEALOGY_SITE_DATA=").removesuffix(";\n"))
        cls.people = {p["id"]: p for p in cls.data["people"]}

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_the_header_above_the_search_box(self):
        main = self.html.split('<main id="main-content">', 1)[1]
        self.assertTrue(main.startswith('<p class="catalogue-links"><a href="sitemap.html#people">Browse the name index</a> · '
                                        '<a href="sitemap.html#downloads">Download research data</a></p><h1>Find a person</h1>'))
        self.assertIn("<title>People — Fictional finder</title>", self.html)
        # One open question, one open hypothesis and four draft or open findings; the resolved question, the reviewed
        # finding and the withheld one are not counted.
        self.assertIn('<p class="catalogue-held"><a href="research.html">Held and pending research · 6 items →</a></p>', main)
        self.assertIn('<p class="lede">Search 10 historical people connected with the Fable surname.</p>'
                      '<p class="catalogue-total"><strong>10</strong> people in catalogue</p>', main)
        self.assertIn('placeholder="Name, FableTree ID or any detail (e.g. Ada Fable, Fable-1, Lanternby, 1801)"', self.form)
        self.assertIn('<form class="catalogue-finder" action="catalogue.html" method="get" role="search" aria-label="Find a person" data-catalogue-form data-surname="Fable">', self.form)
        self.assertIn('<button type="submit">Search</button>', self.form)
        self.assertIn('<h2 id="people">People</h2>', (self.out / "sitemap.html").read_text(encoding="utf-8"))

    def test_the_seven_menus_in_order_with_their_controls(self):
        self.assertEqual(["name", "relatives", "dates", "places", "evidence", "filters", "tree"], self.parsed.panels)
        titles = re.findall(r'<details class="filter-group" data-filter-panel="[a-z]+"><summary>([^<]+)</summary><div class="filter-panel" id="[^"]+"><h3>([^<]+)</h3>', self.form)
        self.assertEqual([("Name",) * 2, ("Relatives",) * 2, ("Dates",) * 2, ("Places",) * 2, ("Evidence",) * 2, ("Filters",) * 2, ("FableTree",) * 2], titles)
        names = [(panel, name) for panel, _, name, _, _ in self.parsed.controls]
        self.assertEqual([("", "q"),
                          ("name", "first"), ("name", "last"), ("name", "last_scope"), ("name", "name"), ("name", "sex"), ("name", "sex"), ("name", "sex"), ("name", "exact"),
                          *(("relatives", k) for k in ("spouse", "father", "mother", "child", "sibling")),
                          ("dates", "date_type"), ("dates", "year_from"), ("dates", "year_to"),
                          ("places", "place_type"), ("places", "place"), ("places", "region"), ("places", "exclude_place"),
                          ("evidence", "study"), ("evidence", "record_type"), ("evidence", "quality"), ("evidence", "evidence"),
                          ("filters", "born_surname"), ("filters", "married_surname"), ("filters", "suffix"),
                          ("filters", "missing_father"), ("filters", "missing_mother"), ("filters", "has_children"), ("filters", "no_spouse"),
                          ("tree", "no_external"), ("tree", "needs_update"), ("tree", "change_relationship"), ("tree", "change_action"), ("tree", "change_confidence")], names)
        placeholders = {name: placeholder for _, _, name, _, placeholder in self.parsed.controls if placeholder}
        self.assertEqual({"first": "e.g. Ada", "last": "e.g. Fable", "name": "First, last, or both", "spouse": "Full name, including married name",
                          "father": "Full name", "mother": "Full name, including married name", "child": "Full name", "sibling": "Full name, including married name",
                          "year_from": "From", "year_to": "To", "place": "Place name", "exclude_place": "e.g. USA"},
                         {k: v for k, v in placeholders.items() if k != "q"})
        for ident in ("catalogue-date-from", "catalogue-date-to"):
            self.assertRegex(self.form, rf'<input id="{ident}" name="year_(?:from|to)" type="number" placeholder="(?:From|To)" min="1000" max="2100">')

    def test_the_labels_notes_and_option_lists(self):
        labels = re.findall(r"<label(?: class=\"[a-z-]+\")?(?: for=\"[^\"]+\")?>(?:<input[^>]*>)?(?:<span>)?([^<]+)", self.form)
        self.assertEqual(["Search people", "First name(s)", "Last name", "Last name matches", "Full name", "Any", "Exact name spelling",
                          "Spouse name", "Father name", "Mother name", "Child name", "Sibling name",
                          "Dates apply to", "From year", "To year", "Location applies to", "Location", "Country or region", "Exclude location",
                          "Possible group", "Record type", "Source quality", "Claims",
                          "Fable at birth", "Women who married a Fable", "Has suffix", "Missing father", "Missing mother", "Has descendants",
                          "No recorded spouse or partner", "No confirmed FableTree link", "Needs updated on FableTree",
                          "Changed relationship", "Relationship change", "New confidence"], labels)
        self.assertIn('<fieldset class="catalogue-gender"><legend>Gender</legend><label><input name="sex" type="radio" value="" checked><span>Any</span></label>'
                      '<label><input name="sex" type="radio" value="M"><span aria-hidden="true">♂</span><span class="sr-only">Male</span></label>'
                      '<label><input name="sex" type="radio" value="F"><span aria-hidden="true">♀</span><span class="sr-only">Female</span></label></fieldset>', self.form)
        for note in ("Male or Female excludes people with no recorded gender.", "<small>Applies to the main search box: Fabel will not also match Fable.</small>",
                     "Each relationship can be used once. People must match every relative entered.",
                     "Either year may be left open. People without a year for the chosen event are excluded.",
                     "Any searches all recorded places and public biography text. Exclude location uses the same selection; separate places with commas.",
                     "<h4>Surname and marriage</h4>", "<h4>Family</h4>",
                     "Filter pending relationship amendments by their relationship, action or proposed confidence."):
            self.assertIn(note, self.form)
        options = {k: [tuple(o) for o in v] for k, v in self.parsed.options.items()}
        self.assertEqual([("", "Any recorded surname"), ("birth", "Surname at birth"), ("current", "Current/last surname")], options["last_scope"])
        self.assertEqual([("", "Any record"), ("birth", "Birth"), ("death", "Death")], options["date_type"])
        self.assertEqual([("", "Any"), ("record", "Any record"), ("birth", "Birth"), ("marriage", "Marriage"), ("death", "Death"), ("bio", "Bio")], options["place_type"])
        # Lists that grow with the case are filled by the script from the shared data.
        self.assertEqual([("", "Any region")], options["region"])
        self.assertEqual([("", "Any group")], options["study"])
        self.assertEqual([("", "Any record type")], options["record_type"])
        self.assertEqual([("", "Any quality"), ("original", "Original record"), ("derivative", "Derivative record"), ("authored", "Authored work"),
                          ("tree_only", "Tree/profile only"), ("unknown", "Unclassified")], options["quality"])
        self.assertEqual([("", "Any evidence"), ("supported", "Supported claim"), ("original", "Backed by an original record"), ("unassessed", "Unassessed or imported")], options["evidence"])
        self.assertEqual([("", "Any relationship change"), ("father", "Father"), ("mother", "Mother"), ("spouse", "Spouse"), ("child", "Child"), ("sibling", "Sibling")],
                         options["change_relationship"])
        self.assertEqual([("", "Any change"), ("topology", "New / replaced relative"), ("add", "New relationship"), ("replace", "Replaced relationship"), ("regrade", "Confidence changed")],
                         options["change_action"])
        # The project's grades, then the standard values it does not override, then Unrated.
        self.assertEqual([("", "Any confidence"), ("strongly_supported", "Strongly supported"), ("documented", "Documented"), ("probable", "Probable"),
                          ("possible", "Possible"), ("disproved", "Disproved"), ("unrated", "Unrated")], options["change_confidence"])

    def test_the_shared_data_carries_each_persons_facets(self):
        people = self.people
        self.assertEqual([{"value": "Ada Fable", "surname": "Fable", "given": "Ada", "kind": "birth"}], people["f01"]["names"])
        self.assertEqual([{"value": "Esme Rook", "surname": "Rook", "kind": "birth"}, {"value": "Esme Fable", "surname": "Fable", "kind": "married"}], people["f05"]["names"])
        self.assertEqual(["st-lantern"], people["f01"]["study_ids"])
        self.assertEqual(["st-rook"], people["f04"]["study_ids"])  # a group member
        self.assertEqual((["parish-register"], ["original"]), (people["f01"]["record_types"], people["f01"]["qualities"]))
        self.assertEqual((["census"], ["derivative"]), (people["f04"]["record_types"], people["f04"]["qualities"]))
        self.assertEqual((["compiled-tree"], ["unknown"]), (people["f05"]["record_types"], people["f05"]["qualities"]))
        self.assertFalse({"record_types", "qualities", "study_ids", "changes"} & set(people["f03"]))  # her only change is withheld
        self.assertEqual({"census": "Census returns", "compiled-tree": "Compiled_tree", "parish-register": "Parish_register"}, self.data["site"]["source_type_labels"])

    def test_pending_changes_from_each_side_of_the_link(self):
        changes = {pid: p.get("changes") for pid, p in self.people.items() if p.get("changes")}
        self.assertEqual({
            # A new father link: Ada's father, Bram's child. The regraded marriage is a spouse change for both.
            "f01": [["father", "add", "documented"], ["spouse", "regrade", "strongly_supported"]],
            "f02": [["child", "add", "documented"]],
            "f04": [["spouse", "regrade", "strongly_supported"], ["child", "replace", "probable"], ["child", "replace", "possible"]],
            # The note says the link replaces another; Jory's new father replaces the link the same finding disproved.
            "f06": [["father", "replace", "probable"]],
            "f08": [["child", "regrade", "disproved"]],
            "f10": [["father", "regrade", "disproved"], ["father", "replace", "possible"]],
        }, changes)

    def test_nothing_withheld_reaches_any_output(self):
        for path in self.out.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="ignore")
                for secret in ("SECRET-FIRST", "SECRET-ID", "SECRET-PERSON", "SECRET-STUDY", "SECRET-SOURCE", "SECRET-TYPE", "SECRET-LOCATOR",
                               "SECRET-FINDING", "SECRET-PLACE", "SECRET-CLAIM", "secret-type"):
                    self.assertNotIn(secret, text, path)
        self.assertNotIn("f99", json.dumps(self.data["people"]))
        self.assertNotIn("f00", self.html)


class FindAPersonDefaultsTests(unittest.TestCase):
    def build(self, cfg, records=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        case = ResearchCase("fictional-defaults", "Fictional defaults")
        case.add_many(records if records is not None else finder_records())
        build_site(case, cfg, Path(directory.name))
        return (Path(directory.name) / "catalogue.html").read_text(encoding="utf-8")

    def test_without_a_surname_or_tree_name(self):
        html = self.build(ProjectConfig(name="Plain", grades=GRADES))
        form, parsed = parse(html)
        self.assertIn('<p class="lede">Search 10 people in this collection.</p>', html)
        self.assertIn('placeholder="Name, record ID or any detail (e.g. Ada Fable, Fable-1, Lanternby, 1801)"', form)
        # No surname: the Surname and marriage checks are left out, and the exact-spelling note is generic.
        self.assertNotIn("Surname and marriage", form)
        self.assertNotIn("born_surname", [name for _, _, name, _, _ in parsed.controls])
        self.assertIn("<small>Applies to the main search box: other spellings will not also match.</small>", form)
        self.assertIn('<summary>Tree</summary><div class="filter-panel" id="catalogue-filter-tree"><h3>Tree</h3>', form)
        self.assertIn("<span>No confirmed tree link</span>", form)
        self.assertIn("<span>Needs updated on the tree</span>", form)
        self.assertIn('placeholder="e.g. Fable"', form)  # the first public person's surname

    def test_the_surname_defaults_to_the_first_variants_group(self):
        html = self.build(ProjectConfig(name="Variants", grades=GRADES, names={"variants": {"Fable": ["Fabel"], "Rook": ["Roke"]}}))
        self.assertIn("connected with the Fable surname.", html)
        self.assertIn("<span>Fable at birth</span>", html)
        # A group no public person is recorded under is never published.
        html = self.build(ProjectConfig(name="Hidden", grades=GRADES, names={"variants": {"Nobody": ["Noboddy"]}}))
        self.assertNotIn("Nobody", html)
        self.assertIn("Search 10 people in this collection.", html)

    def test_no_held_research_line_and_graceful_examples(self):
        html = self.build(ProjectConfig(name="Bare"), [Person("p1", names=[Name("Ada Fable")], living=L.DECEASED, sensitivity=A.PUBLIC)])
        self.assertNotIn("Held and pending research", html)
        self.assertIn('placeholder="Name, record ID or any detail (e.g. Ada Fable, p1)"', html)
        self.assertIn('<input id="catalogue-last-name" name="last" type="search">', html)
        self.assertIn('Search 1 person in this collection.</p><p class="catalogue-total"><strong>1</strong> person in catalogue</p>', html)
        html = self.build(ProjectConfig(name="Empty"), [])
        self.assertIn('placeholder="Name, record ID or any detail"', html)

    def test_the_new_settings_are_validated(self):
        for names, site in (({"surname": ""}, {}), ({"surname": 3}, {}), ({}, {"tree_name": " "}), ({}, {"tree_name": ["WikiTree"]})):
            with self.subTest(names=names, site=site), self.assertRaisesRegex(ValueError, r"(names\.surname|site\.tree_name) must be a non-empty string"):
                ProjectConfig(names=names, raw={"site": site}).validate()
        with self.assertRaisesRegex(ValueError, "names has unknown settings: surnames"):
            ProjectConfig(names={"surnames": "Fable"}).validate()
        cfg = ProjectConfig(names={"surname": " Fable "}, raw={"site": {"tree_name": "WikiTree"}})
        cfg.validate()
        self.assertEqual(("Fable", "WikiTree"), (cfg.catalogue_surname, cfg.tree_name))
        self.assertEqual((None, None), (ProjectConfig().catalogue_surname, ProjectConfig().tree_name))


if __name__ == "__main__":
    unittest.main()
