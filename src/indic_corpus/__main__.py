import argparse
import json
import sys

from .config import Config
from .pipeline import run


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="indic_corpus", description="Raw Hindi/Hinglish text -> clean training corpus + eval set")
    ap.add_argument("raw_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--config", help="JSON file overriding Config fields (recorded in manifest.json)")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=JSON", help="override one Config field, e.g. --set near_dup_threshold=0.7")
    ap.add_argument("--text-field", default="", help="force the text column/key name")
    ap.add_argument("--txt-mode", choices=["line", "file"], default=None, help=".txt files: one document per line (default) or per file")
    ap.add_argument("--keep-work", action="store_true", help="keep _work/ (stage-1 shards) after success")
    a = ap.parse_args(argv)

    overrides = json.load(open(a.config, encoding="utf-8")) if a.config else {}
    for kv in a.set:
        k, _, v = kv.partition("=")
        overrides[k] = json.loads(v)
    if a.text_field:
        overrides["text_field_override"] = a.text_field
    if a.txt_mode:
        overrides["txt_mode"] = a.txt_mode
    run(a.raw_dir, a.out_dir, Config.from_overrides(overrides), keep_work=a.keep_work)
    return 0


if __name__ == "__main__":
    sys.exit(main())
