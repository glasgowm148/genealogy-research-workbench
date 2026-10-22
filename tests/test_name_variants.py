"""Surname variants: [names.variants] folds recorded spellings into one surname."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import AccessLevel as A, Event, LivingStatus as L, Name, Person, Relationship
from genealogy.site import build_site

VARIANTS_TOML = '''
[names.variants]
Fable = ["Fabel", "Faible"]
Secretvale = ["Secretvail"]
'''


def config(directory: Path, extra: str = VARIANTS_TOML) -> ProjectConfig:
    path = directory / "genealogy.toml"
    path.write_text('[project]\nname = "Fictional variant tree"\n' + extra, encoding="utf-8")
    return ProjectConfig.load(path)


def person(pid, given, surname, year, sensitivity=A.PUBLIC):
    return [Person(pid, names=[Name(f"{given} {surname}", surname=surname)], living=L.DECEASED, event_ids=[f"{pid}-b"], sensitivity=sensitivity),
            Event(f"{pid}-b", "birth", date=str(year), participant_ids=[pid], sensitivity=sensitivity)]


def case() -> ResearchCase:
    c = ResearchCase("fictional-variants", "Fictional variants")
    c.add_many([
        *person("p0001", "Ada", "Fable", 1800), *person("p0002", "Bram", "Fabel", 1770), *person("p0003", "Cora", "Fabel", 1802),
        *person("p0004", "Dov", "Fabel", 1805), *person("p0005", "Elin", "Faible", 1808), *person("p0006", "Finn", "Vale", 1801),
        # Withheld: neither the person nor their surname group may reach any output.
        *person("p0007", "Gil", "Secretvale", 1900, A.PRIVATE),
        Relationship("r1", "p0001", "p0002", "parent", sensitivity=A.PUBLIC),
        Relationship("r2", "p0003", "p0002", "parent", sensitivity=A.PUBLIC),
    ])
    return c


class VariantConfigTests(unittest.TestCase):
    def test_variants_load_as_a_casefolded_map(self):
        with tempfile.TemporaryDirectory() as directory:
            loaded = config(Path(directory))
            self.assertEqual({"fable": "Fable", "fabel": "Fable", "faible": "Fable", "secretvale": "Secretvale", "secretvail": "Secretvale"},
                             loaded.name_variants)
            self.assertEqual(loaded.names, loaded.to_dict()["names"])
            self.assertEqual({}, config(Path(directory), "").name_variants)
            # A spelling that repeats its own canonical surname in another case is harmless.
            self.assertEqual({"fable": "Fable"}, config(Path(directory), '[names.variants]\nFable = ["FABLE"]\n').name_variants)

    def test_bad_variants_are_rejected(self):
        for bad, message in (('[names]\nvariants = ["Fabel"]\n', r"\[names.variants\] must be a table"),
                             ('[names]\nvariant = {Fable = ["Fabel"]}\n', "names has unknown settings: variant"),
                             ('[names.variants]\nFable = "Fabel"\n', "names.variants.Fable must be a list of non-empty strings"),
                             ('[names.variants]\nFable = ["Fabel", " "]\n', "names.variants.Fable must be a list of non-empty strings"),
                             ('[names.variants]\nFable = ["Fabel", 3]\n', "names.variants.Fable must be a list of non-empty strings"),
                             ('[names.variants]\n"" = ["Fabel"]\n', "a canonical surname must be non-empty"),
                             # One spelling, in any case, cannot belong to two surnames ...
                             ('[names.variants]\nFable = ["Fabel"]\nVale = ["fabel"]\n', "'fabel' is already listed under 'Fable'"),
                             # ... and a canonical surname cannot be another one's variant, in either order.
                             ('[names.variants]\nFable = ["Vale"]\nVale = ["Vail"]\n', "'Vale' is already listed under 'Fable'"),
                             ('[names.variants]\nVale = ["Vail"]\nFable = ["vale"]\n', "'vale' is already listed under 'Vale'"),
                             ('[names.variants]\nFable = ["Fabel"]\nFABLE = ["Faible"]\n', "'FABLE' is already listed under 'Fable'")):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(ValueError, message):
                    config(Path(directory), bad)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "genealogy.toml"
            path.write_text('names = "Fable"\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"\[names\] must be a table"):
                ProjectConfig.load(path)


class VariantSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.out = cls.root / "site"
        assert validate_case(case()) == []
        build_site(case(), config(cls.root), cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def text(self, path):
        return (self.out / path).read_text(encoding="utf-8")

    def test_branches_group_every_spelling_under_the_canonical_surname(self):
        html = self.text("branches.html")
        rows = re.findall(r'<tr data-surname="([^"]*)"><td>(.*?)</td><td>(\d+)</td>', html)
        self.assertEqual([("Fable", '<a href="catalogue.html?surname=Fable">Fable</a><br><span class="meta">Recorded as Fabel (3), Fable (1), Faible (1)</span>', "5"),
                          ("Vale", '<a href="catalogue.html?surname=Vale">Vale</a>', "1")], rows)
        self.assertIn("spellings this project lists as variants of one surname are grouped under it", html)
        # Ada Fable's recorded parent is Bram Fabel: one surname, so she is not listed as a founder.
        fable_row = html.split('<tr data-surname="Fable">', 1)[1].split("</tr>", 1)[0]
        self.assertEqual(["Bram Fabel", "Dov Fabel", "Elin Faible"], re.findall(r">([^<]+)</a>", fable_row.split("</td>")[-2]))
        self.assertIn("<td>Fable</td>", html.split("<h2>Connected groups</h2>", 1)[1])

    def test_catalogue_filters_by_canonical_surname_and_shows_the_recorded_spelling(self):
        html = self.text("catalogue.html")
        row = re.search(r'<tr data-person-id="p0002" data-surname="([^"]*)".*?</tr>', html)
        self.assertEqual("Fable", row[1])
        self.assertIn(">Bram Fabel</a>", row[0])  # the name as recorded; the table has no surname column
        dossier = next(p for p in (self.out / "people").glob("*.html") if "<h1>Bram Fabel</h1>" in p.read_text(encoding="utf-8"))
        self.assertIn("<li>Bram Fabel — ", dossier.read_text(encoding="utf-8"))

    def test_site_data_ships_the_variants_of_public_surnames_only(self):
        script = self.text("data/site-data.js")
        data = json.loads(script.split("=", 1)[1].rstrip(";\n"))
        self.assertEqual({"fable": "Fable", "fabel": "Fable", "faible": "Fable"}, data["site"]["name_variants"])
        for path in self.out.rglob("*"):
            if path.is_file():
                self.assertNotIn("secretva", path.read_text(encoding="utf-8").casefold(), path)

    def test_a_site_without_variants_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "site"
            build_site(case(), config(Path(directory), ""), out)
            self.assertNotIn('"name_variants"', (out / "data/site-data.js").read_text())
            html = (out / "branches.html").read_text()
            self.assertIn('<tr data-surname="Fabel">', html)
            self.assertNotIn("Recorded as", html)
            self.assertNotIn("variants of one surname", html)


if __name__ == "__main__":
    unittest.main()
