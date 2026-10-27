"""Deterministic, crash-safe file helpers.

* gzip output has mtime=0 and no embedded file name, so identical content gives
  byte-identical files on every run.
* every file is written to ``<name>.tmp`` and renamed into place, so a killed
  process can never leave a half-written file that looks finished.
"""
from __future__ import annotations

import gzip
import io
import json
import os
from contextlib import contextmanager
from typing import Iterable, Iterator


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@contextmanager
def atomic_gz_text(path: str):
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    raw = open(tmp, "wb")
    gz = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6)
    text = io.TextIOWrapper(gz, encoding="utf-8", newline="\n")
    try:
        yield text
        text.flush()
        text.close()          # closes gz
        raw.flush()
        os.fsync(raw.fileno())
        raw.close()
        os.replace(tmp, path)
    except BaseException:
        try:
            text.close()
        except Exception:
            pass
        raw.close()
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def write_jsonl_gz(path: str, rows: Iterable[dict]) -> int:
    n = 0
    with atomic_gz_text(path) as f:
        for r in rows:
            f.write(dumps(r) + "\n")
            n += 1
    return n


def read_jsonl_gz(path: str) -> Iterator[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def atomic_write_text(path: str, content: str) -> None:
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
