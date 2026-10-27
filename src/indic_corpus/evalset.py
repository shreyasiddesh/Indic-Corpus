"""Eval-set selection.

Selection is a pure function of (doc id, seed): each surviving document gets a
rank ``sha1(seed:id)`` and the lowest ranks per language are held out. That makes
the choice independent of file order, shard layout and restarts.

What it measures (one line, also in DECISIONS.md): held-out per-token perplexity /
cloze accuracy on natural, deduplicated, PII-redacted Hindi (Devanagari) and
Hinglish (Latin) passages, i.e. general language-modelling quality in the two
scripts, not task skill.
"""
from __future__ import annotations

import hashlib
import heapq
import re
from typing import Optional

from .config import Config

_SENT_END = re.compile(r"(?<=[।॥.!?])\s+|\n+")


def rank(seed: int, doc_id: str) -> int:
    return int(hashlib.sha1(f"{seed}:{doc_id}".encode()).hexdigest()[:15], 16)


class EvalCandidates:
    """Keeps the ``k`` lowest-ranked candidate documents per language, in memory
    (k is a few hundred, so memory is O(k * doc size), independent of corpus size)."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.k = cfg.eval_candidate_pool
        self.heaps: dict[str, list] = {"hi": [], "hi-Latn": []}
        self.seen = {"hi": 0, "hi-Latn": 0}

    def offer(self, doc_id: str, lang: str, source: str, text: str) -> None:
        if lang not in self.heaps:
            return
        if len(text.split()) < self.cfg.eval_min_doc_words[lang]:
            return
        self.seen[lang] += 1
        r = rank(self.cfg.eval_seed, doc_id)
        h = self.heaps[lang]
        item = (-r, doc_id, source, text)
        if len(h) < self.k:
            heapq.heappush(h, item)
        elif item > h[0]:
            heapq.heapreplace(h, item)

    def exclude(self, ids) -> int:
        """Drop candidates whose id is in ``ids`` (template-family members). Returns how many were removed."""
        removed = 0
        for lang, h in self.heaps.items():
            keep = [it for it in h if it[1] not in ids]
            removed += len(h) - len(keep)
            heapq.heapify(keep)
            self.heaps[lang] = keep
        return removed

    def ordered(self, lang: str) -> list[tuple[int, str, str, str]]:
        return sorted(((-nr, d, s, t) for nr, d, s, t in self.heaps[lang]))


def make_passage(text: str, lang: str, r: int, cfg: Config) -> Optional[str]:
    """Verbatim substring of ``text``: whole doc if short, else a sentence-aligned window."""
    lo, hi = cfg.eval_passage_min_words[lang], cfg.eval_passage_max_words
    if len(text.split()) <= hi:
        return text if len(text.split()) >= lo else None
    bounds = [0] + [m.end() for m in _SENT_END.finditer(text)] + [len(text)]
    starts = sorted(set(bounds))
    if len(starts) < 2:
        return None
    first = r % (len(starts) - 1)
    for off in range(len(starts) - 1):
        i = (first + off) % (len(starts) - 1)
        words, j = 0, i
        while j + 1 < len(starts) and words < lo:
            j += 1
            words = len(text[starts[i]:starts[j]].split())
        cand = text[starts[i]:starts[j]].strip()
        n = len(cand.split())
        if lo <= n <= hi:
            return cand
        if n > hi:                                     # one huge "sentence": cut on a word boundary
            return " ".join(cand.split()[:hi])
    return None


def select_items(cands: EvalCandidates, cfg: Config) -> list[dict]:
    want_latn = min(round(cfg.eval_size * cfg.eval_hi_latn_share), cands.seen["hi-Latn"])
    want_hi = cfg.eval_size - want_latn
    items, used = [], set()
    for lang, want in (("hi", want_hi), ("hi-Latn", want_latn)):
        got = 0
        for r, did, src, text in cands.ordered(lang):
            if got >= want:
                break
            p = make_passage(text, lang, r, cfg)
            if p is None or p in used:
                continue
            used.add(p)
            items.append({"text": p, "lang": lang, "source": src, "source_doc_id": did})
            got += 1
    items.sort(key=lambda d: (d["lang"], d["source_doc_id"]))
    for i, it in enumerate(items, 1):
        it["eval_id"] = f"ev-{i:04d}"
    return [{"eval_id": it["eval_id"], "text": it["text"], "lang": it["lang"],
             "source": it["source"], "source_doc_id": it["source_doc_id"]} for it in items]
