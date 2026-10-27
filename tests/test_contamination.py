from indic_corpus.config import Config
from indic_corpus.contamination import EvalIndex

C = Config()
EV_HI = "गंगा नदी हिमालय से निकलकर बंगाल की खाड़ी में मिलती है और रास्ते में कई शहरों को जल देती है जिससे करोड़ों लोगों का जीवन चलता है"
EV_LATN = "mujhe nahi pata ki wo kab aayega lekin hum intezaar kar rahe hain aur sab log bahut accha mehsoos kar rahe hain aaj"
ITEMS = [{"eval_id": "ev-0001", "text": EV_HI, "lang": "hi"}, {"eval_id": "ev-0002", "text": EV_LATN, "lang": "hi-Latn"}]
IDX = EvalIndex(ITEMS, C)


def methods(text):
    found, _ = IDX.check(text)
    return {ITEMS[i]["eval_id"]: m for i, (m, _) in found.items()}


def test_exact_substring():
    assert methods("आगे यह भी पढ़ें। " + EV_HI + " समाप्त।") == {"ev-0001": "exact"}


def test_normalized_copy():
    variant = EV_HI.replace("हिमालय", "हिमालय,").upper().replace("मिलती है", "मिलती  है") + "।"
    variant = EV_HI.replace("गंगा", "गंगा,").replace("खाड़ी", "खाड़ी").replace("है ", "है।  ", 1)
    assert methods(variant) == {"ev-0001": "normalized"}


def test_near_copy_with_edits():
    words = EV_HI.split()
    edited = " ".join(words[:10] + ["बिल्कुल", "नया"] + words[12:])          # two words changed
    assert methods("प्रस्तावना। " + edited + " उपसंहार।") == {"ev-0001": "near"}


def test_devanagari_item_in_latin_script_training_doc():
    roman = ("Ganga nadi Himalay se nikalkar Bangal ki khadi mein milti hai aur raaste mein kai shehron ko jal deti hai "
             "jisse karodon logon ka jeevan chalta hai")
    assert methods(roman) == {"ev-0001": "transliteration"}


def test_latin_item_in_devanagari_training_doc():
    dev = "मुझे नहीं पता कि वो कब आएगा लेकिन हम इंतज़ार कर रहे हैं और सब लोग बहुत अच्छा महसूस कर रहे हैं आज"
    assert methods(dev) == {"ev-0002": "transliteration"}


def test_unrelated_text_is_clean():
    other = "भारत एक विशाल देश है जहाँ अनेक भाषाएँ बोली जाती हैं और किसान सुबह जल्दी उठकर खेतों में काम करने जाते हैं बारिश आती है"
    english = "The committee approved the budget after a long discussion on Tuesday and the members went home happy that night"
    assert methods(other) == {} and methods(english) == {}


def test_overlapping_topic_is_a_near_miss_not_a_leak():
    partial = " ".join(EV_HI.split()[:8]) + " " + "और फिर बात कहीं और चली गई जहाँ मौसम बदलने लगा था सुबह की ठंडी हवा में"
    found, misses = IDX.check(partial)
    assert not found
