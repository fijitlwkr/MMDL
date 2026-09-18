#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG_PATH="$SCRIPT_DIR/config.json"

export VLLM_ENABLE_V1_MULTIPROCESSING="0"
export VLLM_WORKER_MULTIPROC_METHOD="spawn"
export TOKENIZERS_PARALLELISM="false"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

case "${1:-}" in
  --dry-run)
    shift
    python3 "$REPO_ROOT/run_mmmu_eval.py" \
      --config "$CONFIG_PATH" --presence-penalty 0 --dry-run "$@"
    python3 "$REPO_ROOT/run_mmmu_eval.py" \
      --config "$CONFIG_PATH" --presence-penalty 0.5 --dry-run "$@"
    python3 "$SCRIPT_DIR/compare_conditions.py" --config "$CONFIG_PATH" --dry-run
    ;;
  --all)
    shift
    python3 "$REPO_ROOT/run_mmmu_eval.py" \
      --config "$CONFIG_PATH" --presence-penalty 0 "$@"
    python3 "$REPO_ROOT/run_mmmu_eval.py" \
      --config "$CONFIG_PATH" --presence-penalty 0.5 "$@"
    python3 "$SCRIPT_DIR/compare_conditions.py" --config "$CONFIG_PATH"
    ;;
  --compare-only)
    shift
    python3 "$SCRIPT_DIR/compare_conditions.py" --config "$CONFIG_PATH" "$@"
    ;;
  *)
    python3 "$REPO_ROOT/run_mmmu_eval.py" --config "$CONFIG_PATH" "$@"
    ;;
esac
