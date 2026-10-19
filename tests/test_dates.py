"""GEDCOM text dates and ISO dates share a chronology without inventing precision."""
import unittest

from genealogy.dates import date_sort_key
from genealogy.timelines import timeline_items


class DateOrderingTests(unittest.TestCase):
    def test_mixed_imported_dates_sort_by_year_month_and_day(self):
        dates = ["1 JAN 1850", "31 DEC 1800", None, "1800-01-02", "1 JAN 1800", "JAN 1800"]
        project = {"events": [{"id": str(i), "date": d} for i, d in enumerate(dates)]}
        actual = [e["date"] for e in timeline_items(project)]
        self.assertEqual(["JAN 1800", "1 JAN 1800", "1800-01-02", "31 DEC 1800", "1 JAN 1850", None], actual)
        self.assertEqual(dates, [e["date"] for e in project["events"]])

    def test_qualifiers_keep_recorded_boundary_and_unknowns_sort_last(self):
        for value in ("ABT 1800", "BEF 1800", "BET 1800 AND 1805", "FROM 1800 TO 1805", "1800-00-00"):
            self.assertEqual((0, 1800), date_sort_key(value)[:2], value)
        for value in (None, "unknown", "0000-00-00", "not a date with 1800", "1800-99-99"):
            self.assertEqual(1, date_sort_key(value)[0], value)


class SharedHelperTests(unittest.TestCase):
    def test_year_wikitree_and_historical_helpers(self):
        from genealogy.dates import wikitree_date, year_of
        from genealogy.publication import birth_upper_year, is_historical_birth
        self.assertEqual([birth_upper_year(v) for v in ("1850", "BEF 3 MAR 1850", "ABT 1850", "BET 1840 AND 1845", "AFT 1850", "about then")],
                         [1850, 1850, 1860, 1845, None, None])
        self.assertEqual([wikitree_date(v) for v in ("1850-00-00", "1850-03-00", "1850-03-04", "0000-00-00", "", None)],
                         ["1850", "1850-03", "1850-03-04", None, None, None])
        self.assertEqual(wikitree_date("1850-00-00", "guess"), "ABT 1850")
        self.assertEqual([year_of(v) for v in ("ABT 1850", "@#DJULIAN@ 1 MAR 1750/51", "0000", "unknown", "1850s")],
                         [1850, 1750, None, None, 1850])
        self.assertTrue(is_historical_birth("1811", current_year=2026))
        self.assertTrue(is_historical_birth("ABT 1890", current_year=2026))
        self.assertFalse(is_historical_birth("ABT 1900", current_year=2026))
        self.assertFalse(is_historical_birth("1980-01-01", current_year=2026))
        self.assertFalse(is_historical_birth("AFT 1700", current_year=2026))
