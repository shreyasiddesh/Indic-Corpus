"""Streaming readers for raw input. Every reader is a generator that yields one
``Record`` per input document and never raises on a bad record: malformed
records come out as ``Record(text=None, error=<reason>)`` so the pipeline can
count them and write a ledger row.

Supported: .jsonl/.ndjson, .json (array or JSONL), .csv/.tsv, .txt, .parquet,
each optionally wrapped in .gz or .bz2. Anything else is reported, not guessed.
"""
from __future__ import annotations

import bz2
import csv
import gzip
import hashlib
import io
import json
import os
import re
from dataclasses import dataclass
from typing import Iterator, Optional

from .config import Config

IGNORED_NAMES = {"SOURCES.json", "sources.json", "MANIFEST.json", "DOWNLOAD_LOG.json"}
IGNORED_SUFFIXES = (".md", ".license", ".sha256", ".lock", ".tmp", ".part", ".yaml", ".yml")
_SURROGATE = re.compile("[\udc80-\udcff]")


@dataclass
class Record:
    ordinal: int                  # position of the record inside its file (stable id component)
    text: Optional[str]
    error: Optional[str] = None


def doc_id(rel_path: str, ordinal: int) -> str:
    """Stable id: depends only on where the record sits in the raw input."""
    return hashlib.sha1(f"{rel_path}\0{ordinal}".encode()).hexdigest()[:16]


def discover(raw_dir: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Sorted (rel_path, abs_path) for files we will read + ignored rel paths."""
    files, ignored = [], []
    for root, dirs, names in os.walk(raw_dir):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for n in sorted(names):
            p = os.path.join(root, n)
            rel = os.path.relpath(p, raw_dir).replace(os.sep, "/")
            if n.startswith(".") or n in IGNORED_NAMES or n.lower().endswith(IGNORED_SUFFIXES):
                ignored.append(rel)
            else:
                files.append((rel, p))
    return sorted(files), sorted(ignored)


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def file_format(rel: str) -> tuple[str, str]:
    """-> (format, compression)"""
    low = rel.lower()
    comp = ""
    for ext, name in ((".gz", "gz"), (".bz2", "bz2")):
        if low.endswith(ext):
            comp, low = name, low[: -len(ext)]
    for ext, fmt in (
        (".jsonl", "jsonl"), (".ndjson", "jsonl"), (".json", "json"), (".csv", "csv"),
        (".tsv", "tsv"), (".txt", "txt"), (".text", "txt"), (".parquet", "parquet"),
    ):
        if low.endswith(ext):
            return fmt, comp
    return "unknown", comp


def _open_binary(path: str, comp: str):
    if comp == "gz":
        return gzip.open(path, "rb")
    if comp == "bz2":
        return bz2.open(path, "rb")
    return open(path, "rb")


def _pick_text(obj: dict, cfg: Config) -> tuple[Optional[str], Optional[str]]:
    if cfg.text_field_override:
        if cfg.text_field_override not in obj:
            return None, "missing_text_field"
        v = obj[cfg.text_field_override]
        return (v, None) if isinstance(v, str) else (None, "text_not_string")
    for k in cfg.text_fields:
        if k in obj:
            v = obj[k]
            if isinstance(v, str):
                return v, None
            return None, "text_not_string"
    strs = [v for v in obj.values() if isinstance(v, str)]
    if strs:
        return max(strs, key=len), None     # unseen schema: longest string field
    return None, "missing_text_field"


def _from_json_value(obj, cfg: Config) -> tuple[Optional[str], Optional[str]]:
    if isinstance(obj, str):
        return obj, None
    if isinstance(obj, dict):
        return _pick_text(obj, cfg)
    return None, "unsupported_record_type"


def _finalise(text: Optional[str], err: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if err:
        return None, err
    if text is None or text.strip() == "":
        return None, "empty_text"
    if _SURROGATE.search(text):
        return None, "invalid_utf8"
    return text, None


def _iter_jsonl(f, cfg: Config) -> Iterator[Record]:
    ordinal = -1
    for raw in f:
        ordinal += 1
        if not raw.strip():
            continue
        if len(raw) > cfg.max_record_bytes:
            yield Record(ordinal, None, "record_too_large")
            continue
        try:
            line = raw.decode("utf-8-sig" if ordinal == 0 else "utf-8")
        except UnicodeDecodeError:
            yield Record(ordinal, None, "invalid_utf8")
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, RecursionError):
            yield Record(ordinal, None, "invalid_json")
            continue
        text, err = _finalise(*_from_json_value(obj, cfg))
        yield Record(ordinal, text, err)


def _iter_json_array(f, cfg: Config) -> Iterator[Record]:
    """Incrementally decode a top-level JSON array without loading it all."""
    dec = json.JSONDecoder()
    buf, ordinal, started = "", -1, False
    reader = io.TextIOWrapper(f, encoding="utf-8", errors="surrogateescape")
    eof = False
    while True:
        if not eof and len(buf) < (1 << 20):
            chunk = reader.read(1 << 22)
            if chunk:
                buf += chunk
            else:
                eof = True
        i = 0
        while i < len(buf) and buf[i] in " \t\r\n,":
            i += 1
        if not started:
            if i < len(buf):
                if buf[i] != "[":
                    return
                started, i = True, i + 1
            elif eof:
                return
            buf = buf[i:]
            continue
        if i < len(buf) and buf[i] == "]":
            return
        try:
            obj, end = dec.raw_decode(buf, i)
        except json.JSONDecodeError:
            if eof:
                ordinal += 1
                yield Record(ordinal, None, "invalid_json")
                return
            chunk = reader.read(1 << 22)
            if chunk:
                buf += chunk
            else:
                eof = True
            continue
        ordinal += 1
        buf = buf[end:]
        yield Record(ordinal, *_finalise(*_from_json_value(obj, cfg)))


def _iter_json(f, cfg: Config) -> Iterator[Record]:
    head = f.read(1)
    while head and head in b" \t\r\n\xef\xbb\xbf":
        head = f.read(1)
    rest = io.BufferedReader(_Prepend(head, f))
    if head == b"[":
        yield from _iter_json_array(rest, cfg)
    else:
        yield from _iter_jsonl(rest, cfg)


class _Prepend(io.RawIOBase):
    def __init__(self, first: bytes, f):
        self._first, self._f = first, f

    def readable(self):
        return True

    def readinto(self, b):
        if self._first:
            n = min(len(b), len(self._first))
            b[:n] = self._first[:n]
            self._first = self._first[n:]
            return n
        data = self._f.read(len(b))
        b[: len(data)] = data
        return len(data)


def _iter_csv(f, delimiter: str, cfg: Config) -> Iterator[Record]:
    csv.field_size_limit(1 << 30)
    text_f = io.TextIOWrapper(f, encoding="utf-8-sig", errors="surrogateescape", newline="")
    reader = csv.reader(text_f, delimiter=delimiter)
    header, ordinal = None, -1
    it = iter(reader)
    while True:
        try:
            row = next(it)
        except StopIteration:
            return
        except csv.Error:
            ordinal += 1
            yield Record(ordinal, None, "malformed_csv_row")
            continue
        if header is None:
            header = row
            continue
        ordinal += 1
        if not row:
            continue
        if len(row) != len(header):
            yield Record(ordinal, None, "csv_column_mismatch")
            continue
        yield Record(ordinal, *_finalise(*_pick_text(dict(zip(header, row)), cfg)))


def _iter_txt(f, cfg: Config) -> Iterator[Record]:
    if cfg.txt_mode == "file":
        data = f.read()
        try:
            yield Record(0, *_finalise(data.decode("utf-8-sig"), None))
        except UnicodeDecodeError:
            yield Record(0, None, "invalid_utf8")
        return
    ordinal = -1
    for raw in f:
        ordinal += 1
        if not raw.strip():
            continue
        try:
            line = raw.decode("utf-8-sig" if ordinal == 0 else "utf-8")
        except UnicodeDecodeError:
            yield Record(ordinal, None, "invalid_utf8")
            continue
        yield Record(ordinal, *_finalise(line.rstrip("\r\n"), None))


def _iter_parquet(path: str, cfg: Config) -> Iterator[Record]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    names = pf.schema_arrow.names
    stringy = [f.name for f in pf.schema_arrow
               if pa.types.is_string(f.type) or pa.types.is_large_string(f.type)]
    col = None
    if cfg.text_field_override:
        col = cfg.text_field_override if cfg.text_field_override in names else None
    else:
        col = next((k for k in cfg.text_fields if k in stringy), None) or (stringy[0] if stringy else None)
    if col is None:
        yield Record(0, None, "missing_text_field")
        return
    ordinal = -1
    for batch in pf.iter_batches(batch_size=1024, columns=[col]):
        for v in batch.column(0).to_pylist():
            ordinal += 1
            if v is None:
                yield Record(ordinal, None, "empty_text")
            else:
                yield Record(ordinal, *_finalise(v, None))


def iter_records(path: str, rel: str, cfg: Config) -> Iterator[Record]:
    fmt, comp = file_format(rel)
    try:
        if fmt == "parquet":
            yield from _iter_parquet(path, cfg)
            return
        if fmt == "unknown":
            yield Record(-1, None, "unsupported_file_type")
            return
        with _open_binary(path, comp) as f:
            if fmt == "jsonl":
                yield from _iter_jsonl(f, cfg)
            elif fmt == "json":
                yield from _iter_json(f, cfg)
            elif fmt in ("csv", "tsv"):
                yield from _iter_csv(f, "\t" if fmt == "tsv" else ",", cfg)
            elif fmt == "txt":
                yield from _iter_txt(f, cfg)
    except (OSError, EOFError, ValueError) as e:       # corrupt gzip, truncated parquet, ...
        yield Record(-2, None, f"unreadable_file:{type(e).__name__}")
    except Exception as e:  # pyarrow raises its own hierarchy
        yield Record(-2, None, f"unreadable_file:{type(e).__name__}")
