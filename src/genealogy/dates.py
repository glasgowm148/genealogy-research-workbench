"""Conservative helpers for recorded dates, without rewriting what was supplied.

``date_sort_key`` is a presentation key, not an age/publication assessment.
Approximate and bounded dates use a recorded boundary for ordering while the
original text, including its qualifiers, is what readers see.
"""
from __future__ import annotations

import re

MONTHS = {month: index for index, month in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}
_MONTH_WORDS = {
    "JANUARY": "JAN", "FEBRUARY": "FEB", "MARCH": "MAR", "APRIL": "APR", "JUNE": "JUN", "JULY": "JUL",
    "AUGUST": "AUG", "SEPT": "SEP", "SEPTEMBER": "SEP", "OCTOBER": "OCT", "NOVEMBER": "NOV", "DECEMBER": "DEC",
}
_QUALIFIER = re.compile(
    r"^(?:ABOUT|ABT|CALCULATED|CAL|ESTIMATED|EST|BEFORE|BEF|AFTER|AFT|FROM|TO|CIRCA|CA|C|INT)(?:\.\s*|\s+|(?=\d))"
)
# WikiTree's DataStatus qualifiers for dates, expressed as GEDCOM qualifiers.
_WIKITREE_STATUS = {"guess": "ABT", "before": "BEF", "after": "AFT"}


def _normalise(value: str) -> str:
    text = " ".join(value.upper().replace(",", " ").split())
    text = re.sub(r"^@#D[A-Z ]+@\s*", "", text)          # calendar escape, e.g. @#DJULIAN@
    text = re.sub(r"\s*\(.*\)\s*$", "", text).strip()     # GEDCOM interpreted-date phrase
    text = re.sub(r"\b([1-9]\d{2,3})/\d{1,4}\b", r"\1", text)  # dual year 1750/51 → 1750
    text = re.sub(r"\b(\d{1,2})(?:ST|ND|RD|TH)\b", r"\1", text)
    for word, short in _MONTH_WORDS.items():
        text = re.sub(rf"\b{word}\b", short, text)
    return text


def date_sort_key(value: str | None) -> tuple[int, int, int, int, str]:
    original = str(value or "").strip()
    text = _normalise(original)
    text = _QUALIFIER.sub("", text)
    bounded = re.fullmatch(r"(?:BET|BETWEEN)\s+(.+?)\s+AND\s+.+", text)
    if bounded:
        text = _QUALIFIER.sub("", bounded[1])
    elif " TO " in text:
        text = text.split(" TO ", 1)[0]
    match = re.fullmatch(r"([1-9]\d{2,3})(?:-(\d{2})(?:-(\d{2}))?)?", text)
    if match:
        year, month, day = int(match[1]), int(match[2] or 0), int(match[3] or 0)
        if month <= 12 and day <= 31:
            return 0, year, month, day, original
    match = re.fullmatch(r"(?:(\d{1,2})\s+)?([A-Z]{3})\s+([1-9]\d{2,3})", text)
    if match and match[2] in MONTHS and int(match[1] or 0) <= 31:
        return 0, int(match[3]), MONTHS[match[2]], int(match[1] or 0), original
    match = re.fullmatch(r"([A-Z]{3})\s+(\d{1,2})\s+([1-9]\d{2,3})", text)  # "Mar 4 1850"
    if match and match[1] in MONTHS and int(match[2]) <= 31:
        return 0, int(match[3]), MONTHS[match[1]], int(match[2]), original
    return 1, 0, 0, 0, original


def year_of(value: str | None) -> int | None:
    """The first recorded year in a date value, for display grouping and filters.

    ``0000`` placeholders, bare numbers outside 100–2999, and free text without
    a year return None. This never establishes age or publication eligibility.
    """
    key = date_sort_key(value)
    if key[0] == 0:
        return key[1]
    match = re.search(r"(?<![\d/])([1-9]\d{2,3})(?!\d)", _normalise(str(value or "")))
    if match and 100 <= int(match[1]) <= 2999:
        return int(match[1])
    return None


def wikitree_date(value: str | None, status: str | None = None) -> str | None:
    """Normalise a WikiTree/OneTree ``YYYY-MM-DD`` value with ``00`` placeholders.

    ``1850-00-00`` becomes ``1850`` and ``1850-03-00`` becomes ``1850-03``. A
    DataStatus of guess/before/after is kept as ABT/BEF/AFT so uncertainty is not
    lost. ``0000-00-00`` and empty values mean no date. Other text is returned as
    supplied.
    """
    if value is None:
        return None
    text = str(value).strip()
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        year, month, day = match.groups()
        if year == "0000":
            return None
        text = year if month == "00" else f"{year}-{month}" if day == "00" else text
    if not text:
        return None
    qualifier = _WIKITREE_STATUS.get(str(status or "").strip().casefold())
    if qualifier and not re.match(r"(?i)(ABT|BEF|AFT|BET|EST|CAL|FROM|TO)\b", text):
        text = f"{qualifier} {text}"
    return text
