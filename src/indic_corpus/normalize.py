"""Text normalisation: make things that are the same compare as the same.

Two levels:

* ``normalize_text``  - applied to every document. Conservative: the result is
  still readable, natural text that we are happy to train on.
* ``fold``            - aggressive comparison key used only for contamination
  checks (never written to the corpus).
"""
from __future__ import annotations

import re
import unicodedata

# Invisible characters with no business in training text.
# ZWSP, word joiner, BOM/ZWNBSP, soft hyphen, LRM/RLM, bidi embeddings/isolates,
# Mongolian vowel separator, Arabic letter mark.
_ALWAYS_REMOVE = {
    0x200B, 0x2060, 0xFEFF, 0x00AD, 0x200E, 0x200F, 0x061C, 0x180E,
    0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069,
}
_CTRL_TO_NEWLINE = {0x0B, 0x0C, 0x85, 0x2028, 0x2029}

_CONTROL_TABLE = {}
for _cp in range(0x20):
    if _cp in (0x09, 0x0A):
        continue
    _CONTROL_TABLE[_cp] = "\n" if _cp in _CTRL_TO_NEWLINE or _cp == 0x0D else None
for _cp in list(range(0x7F, 0xA0)) + sorted(_ALWAYS_REMOVE | _CTRL_TO_NEWLINE):
    _CONTROL_TABLE[_cp] = "\n" if _cp in _CTRL_TO_NEWLINE else None
_CONTROL_TABLE[0x0D] = "\n"   # lone CR; CRLF is collapsed afterwards

# ZWJ / ZWNJ matter for rendering half-forms, but in running Hindi text they are
# copy-paste noise: "क्‍ष" and "क्ष" are the same word to a reader and must be the
# same token to a model. Outside Devanagari (emoji ZWJ sequences) they are kept.
_NEEDS_CTRL_FIX = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f" + "".join(chr(c) for c in sorted(_ALWAYS_REMOVE | _CTRL_TO_NEWLINE)) + "]")
_ZWJ_NEAR_DEVANAGARI = re.compile(
    "(?<=[ऀ-ॿ])[‌‍]+|[‌‍]+(?=[ऀ-ॿ])"
)
_EXOTIC_SPACES = re.compile("[ \t   -   　]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")
# ASCII pipe used as a danda: "वह गया |" -> "वह गया ।"
_PIPE_DANDA = re.compile(r"(?<=[ऀ-ॣ०-ॿ]) ?\|(?=\s|$)")

_DEVANAGARI_DIGITS = {0x0966 + i: ord("0") + i for i in range(10)}


def normalize_text(s: str) -> str:
    """NFKC + invisible-character removal + whitespace canonicalisation.

    NFKC subsumes NFC. For Devanagari it matters mainly because the nukta
    precomposed letters (U+0958-095F, U+0929, ...) are composition exclusions:
    both NFC and NFKC rewrite "क़" (U+0958) to "क" + U+093C, so the two ways of
    typing it become identical.
    """
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\r\n", "\n")
    if _NEEDS_CTRL_FIX.search(s):
        s = s.translate(_CONTROL_TABLE)
    s = _ZWJ_NEAR_DEVANAGARI.sub("", s)
    s = _EXOTIC_SPACES.sub(" ", s)
    s = "\n".join(line.strip(" ") for line in s.split("\n"))
    s = _PIPE_DANDA.sub("।", s)
    s = _MULTI_NEWLINE.sub("\n\n", s)
    return s.strip()


_FOLD_PUNCT = re.compile(r"[^\wऀ-ॿ\s]|_", re.UNICODE)
_FOLD_NUKTA = str.maketrans(
    {"\u093c": None, "\u0901": "\u0902", "\u200c": None, "\u200d": None, "\u0964": " ", "\u0965": " "}
)
_FOLD_DIGITS = str.maketrans(_DEVANAGARI_DIGITS)
_WS = re.compile(r"\s+")


def fold(s: str) -> str:
    """Aggressive comparison key: case, punctuation, digit script, nukta,
    chandrabindu/anusvara and whitespace all collapsed."""
    s = normalize_text(s).casefold()
    s = s.translate(_FOLD_NUKTA).translate(_FOLD_DIGITS)
    s = _FOLD_PUNCT.sub(" ", s)
    return _WS.sub(" ", s).strip()


def fold_digits(s: str) -> str:
    """Devanagari digits -> ASCII, length preserving (so spans line up)."""
    return s.translate(_FOLD_DIGITS)
