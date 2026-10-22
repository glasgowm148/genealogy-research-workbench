"""The family reading room (the tree page's Branch cards view): what the build writes for it.

The browser contract is in test_browser_reading_room.py; this file holds the fixture it shares and the checks
that need no browser: the script is shipped and loaded by the tree page alone, dossiers open the view on their
person, and nothing withheld reaches any file.
"""
from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import AccessLevel as A, Claim, Confidence as C, Event, LivingStatus as L, Name, Person, Place, Relationship
from genealogy.site import build_site
from genealogy.sitecheck import check_site

SECRET = "SECRET-Withheld Fable"
SECRET_LINK = "SECRET-rejected-because"
SCRIPT_TAG = '<script src="assets/reading_room.js"></script>'


def person(pid, name, year, sex=None, access=A.PUBLIC, place=None):
    records = [Person(pid, names=[Name(name, given=name.split()[0], surname=name.split()[-1])], living=L.DECEASED, sensitivity=access, event_ids=[f"{pid}-b"]),
               Event(f"{pid}-b", "birth", date=str(year), participant_ids=[pid], place_id=place, sensitivity=access)]
    if sex:
        records.append(Claim(f"{pid}-sex", pid, "sex", sex, sensitivity=access))
    return records


def parent(rid, child, of, confidence=C.DOCUMENTED, estimate=None, access=A.PUBLIC, rationale=None):
    return Relationship(rid, child, of, "parent", confidence=confidence, estimate=estimate, sensitivity=access, rationale=rationale)


def reading_room_case():
    """Ada Fable: two parent sets (Tobin and Wren; the alternative Corin and Mira Vale), a rejected father, three
    generations above, siblings, a husband, children to a great-grandchild, a rejected child and withheld records."""
    case = ResearchCase("fictional-reading-room", "Fictional reading room")
    records = [
        Place("pl-lantern", "Lanternford (fictional)", sensitivity=A.PUBLIC),
        *person("p0001", "Ada Fable", 1850, "F", place="pl-lantern"),
        *person("p0002", "Tobin Fable", 1820, "M"), *person("p0003", "Wren Fable", 1822, "F"),
        *person("p0004", "Corin Vale", 1819, "M"), *person("p0007", "Mira Vale", 1821, "F"),
        *person("p0006", "Rowan Fable", 1818, "M"),
        parent("r-tobin", "p0001", "p0002", C.PROBABLE, 84), parent("r-wren", "p0001", "p0003"),
        parent("r-corin", "p0001", "p0004", C.POSSIBLE, 30), parent("r-mira", "p0001", "p0007", C.POSSIBLE, 20),
        Relationship("r-vales", "p0004", "p0007", "spouse", confidence=C.DOCUMENTED, sensitivity=A.PUBLIC),
        parent("r-rowan", "p0001", "p0006", C.DISPROVED, rationale="The baptism names another Rowan."),
        # Tobin's parents and grandfather.
        *person("p0010", "Old Fable", 1790, "M"), *person("p0011", "Elsa Fable", 1792, "F"), *person("p0012", "Eldest Fable", 1760, "M"),
        parent("r-old", "p0002", "p0010"), parent("r-elsa", "p0002", "p0011"), parent("r-eldest", "p0010", "p0012"),
        # Ada's sisters and a recorded brother with no parent in common; Iris has a daughter of her own.
        *person("p0020", "Iris Fable", 1848, "F"), *person("p0021", "Lark Fable", 1853, "F"), *person("p0022", "Pip Vale", 1855, "M"),
        parent("r-iris-f", "p0020", "p0002"), parent("r-iris-m", "p0020", "p0003"), parent("r-lark-f", "p0021", "p0002"), parent("r-lark-m", "p0021", "p0003"),
        Relationship("r-pip", "p0001", "p0022", "sibling", confidence=C.POSSIBLE, sensitivity=A.PUBLIC),
        *person("p0120", "Niece Fable", 1870, "F"), parent("r-niece", "p0120", "p0020"),
        # Her husband and their line.
        *person("p0005", "Bram Fable", 1848, "M"),
        Relationship("r-bram", "p0001", "p0005", "spouse", confidence=C.PROBABLE, sensitivity=A.PUBLIC),
        *person("p0101", "Child One Fable", 1875, "M"), *person("p0102", "Child Two Fable", 1878, "F"),
        parent("r-c1-m", "p0101", "p0001"), parent("r-c1-f", "p0101", "p0005"), parent("r-c2-m", "p0102", "p0001"),
        *person("p0103", "Nell Fable", 1880, "F"), parent("r-nell", "p0103", "p0001", C.DISPROVED),
        *person("p0201", "Grand Fable", 1900, "M"), parent("r-grand", "p0201", "p0101"),
        *person("p0301", "Great Fable", 1925, "F"), parent("r-great", "p0301", "p0201"),
        # Withheld: a private child, a private candidate father and a private link between public people.
        *person("p0900", SECRET, 1882, access=A.PRIVATE), parent("r-secret", "p0900", "p0001", access=A.PRIVATE),
        *person("p0901", SECRET + " Senior", 1817, "M", access=A.PRIVATE), parent("r-secret-father", "p0001", "p0901", C.POSSIBLE, access=A.PRIVATE),
        parent("r-secret-link", "p0021", "p0004", C.DISPROVED, access=A.PRIVATE, rationale=SECRET_LINK),
    ]
    for record in records:
        case.add(record)
    return case


class ReadingRoomBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.temp.name)
        cls.paths = build_site(reading_room_case(), ProjectConfig(name="Fictional reading room"), cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def text(self, name):
        return (self.out / name).read_text(encoding="utf-8")

    def dossier(self, pid):
        return next(p.read_text(encoding="utf-8") for p in (self.out / "people").glob("*.html") if f'data-person-id="{pid}"' in p.read_text(encoding="utf-8"))

    def test_fixture_is_valid(self):
        self.assertEqual([], validate_case(reading_room_case()))

    def test_the_tree_page_alone_loads_the_script_before_site_js(self):
        tree = self.text("tree.html")
        self.assertEqual(1, tree.count(SCRIPT_TAG))
        # A plain script in the page runs while it is read, so before the deferred site.js that builds the view.
        self.assertIn('<script defer src="assets/site.js"></script>', tree)
        self.assertNotIn(" defer", re.search(r'<script[^>]*reading_room\.js[^>]*>', tree).group(0))
        for path in self.out.rglob("*.html"):
            if path.name != "tree.html":
                self.assertNotIn("reading_room.js", path.read_text(encoding="utf-8"), path)
        script = self.text("assets/reading_room.js")
        self.assertIn("GENEALOGY_TREE_VIEWS", script)
        self.assertNotIn("innerHTML", script)  # record values enter the page as text
        self.assertIn("assets/reading_room.js", self.paths)

    def test_dossier_family_tree_link_opens_the_reading_room_on_the_person(self):
        explore = re.search(r'<p class="explore">(.*?)</p>', self.dossier("p0001")).group(1)
        self.assertIn('<a href="../tree.html#view=branches&amp;person=p0001">Family tree</a>', explore)

    def test_link_check_reads_the_view_address_as_an_address_not_an_anchor(self):
        result = check_site(self.out)
        self.assertEqual([], result["broken"])
        self.assertEqual([], result["missing_anchors"])
        # A real anchor that is missing is still reported.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "a.html").write_text('<a href="b.html#view=branches&amp;person=p1">x</a><a href="b.html#nowhere">y</a>', encoding="utf-8")
            (root / "b.html").write_text('<p id="here">b</p>', encoding="utf-8")
            self.assertEqual(["nowhere"], [row["anchor"] for row in check_site(root)["missing_anchors"]])

    def test_withheld_records_reach_no_file(self):
        for path in self.out.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="ignore")
                self.assertNotIn(SECRET, text, path)
                self.assertNotIn(SECRET_LINK, text, path)
                self.assertNotIn("r-secret", text, path)


if __name__ == "__main__":
    unittest.main()
