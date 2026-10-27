#!/usr/bin/env python3
"""Look at near-duplicate pairs across the similarity range to choose a threshold with eyes, not a blog post.

Needs stage-1 shards: run `./run.sh <raw> <out> --keep-work` first.
Usage: python3 tools/threshold_study.py <out_dir> [--per-bin 3] [--out study.md]
For every 0.05 similarity bin between 0.50 and 1.00 it prints the number of candidate
pairs and a few sampled pairs (estimated + exact Jaccard, word counts, text heads)."""
import argparse
import glob
import gzip
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from indic_corpus.dedup import NearDedup, shingle_ids, tokenize  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("out_dir")
ap.add_argument("--per-bin", type=int, default=3)
ap.add_argument("--out", default="")
ap.add_argument("--shingle", type=int, default=5)
a = ap.parse_args()

shards = sorted(glob.glob(os.path.join(a.out_dir, "_work", "*", "s1", "*.jsonl.gz")))
if not shards:
    sys.exit("no stage-1 shards; rerun with --keep-work")


def rows():
    for sp in shards:
        for line in gzip.open(sp, "rt", encoding="utf-8"):
            r = json.loads(line)
            if r["status"] == "kept":
                yield r


nd = NearDedup(threshold=1.01, num_perm=128, seed=1337, pair_log_min=0.45)   # never drops, logs all candidate pairs
seen_hash = set()
for r in rows():
    if r["h"] in seen_hash:
        continue
    seen_hash.add(r["h"])
    toks = tokenize(r["text"])
    if len(toks) >= 20:
        nd.query_and_add(r["id"], shingle_ids(toks, a.shingle))
pairs = nd.pair_log
rng = random.Random(0)
bins = {}
for p in pairs:
    bins.setdefault(min(int(p["est_jaccard"] * 20) / 20, 0.95), []).append(p)
want = {}
for b, lst in bins.items():
    for p in rng.sample(lst, min(a.per_bin, len(lst))):
        want[p["a"]] = want[p["b"]] = None
for r in rows():
    if r["id"] in want:
        want[r["id"]] = r["text"]
lines = [f"# Near-duplicate threshold study ({len(pairs)} candidate pairs >= 0.45 est. Jaccard)\n"]
for b in sorted(bins):
    lst = bins[b]
    lines.append(f"\n## est. Jaccard {b:.2f}-{b + 0.05:.2f}: {len(lst)} pairs\n")
    for p in rng.sample(lst, min(a.per_bin, len(lst))):
        ta, tb = want.get(p["a"]) or "", want.get(p["b"]) or ""
        sa, sb = set(shingle_ids(tokenize(ta), a.shingle).tolist()), set(shingle_ids(tokenize(tb), a.shingle).tolist())
        ej = len(sa & sb) / max(len(sa | sb), 1)
        lines.append(f"- est={p['est_jaccard']:.3f} exact={ej:.3f} words={len(ta.split())}/{len(tb.split())}\n  A: {ta[:220]!r}\n  B: {tb[:220]!r}\n")
text = "".join(lines)
if a.out:
    open(a.out, "w", encoding="utf-8").write(text)
print(text)
