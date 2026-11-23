#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 2 ]]; then
  echo "Usage: run_test_judge.sh CODE_DIR APPROVED_PREPARED_SCORING_DIR" >&2
  exit 2
fi
python "$1/scoring/evaluate.py" run --out "$2" --ask-key
python "$1/scoring/evaluate.py" summarize --out "$2"
