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
    python3 -m mmmu_pipeline.image_layout \
      --config "$CONFIG_PATH" --image-layout=inline --dry-run "$@"
    python3 -m mmmu_pipeline.image_layout \
      --config "$CONFIG_PATH" --image-layout=prefix --dry-run "$@"
    ;;
  --all)
    shift
    python3 -m mmmu_pipeline.image_layout \
      --config "$CONFIG_PATH" --image-layout=inline "$@"
    python3 -m mmmu_pipeline.image_layout \
      --config "$CONFIG_PATH" --image-layout=prefix "$@"
    ;;
  --compare-only)
    shift
    python3 -m mmmu_pipeline.image_layout \
      --config "$CONFIG_PATH" --compare-only "$@"
    ;;
  *)
    python3 -m mmmu_pipeline.image_layout --config "$CONFIG_PATH" "$@"
    ;;
esac
