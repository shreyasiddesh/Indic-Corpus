#!/usr/bin/env python3
"""Print the numeric tables for DECISIONS.md straight from a finished run, so no number in the
write-up is typed by hand.  Usage: python3 tools/render_numbers.py <out_dir>"""
import gzip
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
out = sys.argv[1]
m = json.load(open(os.path.join(out, "manifest.json"), encoding="utf-8"))


def jl(name):
    p = os.path.join(out, "diagnostics", name)
    return [json.loads(l) for l in gzip.open(p, "rt", encoding="utf-8")] if os.path.exists(p) else []


print("## Sources")
print("| source | license | revision | input files | MB | input docs | kept docs | kept MB (chars/1e6) |")
print("|---|---|---|---|---|---|---|---|")
by_src = {}
for i in m["inputs"]:
    s = by_src.setdefault(i["source"], {"files": 0, "bytes": 0})
    s["files"] += 1
    s["bytes"] += i["bytes"]
meta = {s["name"]: s for s in m["sources"]}
for name, ps in m["per_source"].items():
    b = by_src.get(name, {"files": 0, "bytes": 0})
    md = meta.get(name, {})
    print(f"| {name} | {md.get('license', 'unrecorded')} | {str(md.get('revision', ''))[:8]} | {b['files']} | {b['bytes'] / 1e6:.1f} | {ps['docs_in']:,} | {ps['kept']:,} | {ps['kept_chars'] / 1e6:.1f} |")

print("\n## Funnel (documents remaining after each stage, by detected language)")
f = m["funnel"]
cols = sorted(c for c in f[0] if c not in ("after", "ALL")) + ["ALL"]
print("| after stage | " + " | ".join(cols) + " |")
print("|---|" + "---|" * len(cols))
for row in f:
    print(f"| {row['after']} | " + " | ".join(f"{row.get(c, 0):,}" for c in cols) + " |")

print("\n## Drop reasons")
for k, v in sorted(m["drop_reasons"].items(), key=lambda kv: -kv[1]):
    print(f"- {k}: {v:,}")
print("\nread-level skips:", m["read_skipped_by_reason"])
print("PII redactions in clean output:", m["pii_redactions_in_clean"])
print("dedup:", m["dedup"])
print("eval:", m["eval"], "\ncontamination:", m["contamination"])
print("outputs:", {k: v for k, v in m["outputs"].items() if k != "clean_parts"})

print("\n## Near-duplicate boundary pairs (closest to threshold %.2f)" % m["config"]["near_dup_threshold"])
for p in jl("near_dup_boundary_pairs.jsonl.gz")[:8]:
    print(f"- est={p['est_jaccard']} exact={p['exact_jaccard']} words={p['a_words']}/{p['b_words']} -> {p['decision']}\n    A: {p['a_text'][:160]!r}\n    B: {p['b_text'][:160]!r}")
print("\nnear-dup est-Jaccard histogram:", open(os.path.join(out, 'diagnostics', 'near_dup_similarity_histogram.json'), encoding="utf-8").read())
print("\n## Contamination near-misses (top by score)")
for p in sorted(jl("contamination_near_misses.jsonl.gz"), key=lambda r: -r["score"])[:5]:
    print(f"- {p['eval_id']} {p['kind']} score={p['score']}\n    eval: {p['eval_text'][:140]!r}\n    train {p['train_id']}: {p['snip'][:140]!r}")
