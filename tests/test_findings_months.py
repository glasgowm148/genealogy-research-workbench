"""The findings log's month list: a link to each month's row group, newest first, older months by year on a long page."""
from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import validate_case
from genealogy.models import AccessLevel as A, Finding
from genealogy.site import FINDINGS_PER_PAGE, LATEST_FINDINGS, MONTHS_LISTED
from genealogy.sitecheck import check_site
from test_findings_table import build, case, main  # tests/ is on the path under unittest discovery


def months(html):
    """The month list's (href, link text, count) entries, in page order."""
    nav = re.search(r'<nav class="findings-months" aria-label="Months"[^>]*>(.*?)</nav>', html, re.S)
    return [(href, text, int(n.replace(",", ""))) for href, text, n in
            re.findall(r'<a href="(#[^"]+)">([^<]+)</a> <span class="meta">· ([\d,]+)</span>', nav.group(1))] if nav else None


def monthly(count, *, start=(2026, 10), sensitivity=A.PUBLIC, prefix="m"):
    """One finding in each of `count` months, going back from `start`."""
    year, month, out = *start, []
    for n in range(count):
        out.append(Finding(f"{prefix}{n:03d}", f"Monthly conclusion {n}.", related_ids=["ada"], status="final",
                           recorded_on=f"{year}-{month:02d}-05", sensitivity=sensitivity))
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return out


class FindingsMonthsTests(unittest.TestCase):
    def test_a_short_log_lists_each_month_between_the_legend_and_the_table(self):
        extra = [Finding("f-oct-2", "A second October finding.", related_ids=["bram"], recorded_on="2026-10-20", sensitivity=A.PUBLIC),
                 Finding("f-year", "Only a year is known.", related_ids=["ada"], recorded_on="2024", sensitivity=A.PUBLIC)]
        self.assertEqual([], validate_case(case(extra)))
        with tempfile.TemporaryDirectory() as directory:
            out = build(case(extra), directory)
            log = main((out / "findings.html").read_text())
            self.assertEqual([("#month-2026-10", "October 2026", 2), ("#month-2026-09", "September 2026", 1),
                              ("#month-2024", "2024", 1), ("#month-undated", "Undated", 1)], months(log))
            # Below the legend, above the table.
            self.assertLess(log.index('class="findings-legend"'), log.index('aria-label="Months"'))
            self.assertLess(log.index('aria-label="Months"'), log.index('<table class="evidence-table findings-table"'))
            # Each row group carries the id its link names; every finding sits in one.
            ids = re.findall(r'<tbody id="([^"]+)">', log)
            self.assertEqual(["month-2026-10", "month-2026-09", "month-2024", "month-undated"], ids)
            self.assertEqual(log.count("<tbody"), len(ids))
            report = check_site(out)
            self.assertEqual(([], []), (report["broken"], report["missing_anchors"]))
            self.assertGreater(report["anchor_references"], 0)

    def test_an_empty_log_has_no_month_list(self):
        from genealogy.case import ResearchCase
        with tempfile.TemporaryDirectory() as directory:
            out = build(ResearchCase("fictional-empty", "Fictional empty"), directory)
            self.assertNotIn('aria-label="Months"', (out / "findings.html").read_text())

    def test_past_24_months_the_older_months_go_by_year(self):
        # The newest 30 findings (two case findings and one a month) reach back 28 months: past the list's limit.
        many = monthly(LATEST_FINDINGS + 5)
        with tempfile.TemporaryDirectory() as directory:
            out = build(case(many), directory)
            log = main((out / "findings.html").read_text())
            listed = months(log)
            self.assertGreater(LATEST_FINDINGS, MONTHS_LISTED)
            recent = listed[:MONTHS_LISTED // 2]
            self.assertEqual(("#month-2026-10", "October 2026", 2), recent[0])  # a case finding and a monthly one
            self.assertEqual(("#month-2025-11", "November 2025", 1), recent[-1])
            earlier = log[log.index('class="findings-months-earlier"'):]
            earlier = earlier[:earlier.index("</ul>")]
            self.assertIn("<span>Earlier years:</span>", earlier)
            # Each earlier year links to its newest month still on the page, counting what of that year the list has not named.
            self.assertEqual([("#month-2025-10", "2025", 10), ("#month-2024-12", "2024", 6)], listed[MONTHS_LISTED // 2:-1])
            self.assertEqual(("#month-undated", "Undated", 1), listed[-1])
            self.assertEqual(sum(n for _, _, n in listed), log.count('class="finding-entry"'))
            # Every link has its row group on the page.
            for href, _, _ in listed:
                self.assertIn(f'<tbody id="{href[1:]}">', log)

    def test_an_archive_page_lists_its_own_months(self):
        many = monthly(FINDINGS_PER_PAGE + LATEST_FINDINGS)
        with tempfile.TemporaryDirectory() as directory:
            out = build(case(many), directory)
            pages = sorted((out / "findings").glob("page-*.html"))
            self.assertTrue(pages)
            for page in pages:
                html = main(page.read_text())
                listed = months(html)
                self.assertTrue(listed, page.name)
                self.assertEqual(html.count('class="finding-entry"'), sum(n for _, _, n in listed))
                self.assertEqual(re.findall(r'<tbody id="([^"]+)">', html)[:MONTHS_LISTED // 2], [href[1:] for href, _, _ in listed[:MONTHS_LISTED // 2]])
                self.assertNotIn("#month-undated", html)  # undated findings stay on the latest page
                # Newest first.
                targets = [href for href, _, _ in listed]
                self.assertEqual(sorted(targets, reverse=True), targets)

    def test_a_withheld_finding_names_no_month(self):
        secret = [Finding("f-hidden", "SECRET-MONTH finding.", related_ids=["ada"], recorded_on="2019-07-04", sensitivity=A.PRIVATE),
                  Finding("f-living", "SECRET-LIVING month.", related_ids=["secret"], recorded_on="2018-03-04", sensitivity=A.PUBLIC)]
        with tempfile.TemporaryDirectory() as directory:
            out = build(case(secret), directory)
            self.assertNotIn(("#month-2019-07", "July 2019", 1), months(main((out / "findings.html").read_text())))
            for path in Path(out).rglob("*"):
                if path.is_file():
                    text = path.read_text(errors="ignore")
                    for sentinel in ("SECRET-MONTH", "SECRET-LIVING", "month-2019-07", "July 2019", "month-2018-03", "March 2018"):
                        self.assertNotIn(sentinel, text, f"{sentinel} in {path.relative_to(out)}")


if __name__ == "__main__":
    unittest.main()
