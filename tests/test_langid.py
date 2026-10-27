import pytest

from indic_corpus.config import Config
from indic_corpus.langid import detect

C = Config()


@pytest.mark.parametrize("text,want", [
    ("भारत एक विशाल देश है जहाँ अनेक भाषाएँ बोली जाती हैं।", "hi"),
    ("मैंने आज office में meeting attend की और project का update दिया।", "hi"),   # code-mixed Devanagari -> hi
    ("yaar kal ka match dekha kya, kya zabardast game tha", "hi-Latn"),
    ("mujhe nahi pata ki wo kab aayega", "hi-Latn"),
    ("aaj meeting hai to main late aaunga, ghar pe sab theek hai", "hi-Latn"),
    ("The committee approved the budget after a long discussion on Tuesday.", "en"),
    ("I will go to the main office and do the paperwork for you.", "en"),    # 'main', 'do' are English here
    ("हे पुस्तक आहे आणि ते मराठी भाषेत आहे.", "other"),
    ("这是一个中文句子。", "other"),
    ("1234 5678", "other"),
])
def test_labels(text, want):
    assert detect(text, C).lang == want
