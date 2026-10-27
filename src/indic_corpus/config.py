"""All tunable thresholds live here so they land in manifest.json verbatim.

Nothing in the pipeline reads a magic number from anywhere else. A threshold
that was chosen by looking at data has a comment saying where the evidence is
(see DECISIONS.md).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field

PIPELINE_VERSION = "1.0.0"

# Ordered list of stages a document can be dropped at. Used for funnel tables.
STAGES = (
    "read",
    "normalize",
    "filter",
    "lang",
    "dedup_exact",
    "dedup_near",
    "eval_holdout",
    "contamination",
)


@dataclass(frozen=True)
class Config:
    # ---- reading ---------------------------------------------------------
    text_fields: tuple = (
        "text", "content", "body", "sentence", "article", "document",
        "raw_content", "paragraph", "message", "review", "comment", "story",
    )
    text_field_override: str = ""          # --text-field
    txt_mode: str = "line"                 # "line": one doc per line; "file": one doc per file
    max_record_bytes: int = 64 * 1024 * 1024
    # Deterministic per-source down-sampling (set per source in SOURCES.json, never globally): a record
    # is processed iff sha1(doc_id) falls below this fraction; the rest get a ledger row (read:not_sampled).
    sample_fraction: float = 1.0

    # ---- language --------------------------------------------------------
    keep_langs: tuple = ("hi", "hi-Latn")  # everything else is labelled but dropped
    dev_min_ratio: float = 0.5             # share of WORDS in Devanagari -> "hi" path
    hinglish_min_rate: float = 0.12        # romanised-Hindi function words / Latin tokens
    hinglish_min_hits: int = 2
    hinglish_vs_english: float = 0.4       # hindi_rate must be >= 0.4 * english_stopword_rate
    min_letters_for_lang: int = 3

    # ---- quality filters -------------------------------------------------
    min_words: int = 3                     # "जैसी करनी वैसी भरनी" (4 words) must survive
    max_replacement_char_ratio: float = 0.002
    max_markup_tag_ratio: float = 0.30     # above this the doc IS markup -> drop; below -> strip tags
    max_symbol_ratio: float = 0.10         # < > { } [ ] = | \ _ # * ^ ~ share of chars
    max_question_mark_ratio: float = 0.25  # lossy "????" encodings
    max_invalid_devanagari_ratio: float = 0.01
    max_digit_ratio: float = 0.5           # exempt if the doc is a structured table
    min_words_for_repetition: int = 30
    min_unique_word_ratio: float = 0.15
    max_top_word_ratio: float = 0.40
    max_repeated_line_ratio: float = 0.50
    min_lines_for_line_repetition: int = 6
    max_char_run_ratio: float = 0.20
    max_urls_per_100_words: float = 3.0
    spam_min_distinct_hits: int = 3
    boilerplate_line_max_chars: int = 120
    boilerplate_doc_ratio: float = 0.5     # drop doc if this share of lines is boilerplate
    table_min_lines: int = 3
    table_numeric_token_ratio: float = 0.6

    # ---- near-duplicate detection ---------------------------------------
    shingle_words: int = 5
    num_perm: int = 128
    near_dup_threshold: float = 0.80       # estimated Jaccard; set from tools/threshold_study.py
    near_dup_min_words: int = 20           # shorter docs: exact dedup only
    pair_log_min: float = 0.55             # log candidate pairs >= this for the threshold study
    minhash_seed: int = 1337

    # ---- eval set --------------------------------------------------------
    eval_size: int = 200
    eval_candidate_pool: int = 2000        # lowest-ranked docs kept per language before family/quality exclusion
    eval_hi_latn_share: float = 0.25
    eval_seed: int = 20261026
    eval_min_doc_words: dict = field(default_factory=lambda: {"hi": 40, "hi-Latn": 8})
    eval_passage_min_words: dict = field(default_factory=lambda: {"hi": 20, "hi-Latn": 8})
    eval_passage_max_words: int = 120

    # ---- contamination ---------------------------------------------------
    contam_shingle_words: int = 5
    contam_near_containment: float = 0.60   # share of eval 5-grams found in a train doc
    contam_translit_shingle_words: int = 4   # romanisation is noisy: shorter n-grams, lower bar
    contam_translit_containment: float = 0.60
    contam_near_miss_min: float = 0.30      # logged to diagnostics only
    contam_near_miss_cap: int = 2000

    # ---- output ----------------------------------------------------------
    rows_per_part: int = 50_000

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self), sort_keys=True, ensure_ascii=False)

    def digest(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()[:12]

    @staticmethod
    def from_overrides(overrides: dict) -> "Config":
        base = Config()
        valid = {f.name for f in dataclasses.fields(Config)}
        bad = set(overrides) - valid
        if bad:
            raise SystemExit(f"unknown config keys: {sorted(bad)}")
        cleaned = {}
        for k, v in overrides.items():
            if isinstance(getattr(base, k), tuple) and isinstance(v, list):
                v = tuple(v)
            cleaned[k] = v
        return dataclasses.replace(base, **cleaned)
