"""End-to-end: protected imported material is absent from every generated output."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.cli import main

GEDCOM = """0 HEAD
1 CHAR UTF-8
0 @S1@ SOUR
1 TITL Invented public register
0 @S2@ SOUR
1 TITL LIVINGONLY-SOURCE-TITLE
0 @I1@ INDI
1 NAME Hollis /Fable/
1 SEX M
1 BIRT
2 DATE ABT 1801
2 PLAC Invented Harbour
3 MAP
4 LATI N55.5
4 LONG W4.5
2 SOUR @S1@
3 PAGE folio 2
3 DATA
4 TEXT PRIVATE-QUOTATION-TEXT
1 DEAT
2 DATE 1870
1 NOTE PRIVATE-NOTE-TEXT
1 _UID PRIVATE-UID-VALUE
0 @I2@ INDI
1 NAME Secretly /Living/
1 BIRT
2 DATE 1990
2 PLAC LIVING-ONLY-PLACE
1 SOUR @S2@
0 @I3@ INDI
1 NAME Restricted /Person/
1 RESN privacy
1 DEAT Y
0 @I4@ INDI
1 NAME Unknown /Status/
0 @I5@ INDI
1 NAME Mara /Fable/
1 SEX F
1 BURI
2 DATE 1880
0 @F1@ FAM
1 HUSB @I1@
1 WIFE @I5@
1 CHIL @I2@
1 MARR
2 DATE 1825
0 @F2@ FAM
1 HUSB @I2@
1 WIFE @I3@
1 MARR
2 DATE 2015
2 PLAC LIVING-WEDDING-PLACE
0 TRLR
"""
PROTECTED = ("Secretly", "Restricted /Person", "Restricted Person", "Unknown Status", "LIVINGONLY-SOURCE-TITLE",
             "LIVING-ONLY-PLACE", "LIVING-WEDDING-PLACE", "PRIVATE-NOTE-TEXT", "PRIVATE-QUOTATION-TEXT",
             "PRIVATE-UID-VALUE", "gedcom:person:I2", "gedcom:person:I3", "gedcom:person:I4", "2015")


class PublicOutputPrivacyTests(unittest.TestCase):
    def test_every_output_file_withholds_protected_records_and_references_resolve(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            root = Path(temporary)
            source = root / "tree.ged"
            source.write_text(GEDCOM, encoding="utf-8")
            project = root / "project"
            self.assertEqual(main(["init", str(project), "--name", "Invented study"]), 0)
            (project / "genealogy.toml").write_text((project / "genealogy.toml").read_text() + '\n[site]\nbase_url = "https://example.invalid/"\n')
            self.assertEqual(main(["--project", str(project), "import", str(source), "--publish-deceased", "--publish-reviewed-sources"]), 0)
            self.assertEqual(main(["--project", str(project), "build"]), 0)
            for format_name in ("json", "csv", "ndjson", "geojson", "gedcom"):
                self.assertEqual(main(["--project", str(project), "export", format_name, "--output", str(root / f"export.{format_name}")]), 0)
            files = [path for path in (project / "dist").rglob("*") if path.is_file()] + list(root.glob("export.*"))
            self.assertGreater(len(files), 20)
            for path in files:
                text = path.read_text(encoding="utf-8")
                for value in PROTECTED:
                    self.assertNotIn(value, text, f"{value} leaked into {path.relative_to(root)}")
            data = json.loads((project / "dist" / "data" / "site.json").read_text())
            self.assertEqual(sorted(person["names"][0]["value"] for person in data["people"]), ["Hollis Fable", "Mara Fable"])
            self.assertTrue(any(source["title"] == "Invented public register" for source in data["sources"]))
            self.assertEqual({event["kind"] for event in data["events"]}, {"birth", "death", "burial", "marriage"})
            ids = {row["id"] for rows in data.values() if isinstance(rows, list) for row in rows}
            for collection in ("relationships", "claims", "evidence", "citations", "events", "people"):
                for row in data[collection]:
                    for field in ("subject_id", "object_id", "claim_id", "citation_id", "source_id", "place_id"):
                        if row.get(field):
                            self.assertIn(row[field], ids, (collection, field))
                    for field in ("participant_ids", "event_ids", "citation_ids", "claim_ids"):
                        for value in row.get(field, []):
                            self.assertIn(value, ids, (collection, field))
            pages = json.loads((project / "dist" / "data" / "routes.json").read_text())
            sitemap = (project / "dist" / "sitemap.xml").read_text()
            self.assertEqual(len(re.findall("<loc>", sitemap)), len(pages))
            self.assertEqual(len([page for page in pages if page.startswith("people/")]), 2)


if __name__ == "__main__":
    unittest.main()
