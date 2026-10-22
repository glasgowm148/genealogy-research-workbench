"""Conservative helpers for recorded dates, without rewriting what was supplied.

``date_sort_key`` is a presentation key, not an age/publication assessment.
Approximate and bounded dates use a recorded boundary for ordering while the
original text, including its qualifiers, is what readers see.
"""
from __future__ import annotations

import calendar
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


# Reader-facing dates. The recorded value is never changed: these only decide
# the words printed for it, and the site keeps the value in a data attribute.
SHORT_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# ``Event.date_precision`` values that change what is printed; any other value
# ("unknown", "supplied", ...) prints the date as recorded.
DISPLAY_PRECISIONS = ("day", "month", "year", "decade", "approximate", "about", "circa", "estimated")
_WORDS = {"ABOUT": "c.", "ABT": "c.", "CIRCA": "c.", "CA": "c.", "C": "c.", "EST": "c.", "ESTIMATED": "c.", "CAL": "c.", "CALCULATED": "c.",
          "BEF": "before", "BEFORE": "before", "AFT": "after", "AFTER": "after", "FROM": "from", "TO": "to", "INT": ""}
_NOTES = {"EST": "estimated", "ESTIMATED": "estimated", "CAL": "calculated", "CALCULATED": "calculated"}


def _days(year: int, month: int) -> int:
    return 31 if not month else calendar.monthrange(year, month)[1]


def _date_parts(text: str) -> tuple[int, int, int, str] | None:
    """(year, month, day, dual-year suffix) for one plain date, 0 for a part not recorded."""
    text = text.strip()
    match = re.fullmatch(r"([1-9]\d{2,3})(?:-(\d{2})(?:-(\d{2}))?)?", text)
    if match:  # ISO, with WikiTree's 00 placeholders
        year, month, day = int(match[1]), int(match[2] or 0), int(match[3] or 0)
        month, day = (0, 0) if month == 0 else (month, day)
        return (year, month, day, "") if month <= 12 and day <= _days(year, month) else None
    text = re.sub(r"\b(\d{1,2})(?:ST|ND|RD|TH)\b", r"\1", text)
    for word, short in _MONTH_WORDS.items():
        text = re.sub(rf"\b{word}\b", short, text)
    year = r"([1-9]\d{2,3})(/\d{1,4})?"
    match = re.fullmatch(rf"(?:(\d{{1,2}})\s+)?([A-Z]{{3}})\s+{year}", text)
    if match and match[2] in MONTHS and int(match[1] or 0) <= _days(int(match[3]), MONTHS[match[2]]):
        return int(match[3]), MONTHS[match[2]], int(match[1] or 0), match[4] or ""
    match = re.fullmatch(rf"([A-Z]{{3}})\s+(\d{{1,2}})\s+{year}", text)  # "Mar 4 1850"
    if match and match[1] in MONTHS and int(match[2]) <= _days(int(match[3]), MONTHS[match[1]]):
        return int(match[3]), MONTHS[match[1]], int(match[2]), match[4] or ""
    match = re.fullmatch(year, text)
    return (int(match[1]), 0, 0, match[2] or "") if match else None


def _trim(parts: tuple[int, int, int, str], precision: str) -> tuple[int, int, int, str]:
    year, month, day, dual = parts
    if precision == "year" or precision == "decade":
        return year, 0, 0, dual
    if precision == "month":
        return year, month, 0, dual
    return parts


def _words(parts: tuple[int, int, int, str], precision: str) -> str:
    year, month, day, dual = _trim(parts, precision)
    if precision == "decade":
        return f"{year // 10 * 10}s"
    return " ".join(part for part in (str(day) if day and month else "", SHORT_MONTHS[month - 1] if month else "", f"{year}{dual}") if part)


def display_date(value: str | None, precision: str | None = None) -> str:
    """A recorded date as a reader would write it, without claiming more than was recorded.

    ``1731-05-24`` → "24 May 1731", ``1754-01`` → "Jan 1754", ``1754-01-01``
    with ``precision="year"`` → "1754", ``ABT 1754`` → "c. 1754", ``EST 1265``
    → "c. 1265 (estimated)", ``BEF 1800`` → "before 1800", ``BET 1750 AND
    1760`` → "between 1750 and 1760", WikiTree ``1850-00-00`` → "1850". A
    value it cannot read, such as free text, is returned as recorded.
    """
    original = " ".join(str(value or "").split())
    if not original:
        return ""
    precision = str(precision or "").strip().casefold()
    text = original.upper().replace(",", " ")
    notes = []
    calendar = re.match(r"@#D([A-Z ]+?)\s*@\s*", text)
    if calendar:
        text = text[calendar.end():]
        if calendar[1].strip() != "GREGORIAN":
            notes.append(calendar[1].strip().title())
    phrase = re.search(r"\s*\((.*)\)\s*$", original)
    if phrase:
        text = text[:text.rfind("(")]
        notes.append(phrase[1].strip())
    text = " ".join(text.split())
    approximate = precision in ("approximate", "about", "circa", "estimated")
    if precision == "estimated":
        notes.append("estimated")
    bounded = re.fullmatch(r"(?:BET|BETWEEN)\s+(.+?)\s+AND\s+(.+)", text) or re.fullmatch(r"FROM\s+(.+?)\s+TO\s+(.+)", text)
    if bounded:
        ends = [_date_parts(part) for part in (bounded[1], bounded[2])]
        if not all(ends):
            return original
        words = ("between {} and {}" if text.startswith("BET") else "from {} to {}").format(*(_words(p, precision) for p in ends))
    else:
        qualifier = re.match(r"(ABOUT|ABT|CIRCA|CA|C|ESTIMATED|EST|CALCULATED|CAL|BEFORE|BEF|AFTER|AFT|FROM|TO|INT)(?:\.\s*|\s+|(?=\d))", text)
        parts = _date_parts(text[qualifier.end():] if qualifier else text)
        if not parts:
            return original
        words = _words(parts, precision)
        if qualifier:
            word = _WORDS[qualifier[1]]
            words = f"{word} {words}" if word else words
            if qualifier[1] in _NOTES:
                notes.insert(0, _NOTES[qualifier[1]])
            approximate = False
        if approximate:
            words = f"c. {words}"
    for note in dict.fromkeys(notes):
        words += f" ({note})"
    return words


def machine_date(value: str | None, precision: str | None = None) -> str | None:
    """The ``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD`` form of a plain recorded date, for
    ``<time datetime>``; None for a qualified, bounded or unreadable one, which no
    machine-readable date could state honestly."""
    text = " ".join(str(value or "").upper().split())
    precision = str(precision or "").strip().casefold()
    if not text or precision in ("approximate", "about", "circa", "estimated", "decade") or "@" in text or "(" in text:
        return None
    parts = _date_parts(text)
    if not parts or parts[3]:
        return None
    year, month, day, _ = _trim(parts, precision)
    return f"{year:04d}" + (f"-{month:02d}" if month else "") + (f"-{day:02d}" if month and day else "")
