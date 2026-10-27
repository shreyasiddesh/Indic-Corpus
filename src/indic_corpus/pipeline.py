"""Orchestration: raw_dir -> out_dir.

    S1  per input file  : read, normalise, label, filter, redact -> shard   (checkpointed)
    S2  all shards      : exact + near dedup, pick eval candidates          (recomputed, deterministic)
    S3  all shards      : eval hold-out, contamination, write clean/ledger  (recomputed, deterministic)

A killed run leaves only complete S1 shards (atomic rename); S2/S3 always
recompute from them, and S3 builds the final files in a temp location that is
swapped in only at the end. Result: restart == uninterrupted run, byte for byte.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import platform
import shutil
import sys
from collections import Counter, defaultdict

from . import __version__
from .config import STAGES, Config
from .contamination import METHOD_ORDER, EvalIndex
from .dedup import NearDedup, shingle_ids, tokenize
from .evalset import EvalCandidates, select_items
from .io_utils import atomic_gz_text, atomic_write_text, dumps, read_jsonl_gz, write_jsonl_gz
from .readers import discover, file_format, sha256_file
from .stage1 import process_file

LANG_NA = "n/a"


def log(msg: str) -> None:
    print(f"[indic_corpus] {msg}", file=sys.stderr, flush=True)


def code_hash() -> str:
    h = hashlib.sha256()
    d = os.path.dirname(__file__)
    for n in sorted(os.listdir(d)):
        if n.endswith(".py"):
            h.update(n.encode())
            h.update(open(os.path.join(d, n), "rb").read())
    return h.hexdigest()[:12]


# --------------------------------------------------------------------------- sources
def load_sources(raw_dir: str) -> list[dict]:
    p = os.path.join(raw_dir, "SOURCES.json")
    if not os.path.exists(p):
        return []
    try:
        data = json.load(open(p, encoding="utf-8"))
    except Exception:
        return []
    return data["sources"] if isinstance(data, dict) else data


def source_for(rel: str, sources: list[dict]) -> tuple[str, dict]:
    """-> (source name, SOURCES.json entry or {}). Longest path-prefix wins."""
    best, best_len = None, -1
    for s in sources:
        prefix = s.get("path", "")
        if prefix and rel.startswith(prefix) and len(prefix) > best_len:
            best, best_len = s, len(prefix)
    if best:
        return best["name"], best
    parts = rel.split("/")
    return (parts[0] if len(parts) > 1 else os.path.splitext(parts[0])[0]), {}


# --------------------------------------------------------------------------- run
def run(raw_dir: str, out_dir: str, cfg: Config, keep_work: bool = False) -> dict:
    raw_dir, out_dir = os.path.abspath(raw_dir), os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    sources = load_sources(raw_dir)
    files, ignored = discover(raw_dir)
    log(f"{len(files)} input files ({len(ignored)} ignored)")

    chash = code_hash()
    sources_digest = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
    run_key = hashlib.sha256((cfg.digest() + chash + sources_digest).encode()).hexdigest()[:12]
    work = os.path.join(out_dir, "_work", run_key)
    s1_dir = os.path.join(work, "s1")
    os.makedirs(s1_dir, exist_ok=True)
    for stale in os.listdir(s1_dir):                      # leftovers of a killed run
        if stale.endswith(".tmp"):
            os.remove(os.path.join(s1_dir, stale))

    # ---- inputs + S1 ------------------------------------------------------
    inputs, shard_paths = [], []
    read_skips: Counter = Counter()
    for idx, (rel, path) in enumerate(files):
        digest = sha256_file(path)
        fmt, comp = file_format(rel)
        shard = os.path.join(s1_dir, f"{idx:05d}-{digest[:12]}.jsonl.gz")
        stats_path = shard + ".stats.json"
        source, entry = source_for(rel, sources)
        file_cfg = cfg
        if entry.get("text_field") and not cfg.text_field_override:
            file_cfg = dataclasses.replace(file_cfg, text_field_override=entry["text_field"])
        if entry.get("sample_fraction"):
            file_cfg = dataclasses.replace(file_cfg, sample_fraction=float(entry["sample_fraction"]))
        if os.path.exists(shard) and os.path.exists(stats_path):
            stats = json.load(open(stats_path, encoding="utf-8"))
            log(f"S1 {rel}: resumed from checkpoint")
        else:
            log(f"S1 {rel}: processing")
            stats = process_file(rel, path, source, file_cfg, shard)
            atomic_write_text(stats_path, json.dumps(stats, sort_keys=True))
        for k, v in stats.items():
            if k.startswith("skipped:"):
                read_skips[k[8:]] += v
        inputs.append({"path": rel, "bytes": os.path.getsize(path), "sha256": digest, "format": fmt,
                       "compression": comp or None, "source": source, "records": stats.get("records", 0)})
        shard_paths.append(shard)

    def rows():
        for sp in shard_paths:
            yield from read_jsonl_gz(sp)

    # ---- S2: dedup + eval candidates -------------------------------------
    log("S2 dedup")
    exact: dict[str, str] = {}
    near = NearDedup(cfg.near_dup_threshold, cfg.num_perm, cfg.minhash_seed, cfg.pair_log_min)
    decisions: dict[str, tuple] = {}
    cands = EvalCandidates(cfg)
    for r in rows():
        if r["status"] != "kept":
            continue
        did, h = r["id"], r["h"]
        if h in exact:
            decisions[did] = ("dedup_exact", "exact_duplicate", exact[h], 1.0)
            continue
        toks = tokenize(r["text"])
        if len(toks) >= cfg.near_dup_min_words:
            dup, sim = near.query_and_add(did, shingle_ids(toks, cfg.shingle_words))
            if dup:
                decisions[did] = ("dedup_near", f"near_duplicate(est_jaccard={sim:.3f})", dup, sim)
                exact.setdefault(h, dup)
                continue
        exact[h] = did
        cands.offer(did, r["lang"], r["src"], r["text"])
    del exact

    n_family = cands.exclude(near.family)
    log(f"S2: {n_family} eval candidates excluded (member of a near-duplicate template family)")
    eval_items = select_items(cands, cfg)
    del cands
    held = {it["source_doc_id"]: it["eval_id"] for it in eval_items}
    log(f"S2: {len(decisions)} duplicates, {len(eval_items)} eval items")

    boundary = sorted(
        near.pair_log, key=lambda p: (abs(p["est_jaccard"] - cfg.near_dup_threshold), p["a"], p["b"])
    )[:60]
    wanted_ids = {p["a"] for p in boundary} | {p["b"] for p in boundary}
    pair_hist = Counter(round(int(p["est_jaccard"] * 20) / 20, 2) for p in near.pair_log)
    bands = (near.bands, near.rows)
    del near

    # ---- S3: contamination + outputs -------------------------------------
    log("S3 contamination + write")
    index = EvalIndex(eval_items, cfg)
    tmp_clean = os.path.join(work, "clean.tmp")
    shutil.rmtree(tmp_clean, ignore_errors=True)
    os.makedirs(tmp_clean)
    ledger_tmp = os.path.join(work, "ledger.jsonl.gz")

    leaks: dict[int, dict] = defaultdict(dict)       # eval idx -> {train_id: method}
    near_misses, filter_samples = [], defaultdict(list)
    boundary_texts: dict[str, str] = {}
    final_lang: dict[str, Counter] = defaultdict(Counter)      # lang -> {drop stage index | len(STAGES)}
    reason_counts: Counter = Counter()
    per_source: dict[str, dict] = defaultdict(lambda: {"docs_in": 0, "kept": 0, "kept_chars": 0, "dropped": Counter()})
    pii_totals: Counter = Counter()
    kept_by_lang: Counter = Counter()
    parts, part_idx, part_rows, part_writer, part_cm = [], 0, 0, None, None
    ledger_rows = 0

    def open_part():
        nonlocal part_cm, part_writer, part_rows
        name = f"part-{part_idx:05d}.jsonl.gz"
        part_cm = atomic_gz_text(os.path.join(tmp_clean, name))
        part_writer = part_cm.__enter__()
        part_rows = 0
        parts.append({"name": name, "rows": 0})

    def close_part():
        nonlocal part_cm
        if part_cm is not None:
            part_cm.__exit__(None, None, None)
            part_cm = None

    with atomic_gz_text(ledger_tmp) as ledger:
        for r in rows():
            did, lang = r["id"], r.get("lang")
            status, stage, reason, dup_of = r["status"], r["stage"], r["reason"], None
            if did in wanted_ids and r["status"] == "kept":
                boundary_texts[did] = r["text"]
            if status == "kept":
                if did in decisions:
                    stage, reason, dup_of, _ = decisions[did]
                    status = "dropped"
                elif did in held:
                    status, stage, reason, dup_of = "dropped", "eval_holdout", "held_out_for_eval", f"eval:{held[did]}"
                else:
                    found, misses = index.check(r["text"])
                    for m in misses:
                        if len(near_misses) < cfg.contam_near_miss_cap:
                            m.update(train_id=did, snip=r["text"][:300], eval_text=None)
                            near_misses.append(m)
                    if found:
                        best = min(found.items(), key=lambda kv: (METHOD_ORDER[kv[1][0]], -kv[1][1], kv[0]))
                        for i, (method, _score) in found.items():
                            leaks[i][did] = method
                        status, stage = "dropped", "contamination"
                        reason = f"eval_leak:{best[1][0]}"
                        dup_of = f"eval:{eval_items[best[0]]['eval_id']}"
                    else:
                        if part_cm is None or part_rows >= cfg.rows_per_part:
                            if part_cm is not None:
                                close_part()
                                part_idx += 1
                            open_part()
                        part_writer.write(dumps({"id": did, "text": r["text"], "lang": lang, "source": r["src"]}) + "\n")
                        part_rows += 1
                        parts[-1]["rows"] = part_rows
                        kept_by_lang[lang] += 1
                        for k, v in r.get("pii", {}).items():
                            pii_totals[k] += v
            ps = per_source[r["src"]]
            ps["docs_in"] += 1
            if status == "kept":
                ps["kept"] += 1
                ps["kept_chars"] += len(r["text"])
                final_lang[lang or LANG_NA][len(STAGES)] += 1
            else:
                final_lang[lang or LANG_NA][STAGES.index(stage)] += 1
                reason_counts[f"{stage}:{reason.split('(')[0]}"] += 1
                ps["dropped"][f"{stage}:{reason.split('(')[0]}"] += 1
                if r["status"] == "dropped" and "snip" in r and len(filter_samples[(stage, reason)]) < 25:
                    filter_samples[(stage, reason)].append(
                        {"id": did, "stage": stage, "reason": reason, "lang": lang, "ls": r.get("ls"),
                         "source": r["src"], "snip": r["snip"]})
            ledger.write(dumps({
                "id": did, "status": status, "stage": stage if status == "dropped" else "final",
                "reason": reason if status == "dropped" else "", "dup_of": dup_of if status == "dropped" else None,
                "source": r["src"], "lang": lang, "chars": r["chars"], "file": r["file"], "ord": r["ord"],
            }) + "\n")
            ledger_rows += 1
        close_part()
    if not parts:                                   # no survivors: still emit an empty, valid clean/
        open_part()
        close_part()

    # ---- contamination.jsonl, eval.jsonl, diagnostics --------------------
    contam_rows = []
    for i in sorted(leaks, key=lambda k: eval_items[k]["eval_id"]):
        methods = leaks[i]
        strongest = min(methods.values(), key=lambda m: METHOD_ORDER[m])
        contam_rows.append({"eval_id": eval_items[i]["eval_id"], "train_ids": sorted(methods),
                            "method": strongest, "methods_by_train_id": dict(sorted(methods.items()))})
    for m in near_misses:
        m["eval_text"] = next(it["text"] for it in eval_items if it["eval_id"] == m["eval_id"])[:300]

    from .dedup import shingle_ids as _sh
    boundary_rows = []
    for p in boundary:
        ta, tb = boundary_texts.get(p["a"]), boundary_texts.get(p["b"])
        if ta is None or tb is None:
            continue
        sa, sb = set(_sh(tokenize(ta), cfg.shingle_words).tolist()), set(_sh(tokenize(tb), cfg.shingle_words).tolist())
        exact_j = len(sa & sb) / max(len(sa | sb), 1)
        boundary_rows.append({**p, "exact_jaccard": round(exact_j, 4), "a_text": ta[:700], "b_text": tb[:700],
                              "a_words": len(ta.split()), "b_words": len(tb.split()),
                              "decision": "dropped_as_duplicate" if p["est_jaccard"] >= cfg.near_dup_threshold else "kept_as_distinct"})

    diag = os.path.join(work, "diagnostics")
    shutil.rmtree(diag, ignore_errors=True)
    write_jsonl_gz(os.path.join(diag, "near_dup_boundary_pairs.jsonl.gz"), boundary_rows)
    write_jsonl_gz(os.path.join(diag, "contamination_near_misses.jsonl.gz"), near_misses)
    write_jsonl_gz(os.path.join(diag, "dropped_samples.jsonl.gz"),
                   [x for k in sorted(filter_samples) for x in filter_samples[k]])
    atomic_write_text(os.path.join(diag, "near_dup_similarity_histogram.json"),
                      json.dumps({"lsh_bands_rows": bands, "est_jaccard_bucket_counts": dict(sorted(pair_hist.items()))},
                                 indent=1, sort_keys=True))

    eval_tmp = os.path.join(work, "eval.jsonl")
    atomic_write_text(eval_tmp, "".join(dumps(it) + "\n" for it in eval_items))
    contam_tmp = os.path.join(work, "contamination.jsonl")
    atomic_write_text(contam_tmp, "".join(dumps(r) + "\n" for r in contam_rows))

    # ---- manifest ---------------------------------------------------------
    funnel = build_funnel(final_lang)
    for p in parts:
        p["sha256"] = sha256_file(os.path.join(tmp_clean, p["name"]))
    manifest = {
        "pipeline_version": __version__, "code_hash": chash, "python": platform.python_version(),
        "config": json.loads(cfg.to_json()), "config_digest": cfg.digest(),
        "sources": sources, "inputs": inputs, "ignored_files": ignored,
        "read_skipped_by_reason": dict(sorted(read_skips.items())),
        "funnel": funnel, "drop_reasons": dict(sorted(reason_counts.items())),
        "per_source": {k: {"docs_in": v["docs_in"], "kept": v["kept"], "kept_chars": v["kept_chars"],
                           "dropped": dict(sorted(v["dropped"].items()))} for k, v in sorted(per_source.items())},
        "pii_redactions_in_clean": dict(sorted(pii_totals.items())),
        "dedup": {"exact_dropped": sum(1 for d in decisions.values() if d[0] == "dedup_exact"),
                  "near_dropped": sum(1 for d in decisions.values() if d[0] == "dedup_near"),
                  "lsh_bands_rows": bands},
        "eval": {"items": len(eval_items), "by_lang": dict(Counter(i["lang"] for i in eval_items))},
        "contamination": {"eval_items_affected": len(contam_rows),
                          "training_docs_removed": reason_counts_for(reason_counts, "contamination"),
                          "by_method": dict(Counter(r["method"] for r in contam_rows))},
        "outputs": {"clean_rows": sum(p["rows"] for p in parts), "clean_by_lang": dict(sorted(kept_by_lang.items())),
                    "clean_parts": parts, "ledger_rows": ledger_rows,
                    "ledger_sha256": sha256_file(ledger_tmp),
                    "eval_sha256": sha256_file(eval_tmp), "contamination_sha256": sha256_file(contam_tmp)},
    }

    # ---- publish (swap into place; manifest last = completion marker) ------
    final_clean = os.path.join(out_dir, "clean")
    shutil.rmtree(final_clean, ignore_errors=True)
    os.replace(tmp_clean, final_clean)
    os.replace(ledger_tmp, os.path.join(out_dir, "ledger.jsonl.gz"))
    os.replace(eval_tmp, os.path.join(out_dir, "eval.jsonl"))
    os.replace(contam_tmp, os.path.join(out_dir, "contamination.jsonl"))
    shutil.rmtree(os.path.join(out_dir, "diagnostics"), ignore_errors=True)
    os.replace(diag, os.path.join(out_dir, "diagnostics"))
    atomic_write_text(os.path.join(out_dir, "manifest.json"), json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    if not keep_work:
        shutil.rmtree(os.path.join(out_dir, "_work"), ignore_errors=True)
    log(f"done: {manifest['outputs']['clean_rows']} kept / {ledger_rows} input docs")
    return manifest


def reason_counts_for(reason_counts: Counter, stage: str) -> int:
    return sum(v for k, v in reason_counts.items() if k.startswith(stage + ":"))


def build_funnel(final_lang: dict[str, Counter]) -> list[dict]:
    """Ordered rows: documents remaining after each stage, per language label
    (language = what the detector said; docs dropped before language ID are 'n/a')."""
    langs = sorted(final_lang, key=lambda l: (l == LANG_NA, l))
    rows = [{"after": "input", **{l: sum(final_lang[l].values()) for l in langs}}]
    for i, s in enumerate(STAGES):
        rows.append({"after": s, **{l: sum(v for k, v in final_lang[l].items() if k > i) for l in langs}})
    for r in rows:
        r["ALL"] = sum(v for k, v in r.items() if k != "after")
    return rows
