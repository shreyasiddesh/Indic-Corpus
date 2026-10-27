from indic_corpus.normalize import fold, normalize_text


def test_nukta_forms_compare_equal():
    assert normalize_text("क़") == normalize_text("क़")


def test_invisible_characters_removed():
    assert normalize_text("ह​ै﻿­") == "है"


def test_zwj_zwnj_noise_removed_in_devanagari_only():
    assert normalize_text("क्‍ष") == "क्ष"
    assert normalize_text("क्‌ष") == "क्ष"
    assert "‍" in normalize_text("👩‍💻")      # emoji sequence intact


def test_whitespace_canonical():
    assert normalize_text("a  b\t c\r\n\r\n\r\n\r\nd ") == "a b c\n\nd"


def test_ascii_pipe_becomes_danda_only_after_devanagari():
    assert normalize_text("वह गया |") == "वह गया।"
    assert normalize_text("a | b") == "a | b"


def test_fold_digits_punct_case():
    assert fold("Hello, World!") == fold("hello world")
    assert fold("साल २०२४।") == fold("साल 2024")
    assert fold("आँख") == fold("आंख")
