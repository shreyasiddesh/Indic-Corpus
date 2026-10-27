import pytest

from indic_corpus.pii import redact, verhoeff_valid


def r(s):
    return redact(s)[0]


@pytest.mark.parametrize("s", [
    "call 9876543210 now", "call +91 98765 43210 now", "call +91-9876543210", "call 098765 43210",
    "फोन: ९८७६५४३२१०", "ring 91 98765-43210", "080-23456789 पर", "011 2345 6789",
])
def test_phone_redacted(s):
    assert "<PHONE>" in r(s) and not any(c.isdigit() for c in r(s).replace("<PHONE>", ""))


@pytest.mark.parametrize("s", [
    "population 1234567890", "year 2024 and 2025", "₹1,50,000 की कीमत", "7,654,321,098 लोग",
    "ISBN 8123456789", "score 5.5 out of 10", "12345", "tracking 1987654321",
    "card 1234 5678 9012 3456",
])
def test_non_pii_numbers_survive(s):
    assert r(s) == s


def test_email():
    assert r("mail a.b+c@ex-ample.co.in now") == "mail <EMAIL> now"
    assert r("not@") == "not@"


def test_pan_valid_pattern_only():
    assert r("PAN ABCPK1234F है") == "PAN <PAN> है"
    assert r("ABCDE1234") == "ABCDE1234"          # too short
    assert r("abcpk1234f") == "abcpk1234f"        # lowercase is not a PAN
    assert r("ABCXK1234F") == "ABCXK1234F"        # 4th letter not an entity type


def test_aadhaar_formats_and_checksum():
    assert r("आधार 2345 6789 0123") == "आधार <AADHAAR>"
    assert r("id 2345-6789-0123") == "id <AADHAAR>"
    valid = "234567890124"                         # make a Verhoeff-valid 12-digit number
    for check in "0123456789":
        cand = "23456789012" + check
        if verhoeff_valid(cand):
            valid = cand
            break
    assert r(f"no. {valid} here") == "no. <AADHAAR> here"
    invalid = "234567890123" if not verhoeff_valid("234567890123") else "234567890124"
    assert r(f"no. {invalid} here") == f"no. {invalid} here"       # no keyword, bad checksum -> survives
    assert r(f"Aadhaar {invalid}") == "Aadhaar <AADHAAR>"          # keyword forces it


def test_counts():
    _, c = redact("a@b.com 9876543210 ABCPK1234F")
    assert c["EMAIL"] == c["PHONE"] == c["PAN"] == 1
