#!/usr/bin/env bash
# Usage: ./run.sh <raw_dir> <out_dir> [--keep-work] [--set KEY=JSON ...]
# Offline by design: reads only <raw_dir>, writes only <out_dir>.
# Requires: python>=3.10, numpy, pyarrow (pip install -r requirements.txt; done once, before going offline).
set -euo pipefail
if [ "$#" -lt 2 ]; then echo "usage: $0 <raw_dir> <out_dir> [options]" >&2; exit 2; fi
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1
exec env PYTHONPATH="$HERE/src" python3 -m indic_corpus "$@"
