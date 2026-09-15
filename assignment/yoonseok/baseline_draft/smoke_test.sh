#!/usr/bin/env bash
set -euo pipefail
BASELINE_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${BASELINE_SCRIPT_DIR}/env.sh"
case "${1:-}" in
  --help|-h)
    echo 'Usage: bash smoke_test.sh [--parsers-only]'
    echo 'Default: download 3 pinned MMMU examples, run vLLM, and check both scoring paths.'
    exit 0 ;;
  ''|--parsers-only) ;;
  *) echo "Unknown option: $1" >&2; exit 2 ;;
esac
"${BASELINE_PYTHON}" "${BASELINE_ROOT}/mc_parsers.py" --self-test
if [[ "${1:-}" == --parsers-only ]]; then
  exit 0
fi
# Each run gets a new directory, keeping previous evidence intact.
BASELINE_SMOKE_DIR="$(mktemp -d "${BASELINE_ROOT}/data/smoke.XXXXXX")"
"${BASELINE_PYTHON}" "${BASELINE_ROOT}/build_dataset.py" \
  --subjects Accounting Physics Art --per-subject 1 --output "${BASELINE_SMOKE_DIR}/dataset.jsonl"
"${BASELINE_PYTHON}" "${BASELINE_ROOT}/run_inference.py" \
  --input "${BASELINE_SMOKE_DIR}/dataset.jsonl" --output "${BASELINE_SMOKE_DIR}/predictions.jsonl"
"${BASELINE_PYTHON}" "${BASELINE_ROOT}/evaluate_baseline.py" \
  --input "${BASELINE_SMOKE_DIR}/predictions.jsonl" --output "${BASELINE_SMOKE_DIR}/eval.json" --allow-partial
"${BASELINE_PYTHON}" "${BASELINE_ROOT}/compare_scoring_pipelines.py" \
  --input "${BASELINE_SMOKE_DIR}/predictions.jsonl" --output "${BASELINE_SMOKE_DIR}/comparison.json" \
  --table "${BASELINE_SMOKE_DIR}/table.md" --allow-partial
echo "Smoke test completed: ${BASELINE_SMOKE_DIR}"
