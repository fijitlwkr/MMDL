#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG_PATH="$SCRIPT_DIR/config.json"

export VLLM_ENABLE_V1_MULTIPROCESSING="0"
export VLLM_WORKER_MULTIPROC_METHOD="spawn"
export TOKENIZERS_PARALLELISM="false"

python3 "$REPO_ROOT/run_mmmu_eval.py" --config "$CONFIG_PATH" "$@"
