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
    python3 -m mmmu_pipeline.seed_repro \
      --config "$CONFIG_PATH" --seed=42 --dry-run "$@"
    python3 -m mmmu_pipeline.seed_repro \
      --config "$CONFIG_PATH" --seed=3407 --dry-run "$@"
    python3 -m mmmu_pipeline.seed_repro \
      --config "$CONFIG_PATH" --seed=1234 --dry-run "$@"
    ;;
  --all)
    shift
    python3 -m mmmu_pipeline.seed_repro \
      --config "$CONFIG_PATH" --seed=42 "$@"
    python3 -m mmmu_pipeline.seed_repro \
      --config "$CONFIG_PATH" --seed=3407 "$@"
    python3 -m mmmu_pipeline.seed_repro \
      --config "$CONFIG_PATH" --seed=1234 "$@"
    ;;
  --compare-only)
    shift
    python3 -m mmmu_pipeline.seed_repro \
      --config "$CONFIG_PATH" --compare-only "$@"
    ;;
  *)
    python3 -m mmmu_pipeline.seed_repro --config "$CONFIG_PATH" "$@"
    ;;
esac
