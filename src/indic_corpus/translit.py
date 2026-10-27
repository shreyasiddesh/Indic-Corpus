"""Script-independent phonetic skeleton, used to detect that a Devanagari eval
item reappears in training *written in Latin script* (and vice versa).

Both scripts are reduced to the same coarse consonant string, word by word:

    है / hai / hain          -> "h" / "h" / "hn"
    नमस्ते / namaste           -> "nmst" / "nmst"

Vowels are dropped (romanisation of vowels is the least consistent part of
Hinglish: kya/kyaa, hai/hai/hay, mein/main/men), aspirates and retroflexes fold
onto their plain consonants, and sibilants merge. It is deliberately lossy:
it is a *candidate generator* judged by long (5-word) shingle containment, never
by single words. Precision is verified in tests/test_contamination.py and in
DECISIONS.md with a rejected match.
"""
from __future__ import annotations

import re
from functools import lru_cache

# Devanagari consonants -> skeleton letters; everything else (vowels, matras,
# virama, nukta, danda, punctuation) maps to nothing.
_DEV = {
    "क": "k", "ख": "k", "ग": "g", "घ": "g", "ङ": "n",
    "च": "c", "छ": "c", "ज": "j", "झ": "j", "ञ": "n",
    "ट": "t", "ठ": "t", "ड": "d", "ढ": "d", "ण": "n",
    "त": "t", "थ": "t", "द": "d", "ध": "d", "न": "n",
    "प": "p", "फ": "p", "ब": "b", "भ": "b", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "श": "s", "ष": "s", "स": "s", "ह": "h",
    "ळ": "l", "ड़": "d", "ढ़": "d", "क़": "k", "ख़": "k", "ग़": "g", "ज़": "j", "फ़": "p",
}
_DEV_TABLE = {ord(k): v for k, v in _DEV.items() if len(k) == 1}
for _cp in range(0x0900, 0x0980):
    _DEV_TABLE.setdefault(_cp, None)
_DEV_TABLE[0x0901] = _DEV_TABLE[0x0902] = "n"      # anusvara / chandrabindu
_DEV_TABLE[0x093C] = None    # nukta handled by base letter
_DEV_TABLE[0x094D] = None    # virama
_DEV_TABLE[0x0964] = " "
_DEV_TABLE[0x0965] = " "

_DIGRAPHS = [
    (re.compile(r"ksh|x"), "ks"), (re.compile(r"chh|ch"), "c"), (re.compile(r"sh|ss"), "s"),
    (re.compile(r"([kgcjtdpb])h"), r"\1"), (re.compile(r"gn|gy"), "jn"), (re.compile(r"ph|f"), "p"),
    (re.compile(r"z"), "j"), (re.compile(r"w"), "v"), (re.compile(r"q"), "k"),
]
_LATIN_STRIP = re.compile(r"[^a-z]")
_DOUBLE = re.compile(r"(.)\1+")
_DEV_ANY = re.compile("[ऀ-ॿ]")


def _latin_word(w: str) -> str:
    w = _LATIN_STRIP.sub("", w.lower())
    if not w:
        return ""
    # a vowel-initial word keeps no letter for that vowel; y only counts as a
    # consonant when followed by a vowel (kya -> ky, hai -> h)
    for pat, rep in _DIGRAPHS:
        w = pat.sub(rep, w)
    out = []
    for i, ch in enumerate(w):
        if ch in "aeiou":
            continue
        if ch == "y" and not (i + 1 < len(w) and w[i + 1] in "aeiou"):
            continue
        out.append(ch)
    return _DOUBLE.sub(r"\1", "".join(out))


_TRAILING = re.compile(r"[ny]+$")


def _finish(w: str) -> str:
    """Word-final nasal / y are the least stable letters across romanisations
    (nahi/nahin, mein/me, hai/hay, Himalay/Himalaya): drop them on both sides."""
    return _TRAILING.sub("", w) or w


@lru_cache(maxsize=1 << 20)
def _token_skeleton(tok: str) -> str:
    if _DEV_ANY.search(tok):
        w = tok.translate(_DEV_TABLE)
        return _finish(_DOUBLE.sub(r"\1", re.sub(r"[^a-z]", "", w)))
    return _finish(_latin_word(tok))


def skeleton_words(text: str) -> list[str]:
    """Skeleton token list for mixed-script text (empty skeletons dropped)."""
    return [w for w in map(_token_skeleton, text.split()) if w]
