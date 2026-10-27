"""Stage 1: raw record -> normalised, labelled, filtered, redacted document.

Pure per-document work (no cross-document state), so it is checkpointed per
input file and trivially parallelisable.
"""
from __future__ import annotations

import hashlib
import os
import re
from collections import Counter

from .config import Config
from .io_utils import atomic_gz_text, dumps
from .langid import detect
from .normalize import normalize_text
from .pii import redact
from .quality import clean_markup_and_boilerplate, count_words, gate_post_lang, gate_pre_lang
from .readers import doc_id, iter_records

_PLACEHOLDER = re.compile(r"<(?:PHONE|EMAIL|AADHAAR|PAN)>")


def _drop(stage: str, reason: str, lang, chars: int, ls=None, text: str = "") -> dict:
    row = {"status": "dropped", "stage": stage, "reason": reason, "lang": lang, "chars": chars, "ls": ls}
    if text and stage in ("filter", "lang"):
        row["snip"] = text[:400]          # lets us audit what the filters throw away (diagnostics only)
    return row


def sampled_in(doc_id: str, fraction: float) -> bool:
    return int(hashlib.sha1(doc_id.encode()).hexdigest()[:8], 16) / 0x100000000 < fraction


def process_text(raw: str, cfg: Config) -> dict:
    """-> row fields. Kept rows carry ``text`` (final, redacted) and ``h``."""
    chars = len(raw)
    text = normalize_text(raw)
    if not text:
        return _drop("normalize", "empty_after_normalization", None, chars)

    text, info = clean_markup_and_boilerplate(text, cfg)
    text = normalize_text(text)

    res = detect(text, cfg) if text else None
    lang = res.lang if res else None
    ls = res.summary() if res else None

    reason = gate_pre_lang(text, info, cfg)
    if reason:
        return _drop("filter", reason, lang, chars, ls, text)
    if lang not in cfg.keep_langs:
        return _drop("lang", f"lang={lang}", lang, chars, ls, text)
    reason = gate_post_lang(text, cfg)
    if reason:
        return _drop("filter", reason, lang, chars, ls, text)

    text, pii = redact(text)
    stripped = _PLACEHOLDER.sub(" ", text)
    if count_words(stripped) < cfg.min_words:
        return _drop("filter", "pii_only", lang, chars, ls, text)

    return {
        "status": "kept", "stage": "final", "reason": "", "lang": lang, "chars": chars, "ls": ls,
        "pii": dict(pii), "bp": info["boilerplate_lines"],
        "h": hashlib.sha1(text.encode("utf-8")).hexdigest(), "text": text,
    }


def process_file(rel: str, path: str, source: str, cfg: Config, shard_path: str) -> dict:
    """Stream one raw file into one shard. Returns small stats dict."""
    stats = Counter()
    with atomic_gz_text(shard_path) as out:
        for rec in iter_records(path, rel, cfg):
            row = {"id": doc_id(rel, rec.ordinal), "src": source, "file": rel, "ord": rec.ordinal}
            stats["records"] += 1
            if cfg.sample_fraction < 1.0 and not sampled_in(row["id"], cfg.sample_fraction):
                row.update(_drop("read", "not_sampled", None, 0))
                stats["skipped:not_sampled"] += 1
            elif rec.text is None:
                row.update(_drop("read", rec.error or "unreadable", None, 0))
                stats[f"skipped:{rec.error}"] += 1
            else:
                row.update(process_text(rec.text, cfg))
            out.write(dumps(row) + "\n")
            die = os.environ.get("INDIC_CORPUS_TEST_DIE_AFTER_RECORDS")  # crash-recovery test hook
            if die and stats["records"] >= int(die):
                out.flush()
                os._exit(137)
    return dict(stats)
