"""Competing hypotheses side by side, each with the researcher's points for and against."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Citation, Claim, Confidence, Evidence, Hypothesis, LivingStatus as L, Name, Person, Source,
                              record_from_dict)
from genealogy.site import _anchor, build_site

BRAM_FOR = ["The banns name a Bram Fable of the same parish.", "Bram's will leaves a <cottage> to 'my daughter A.'"]
BRAM_AGAINST = ["Bram would have been fourteen at Ada's birth."]
ODO_FOR = ["Odo stood as witness at Ada's wedding."]


def person(pid, name):
    return Person(pid, names=[Name(name)], living=L.DECEASED, sensitivity=A.PUBLIC)


def hypothesis(hid, statement, related=("p0001",), **fields):
    return Hypothesis(hid, statement, related_ids=list(related), sensitivity=A.PUBLIC, **fields)


def records():
    return [person("p0001", "Ada Fable"), person("p0002", "Bram Fable"), person("p0003", "Odo Fable"),
            Source("s1", "Invented parish register", "register", sensitivity=A.PUBLIC),
            Citation("c1", "s1", locator="folio 3", sensitivity=A.PUBLIC),
            Claim("cl-father", "p0001", "father", "Bram Fable", citation_ids=["c1"], sensitivity=A.PUBLIC),
            Evidence("e-bram", "cl-father", "c1", "The banns name a father Bram.", sensitivity=A.PUBLIC),
            Evidence("e-odo", "cl-father", "c1", "The banns name Bram, not Odo.", supports=False, sensitivity=A.PUBLIC),
            # Two open hypotheses about Ada alone compete; listed out of id order on purpose.
            hypothesis("h-odo", "Ada's father was Odo Fable", supports=ODO_FOR, evidence_ids=["e-odo"], confidence=Confidence.POSSIBLE),
            hypothesis("h-bram", "Ada's father was Bram Fable", supports=BRAM_FOR, objections=BRAM_AGAINST, evidence_ids=["e-bram"],
                       confidence=Confidence.PROBABLE),
            # Not competing: rejected, disproved, or about a different set of people.
            hypothesis("h-rejected", "Ada was a foundling", status="rejected", objections=["Her baptism names both parents."]),
            hypothesis("h-disproved", "Ada's father was a sailor", confidence=Confidence.DISPROVED),
            hypothesis("h-pair", "Ada and Odo were cousins", related=("p0003", "p0001"), supports=["They shared a godparent."]),
            hypothesis("h-plain", "Bram moved away after 1850", related=("p0002",))]


def case(*extra):
    c = ResearchCase("fictional-hypotheses", "Fictional hypotheses")
    c.add_many([*records(), *extra])
    return c


def compare_blocks(page):
    return re.findall(r'<li class="hypotheses-group">.*?</div></li>', page)


class HypothesesCompareTests(unittest.TestCase):
    def build(self, c, directory):
        self.assertEqual([], validate_case(c))
        out = Path(directory)
        build_site(c, ProjectConfig(name="Fictional"), out)
        dossier = lambda pid: next(p for p in (out / "people").glob("*.html") if f'data-person-id="{pid}"' in p.read_text()).read_text()
        return (out / "research.html").read_text(), dossier, out

    def test_the_points_round_trip_and_are_exported(self):
        record = hypothesis("h-bram", "Ada's father was Bram Fable", supports=BRAM_FOR, objections=BRAM_AGAINST)
        again = record_from_dict("Hypothesis", json.loads(json.dumps(record.to_dict())))
        self.assertEqual(record, again)
        self.assertEqual((BRAM_FOR, BRAM_AGAINST), (again.supports, again.objections))
        self.assertEqual(([], []), (Hypothesis("h", "A statement").supports, Hypothesis("h", "A statement").objections))
        with tempfile.TemporaryDirectory() as directory:
            *_, out = self.build(case(), directory)
            exported = {h["id"]: h for h in json.loads((out / "data/site.json").read_text())["hypotheses"]}
            self.assertEqual((BRAM_FOR, BRAM_AGAINST), (exported["h-bram"]["supports"], exported["h-bram"]["objections"]))

    def test_open_hypotheses_about_the_same_people_sit_side_by_side_on_the_research_page(self):
        with tempfile.TemporaryDirectory() as directory:
            research, *_ = self.build(case(), directory)
            blocks = compare_blocks(research)
            self.assertEqual(1, len(blocks))
            block = blocks[0]
            self.assertIn('<div class="hypotheses-compare" role="group" aria-labelledby="compare-' + _anchor("h-bram") + '">', block)
            self.assertIn('id="compare-' + _anchor("h-bram") + '">Competing hypotheses about <a href="people/', block)
            self.assertIn('evidence.html#for-and-against', block)
            # Both cards keep their anchors, in id order: neither is placed first on merit.
            self.assertLess(block.index(f'id="{_anchor("h-bram")}"'), block.index(f'id="{_anchor("h-odo")}"'))
            self.assertEqual(2, block.count('class="card hypothesis-card"'))
            self.assertIn("<h3>Ada&#x27;s father was Bram Fable</h3>", block)
            self.assertIn('<dt>For</dt><dd class="points-for"><ul><li>The banns name a Bram Fable of the same parish.</li>'
                          '<li>Bram&#x27;s will leaves a &lt;cottage&gt; to &#x27;my daughter A.&#x27;</li></ul></dd>', block)
            self.assertIn('<dt>Against</dt><dd class="points-against"><ul><li>Bram would have been fourteen at Ada&#x27;s birth.</li></ul></dd>', block)
            # A blank side says so; the evidence links name the claim they assess.
            self.assertIn('<dd class="points-against"><p class="meta">None recorded</p></dd>', block)
            self.assertIn(f'#{_anchor("e-bram")}">father: Bram Fable</a>', block)
            self.assertIn(f'#{_anchor("e-odo")}">father: Bram Fable</a> <span class="meta">(challenges)</span>', block)
            for excluded in ("h-rejected", "h-disproved", "h-pair", "h-plain"):
                self.assertNotIn(_anchor(excluded), block)
                self.assertIn(f'<li id="{_anchor(excluded)}"', research)

    def test_no_score_ranking_or_verdict_is_added(self):
        with tempfile.TemporaryDirectory() as directory:
            research, dossier, _ = self.build(case(), directory)
            for page in (research, dossier("p0001")):
                text = re.sub(r"<[^>]+>", " ", compare_blocks(page)[0]).casefold()
                for word in ("score", "/100", "likely", "most", "best", "verdict", "winner", "1 for", "2 for", "points for"):
                    self.assertNotIn(word, text)

    def test_a_lone_hypothesis_shows_its_points_inline(self):
        with tempfile.TemporaryDirectory() as directory:
            research, dossier, _ = self.build(case(), directory)
            inline = ('<dl class="hypothesis-points"><dt>For</dt><dd class="points-for"><p class="meta">None recorded</p></dd><dt>Against</dt>'
                      '<dd class="points-against"><ul><li>Her baptism names both parents.</li></ul></dd></dl>'
                      '<p class="meta points-note"><a href="{}evidence.html#for-and-against">Recorded points, not a tally</a></p>')
            self.assertIn(inline.format(""), research)
            self.assertIn(inline.format("../"), dossier("p0001"))
            # A different set of people is its own question: shown alone on both dossiers.
            for pid in ("p0001", "p0003"):
                self.assertIn('<li>They shared a godparent.</li>', dossier(pid))
            self.assertEqual([], compare_blocks(dossier("p0003")))
            # With neither list recorded, the entry is as before.
            plain = re.search(rf'<li id="{_anchor("h-plain")}".*?</li>', research)[0]
            self.assertNotIn("hypothesis-points", plain)
            self.assertNotIn("hypothesis-points", dossier("p0002"))

    def test_each_related_dossier_compares_them(self):
        with tempfile.TemporaryDirectory() as directory:
            _, dossier, _ = self.build(case(hypothesis("h-ada-bram", "Bram raised Ada", related=("p0002", "p0001")),
                                            hypothesis("h-ada-bram-2", "Ada was Bram's ward", related=("p0001", "p0002"))), directory)
            ada, bram = dossier("p0001"), dossier("p0002")
            self.assertEqual(2, len(compare_blocks(ada)))
            self.assertEqual(1, len(compare_blocks(bram)))
            block = compare_blocks(ada)[0]
            self.assertIn(f'<h3><a href="../research.html#{_anchor("h-bram")}">Ada&#x27;s father was Bram Fable</a></h3>', block)
            self.assertNotIn(f'id="{_anchor("h-bram")}"', block)
            self.assertIn('../evidence.html#for-and-against', block)
            self.assertIn("Bram raised Ada", compare_blocks(bram)[0])
            self.assertIn("Ada was Bram&#x27;s ward", compare_blocks(bram)[0])
            # The group appears once, not once per member.
            self.assertEqual(1, ada.count("Ada&#x27;s father was Odo Fable"))

    def test_the_guide_explains_the_points(self):
        with tempfile.TemporaryDirectory() as directory:
            *_, out = self.build(case(), directory)
            guide = (out / "evidence.html").read_text()
            self.assertIn('<h2>Hypotheses</h2><dl class="evidence-guide"><dt id="for-and-against">For and against</dt>', guide)
            self.assertIn("not a tally", guide)

    def test_a_withheld_rival_leaves_the_other_alone_and_its_points_private(self):
        private = Hypothesis("h-secret", "SECRET-statement", related_ids=["p0001"], supports=["SECRET-for"], objections=["SECRET-against"])
        hidden_person = Person("p0009", names=[Name("SECRET-name")], living=L.LIVING, sensitivity=A.PUBLIC)
        depends = hypothesis("h-depends", "Ada's father was SECRET-person", related=("p0001", "p0009"), supports=["SECRET-depends"])
        c = ResearchCase("fictional-hypotheses", "Fictional hypotheses")
        c.add_many([*(r for r in records() if r.id != "h-odo"), private, hidden_person, depends])
        with tempfile.TemporaryDirectory() as directory:
            research, dossier, out = self.build(c, directory)
            everything = "".join(p.read_text(errors="ignore") for p in out.rglob("*") if p.is_file())
            self.assertNotIn("SECRET-", everything)
            self.assertEqual([], compare_blocks(research))
            self.assertIn("<li>Bram would have been fourteen at Ada&#x27;s birth.</li>", dossier("p0001"))

    def test_the_points_must_be_lists_of_text(self):
        errors = validate_case(case(hypothesis("h-bad", "A statement", supports="one point", objections=["ok", ""]),
                                    hypothesis("h-bad-2", "A statement", supports=[" "], objections=[3])))
        for hid in ("h-bad", "h-bad-2"):
            for field in ("supports", "objections"):
                self.assertIn(f"{hid}.{field} must be a list of non-empty text points", errors)


if __name__ == "__main__":
    unittest.main()
