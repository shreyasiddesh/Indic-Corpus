#!/usr/bin/env bash
# Usage: ./download.sh [raw_dir]      (default: ./raw)
# The ONLY script that touches the network. Writes raw data exactly as published,
# plus raw/SOURCES.json (name, URL, license, pinned revision, download date, sha256 per file)
# and raw/DOWNLOAD_LOG.json (every source we tried, including refusals and failures).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAW="${1:-$HERE/raw}"
exec python3 "$HERE/tools/download.py" "$RAW" --sources "$HERE/sources/sources.json"
