#!/usr/bin/env python3
"""Download raw data exactly as published and write raw/SOURCES.json.

Needs network access (run.sh does not). Standard library only.
Usage: python3 tools/download.py <raw_dir> [--sources sources/sources.json]
Env:   HF_TOKEN (optional), HF_ENDPOINT (default https://huggingface.co)
"""
import argparse
import datetime
import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

HF = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
TOKEN = os.environ.get("HF_TOKEN")


def http(url, stream=False, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "indic-corpus-downloader/1.0"})
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    return urllib.request.urlopen(req, timeout=timeout)


def get_json(url):
    for attempt in range(4):
        try:
            with http(url) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                raise
            time.sleep(2 ** attempt)
        except Exception:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"giving up on {url}")


def list_files(dataset, sha, prefix):
    """Recursive file listing with LFS sha256 for integrity checks."""
    out, stack = [], [prefix.rstrip("/")]
    while stack:
        path = stack.pop()
        url = f"{HF}/api/datasets/{dataset}/tree/{sha}/{path}".rstrip("/") + "?recursive=false"
        for ent in get_json(url):
            if ent["type"] == "directory":
                stack.append(ent["path"])
            else:
                out.append({"path": ent["path"], "size": ent.get("size", 0), "sha256": (ent.get("lfs") or {}).get("oid")})
    return sorted(out, key=lambda e: e["path"])


PARALLEL = int(os.environ.get("DOWNLOAD_STREAMS", "8"))   # the CDN throttles per connection, not per client
CHUNK = 8 << 20


def _range_get(url, start, end):
    for attempt in range(12):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "indic-corpus-downloader/1.0",
                                                       "Range": f"bytes={start}-{end}"})
            if TOKEN:
                req.add_header("Authorization", f"Bearer {TOKEN}")
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if len(data) != end - start + 1:
                raise RuntimeError(f"short read {len(data)} != {end - start + 1}")
            return data
        except Exception as e:
            print(f"  chunk {start}: retry {attempt + 1}: {e}", file=sys.stderr)
            time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"failed range {start}-{end} of {url}")


def _fetch_parallel(url, tmp, size):
    """Ranged parallel download. Finished chunks are recorded in <tmp>.done so a flaky network
    (or a killed run) resumes instead of starting over; the final sha256 check still covers every byte."""
    from concurrent.futures import ThreadPoolExecutor
    side = tmp + ".done"
    done_set = set()
    if os.path.exists(tmp) and os.path.getsize(tmp) == size and os.path.exists(side):
        done_set = set(json.load(open(side, encoding="utf-8")))
    else:
        with open(tmp, "wb") as f:
            f.truncate(size)
    ranges = [(o, min(o + CHUNK, size) - 1) for o in range(0, size, CHUNK)]
    lock = threading.Lock()

    def work(rg):
        if rg[0] in done_set:
            return 0
        data = _range_get(url, *rg)
        with lock:
            with open(tmp, "r+b") as f:        # distinct byte ranges, so writers never overlap
                f.seek(rg[0])
                f.write(data)
            done_set.add(rg[0])
            with open(side, "w", encoding="utf-8") as f:
                json.dump(sorted(done_set), f)
        return len(data)

    got = 0
    with ThreadPoolExecutor(PARALLEL) as ex:
        for n in ex.map(work, ranges):
            got += n
            print(f"  {len(done_set) * CHUNK / 1e6:.0f}/{size / 1e6:.0f} MB", file=sys.stderr, flush=True)
    os.remove(side)


def fetch(url, dest, expect_sha, expect_size):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) == expect_size:
        return sha256(dest)
    tmp = dest + ".part"
    for attempt in range(4):
        try:
            if PARALLEL > 1 and expect_size > 2 * CHUNK:
                _fetch_parallel(url, tmp, expect_size)
                digest = sha256(tmp)
            else:
                h = hashlib.sha256()
                with http(url, timeout=120) as r, open(tmp, "wb") as f:
                    while True:
                        b = r.read(1 << 20)
                        if not b:
                            break
                        f.write(b)
                        h.update(b)
                digest = h.hexdigest()
            if expect_sha and digest != expect_sha:
                raise RuntimeError("sha256 mismatch")
            os.replace(tmp, dest)
            return digest
        except Exception as e:
            print(f"  retry {attempt + 1}: {e}", file=sys.stderr)
            time.sleep(2 ** attempt)
    raise RuntimeError(f"failed to download {url}")


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def take(entry, raw_dir, allowed, log):
    ds = entry["hf_dataset"]
    rec = {"name": entry["name"], "dataset": ds, "status": "started"}
    log.append(rec)
    try:
        meta = get_json(f"{HF}/api/datasets/{ds}")
    except Exception as e:
        rec.update(status="unavailable", error=str(e))
        return None
    card = meta.get("cardData") or {}
    lic = card.get("license")
    lic = ",".join(lic) if isinstance(lic, list) else (lic or "unknown")
    rec["license"] = lic
    lics = {x.strip().lower() for x in lic.split(",")}
    if not (lics & set(allowed)):
        rec.update(status="refused_license")
        return None
    sha = meta["sha"]
    try:
        files = [f for f in list_files(ds, sha, entry.get("include_prefix", ""))
                 if f["path"].endswith((".parquet", ".jsonl", ".jsonl.gz", ".json", ".csv", ".tsv", ".txt", ".txt.gz"))]
    except Exception as e:
        rec.update(status="listing_failed", error=str(e))
        return None
    files = files[: entry.get("max_files", 1)]
    if not files:
        rec.update(status="no_data_files")
        return None
    dl, total = [], 0
    for f in files:
        dest = os.path.join(raw_dir, entry["name"], f["path"].replace("/", "__"))
        print(f"  {ds}: {f['path']} ({f['size'] / 1e6:.1f} MB)", file=sys.stderr)
        digest = fetch(f"{HF}/datasets/{ds}/resolve/{sha}/{f['path']}", dest, f.get("sha256"), f["size"])
        dl.append({"file": os.path.relpath(dest, raw_dir), "bytes": os.path.getsize(dest), "sha256": digest, "origin_path": f["path"]})
        total += os.path.getsize(dest)
    try:
        with http(f"{HF}/datasets/{ds}/resolve/{sha}/README.md") as r:
            open(os.path.join(raw_dir, entry["name"], "DATASET_CARD.md"), "wb").write(r.read())
    except Exception:
        pass
    rec.update(status="downloaded", bytes=total)
    return {
        "name": entry["name"], "role": entry.get("role", "unknown"),
        "url": f"{HF}/datasets/{ds}", "revision": sha, "license": lic,
        "downloaded_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
        "path": entry["name"] + "/", "files": dl, "bytes": total,
        **({"text_field": entry["text_field"]} if entry.get("text_field") else {}),
        **({"sample_fraction": entry["sample_fraction"]} if entry.get("sample_fraction") else {}),
        "notes": entry.get("notes", ""),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw_dir")
    ap.add_argument("--sources", default=os.path.join(os.path.dirname(__file__), "..", "sources", "sources.json"))
    a = ap.parse_args()
    cfg = json.load(open(a.sources, encoding="utf-8"))
    os.makedirs(a.raw_dir, exist_ok=True)
    log, done = [], []
    for s in cfg["sources"]:
        print(f"== {s['name']}", file=sys.stderr)
        r = take(s, a.raw_dir, cfg["license_allowlist"], log)
        if r:
            done.append(r)
    have = 0
    for c in cfg["hinglish_candidates"]:
        if have >= cfg["hinglish_min_total_bytes"]:
            break
        print(f"== (hinglish candidate) {c['name']}", file=sys.stderr)
        r = take(dict(c, role="hinglish_latin"), a.raw_dir, cfg["license_allowlist"], log)
        if r:
            done.append(r)
            have += r["bytes"]
    json.dump({"sources": done}, open(os.path.join(a.raw_dir, "SOURCES.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump({"attempts": log}, open(os.path.join(a.raw_dir, "DOWNLOAD_LOG.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps(log, indent=1))
    if have < cfg["hinglish_min_total_bytes"]:
        print("WARNING: no usable Hinglish source reached the size target; see DOWNLOAD_LOG.json for what was tried.", file=sys.stderr)
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
