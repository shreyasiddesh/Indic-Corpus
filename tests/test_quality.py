from indic_corpus.config import Config
from indic_corpus.quality import clean_markup_and_boilerplate, gate_post_lang, gate_pre_lang, looks_like_table

C = Config()


def verdict(text):
    t, info = clean_markup_and_boilerplate(text, C)
    return gate_pre_lang(t, info, C) or gate_post_lang(t, C)


def test_short_legit_proverb_and_poem_survive():
    assert verdict("जैसी करनी वैसी भरनी।") is None
    assert verdict("चाँद निकला रात आई\nतारे जगमग गीत गाए\nनींद आँखों में समाई\nसपने सारे पास आए") is None


def test_poem_with_refrain_survives():
    # a song: 4 distinct verse lines + a 2-line chorus sung three times (40% repeated lines)
    chorus = ["हरे राम हरे राम राम राम हरे हरे", "हरे कृष्ण हरे कृष्ण कृष्ण कृष्ण हरे हरे"]
    verses = ["तेरा नाम सुमिरन करूँ मैं हर घड़ी", "तेरी शरण में आ गया हूँ मैं प्रभु", "दुनिया के सारे दुख मिटा दे तू", "मन में बसी है बस तेरी ही मूरत"]
    poem = "\n".join(verses[:2] + chorus + verses[2:] + chorus + chorus)
    assert verdict(poem) is None


def test_numeric_table_survives_but_digit_soup_does_not():
    table = "वर्ष बिक्री लाभ\n2019 120 30\n2020 135 33\n2021 150 41"
    assert looks_like_table(table, C) and verdict(table) is None
    assert verdict("1234567890 " * 40) == "numeric_junk"


def test_markup_stripped_when_minor_dropped_when_dominant():
    good = "<p>भारत एक विशाल देश है जहाँ अनेक भाषाएँ बोली जाती हैं।</p>"
    t, info = clean_markup_and_boilerplate(good, C)
    assert "<" not in t and verdict(good) is None
    junk = "<div class='a'><span><b></b></span></div>" * 5 + "भारत देश है"
    assert verdict(junk) == "markup"


def test_boilerplate_lines_removed_not_whole_doc():
    doc = "भारत एक विशाल देश है जहाँ अनेक भाषाएँ बोली जाती हैं।\nShare on Facebook\nऔर पढ़ें\nसभी अधिकार सुरक्षित"
    t, _ = clean_markup_and_boilerplate(doc, C)
    assert "Facebook" not in t and "भारत" in t


def test_garbage_gates():
    assert verdict("à¤¹à¤¿à¤¨à¥à¤¦à¥€ à¤­à¤¾à¤·à¤¾ à¤¹à¥ˆ à¤¯à¤¹ à¤¬à¤¹à¥à¤¤") == "garbled_mojibake"
    assert verdict("��� भारत एक देश है यह बहुत बड़ा") == "garbled_replacement_chars"
    assert verdict("???? ?????? ??? ???? ????? ???? ????") == "garbled_question_marks"
    assert verdict("ाे कि ं ्ा ेै ्् ांा क ि ाा ीी ूू ुु ेे ाा ोो ीी") == "garbled_devanagari"


def test_spam_and_repetition():
    assert verdict("click here to buy now: free download casino betting jackpot lottery today only, limited offer for all members") == "spam_keywords"
    assert verdict("खरीदो " * 60) == "repetitive_words"
    assert verdict("अ" * 200 + " देश है यह बहुत बड़ा") == "char_runs"


def test_too_short():
    assert verdict("ठीक है") == "too_short"


def test_short_hinglish_with_glued_punctuation_is_not_too_short():
    # str.split() counts "chalo,ghar chaliye?" as 2 words; real words are 4.
    assert verdict("chalo,ghar chaliye?") is None


def test_lorem_ipsum_dropped():
    assert verdict("यह एक परीक्षण है. Lorem ipsum dolor sit amet, consectetur adipiscing elit") == "placeholder_text"
