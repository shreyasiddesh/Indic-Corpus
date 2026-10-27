"""PII redaction: Indian phone numbers, e-mail, Aadhaar, PAN.

Design rule: a number that is not PII must survive. So every pattern is
anchored on digit boundaries (never a slice of a longer number), Aadhaar uses
the Verhoeff checksum when the number is not formatted like an Aadhaar, and
phone numbers must look like Indian mobiles (10 digits, first digit 6-9) or
STD landlines.

Matching runs on a Devanagari-digit-folded copy of the text with identical
length, so spans map 1:1 back onto the original string.
"""
from __future__ import annotations

import re
from collections import Counter

from .normalize import fold_digits

# ---- Verhoeff ---------------------------------------------------------------
_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6), (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8), (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2), (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4), (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2), (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0), (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5), (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def verhoeff_valid(number: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


# ---- patterns ---------------------------------------------------------------
_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}(?![A-Za-z0-9\-@])"
)
_AADHAAR_FMT = re.compile(r"(?<![\d])(?<!\d[ \-])[2-9]\d{3}([ \-])\d{4}\1\d{4}(?!\d)(?![ \-]\d{4})")
_AADHAAR_RAW = re.compile(r"(?<![\d])[2-9]\d{11}(?!\d)")
_AADHAAR_KEYWORD = re.compile(r"aadhaar|aadhar|adhar|uidai|\buid\b|आधार", re.I)
_PAN = re.compile(r"(?<![A-Za-z0-9])[A-Z]{3}[ABCFGHLJPTK][A-Z][0-9]{4}[A-Z](?![A-Za-z0-9])")

# +91 / 0091 / 91 / 0 prefix (optional), then 10 digits starting 6-9 with at
# most single spaces/hyphens between digits.
_MOBILE = re.compile(
    r"(?<![\d\w])(?P<prefix>(?:\(?\+\s?91\)?|0091|91|0)[\s\-]?)?(?P<num>[6-9](?:[ \-]?\d){9})(?![\d])"
)
# STD landline: 0 + 2-4 digit area code, a separator, then 6-8 digits (10-11 digits total).
_LANDLINE = re.compile(r"(?<![\d\w])0\d{2,4}[ \-]\d{3,4}(?:[ \-]?\d{2,4})?(?![\d])")
_ISBN_BEFORE = re.compile(r"isbn[\s:\-]*(?:1[03])?[\s:\-]*$", re.I)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _redact_emails(text: str, folded: str, counts: Counter) -> str:
    def repl(_m):
        counts["EMAIL"] += 1
        return "<EMAIL>"
    return _EMAIL.sub(repl, text)


def _splice(text: str, folded: str, spans: list[tuple[int, int, str]], counts: Counter) -> str:
    if not spans:
        return text
    out, last = [], 0
    for a, b, tag in sorted(spans):
        if a < last:
            continue
        out.append(text[last:a])
        out.append(f"<{tag}>")
        counts[tag] += 1
        last = b
    out.append(text[last:])
    return "".join(out)


def redact(text: str) -> tuple[str, Counter]:
    """Return (redacted_text, per-type counts)."""
    counts: Counter = Counter()
    text = _redact_emails(text, text, counts)

    # Aadhaar
    folded = fold_digits(text)
    spans = []
    for m in _AADHAAR_FMT.finditer(folded):
        spans.append((m.start(), m.end(), "AADHAAR"))
    for m in _AADHAAR_RAW.finditer(folded):
        d = m.group()
        window = folded[max(0, m.start() - 40): m.end() + 40]
        has_kw = bool(_AADHAAR_KEYWORD.search(window))
        looks_like_intl_phone = d.startswith("91") and d[2] in "6789"
        if has_kw or (verhoeff_valid(d) and not looks_like_intl_phone):
            spans.append((m.start(), m.end(), "AADHAAR"))
    text = _splice(text, folded, spans, counts)

    # PAN
    spans = [(m.start(), m.end(), "PAN") for m in _PAN.finditer(text)]
    text = _splice(text, text, spans, counts)

    # Phone
    folded = fold_digits(text)
    spans = []
    for m in _MOBILE.finditer(folded):
        if len(_digits(m.group("num"))) != 10:
            continue
        if _ISBN_BEFORE.search(folded[max(0, m.start() - 12): m.start()]):
            continue
        spans.append((m.start(), m.end(), "PHONE"))
    for m in _LANDLINE.finditer(folded):
        n = len(_digits(m.group()))
        if 10 <= n <= 11 and not any(a <= m.start() < b for a, b, _ in spans):
            spans.append((m.start(), m.end(), "PHONE"))
    text = _splice(text, folded, spans, counts)
    return text, counts
