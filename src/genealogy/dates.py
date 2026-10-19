"""Conservative display ordering for recorded dates, without rewriting their text.

This is a presentation key, not an age/publication assessment. Approximate and
bounded dates use a recorded boundary for ordering while retaining qualifiers.
"""
from __future__ import annotations

import re

MONTHS = {month: index for index, month in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}


def date_sort_key(value: str | None) -> tuple[int, int, int, int, str]:
    original = str(value or "").strip()
    text = original.upper()
    text = re.sub(r"^(?:ABT|ABOUT|CAL|EST|BEF|BEFORE|AFT|AFTER|TO|FROM|CIRCA|C\.)\s*", "", text)
    bounded = re.fullmatch(r"(?:BET|BETWEEN)\s+(.+?)\s+AND\s+.+", text)
    if bounded:
        text = bounded[1]
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
    return 1, 0, 0, 0, original
