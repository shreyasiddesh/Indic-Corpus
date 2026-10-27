import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys

import pytest

import synth

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = os.path.join(ROOT, "run.sh")


def _find_bash():
    # On Windows a bare "bash" may be WSL, which cannot see C:\ paths; prefer Git Bash.
    if os.name != "nt":
        return "bash"
    git = shutil.which("git")
    if git:
        root = os.path.dirname(git)
        for _ in range(3):
            root = os.path.dirname(root)
            for rel in ("bin", "usr/bin"):
                p = os.path.join(root, rel, "bash.exe")
                if os.path.exists(p):
                    return p
    return "bash"


BASH = _find_bash()


def run(raw, out, extra_env=None, args=()):
    env = dict(os.environ, **(extra_env or {}))
    return subprocess.run([BASH, RUN, raw, out, *args], capture_output=True, text=True, env=env)


def tree_hash(out):
    h = hashlib.sha256()
    for root, dirs, files in os.walk(out):
        dirs.sort()
        if "_work" in root:
            continue
        for f in sorted(files):
            p = os.path.join(root, f)
            h.update(os.path.relpath(p, out).encode())
            h.update(open(p, "rb").read())
    return h.hexdigest()


def ledger(out):
    return [json.loads(l) for l in gzip.open(os.path.join(out, "ledger.jsonl.gz"), "rt", encoding="utf-8")]


@pytest.fixture(scope="module")
def raw(tmp_path_factory):
    d = str(tmp_path_factory.mktemp("raw"))
    synth.make(d)
    return d


@pytest.fixture(scope="module")
def full_run(raw, tmp_path_factory):
    out = str(tmp_path_factory.mktemp("out_full"))
    r = run(raw, out)
    assert r.returncode == 0, r.stderr
    return out


def test_outputs_exist_and_schema(full_run):
    for name in ("clean", "ledger.jsonl.gz", "eval.jsonl", "contamination.jsonl", "manifest.json"):
        assert os.path.exists(os.path.join(full_run, name))
    part = os.path.join(full_run, "clean", "part-00000.jsonl.gz")
    row = json.loads(gzip.open(part, "rt", encoding="utf-8").readline())
    assert set(row) == {"id", "text", "lang", "source"}
    led = ledger(full_run)[0]
    assert {"id", "status", "stage", "reason", "dup_of"} <= set(led)


def test_ledger_covers_every_input_record_once(full_run):
    led = ledger(full_run)
    assert len({r["id"] for r in led}) == len(led)
    m = json.load(open(os.path.join(full_run, "manifest.json"), encoding="utf-8"))
    assert len(led) == sum(i["records"] for i in m["inputs"])
    kept_ids = set()
    for p in m["outputs"]["clean_parts"]:
        kept_ids |= {json.loads(l)["id"] for l in gzip.open(os.path.join(full_run, "clean", p["name"]), "rt", encoding="utf-8")}
    assert kept_ids == {r["id"] for r in led if r["status"] == "kept"}


def test_malformed_records_are_counted_not_fatal(full_run):
    m = json.load(open(os.path.join(full_run, "manifest.json"), encoding="utf-8"))
    skips = m["read_skipped_by_reason"]
    assert skips["invalid_json"] >= 1 and skips["invalid_utf8"] == 1 and skips["text_not_string"] >= 1


def test_wrong_source_labels_are_ignored(full_run):
    # every synth_news doc carries lang="en"; hindi docs must still come out as hi
    m = json.load(open(os.path.join(full_run, "manifest.json"), encoding="utf-8"))
    assert m["outputs"]["clean_by_lang"]["hi"] > 50
    labelled_latn = m["outputs"]["clean_by_lang"].get("hi-Latn", 0) + m["eval"]["by_lang"].get("hi-Latn", 0)
    assert labelled_latn > 20


def test_pii_redacted_in_output_and_nonpii_survives(full_run):
    text = "".join(gzip.open(os.path.join(full_run, "clean", "part-00000.jsonl.gz"), "rt", encoding="utf-8").readlines())
    assert "98765" not in text and "example.com" not in text and "ABCPK1234F" not in text
    assert "1234567890" in text and "1,50,000" in text
    assert "<PHONE>" in text and "<EMAIL>" in text


def test_eval_not_in_clean(full_run):
    ev = [json.loads(l) for l in open(os.path.join(full_run, "eval.jsonl"), encoding="utf-8")]
    assert 150 <= len(ev) <= 200
    held = {e["source_doc_id"] for e in ev}
    kept = {r["id"] for r in ledger(full_run) if r["status"] == "kept"}
    assert not (held & kept)


def test_rerun_is_byte_identical(raw, full_run, tmp_path):
    out2 = str(tmp_path / "again")
    assert run(raw, out2).returncode == 0
    assert tree_hash(full_run) == tree_hash(out2)


def test_killed_run_resumes_to_identical_output(raw, full_run, tmp_path):
    out = str(tmp_path / "killed")
    r = run(raw, out, {"INDIC_CORPUS_TEST_DIE_AFTER_RECORDS": "20"})
    assert r.returncode != 0                                   # died mid stage-1
    assert not os.path.exists(os.path.join(out, "manifest.json"))
    r = run(raw, out)                                          # restart
    assert r.returncode == 0, r.stderr
    assert "resumed from checkpoint" in r.stderr or "processing" in r.stderr
    assert tree_hash(full_run) == tree_hash(out)
    led = ledger(out)
    assert len({x["id"] for x in led}) == len(led)             # no duplicated rows


def test_unseen_formats_and_schemas(tmp_path):
    raw = tmp_path / "raw" / "mystery"
    raw.mkdir(parents=True)
    hi = "भारत एक विशाल देश है जहाँ अनेक भाषाएँ बोली जाती हैं। गंगा नदी हिमालय से निकलती है।"
    (raw / "a.csv").write_text('title,body,n\nx,"%s",1\nbroken,row\ny,"%s अलग वाक्य यहाँ जुड़ा है",2\n' % (hi, hi), encoding="utf-8")
    (raw / "b.json").write_text(json.dumps([{"content": hi + " तीसरा"}, {"nothing": 1}, "सिर्फ़ स्ट्रिंग भी चलेगी, यह भी एक वाक्य है।"], ensure_ascii=False), encoding="utf-8")
    (raw / "c.txt").write_text(hi + " पहली पंक्ति\n\n" + hi + " दूसरी पंक्ति\n", encoding="utf-8")
    (raw / "d.bin").write_bytes(b"\x00\x01\x02")
    out = str(tmp_path / "out")
    r = run(str(tmp_path / "raw"), out)
    assert r.returncode == 0, r.stderr
    led = ledger(out)
    reasons = {x["reason"] for x in led if x["status"] == "dropped"}
    assert "csv_column_mismatch" in reasons and "missing_text_field" in reasons and "unsupported_file_type" in reasons
    assert sum(1 for x in led if x["status"] == "kept" or x["stage"] == "eval_holdout") >= 5
