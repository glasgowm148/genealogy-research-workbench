"""Bulk imports preserve the same identity and privacy boundaries as small cases."""
from __future__ import annotations

import unittest

from genealogy.case import ResearchCase
from genealogy.models import Finding, Person, ResearchQuestion, Sensitivity


class BulkCaseTests(unittest.TestCase):
    def test_conflict_or_raw_material_does_not_partially_insert_batch(self):
        case = ResearchCase(id="batch", title="Fictional batch")
        case.add(Person(id="existing"))
        for records in (
            [Person(id="new"), Person(id="existing")],
            [Person(id="new"), Person(id="raw", sensitivity=Sensitivity.RAW_DNA)],
            [Person(id="same"), Person(id="same")],
        ):
            with self.assertRaises(ValueError):
                case.add_many(records)
            self.assertEqual([p.id for p in case.records("Person")], ["existing"])

    def test_bulk_indexes_and_externally_modified_cases_remain_consistent(self):
        case = ResearchCase(id="batch", title="Fictional batch")
        case.add_many([Person(id=f"fiction-{n}") for n in range(5000)])
        case.add_many([Finding(id="finding", conclusion="Synthetic"),
                       ResearchQuestion(id="question", question="Synthetic?")])
        self.assertEqual(len(case.records("Person")), 5000)
        self.assertEqual(case.finding_ids, ["finding"])
        self.assertEqual(case.question_ids, ["question"])
        case.record_sets["Person"].append(Person(id="external"))
        with self.assertRaisesRegex(ValueError, "duplicate record id"):
            case.add_many([Person(id="external")])
