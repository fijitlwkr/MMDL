#!/usr/bin/env bash
# Phase 2 only, after the user prepares and approves the GPU pod.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
case "$ROOT" in /workspace/*) ;; *) echo "Checkout must be under /workspace" >&2; exit 2;; esac
export HF_HOME=/workspace/hf_cache
export XDG_CACHE_HOME=/workspace/cache PIP_CACHE_DIR=/workspace/pip_cache TMPDIR=/workspace/tmp
mkdir -p "$HF_HOME" "$XDG_CACHE_HOME" "$PIP_CACHE_DIR" "$TMPDIR"
python3.12 -c 'import sys; assert sys.version_info[:3] == (3,12,3), sys.version'
nvidia-smi --query-gpu=name --format=csv,noheader | grep -F 'RTX 4090'
python3.12 -m venv /workspace/hypB-eval-env
/workspace/hypB-eval-env/bin/python -m pip install -r "$ROOT/code/requirements.txt" peft==0.17.1
/workspace/hypB-eval-env/bin/python -m pip check
/workspace/hypB-eval-env/bin/python "$HERE/verify_code.py"
