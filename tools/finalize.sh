#!/usr/bin/env bash
# After ./run.sh raw out --keep-work: copy deliverables into the repo and render numbers/charts.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p eval sample docs/img
cp out/eval.jsonl eval/eval.jsonl
cp out/contamination.jsonl eval/contamination.jsonl
cp out/manifest.json docs/manifest.json
python tools/make_sample.py out sample/clean_sample_1000.jsonl
python tools/make_charts.py out docs/img
python tools/render_numbers.py out > docs/numbers.txt
echo finalized
