"""Exact and near-duplicate detection (MinHash + banded LSH).

* Shingles are word n-grams (not characters): Devanagari conjuncts make
  character n-grams noisy, and word 5-grams are the unit a model memorises.
* Hash family is multiply-shift on uint64 with a fixed seed, and shingle ids
  come from CRC32 (not Python's salted ``hash``): the result is identical on
  every machine and every run.
* The LSH band layout is derived from the threshold (minimise expected false
  positives + false negatives), so changing ``near_dup_threshold`` in the
  config is a one-line change.
* Streaming/greedy: documents arrive in a deterministic order; the first
  document of a cluster is the representative and later members point at it.
"""
from __future__ import annotations

import zlib
from typing import Optional

import numpy as np

_trapezoid = getattr(np, "trapezoid", None) or np.trapz   # np.trapezoid is NumPy>=2.0 only

_PUNCT = ".,;:!?\"'()[]{}<>|/\\-–—_*#~`^=+@&%$।॥…“”‘’"


def tokenize(text: str) -> list[str]:
    toks = (t.strip(_PUNCT) for t in text.lower().split())
    return [t for t in toks if t]


def shingle_ids(tokens: list[str], n: int) -> np.ndarray:
    if not tokens:
        return np.zeros(0, dtype=np.uint64)
    if len(tokens) < n:
        grams = [" ".join(tokens)]
    else:
        grams = [" ".join(tokens[i: i + n]) for i in range(len(tokens) - n + 1)]
    ids = np.fromiter((zlib.crc32(g.encode("utf-8")) for g in grams), dtype=np.uint64, count=len(grams))
    return np.unique(ids)


def optimal_bands(threshold: float, num_perm: int, fp_weight: float = 0.5) -> tuple[int, int]:
    """(bands, rows) minimising fp_weight*FP + (1-fp_weight)*FN around threshold."""
    best, best_err = (1, num_perm), 1e9
    xs = np.linspace(0.0, 1.0, 201)
    for r in range(2, num_perm + 1):
        b = num_perm // r
        if b < 2:
            continue
        p = 1.0 - (1.0 - xs ** r) ** b
        fp = _trapezoid(p[xs < threshold], xs[xs < threshold]) if (xs < threshold).sum() > 1 else 0.0
        fn = _trapezoid(1.0 - p[xs >= threshold], xs[xs >= threshold])
        err = fp_weight * fp + (1 - fp_weight) * fn
        if err < best_err:
            best, best_err = (b, r), err
    return best


class MinHasher:
    def __init__(self, num_perm: int, seed: int):
        rng = np.random.RandomState(seed)
        self.a = (rng.randint(1, 2 ** 62, size=num_perm, dtype=np.int64).astype(np.uint64) * 2 + 1)
        self.b = rng.randint(0, 2 ** 62, size=num_perm, dtype=np.int64).astype(np.uint64)
        self.num_perm = num_perm

    def signature(self, ids: np.ndarray) -> np.ndarray:
        sig = np.full(self.num_perm, np.iinfo(np.uint32).max, dtype=np.uint32)
        with np.errstate(over="ignore"):
            for i in range(0, len(ids), 8192):
                chunk = ids[i: i + 8192]
                h = (self.a[:, None] * chunk[None, :] + self.b[:, None]) >> np.uint64(32)
                sig = np.minimum(sig, h.min(axis=1).astype(np.uint32))
        return sig


class NearDedup:
    """Greedy streaming near-dup index. ``query_and_add`` returns
    (dup_of_id, similarity) or (None, best_similarity_seen)."""

    def __init__(self, threshold: float, num_perm: int, seed: int, pair_log_min: float):
        self.threshold = threshold
        self.hasher = MinHasher(num_perm, seed)
        self.bands, self.rows = optimal_bands(min(threshold, pair_log_min + 0.15), num_perm)
        self.pair_log_min = pair_log_min
        self.buckets: dict[tuple[int, bytes], list[int]] = {}
        self.sigs: list[np.ndarray] = []
        self.ids: list[str] = []
        self.pair_log: list[dict] = []
        # ids of every document that has at least one neighbour >= pair_log_min: a "template family"
        # (e.g. thousands of "X is a village in Y district" stubs). Used to keep such documents out of the eval set.
        self.family: set[str] = set()

    def _keys(self, sig: np.ndarray):
        r = self.rows
        for b in range(self.bands):
            yield (b, sig[b * r:(b + 1) * r].tobytes())

    def query_and_add(self, doc_id: str, ids: np.ndarray) -> tuple[Optional[str], float]:
        sig = self.hasher.signature(ids)
        cands: set[int] = set()
        for k in self._keys(sig):
            lst = self.buckets.get(k)
            if lst:
                cands.update(lst)
        best_j, best_idx = 0.0, -1
        for c in sorted(cands):
            j = float((self.sigs[c] == sig).mean())
            if j >= self.pair_log_min:
                self.pair_log.append({"a": self.ids[c], "b": doc_id, "est_jaccard": round(j, 4)})
                self.family.add(self.ids[c])
                self.family.add(doc_id)
            if j > best_j:
                best_j, best_idx = j, c
        if best_idx >= 0 and best_j >= self.threshold:
            return self.ids[best_idx], best_j
        idx = len(self.sigs)
        self.sigs.append(sig)
        self.ids.append(doc_id)
        for k in self._keys(sig):
            self.buckets.setdefault(k, []).append(idx)
        return None, best_j
