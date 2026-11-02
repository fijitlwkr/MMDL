#!/usr/bin/env bash
# Setup evaluation environment for Jinho (Hypothesis B MMMU evaluation)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
case "$ROOT" in /workspace/*) ;; *) echo "Checkout must be under /workspace" >&2; exit 2;; esac

export HF_HOME=/workspace/hf_cache
export XDG_CACHE_HOME=/workspace/cache PIP_CACHE_DIR=/workspace/pip_cache TMPDIR=/workspace/tmp
mkdir -p "$HF_HOME" "$XDG_CACHE_HOME" "$PIP_CACHE_DIR" "$TMPDIR"

TRAIN_DIR="$ROOT/assignment/experiments/hypB_train/jinho"
EVAL_ENV="$TRAIN_DIR/.venv-eval"
TRAIN_ENV="$TRAIN_DIR/.venv-train"

echo "=== 1. Checking training and evaluation virtualenvs ==="
if [ ! -d "$EVAL_ENV" ]; then
    echo "Creating .venv-eval..."
    python3.12 -m venv "$EVAL_ENV"
    "$EVAL_ENV/bin/python" -m pip install --upgrade pip setuptools wheel
    "$EVAL_ENV/bin/python" -m pip install -r "$ROOT/code/requirements.txt"
fi

if [ ! -d "$TRAIN_ENV" ]; then
    echo "Warning: .venv-train not found at $TRAIN_ENV. Please run setup_gpu.sh in hypB_train/jinho first."
fi

echo "=== 2. Verifying python packages in .venv-eval ==="
"$EVAL_ENV/bin/python" -m pip check
"$EVAL_ENV/bin/python" -c 'import vllm, torch, transformers; print("vllm:", vllm.__version__, "torch:", torch.__version__, "transformers:", transformers.__version__)'

echo "=== 3. Verifying code freeze ==="
"$EVAL_ENV/bin/python" "$HERE/verify_code.py"

echo "=== Setup evaluation environment completed successfully! ==="

