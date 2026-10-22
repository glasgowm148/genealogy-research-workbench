"""A citation's record quality: its form and its information, in the standard terms."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.labels import INFORMATION, SOURCE_QUALITY, guide_entries, quality_label
from genealogy.models import (AccessLevel as A, Citation, Claim, ClaimStatus, Evidence, LivingStatus as L, Name, Person, Source,
                              record_from_dict)
from genealogy.site import build_site
from genealogy.sitecheck import check_site

BADGES = ('<a class="badge badge-kind" href="{p}evidence.html#quality-original" data-quality="original">Original record</a> · '
          '<a class="badge badge-kind" href="{p}evidence.html#information-primary" data-information="primary">primary information</a>')


def case(quality="original", information="primary"):
    c = ResearchCase("fictional-quality", "Fictional record quality")
    c.add_many([
        Person("ada", names=[Name("Ada Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Source("register", "Invented register", "register", sensitivity=A.PUBLIC),
        Source("history", "An invented family history", "book", sensitivity=A.PUBLIC),
        Citation("entry", "register", locator="entry 4", quality=quality, information=information, sensitivity=A.PUBLIC),
        Citation("copy", "register", locator="index p. 2", quality="derivative", sensitivity=A.PUBLIC),
        Citation("plain", "register", locator="entry 9", sensitivity=A.PUBLIC),
        # A private citation's terms are as private as the rest of it.
        Citation("SECRET-chapter", "history", locator="SECRET-page", quality="authored", information="secondary"),
        Claim("ada-born", "ada", "birth", "1850", citation_ids=["entry", "copy", "plain"], status=ClaimStatus.SUPPORTED,
              sensitivity=A.PUBLIC),
        Claim("ada-moved", "ada", "residence", "Mill Lane", citation_ids=["SECRET-chapter"], sensitivity=A.PUBLIC),
        Evidence("ev-entry", "ada-born", "entry", "Records the baptism and birth date.", sensitivity=A.PUBLIC),
    ])
    return c


class CitationQualityTests(unittest.TestCase):
    def build(self, directory, c=None):
        out = Path(directory)
        build_site(c or case(), ProjectConfig(name="Fictional"), out)
        return out

    def test_the_standard_terms_are_accepted_and_round_trip(self):
        for quality in ("original", "derivative", "authored", None):
            for information in ("primary", "secondary", "undetermined", None):
                c = case(quality, information)
                self.assertEqual([], validate_case(c), (quality, information))
        c = case()
        record = c.records("Citation")[0]
        self.assertEqual(("original", "primary"), (record.quality, record.information))
        self.assertEqual(record, record_from_dict("Citation", json.loads(json.dumps(record.to_dict()))))
        self.assertEqual(c.to_dict(), ResearchCase.from_dict(json.loads(json.dumps(c.to_dict()))).to_dict())

    def test_anything_else_is_rejected(self):
        # Neither a differently written term, a GEDCOM QUAY grade, nor a confidence is a record's quality.
        for quality, information in (("Original", None), ("3", None), (3, None), ("documented", None), (None, "first-hand"), (None, "Primary"), (None, ["primary"])):
            errors = validate_case(case(quality, information))
            field, allowed = ("quality", "original, derivative, authored") if quality is not None else ("information", "primary, secondary, undetermined")
            self.assertIn(f"entry.{field} must be one of: {allowed}, or null", errors, (quality, information))

    def test_labels_name_the_record_in_standard_terms(self):
        self.assertEqual({"original", "derivative", "authored"}, set(SOURCE_QUALITY))
        self.assertEqual({"primary", "secondary", "undetermined"}, set(INFORMATION))
        self.assertEqual("Original record · primary information", quality_label({"quality": "original", "information": "primary"}))
        self.assertEqual("Derivative record", quality_label({"quality": "derivative"}))
        self.assertEqual("Undetermined information", quality_label({"information": "undetermined"}))
        self.assertEqual("", quality_label({}))
        rows = {anchor: (label, meaning) for anchor, label, meaning, group in guide_entries() if group == "Record quality"}
        self.assertEqual({"quality-original", "quality-derivative", "quality-authored", "information-primary", "information-secondary",
                          "information-undetermined", "record-quality"}, set(rows))
        self.assertIn("never how far a claim is believed", rows["record-quality"][1])

    def test_the_source_page_and_evidence_table_show_the_terms(self):
        with tempfile.TemporaryDirectory() as directory:
            out = self.build(directory)
            sources = (out / "sources.html").read_text()
            self.assertIn('<p class="record-quality">' + BADGES.format(p="") + "</p><p><strong>Locator:</strong> entry 4</p>", sources)
            self.assertIn('<p class="record-quality"><a class="badge badge-kind" href="evidence.html#quality-derivative" data-quality="derivative">Derivative record</a></p>'
                          "<p><strong>Locator:</strong> index p. 2</p>", sources)
            self.assertEqual(2, sources.count('class="record-quality"'))  # the plain citation states neither
            dossier = next((out / "people").glob("*.html")).read_text()
            self.assertIn('<br><span class="meta">entry 4</span><br><span class="record-quality">' + BADGES.format(p="../") + "</span></td>", dossier)
            self.assertIn('<br><span class="meta">entry 9</span></td>', dossier)
            # The by-type table adds nothing.
            start = sources.index("<h2>By record type</h2>")
            self.assertNotIn("record-quality", sources[start:sources.index("</table>", start)])
            guide = (out / "evidence.html").read_text()
            self.assertIn('<h2>Record quality</h2><dl class="evidence-guide"><dt id="quality-original">Original record</dt>', guide)
            self.assertIn('<dt id="information-undetermined">Undetermined information</dt>', guide)
            self.assertIn('<dt id="record-quality">Quality is not confidence</dt>', guide)
            self.assertEqual([], check_site(out)["broken"])
            # The catalogue's filter reads the stated terms; a citation stating neither is not carried.
            script = (out / "data/site-data.js").read_text()
            data = json.loads(script[script.index("{"):script.rindex("}") + 1])
            self.assertEqual([{"id": "entry", "source_id": "register", "quality": "original", "information": "primary"},
                              {"id": "copy", "source_id": "register", "quality": "derivative"}], data["citations"])
            self.assertEqual(["entry", "copy", "plain"], data["claims"][0]["citation_ids"])
            self.assertEqual("original", json.loads((out / "data/site.json").read_text())["citations"][0]["quality"])

    def test_a_private_citation_keeps_its_terms_private(self):
        with tempfile.TemporaryDirectory() as directory:
            out = self.build(directory)
            for path in out.rglob("*"):
                if not path.is_file():
                    continue
                text = path.read_text(errors="ignore")
                self.assertNotIn("SECRET-", text, path)
                self.assertNotIn('data-quality="authored"', text, path)
                self.assertNotIn('data-information="secondary"', text, path)
                if path.name != "evidence.html":  # the guide explains every term
                    self.assertNotIn("authored", text.casefold(), path)
                    self.assertNotIn("secondary", text.casefold(), path)


if __name__ == "__main__":
    unittest.main()
