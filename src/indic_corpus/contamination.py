"""Eval-contamination detection against the training corpus.

Methods, strongest first:

exact            the eval passage occurs verbatim inside the training document
normalized       same after ``fold`` (case, punctuation, digit script, nukta,
                 chandrabindu, whitespace) - "differs only after normalization"
near             >= ``contam_near_containment`` of the eval passage's word
                 5-grams occur in the document (edits, truncation, re-wrapping)
transliteration  the *phonetic skeleton* of the passage (see translit.py) is
                 contained >= ``contam_translit_containment`` in a document of
                 the OTHER script (Devanagari eval <-> Latin training and v.v.)

Containment, not Jaccard: an eval passage is short and the training document is
long, so Jaccard would be near zero even for a verbatim copy.
"""
from __future__ import annotations

import zlib
from collections import defaultdict

from .config import Config
from .langid import script_counts
from .normalize import fold
from .translit import skeleton_words

METHOD_ORDER = {"exact": 0, "normalized": 1, "near": 2, "transliteration": 3}


def _ids(tokens: list[str], n: int) -> set[int]:
    if not tokens:
        return set()
    if len(tokens) < n:
        return {zlib.crc32(" ".join(tokens).encode())}
    return {zlib.crc32(" ".join(tokens[i:i + n]).encode()) for i in range(len(tokens) - n + 1)}


def script_of(text: str) -> str:
    total, dev, lat = script_counts(text)
    return "dev" if dev >= lat else "lat"


class EvalIndex:
    def __init__(self, items: list[dict], cfg: Config):
        self.cfg, self.items = cfg, items
        self.fold_text, self.script = [], []
        self.native_sets, self.skel_sets = [], []
        self.native_index: dict[int, list[int]] = defaultdict(list)
        self.skel_index: dict[int, list[int]] = defaultdict(list)
        for i, it in enumerate(items):
            f = fold(it["text"])
            self.fold_text.append(f)
            self.script.append(script_of(it["text"]))
            ns = _ids(f.split(), cfg.contam_shingle_words)
            ss = _ids(skeleton_words(it["text"]), cfg.contam_translit_shingle_words)
            self.native_sets.append(ns)
            self.skel_sets.append(ss)
            for s in ns:
                self.native_index[s].append(i)
            for s in ss:
                self.skel_index[s].append(i)

    def check(self, text: str) -> tuple[dict[int, tuple[str, float]], list[dict]]:
        """-> ({eval_idx: (method, score)}, near_miss_rows)."""
        cfg = self.cfg
        f = fold(text)
        ftoks = f.split()
        hits: dict[int, int] = defaultdict(int)
        for s in _ids(ftoks, cfg.contam_shingle_words):
            for i in self.native_index.get(s, ()):
                hits[i] += 1
        found: dict[int, tuple[str, float]] = {}
        misses: list[dict] = []
        for i, h in sorted(hits.items()):
            score = h / max(len(self.native_sets[i]), 1)
            if self.items[i]["text"] in text:
                found[i] = ("exact", 1.0)
            elif self.fold_text[i] in f:
                found[i] = ("normalized", 1.0)
            elif score >= cfg.contam_near_containment:
                found[i] = ("near", round(score, 4))
            elif score >= cfg.contam_near_miss_min:
                misses.append({"eval_id": self.items[i]["eval_id"], "kind": "native_5gram",
                               "score": round(score, 4)})
        # cross-script (transliteration) check
        doc_script = script_of(text)
        skel_hits: dict[int, int] = defaultdict(int)
        sids = _ids(skeleton_words(text), cfg.contam_translit_shingle_words)
        for s in sids:
            for i in self.skel_index.get(s, ()):
                if self.script[i] != doc_script:
                    skel_hits[i] += 1
        for i, h in sorted(skel_hits.items()):
            score = h / max(len(self.skel_sets[i]), 1)
            if i in found:
                continue
            if score >= cfg.contam_translit_containment:
                found[i] = ("transliteration", round(score, 4))
            elif score >= cfg.contam_near_miss_min:
                misses.append({"eval_id": self.items[i]["eval_id"], "kind": "skeleton_cross_script",
                               "score": round(score, 4)})
        return found, misses
