import tempfile
import unittest

from genealogy import (
    CaseStore, Citation, Claim, Evidence, Finding, Hypothesis, Name, Person,
    ResearchQuestion, ResearchService, Source,
)


class ResearchServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = ResearchService(CaseStore(self.temp.name))
        self.service.create_case("case-a", "Synthetic correspondence")

    def test_case_lifecycle_search_and_reference_queries(self) -> None:
        source = Source(id="source-a", title="Imaginary register")
        citation = Citation(id="citation-a", source_id=source.id, locator="entry 3")
        claim = Claim(id="claim-a", subject_id=source.id, predicate="residence", value="Northfield",
                      citation_ids=[citation.id])
        evidence = Evidence(id="evidence-a", claim_id=claim.id, citation_id=citation.id,
                            assessment="direct support")
        question = ResearchQuestion(id="question-a", question="Who lived in Northfield?",
                                    related_ids=[claim.id], priority="high")
        for record in (source, citation, claim):
            self.service.add_record("case-a", record)
        self.service.add_evidence("case-a", evidence)
        self.service.add_question("case-a", question)

        hits = self.service.search_records("case-a", "northfield")
        self.assertEqual({hit.record.id for hit in hits}, {"claim-a", "question-a"})
        self.assertEqual([record.id for record in self.service.query_records("case-a", related_to="claim-a")],
                         ["evidence-a", "question-a"])
        self.assertEqual([case.id for case in self.service.list_cases()], ["case-a"])
        self.service.add_record("case-a", Person(id="person-a", names=[Name(value="Elian Marrow")]))
        nested_hit = self.service.search_records("case-a", "marrow")
        self.assertEqual(nested_hit[0].matched_fields, ("names[0].value",))
        with self.assertRaisesRegex(ValueError, "unsupported record type"):
            self.service.query_records("case-a", kind="NotARecord")

    def test_updates_validate_references_without_corrupting_stored_case(self) -> None:
        question = ResearchQuestion(id="question-a", question="Can this be resolved?")
        self.service.add_question("case-a", question)
        updated = self.service.update_question("case-a", question.id, status="resolved")
        self.assertEqual(updated.status, "resolved")
        with self.assertRaisesRegex(ValueError, "missing record"):
            self.service.update_question("case-a", question.id, related_ids=["not-a-record"])
        self.assertEqual(self.service.get_case("case-a").records("ResearchQuestion")[0].related_ids, [])

    def test_unresolved_work_and_completeness_distinguish_evidence_gaps(self) -> None:
        source = Source(id="source-a", title="Synthetic note")
        claim = Claim(id="claim-a", subject_id=source.id, predicate="identity", value="candidate")
        finding = Finding(id="finding-a", conclusion="Not established", status="draft")
        hypothesis = Hypothesis(id="hypothesis-a", statement="Two records refer to one person")
        question = ResearchQuestion(id="question-a", question="Are the records connected?")
        self.service.add_record("case-a", source)
        self.service.add_claim("case-a", claim)
        self.service.add_finding("case-a", finding)
        self.service.add_hypothesis("case-a", hypothesis)
        self.service.add_question("case-a", question)

        completeness = self.service.evidence_completeness("case-a")
        self.assertFalse(completeness.complete)
        self.assertEqual((completeness.claims, completeness.claims_with_citations), (1, 0))
        report = self.service.unresolved_work("case-a")
        self.assertEqual(report.open_question_ids, ("question-a",))
        self.assertEqual(report.uncited_claim_ids, ("claim-a",))
        self.assertEqual(report.unsupported_finding_ids, ("finding-a",))
        brief = self.service.research_brief("case-a")
        self.assertIn("## Evidence coverage", brief)
        self.assertIn("Are the records connected?", brief)
        self.assertIn("Claims without citations: claim-a", brief)

    def test_invalid_references_are_rejected_before_an_add_is_saved(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing record"):
            self.service.add_finding(
                "case-a", Finding(id="finding-a", conclusion="Unsupported", evidence_ids=["absent"])
            )
        self.assertEqual(self.service.get_case("case-a").records("Finding"), [])


if __name__ == "__main__":
    unittest.main()
