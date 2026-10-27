"""Quality filtering.

Two kinds of rule:

* ``clean_markup_and_boilerplate``  - *repairs*: strips tags/entities and
  removes obvious boilerplate lines, so a good article with a "Share on
  Facebook" footer is kept rather than thrown away.
* ``gate_*``                         - *rejects*, each with a short reason code
  that ends up in the ledger.

Legitimate-but-unusual text (short proverbs, poems with refrains, tables of
numbers) is protected explicitly; see ``looks_like_table`` and the repetition
thresholds in config.py, and the tests in tests/test_quality.py.
"""
from __future__ import annotations

import html
import re
from collections import Counter

from .config import Config

# ---------------------------------------------------------------- repairs
_SCRIPT_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.I | re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_TAG = re.compile(r"</?[A-Za-z][^<>\n]{0,300}>")

_BOILERPLATE_LINE = re.compile(
    r"""^(?:
        share(?:\s+(?:on|this|via))?.{0,30}|tweet|pin\s?it|follow\s+us.{0,40}|like\s+us.{0,40}
        |read\s+more.{0,40}|click\s+here.{0,60}|continue\s+reading.{0,40}|also\s+read.{0,80}
        |related\s+(?:posts?|articles?|news|stories).{0,40}|advertisement|sponsored|subscribe.{0,60}
        |sign\s+(?:in|up)|log\s?in|register|home|menu|search|skip\s+to\s+content
        |copyright\s*(?:©|\(c\))?.{0,100}|©.{0,100}|all\s+rights\s+reserved.{0,60}
        |privacy\s+policy.{0,40}|terms\s+(?:of\s+use|and\s+conditions|&\s+conditions).{0,40}
        |cookies?.{0,80}|we\s+use\s+cookies.{0,100}|leave\s+a\s+(?:reply|comment).{0,40}
        |posted\s+(?:by|on).{0,60}|tags?\s*:.{0,100}|filed\s+under.{0,60}
        |सभी\s+अधिकार\s+सुरक्षित.{0,60}|और\s+पढ़ें.{0,40}|ये\s+भी\s+पढ़ें.{0,80}|यह\s+भी\s+पढ़ें.{0,80}
        |संबंधित\s+(?:खबरें|ख़बरें|समाचार|लेख).{0,40}|विज्ञापन|शेयर\s+करें.{0,30}|फॉलो\s+करें.{0,40}
        |हमें\s+फॉलो\s+करें.{0,40}|सब्सक्राइब.{0,60}|कॉपीराइट.{0,80}|गोपनीयता\s+नीति.{0,30}
        |अधिक\s+जानकारी\s+के\s+लिए.{0,60}|टिप्पणी\s+(?:करें|लिखें).{0,40}|लॉग\s?इन|होम|मेन्यू
    )\s*[:\-|।]?$""",
    re.I | re.X,
)

_SPAM_TERMS = [
    "click here", "buy now", "free download", "casino", "betting", "whatsapp group",
    "join telegram", "telegram channel", "lottery", "viagra", "porn", "xxx", "sex video",
    "earn money", "work from home", "100% free", "limited offer", "loan approval", "satta",
    "matka", "bonus", "jackpot", "mlm", "weight loss", "adult video", "dating",
    "यहाँ क्लिक", "यहां क्लिक", "अभी जुड़ें", "सट्टा", "मटका", "लॉटरी", "फ्री डाउनलोड",
    "ऑनलाइन कमाएं", "घर बैठे कमाएं", "व्हाट्सएप ग्रुप", "टेलीग्राम", "जैकपॉट", "बोनस",
    "सेक्स", "वियाग्रा", "ऑफर",
]
_SPAM_RE = re.compile("|".join(re.escape(t) for t in _SPAM_TERMS), re.I)


def clean_markup_and_boilerplate(text: str, cfg: Config) -> tuple[str, dict]:
    """Return (text, info). info has tag_ratio, boilerplate_lines, total_lines."""
    info = {"tag_ratio": 0.0, "boilerplate_lines": 0, "total_lines": 0}
    n0 = max(len(text), 1)
    if "<" in text:
        stripped = _SCRIPT_STYLE.sub(" ", text)
        stripped = _COMMENT.sub(" ", stripped)
        tag_chars = sum(len(m.group()) for m in _TAG.finditer(stripped)) + (len(text) - len(stripped))
        info["tag_ratio"] = tag_chars / n0
        if info["tag_ratio"] <= cfg.max_markup_tag_ratio:
            text = _TAG.sub(" ", stripped)
    if "&" in text:
        text = html.unescape(text)
    if info["tag_ratio"] <= cfg.max_markup_tag_ratio:
        # tidy whitespace left by removed tags without re-running full normalisation
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\n[ \t]+", "\n", text).strip()

    lines = text.split("\n")
    kept = []
    for ln in lines:
        s = ln.strip()
        if s and len(s) <= cfg.boilerplate_line_max_chars and _BOILERPLATE_LINE.match(s):
            info["boilerplate_lines"] += 1
            continue
        kept.append(ln)
    info["total_lines"] = sum(1 for ln in lines if ln.strip())
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return text, info


# ---------------------------------------------------------------- gates
_MOJIBAKE = re.compile(r"à[¤¥]|Ã[\u0080-¿]|â€[\u0080-¿™œ”“˜]|�")
_SYMBOLS = re.compile(r"[<>{}\[\]=|\\_#*^~`]")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_RUN = re.compile(r"(.)\1{9,}")
_RUN_OK = set(" -=_*.~#।\n\t─━")
# Devanagari structure checks: dependent signs with no base, stacked vowel signs
_DEV_BAD = re.compile(
    "(?<![ऀ-ॿ])[ऀ-ःऺ-ॏ॑-ॗॢॣ़]"  # sign at word start
    "|[ा-ौ][ा-्]"                                                   # vowel sign + vowel sign / virama
    "|्{2,}"                                                                       # double virama
    "|्[ऀ-ः़]"                                                      # virama + anusvara/nukta
)
_DEV_CHAR = re.compile("[ऀ-ॿ]")
# Word separators for *counting*: whitespace plus sentence punctuation. Plain str.split() counts
# "chalo,chalte hain." as 2 words (the comma is glued), which wrongly sank short Hinglish utterances.
# \w is NOT used: it does not match Devanagari vowel signs and would cut Hindi words apart.
_WORD_SEP = re.compile(r"[\s,;:.।॥…\"'()\[\]/|\-]+")
_PLACEHOLDER_TEXT = re.compile(r"lorem\s+ipsum|dummy\s+text\s+of\s+the\s+(?:printing|typesetting)", re.I)


def count_words(text: str) -> int:
    return sum(1 for t in _WORD_SEP.split(text) if t)
_DIGIT = re.compile(r"\d")
_SPACE = re.compile(r"\s")


def looks_like_table(text: str, cfg: Config) -> bool:
    """Structured numeric/text table: >=3 lines, most tokens numeric, and the
    column count is consistent. Such documents are exempt from digit/symbol/
    repetition filters (a table of 1000 rows of '0 0 0' is legitimate data)."""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if len(lines) < cfg.table_min_lines:
        return False
    counts, numeric = Counter(), 0
    total = 0
    for ln in lines:
        toks = [t for t in re.split(r"[\s|,;\t]+", ln.strip()) if t]
        if not toks:
            continue
        counts[len(toks)] += 1
        total += len(toks)
        numeric += sum(1 for t in toks if re.fullmatch(r"[-+₹$%.,\d०-९/:]+", t))
    if not total:
        return False
    mode_share = counts.most_common(1)[0][1] / len(lines)
    return numeric / total >= cfg.table_numeric_token_ratio and mode_share >= 0.6


def devanagari_invalid_ratio(text: str) -> float:
    n = len(_DEV_CHAR.findall(text))
    if n < 20:
        return 0.0
    return len(_DEV_BAD.findall(text)) / n


def gate_pre_lang(text: str, info: dict, cfg: Config) -> str | None:
    """Garbage that must be rejected *before* language ID (it would be
    mislabelled otherwise)."""
    n = len(text)
    if not n:
        return "boilerplate" if info["boilerplate_lines"] else "empty"
    if count_words(text) < cfg.min_words:
        return "too_short"
    if _PLACEHOLDER_TEXT.search(text):
        return "placeholder_text"
    if info["tag_ratio"] > cfg.max_markup_tag_ratio:
        return "markup"
    if text.count("�") / n > cfg.max_replacement_char_ratio:
        return "garbled_replacement_chars"
    if len(_MOJIBAKE.findall(text)) >= 3:
        return "garbled_mojibake"
    nonspace = n - len(_SPACE.findall(text))
    if nonspace >= 10 and text.count("?") / max(nonspace, 1) > cfg.max_question_mark_ratio:
        return "garbled_question_marks"
    if devanagari_invalid_ratio(text) > cfg.max_invalid_devanagari_ratio:
        return "garbled_devanagari"
    if info["total_lines"] >= 4 and info["boilerplate_lines"] / info["total_lines"] >= cfg.boilerplate_doc_ratio:
        return "boilerplate"
    return None


def gate_post_lang(text: str, cfg: Config) -> str | None:
    """Content-quality rejects, applied to text in a target language."""
    words = text.split()
    table = looks_like_table(text, cfg)
    n = len(text)
    if not table:
        digits = len(_DIGIT.findall(text))
        if digits / n > cfg.max_digit_ratio:
            return "numeric_junk"
        if len(_SYMBOLS.findall(text)) / n > cfg.max_symbol_ratio:
            return "markup_or_code"
    urls = len(_URL.findall(text))
    if urls and urls / len(words) * 100 > cfg.max_urls_per_100_words:
        return "url_heavy"
    hits = {m.group().lower() for m in _SPAM_RE.finditer(text)}
    if len(hits) >= cfg.spam_min_distinct_hits:
        return "spam_keywords"
    if not table:
        run_chars = sum(len(m.group()) for m in _RUN.finditer(text) if m.group(1) not in _RUN_OK)
        if run_chars / n > cfg.max_char_run_ratio:
            return "char_runs"
        if len(words) >= cfg.min_words_for_repetition:
            lw = [w.strip(".,;:!?।॥\"'()").lower() for w in words]
            counts = Counter(lw)
            if len(counts) / len(lw) < cfg.min_unique_word_ratio:
                return "repetitive_words"
            if counts.most_common(1)[0][1] / len(lw) > cfg.max_top_word_ratio:
                return "repetitive_words"
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if len(lines) >= cfg.min_lines_for_line_repetition:
            if 1 - len(set(lines)) / len(lines) > cfg.max_repeated_line_ratio:
                return "repeated_lines"
    return None
