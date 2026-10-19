"""Decode GEDCOM bytes using the file's own declaration, never a silent guess.

GEDCOM 5.5 files declare their character set in ``HEAD.CHAR``. Common values are
UTF-8, UNICODE (UTF-16), ANSI (Windows-1252), ANSEL (ANSI Z39.47 with combining
diacritics written *before* their base letter), ASCII and MACINTOSH. GEDCOM 7 is
always UTF-8. Undecodable bytes raise a ValueError naming the line, so a user can
re-export rather than receive silently corrupted names.
"""
from __future__ import annotations

import re
import unicodedata

# ANSEL (ANSI/NISO Z39.47) spacing graphics, with the GEDCOM 5.5 additions.
_ANSEL_SPACING = {
    0xA1: "Ł", 0xA2: "Ø", 0xA3: "Đ", 0xA4: "Þ", 0xA5: "Æ",
    0xA6: "Œ", 0xA7: "ʹ", 0xA8: "·", 0xA9: "♭", 0xAA: "®",
    0xAB: "±", 0xAC: "Ơ", 0xAD: "Ư", 0xAE: "ʼ", 0xB0: "ʻ",
    0xB1: "ł", 0xB2: "ø", 0xB3: "đ", 0xB4: "þ", 0xB5: "æ",
    0xB6: "œ", 0xB7: "ʺ", 0xB8: "ı", 0xB9: "£", 0xBA: "ð",
    0xBC: "ơ", 0xBD: "ư", 0xBE: "□", 0xBF: "■", 0xC0: "°",
    0xC1: "ℓ", 0xC2: "℗", 0xC3: "©", 0xC4: "♯", 0xC5: "¿",
    0xC6: "¡", 0xC7: "ß", 0xC8: "€", 0xCF: "ß",
}
# Non-spacing marks; in ANSEL they precede the character they modify.
_ANSEL_COMBINING = {
    0xE0: "̉", 0xE1: "̀", 0xE2: "́", 0xE3: "̂", 0xE4: "̃",
    0xE5: "̄", 0xE6: "̆", 0xE7: "̇", 0xE8: "̈", 0xE9: "̌",
    0xEA: "̊", 0xEB: "︠", 0xEC: "︡", 0xED: "̕", 0xEE: "̋",
    0xEF: "̐", 0xF0: "̧", 0xF1: "̨", 0xF2: "̣", 0xF3: "̤",
    0xF4: "̥", 0xF5: "̳", 0xF6: "̲", 0xF7: "̦", 0xF8: "̜",
    0xF9: "̮", 0xFA: "︢", 0xFB: "︣", 0xFE: "̓",
}

_DECLARED = {
    "UTF-8": "utf-8", "UTF8": "utf-8", "UNICODE": "utf-16", "UTF-16": "utf-16",
    "ANSI": "cp1252", "WINDOWS": "cp1252", "IBM WINDOWS": "cp1252", "CP1252": "cp1252",
    "WINDOWS-1252": "cp1252", "ISO-8859-1": "latin-1", "ISO8859-1": "latin-1",
    "LATIN1": "latin-1", "ISO-8859-15": "iso8859-15", "MACINTOSH": "mac_roman",
    "MACROMAN": "mac_roman", "ANSEL": "ansel", "ASCII": "ascii",
}


def decode_ansel(raw: bytes) -> str:
    """Decode ANSEL bytes to NFC Unicode, moving each prefix mark after its base."""
    output: list[str] = []
    pending: list[str] = []
    for offset, byte in enumerate(raw):
        if byte in _ANSEL_COMBINING:
            pending.append(_ANSEL_COMBINING[byte])
            continue
        if byte < 0x80:
            character = chr(byte)
        elif byte in _ANSEL_SPACING:
            character = _ANSEL_SPACING[byte]
        else:
            line = raw.count(b"\n", 0, offset) + 1
            raise ValueError(f"GEDCOM declares ANSEL but byte 0x{byte:02X} on line {line} is not ANSEL")
        if pending and character in "\r\n":
            # A mark without a base letter: keep it visible rather than lose it.
            output.extend(pending)
            pending = []
        output.append(character)
        output.extend(pending)
        pending = []
    output.extend(pending)
    return unicodedata.normalize("NFC", "".join(output))


def declared_charset(raw: bytes) -> str | None:
    """Return HEAD.CHAR from an ASCII-compatible header, if one is present."""
    head = raw[:65536].decode("latin-1")
    match = re.search(r"(?m)^\s*1\s+CHAR\s+([^\r\n]+?)\s*$", head)
    return " ".join(match[1].upper().split()) if match else None


def _line_of(raw: bytes, offset: int) -> int:
    return raw.count(b"\n", 0, offset) + 1


def decode_gedcom(raw: bytes) -> tuple[str, str, list[str]]:
    """Return text, the encoding used and any diagnostic warnings."""
    warnings: list[str] = []
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
        bom = "utf-8"
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return raw.decode("utf-16"), "utf-16", warnings
        except UnicodeDecodeError as error:
            raise ValueError("GEDCOM has a UTF-16 byte-order mark but invalid UTF-16 content") from error
    elif raw[:2] in (b"0\x00", b"\x000"):
        encoding = "utf-16-le" if raw[:2] == b"0\x00" else "utf-16-be"
        try:
            return raw.decode(encoding), encoding, warnings
        except UnicodeDecodeError as error:
            raise ValueError("GEDCOM appears to be UTF-16 without a byte-order mark but is not valid UTF-16") from error
    else:
        bom = None
    declared = declared_charset(raw)
    expected = _DECLARED.get(declared or "")
    if declared and expected is None:
        raise ValueError(f"GEDCOM declares unsupported character set {declared!r}; re-export it as UTF-8")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        if bom or expected in (None, "utf-8", "utf-16"):
            label = f"declares {declared}" if declared else "has no HEAD.CHAR declaration"
            raise ValueError(f"GEDCOM {label} but line {_line_of(raw, error.start)} is not valid UTF-8; "
                             "re-export it as UTF-8 or correct its CHAR declaration") from error
    else:
        if declared and expected not in ("utf-8", "utf-16") and not text.isascii():
            warnings.append(f"GEDCOM declares {declared} but its bytes are valid UTF-8; decoded as UTF-8")
        return text, "utf-8", warnings
    if expected == "ansel":
        return decode_ansel(raw), "ansel", warnings
    try:
        return raw.decode(expected), expected, warnings
    except UnicodeDecodeError as error:
        raise ValueError(f"GEDCOM declares {declared} but line {_line_of(raw, error.start)} cannot be decoded as {expected}") from error
