#!/usr/bin/env python3
"""Deterministic 1,000-row random sample of the cleaned output (lowest sha1(seed:id) ranks).
Usage: python3 tools/make_sample.py <out_dir> <sample_path> [--n 1000] [--seed 1]"""
import argparse
import glob
import gzip
import hashlib
import heapq
import json
import os

ap = argparse.ArgumentParser()
ap.add_argument("out_dir")
ap.add_argument("sample_path")
ap.add_argument("--n", type=int, default=1000)
ap.add_argument("--seed", default="1")
a = ap.parse_args()

heap = []   # max-heap on rank via negation
for p in sorted(glob.glob(os.path.join(a.out_dir, "clean", "part-*.jsonl.gz"))):
    for line in gzip.open(p, "rt", encoding="utf-8"):
        row = json.loads(line)
        r = int(hashlib.sha1(f"{a.seed}:{row['id']}".encode()).hexdigest()[:15], 16)
        item = (-r, row["id"], line)
        if len(heap) < a.n:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
rows = sorted(heap, key=lambda t: (-t[0], t[1]))
os.makedirs(os.path.dirname(os.path.abspath(a.sample_path)), exist_ok=True)
with open(a.sample_path, "w", encoding="utf-8", newline="\n") as f:
    for _, _, line in rows:
        f.write(line if line.endswith("\n") else line + "\n")
print(f"wrote {len(rows)} rows to {a.sample_path}")
