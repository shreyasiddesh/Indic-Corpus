"""Language labelling without trusting the source's own labels.

Labels: ``hi`` (Devanagari Hindi, English words allowed), ``hi-Latn`` (romanised
Hindi / Hinglish), ``en`` and ``other``.

Why not fastText/langid? (1) no model download is allowed in run.sh (offline),
(2) off-the-shelf identifiers have no Hinglish class at all, and (3) Devanagari
is shared by Hindi, Marathi, Nepali and Sanskrit, which we need to separate.
So: script statistics first, then closed-class word lists, which are the most
reliable signal for short text and are inspectable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .config import Config

_LETTER = re.compile(r"[^\W\d_]")
_DEV_LETTER = re.compile("[ऄ-हऽॐक़-ॡॱ-ॿ]")
_LATIN_LETTER = re.compile("[A-Za-zÀ-ɏ]")
_DEV_TOKEN = re.compile("[ऀ-ॿ]+")
_LATIN_TOKEN = re.compile(r"[A-Za-z]+")

# Devanagari function words. Hindi-only vs Marathi-only vs Nepali-only sets are
# deliberately disjoint so shared words (तो, हे, या) do not vote.
_HI = frozenset(
    "है हैं था थे थी का की के को में से पर और यह वह इस उस नहीं कि भी हो एक लिए कर किया "
    "करने जो हम आप मैं क्या लेकिन अपने रहा रही गया गई होता होती हुआ हुई हुए सकता सकती "
    "तथा जब तक वे उन इन कुछ बहुत साथ द्वारा".split()
)
_MR = frozenset(
    "आहे आहेत होते होती मध्ये आणि च्या ची चे चा नाही केले केला केली त्यांनी तसेच "
    "त्याचा त्याची त्यांच्या झाले झाला झाली असे असा आपल्या मराठी".split()
)
_NE = frozenset(
    "छ छन् हुन्छ गर्न गरेको भएको लाई बाट पनि थियो गर्ने हरू हरु भने त्यो यो".split()
)

# Romanised-Hindi closed class. Words that are also common English words
# (is, to, me, main, par, do, hum, bad, the ...) are intentionally absent.
_HL = frozenset(
    """hai hain hoon tha thi thay hoga hogi honge raha rahi rahe rahega
    nahi nahin nhi kya kyu kyun kyon kaise kaisa kaisi kab kahan kaun koi kuch
    kuchh bahut bohot bhut bht bhi aur lekin magar toh phir fir abhi kabhi
    karna karne karo kiya kiye kare karta karti karte kar sakta sakti sakte
    gaya gayi gaye aaya aayi aaye aana jana jaana chalo chal chala chalte
    mujhe mujhko tumhe tumhein tum tumhara tera tere teri mera meri mere
    hamara hamare hamein hume humko apna apni apne aap aapka aapki aapko
    yeh woh wo vo ise usse unhe unka unki uska uski iska iski inka kisi kiska
    ek teen chaar paanch sab sabhi log logon desh ghar paisa paise kaam baat
    accha achha acha achcha theek thik yaar yar bhai bhaiya didi dost haan
    matlab zindagi pyaar pyar dil kal aaj raat din subah shaam
    chahiye chahta chahti chahte wala wali wale liye liya saath sath bina
    zyada jyada thoda thodi bilkul sirf bas lagta lagti lagi lagta
    dekh dekho dekha dekhna dekhne bol bolo bola bolna suno suna sunna
    batao bata bataya samajh samjha samjhe mat milega mila mili milte milna
    kyunki kyonki isliye agar warna shayad jaise waise aisa aisi aise
    itna itni itne utna utni kitna kitni kitne jitna hamesha zaroor
    mast sahi galat pata naya nayi purana bada badi chhota chhoti
    wahan yahan yaha waha idhar udhar kahin kaha kahaan
    mein ka ki ke ko se ne hota hoti hote hona hua hui hue
    beta beti papa mummy bhabhi chacha chachi nana nani dada dadi
    namaste dhanyavaad shukriya dhanyavad
    """.split()
)
# Of the above, the shortest / most ambiguous ones are only counted when they
# co-occur with at least one unambiguous word (see detect()).
_HL_AMBIGUOUS = frozenset("ka ki ke ko se ne mein kar mat bas sab sath".split())

_EN_STOP = frozenset(
    """the and of to is in that it for with as was on are this be at by have
    from or an not but they his her you we will would there their what which
    who when your can said been has had were if my all any about more some
    just very also than then them into out up so how our me i he she""".split()
)


@dataclass(frozen=True)
class LangResult:
    lang: str
    dev_ratio: float
    latin_ratio: float
    hinglish_rate: float
    hinglish_hits: int
    english_rate: float

    def summary(self) -> list:
        return [round(self.dev_ratio, 3), round(self.hinglish_rate, 3), round(self.english_rate, 3)]


def script_counts(text: str) -> tuple[int, int, int]:
    total = len(_LETTER.findall(text))
    dev = len(_DEV_LETTER.findall(text))
    lat = len(_LATIN_LETTER.findall(text))
    return total, dev, lat


def detect(text: str, cfg: Config) -> LangResult:
    """Script is decided per *word* (not per letter): Devanagari words carry
    fewer letters than the long English words typically mixed into them, so a
    letter ratio would mislabel "मैंने meeting attend की" as English."""
    total, dev, lat = script_counts(text)
    if total < cfg.min_letters_for_lang:
        return LangResult("other", 0.0, 0.0, 0.0, 0, 0.0)
    dev_toks = _DEV_TOKEN.findall(text)
    lat_toks = [t.lower() for t in _LATIN_TOKEN.findall(text)]
    n_dev, n_lat = len(dev_toks), len(lat_toks)
    other_share = 1 - (dev + lat) / total          # Arabic, Bengali, CJK, ... letters
    if other_share > 0.5 or n_dev + n_lat == 0:
        return LangResult("other", dev / total, lat / total, 0.0, 0, 0.0)
    dev_r, lat_r = n_dev / (n_dev + n_lat), n_lat / (n_dev + n_lat)

    # ---- Devanagari majority --------------------------------------------
    if dev_r >= cfg.dev_min_ratio:
        h = sum(1 for t in dev_toks if t in _HI)
        m = sum(1 for t in dev_toks if t in _MR)
        n = sum(1 for t in dev_toks if t in _NE)
        if (m >= 2 and m >= 0.5 * h) or (n >= 2 and n >= 0.5 * h):
            return LangResult("other", dev_r, lat_r, 0.0, 0, 0.0)  # Marathi / Nepali
        return LangResult("hi", dev_r, lat_r, 0.0, 0, 0.0)

    # ---- Latin majority: Hinglish vs English -----------------------------
    toks = lat_toks
    hl_strong = sum(1 for t in toks if t in _HL and t not in _HL_AMBIGUOUS)
    hl_weak = sum(1 for t in toks if t in _HL_AMBIGUOUS)
    hits = hl_strong + (hl_weak if hl_strong else 0)
    rate = hits / len(toks)
    en_rate = sum(1 for t in toks if t in _EN_STOP) / len(toks)
    # A little Devanagari inside a mostly-Latin sentence is a strong extra hint
    # that the Latin part is code-mixed Hindi rather than English.
    if (
        hits >= cfg.hinglish_min_hits
        and rate >= cfg.hinglish_min_rate
        and rate >= cfg.hinglish_vs_english * en_rate
    ) or (n_dev > 0 and hits >= 1 and rate >= cfg.hinglish_min_rate):
        return LangResult("hi-Latn", dev_r, lat_r, rate, hits, en_rate)
    return LangResult("en", dev_r, lat_r, rate, hits, en_rate)
