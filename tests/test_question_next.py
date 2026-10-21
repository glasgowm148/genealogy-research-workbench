"""An open question's plan: what would answer it and the next record to check."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import AccessLevel as A, LivingStatus as L, Name, Person, ResearchQuestion, record_from_dict
from genealogy.site import build_site

RESOLVES = "A baptism entry naming Ada's <parents>."
NEXT = "Invented parish register, 1840–1845"
GAP = '<a class="not-identified" href="{}evidence.html#not-yet-identified">Not yet identified</a>'


def case(*questions):
    c = ResearchCase("fictional-questions", "Fictional questions")
    c.add_many([Person("p0001", names=[Name("Ada Fable")], living=L.DECEASED, sensitivity=A.PUBLIC), *questions])
    return c


def question(qid="q-parents", status="open", **fields):
    return ResearchQuestion(qid, "Who were Ada Fable's parents?", related_ids=["p0001"], status=status, sensitivity=A.PUBLIC, **fields)


def plan(resolves, next_record):
    return ('<dl class="question-next"><dt>What would answer this</dt><dd>' + resolves
            + '</dd><dt>Next record to check</dt><dd>' + next_record + '</dd></dl>')


class QuestionNextTests(unittest.TestCase):
    def build(self, c, directory):
        self.assertEqual([], validate_case(c))
        out = Path(directory)
        build_site(c, ProjectConfig(name="Fictional"), out)
        return (out / "research.html").read_text(), next((out / "people").glob("*.html")).read_text(), out

    def test_the_fields_round_trip_and_are_exported(self):
        record = question(resolves=RESOLVES, next_record=NEXT)
        self.assertEqual(record, record_from_dict("ResearchQuestion", record.to_dict()))
        self.assertEqual(RESOLVES, record_from_dict("ResearchQuestion", json.loads(json.dumps(record.to_dict()))).resolves)
        with tempfile.TemporaryDirectory() as directory:
            *_, out = self.build(case(record), directory)
            exported = json.loads((out / "data/site.json").read_text())["questions"][0]
            self.assertEqual((RESOLVES, NEXT), (exported["resolves"], exported["next_record"]))

    def test_an_open_question_shows_its_plan_on_the_research_page_and_dossier(self):
        with tempfile.TemporaryDirectory() as directory:
            research, dossier, _ = self.build(case(question(resolves=RESOLVES, next_record=NEXT)), directory)
            shown = plan("A baptism entry naming Ada&#x27;s &lt;parents&gt;.", NEXT)
            self.assertIn(shown, research)
            self.assertIn(shown, dossier)

    def test_a_blank_says_not_yet_identified(self):
        with tempfile.TemporaryDirectory() as directory:
            research, dossier, out = self.build(case(question(next_record=NEXT), question("q-death", status="draft")), directory)
            self.assertIn(plan(GAP.format(""), NEXT), research)
            self.assertIn(plan(GAP.format(""), GAP.format("")), research)
            self.assertIn(plan(GAP.format("../"), NEXT), dossier)
            self.assertIn('<dt id="not-yet-identified">Not yet identified</dt>', (out / "evidence.html").read_text())

    def test_an_answered_question_shows_neither_row(self):
        with tempfile.TemporaryDirectory() as directory:
            research, dossier, _ = self.build(case(question(status="resolved", resolves=RESOLVES, next_record=NEXT), question("q-closed", status="closed")), directory)
            for page in (research, dossier):
                self.assertIn("Who were Ada Fable", page)
                self.assertNotIn("question-next", page)
                self.assertNotIn("Not yet identified", page)
                self.assertNotIn(NEXT, page)

    def test_a_private_question_keeps_its_plan_private(self):
        private = ResearchQuestion("q-private", "Who was Ada's guardian?", related_ids=["p0001"], resolves="SECRET-resolves", next_record="SECRET-next")
        with tempfile.TemporaryDirectory() as directory:
            *_, out = self.build(case(private), directory)
            everything = "".join(p.read_text(errors="ignore") for p in out.rglob("*") if p.is_file())
            self.assertNotIn("SECRET-", everything)

    def test_the_fields_must_be_text(self):
        errors = validate_case(case(question(resolves=["a", "list"], next_record=7)))
        self.assertIn("q-parents.resolves must be a string or null", errors)
        self.assertIn("q-parents.next_record must be a string or null", errors)


if __name__ == "__main__":
    unittest.main()
