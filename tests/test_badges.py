"""One badge system: every pill is linked to its guide entry, with a family colour and glyph."""
from __future__ import annotations

import json
import re
from pathlib import Path
import tempfile
import unittest

from genealogy.case import ResearchCase
from genealogy.config import ProjectConfig
from genealogy.labels import BADGE_GLYPHS, badge_family, guide_entries
from genealogy.models import (AccessLevel as A, Citation, Claim, ClaimStatus, Confidence as C, Finding, LivingStatus as L, Name, Person,
                              Relationship, Source, Study)
from genealogy.site import build_site

GRADES_TOML = '''
[grades.strongly_supported]
label = "Strongly supported"
meaning = "Several independent records agree, short of proof."
confidence = "probable"

[grades.ruled_out]
label = "Ruled out"
meaning = "The records exclude this link."
confidence = "disproved"
'''
BADGE = re.compile(r'<a class="badge(?: evidence-badge)? badge-(\w+)[^"]*" href="(?:\.\./)?evidence\.html#([^"]+)"[^>]*>(.*?)</a>')


def build(directory: Path) -> Path:
    path = directory / "genealogy.toml"
    path.write_text('[project]\nname = "Fictional badges"\n' + GRADES_TOML, encoding="utf-8")
    c = ResearchCase("fictional-badges", "Fictional badges")
    public = dict(sensitivity=A.PUBLIC)
    c.add_many([
        Person("ada", names=[Name("Ada Fable")], living=L.DECEASED, **public),
        Person("bram", names=[Name("Bram Fable")], living=L.DECEASED, **public),
        Person("cora", names=[Name("Cora Fable")], living=L.DECEASED, **public),
        Person("dell", names=[Name("Dell Fable")], living=L.DECEASED, **public),
        Person("secret", names=[Name("SECRET-BADGE Vale")], living=L.LIVING, sensitivity=A.PRIVATE),
        Relationship("r1", "ada", "bram", "parent", confidence=C.DOCUMENTED, **public),
        Relationship("r2", "ada", "cora", "parent", confidence=C.UNKNOWN, tree_status="uncertain", **public),
        Relationship("r3", "ada", "dell", "parent", confidence=C.DISPROVED, grade="ruled_out", **public),
        Relationship("r4", "ada", "secret", "parent", confidence=C.PROBABLE, grade="strongly_supported", sensitivity=A.PRIVATE),
        Source("register", "Invented register", **public),
        Citation("cit", "register", locator="entry 4", quality="original", information="primary", **public),
        Claim("born", "ada", "birth", "1801", citation_ids=["cit"], status=ClaimStatus.DISPUTED, **public),
        Finding("f1", "Ada's father is Bram Fable.", related_ids=["ada"], status="reviewed", confidence=C.PROBABLE, kind="relationship",
                recorded_on="2026-10-01", changes=[{"record_id": "r1", "before": "possible", "after": "documented"}], **public),
        Study("s1", "The Fable household", related_ids=["ada"], status="open", **public),
    ])
    out = directory / "site"
    build_site(c, ProjectConfig.load(path), out)
    return out


class BadgeFamilyTests(unittest.TestCase):
    def test_the_guide_entry_decides_the_family(self):
        grades = {"strongly_supported": {"confidence": "probable"}, "ruled_out": {"confidence": "disproved"}}
        for anchor, family in (("confidence-documented", "documented"), ("status-supported", "documented"), ("confidence-probable", "probable"),
                               ("grade-strongly_supported", "probable"), ("confidence-possible", "possible"), ("confidence-unknown", "unassessed"),
                               ("confidence-tree-link", "unassessed"), ("status-asserted", "unassessed"), ("confidence-disproved", "conflict"),
                               ("grade-ruled_out", "conflict"), ("status-disputed", "conflict"), ("status-rejected", "conflict"),
                               ("tree-marked", "tree"), ("quality-original", "kind"), ("information-primary", "kind"), ("finding-kind", "kind"),
                               ("status-open", "status"), ("research-status", "status")):
            with self.subTest(anchor=anchor):
                self.assertEqual(family, badge_family(anchor, grades))
        # Glyphs mark evidence strength only; a type or research status is not a judgement.
        self.assertEqual(["✓", "~", "?", "○", "✕", "◇"], [g for g in BADGE_GLYPHS.values() if g])
        self.assertEqual("", BADGE_GLYPHS["kind"] + BADGE_GLYPHS["status"])


class BadgeSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = build(Path(cls.tmp.name))
        cls.pages = {str(p.relative_to(cls.out)): p.read_text() for p in cls.out.rglob("*.html")}
        cls.guide = cls.pages["evidence.html"]
        cls.ada = next(text for name, text in cls.pages.items() if name.startswith("people/") and "<h1>Ada Fable</h1>" in text)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_pill_is_a_family_badge_linked_to_an_entry_with_a_hidden_glyph(self):
        grades = ProjectConfig.load(Path(self.tmp.name) / "genealogy.toml").grades
        anchors = {anchor for anchor, *_ in guide_entries(grades)}
        seen = set()
        for name, text in self.pages.items():
            self.assertNotRegex(text, r'<span class="badge[ "]', name)  # every pill is a link now
            for family, anchor, inner in BADGE.findall(text):
                with self.subTest(page=name, anchor=anchor):
                    self.assertIn(anchor, anchors)
                    self.assertEqual(badge_family(anchor, grades), family)
                    glyph = BADGE_GLYPHS[family]
                    self.assertEqual(inner.startswith(f'<span class="badge-glyph" aria-hidden="true">{glyph}</span>'), bool(glyph))
                    self.assertTrue(re.sub(r"<[^>]+>", "", inner).lstrip(glyph).strip())  # the words carry the label
                seen.add(family)
        self.assertEqual(set(BADGE_GLYPHS), seen)

    def test_each_kind_of_pill_keeps_its_stored_values(self):
        self.assertIn('<a class="badge evidence-badge badge-documented" href="../evidence.html#confidence-documented" data-confidence="documented">'
                      '<span class="badge-glyph" aria-hidden="true">✓</span>Documented</a>', self.ada)
        self.assertIn('<a class="badge evidence-badge badge-conflict" href="../evidence.html#grade-ruled_out" data-confidence="disproved" data-grade="ruled_out">'
                      '<span class="badge-glyph" aria-hidden="true">✕</span>Ruled out</a>', self.ada)
        # An imported link and its tree's own mark: two badges, each linked to its own entry.
        self.assertIn('data-confidence="unknown" data-tree-status="uncertain"><span class="badge-glyph" aria-hidden="true">○</span>Unassessed tree link</a> '
                      '<a class="badge evidence-badge badge-tree" href="../evidence.html#tree-marked"><span class="badge-glyph" aria-hidden="true">◇</span>'
                      'Tree-marked uncertain</a>', self.ada)
        findings = self.pages["findings.html"]
        self.assertIn('<a class="badge evidence-badge badge-kind finding-kind" href="evidence.html#finding-kind" data-kind="relationship">Relationship</a>', findings)
        self.assertIn('<a class="badge evidence-badge badge-documented change" href="evidence.html#confidence-documented" data-after="documented" '
                      'data-before="possible"><span class="badge-glyph" aria-hidden="true">✓</span>Possible → Documented</a>', findings)
        study = next(text for name, text in self.pages.items() if name.startswith("studies/s-"))
        self.assertIn('<a class="badge evidence-badge badge-status" href="../evidence.html#status-open" data-status="open">Open</a>', study)
        self.assertIn('<a class="badge badge-kind" href="evidence.html#quality-original" data-quality="original">Original record</a> · '
                      '<a class="badge badge-kind" href="evidence.html#information-primary" data-information="primary">primary information</a>',
                      self.pages["sources.html"])

    def test_the_guide_opens_with_each_badge_once_and_its_meaning(self):
        glance = re.search(r'<section class="guide-glance" aria-labelledby="at-a-glance">.*?</section>', self.guide).group(0)
        self.assertLess(self.guide.index(glance), self.guide.index("<h2>Confidence</h2>"))
        drawn = [anchor for _, anchor, _ in BADGE.findall(glance)]
        self.assertEqual(len(drawn), len(set(drawn)))
        for anchor in ("confidence-documented", "grade-strongly_supported", "confidence-tree-link", "tree-marked", "grade-ruled_out",
                       "status-disputed", "status-open", "quality-original", "finding-kind"):
            self.assertIn(anchor, drawn)
            self.assertIn(f'<dt id="{anchor}">', self.guide)
        # From strongest to weakest, then conflicts: a project grade sits with the grade it counts as.
        evidence = [anchor for _, anchor, _ in BADGE.findall(glance.split("</ol>", 1)[0])]
        self.assertEqual(["confidence-documented", "confidence-probable", "grade-strongly_supported", "confidence-possible", "confidence-unknown",
                          "confidence-tree-link", "confidence-disproved", "grade-ruled_out", "tree-marked"], evidence)
        self.assertIn('evidence.html#confidence-documented"><span class="badge-glyph" aria-hidden="true">✓</span>Documented</a> '
                      '<span class="glance-meaning">An assessed, cited record states this directly.</span>', glance)
        # Entries that are not pills are linked once, in a closing line.
        self.assertIn('Also: <a href="#estimate">probable (70%) and similar</a>', glance)
        self.assertNotIn(' id="', glance.replace('<h2 id="at-a-glance">', ""))  # the full entries keep the anchors

    def test_the_script_draws_the_same_badges(self):
        script = (self.out / "assets/site.js").read_text()
        for needle in ("badge evidence-badge badge-${family}", "badge-glyph", "'aria-hidden','true'", "'tree-marked','tree'"):
            self.assertIn(needle, script)
        data = (self.out / "data/site-data.js").read_text()
        data = json.loads(data[data.index("{"):data.rindex("}") + 1])
        self.assertEqual({"strongly_supported": "probable", "ruled_out": "disproved"}, data["site"]["grade_confidence"])

    def test_nothing_withheld_reaches_any_output(self):
        for path in self.out.rglob("*"):
            if path.is_file():
                self.assertNotIn("SECRET-BADGE", path.read_text(errors="ignore"), path.name)


if __name__ == "__main__":
    unittest.main()
