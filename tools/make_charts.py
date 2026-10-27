#!/usr/bin/env python3
"""Render README figures (SVG, no dependencies) from a finished run's manifest.json.

Every bar is a number read from the manifest/diagnostics, never typed by hand.
Usage: python3 tools/make_charts.py <out_dir> [docs/img]
"""
import json
import os
import sys
from xml.sax.saxutils import escape

out = sys.argv[1]
dest = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "..", "docs", "img")
os.makedirs(dest, exist_ok=True)
m = json.load(open(os.path.join(out, "manifest.json"), encoding="utf-8"))

# Self-contained card (own background) so the figure reads the same on GitHub light and dark.
BG, FG, MUTED, GRID = "#0f172a", "#e2e8f0", "#94a3b8", "#1e293b"
LANG_COLOR = {"hi": "#f59e0b", "hi-Latn": "#22d3ee", "en": "#a78bfa", "other": "#64748b", "n/a": "#475569"}
FONT = "font-family=\"ui-sans-serif,system-ui,Segoe UI,Helvetica,Arial,sans-serif\""


def svg(w, h, body, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
            f'aria-label="{escape(title)}"><rect width="{w}" height="{h}" rx="14" fill="{BG}"/>'
            f'<text x="24" y="36" {FONT} font-size="17" font-weight="700" fill="{FG}">{escape(title)}</text>{body}</svg>')


def text(x, y, s, size=12, fill=FG, anchor="start", weight="400"):
    return f'<text x="{x}" y="{y}" {FONT} font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}">{escape(str(s))}</text>'


def fmt(n):
    return f"{n:,}"


def funnel():
    rows = m["funnel"]
    langs = [k for k in rows[0] if k not in ("after", "ALL")]
    langs.sort(key=lambda l: list(LANG_COLOR).index(l) if l in LANG_COLOR else 99)
    W, left, right, top, bh = 920, 150, 130, 70, 34
    H = top + len(rows) * (bh + 12) + 56
    mx = max(r["ALL"] for r in rows) or 1
    scale = (W - left - right) / mx
    body = []
    for i, r in enumerate(rows):
        y = top + i * (bh + 12)
        body.append(text(left - 12, y + bh / 2 + 4, r["after"], 13, FG, "end", "600"))
        x = left
        for l in langs:
            w = r.get(l, 0) * scale
            if w > 0:
                body.append(f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="{bh}" fill="{LANG_COLOR.get(l, "#64748b")}"/>')
            x += w
        body.append(text(x + 10, y + bh / 2 + 4, fmt(r["ALL"]), 13, FG, "start", "700"))
    lx = left
    for l in langs:
        body.append(f'<rect x="{lx}" y="{H - 34}" width="14" height="14" rx="3" fill="{LANG_COLOR.get(l, "#64748b")}"/>')
        body.append(text(lx + 20, H - 22, l, 12, MUTED))
        lx += 90
    body.append(text(W - 24, H - 22, "documents remaining after each stage, by detected language", 11, MUTED, "end"))
    return svg(W, H, "".join(body), "Funnel: documents surviving each stage")


def drop_reasons():
    items = sorted(m["drop_reasons"].items(), key=lambda kv: -kv[1])[:14]
    W, left, top, bh = 920, 290, 60, 24
    H = top + len(items) * (bh + 8) + 24
    mx = max(v for _, v in items) if items else 1
    sc = (W - left - 130) / mx
    body = []
    for i, (k, v) in enumerate(items):
        y = top + i * (bh + 8)
        stage = k.split(":")[0]
        col = {"read": "#f87171", "normalize": "#fb923c", "filter": "#f59e0b", "lang": "#a78bfa",
               "dedup_exact": "#22d3ee", "dedup_near": "#38bdf8", "eval_holdout": "#34d399",
               "contamination": "#f472b6"}.get(stage, "#64748b")
        body.append(text(left - 12, y + bh / 2 + 4, k, 12, FG, "end"))
        body.append(f'<rect x="{left}" y="{y}" width="{max(v * sc, 2):.1f}" height="{bh}" rx="4" fill="{col}"/>')
        body.append(text(left + max(v * sc, 2) + 8, y + bh / 2 + 4, fmt(v), 12, FG, "start", "700"))
    return svg(W, H, "".join(body), "Why documents were dropped (stage:reason)")


def sources():
    ps = m["per_source"]
    names = list(ps)
    W, left, top, bh = 920, 250, 70, 30
    H = top + len(names) * (2 * bh + 26) + 40
    mx = max(v["docs_in"] for v in ps.values()) or 1
    sc = (W - left - 150) / mx
    body = []
    for i, n in enumerate(names):
        y = top + i * (2 * bh + 26)
        v = ps[n]
        body.append(text(left - 12, y + bh + 2, n, 13, FG, "end", "600"))
        body.append(f'<rect x="{left}" y="{y}" width="{v["docs_in"] * sc:.1f}" height="{bh}" rx="4" fill="#475569"/>')
        body.append(text(left + v["docs_in"] * sc + 8, y + bh / 2 + 4, f'{fmt(v["docs_in"])} in', 12, MUTED))
        body.append(f'<rect x="{left}" y="{y + bh + 4}" width="{max(v["kept"] * sc, 1):.1f}" height="{bh}" rx="4" fill="#22c55e"/>')
        body.append(text(left + max(v["kept"] * sc, 1) + 8, y + bh + 4 + bh / 2 + 4,
                         f'{fmt(v["kept"])} kept ({v["kept_chars"] / 1e6:.1f}M chars)', 12, FG, "start", "700"))
    return svg(W, H, "".join(body), "Per-source yield: documents in vs. kept")


def near_dup():
    p = os.path.join(out, "diagnostics", "near_dup_similarity_histogram.json")
    if not os.path.exists(p):
        return None
    h = json.load(open(p, encoding="utf-8"))["est_jaccard_bucket_counts"]
    thr = m["config"]["near_dup_threshold"]
    keys = sorted(h, key=float)
    if not keys:
        return None
    W, H, left, bottom, top = 920, 330, 70, 60, 70
    mx = max(h.values())
    bw = (W - left - 40) / len(keys)
    body = [f'<line x1="{left}" y1="{H - bottom}" x2="{W - 30}" y2="{H - bottom}" stroke="{GRID}" stroke-width="2"/>']
    for i, k in enumerate(keys):
        v = h[k]
        bh = (H - bottom - top) * v / mx
        x = left + i * bw
        col = "#f87171" if float(k) >= thr else "#38bdf8"
        body.append(f'<rect x="{x + 3:.1f}" y="{H - bottom - bh:.1f}" width="{bw - 6:.1f}" height="{bh:.1f}" rx="3" fill="{col}"/>')
        body.append(text(x + bw / 2, H - bottom + 18, f"{float(k):.2f}", 11, MUTED, "middle"))
        body.append(text(x + bw / 2, H - bottom - bh - 6, fmt(v), 11, FG, "middle", "600"))
    tx = left + (thr - float(keys[0])) / 0.05 * bw
    body.append(f'<line x1="{tx:.1f}" y1="{top - 10}" x2="{tx:.1f}" y2="{H - bottom}" stroke="#fbbf24" stroke-width="2" stroke-dasharray="6 5"/>')
    body.append(text(tx + 8, top - 2, f"threshold {thr:.2f}  (red = dropped as near-duplicate)", 12, "#fbbf24"))
    body.append(text(W / 2, H - 14, "estimated Jaccard of candidate pairs (MinHash, 128 perms, word 5-gram shingles)", 11, MUTED, "middle"))
    return svg(W, H, "".join(body), "Near-duplicate candidate pairs by similarity")


for name, fn in (("funnel", funnel), ("drop_reasons", drop_reasons), ("sources", sources), ("near_dup", near_dup)):
    s = fn()
    if s:
        with open(os.path.join(dest, name + ".svg"), "w", encoding="utf-8", newline="\n") as f:
            f.write(s)
        print("wrote", os.path.join(dest, name + ".svg"))
